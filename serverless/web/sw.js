// MOLGANG service worker — offline-first PWA cache for the serverless peer.
//
// PURPOSE (GRAFT 2 from the runner-up variant): the only real weakness of
// "real engine in every tab" is Pyodide's cold start — a tens-of-MB WASM
// download on first load. This service worker makes the SECOND load near-instant
// and fully OFFLINE by caching the app shell AND the Pyodide/cryptography WASM.
// After the first visit a tab boots its full Knitweb peer with no network at all.
//
// CACHING STRATEGY:
//   • App shell (this origin: html/js/css/manifest/engine wheel) — cache-first,
//     revalidated on activate by version bump. These are small and versioned.
//   • Pyodide CDN assets (pyodide.js, *.wasm, package wheels) — stale-while-
//     revalidate into a SEPARATE, long-lived cache keyed by the pinned Pyodide
//     version, because they are large and immutable per version.
//   • Everything else (STUN is not HTTP; there is no /api/*) — network-only
//     pass-through. There is deliberately NO API to cache: the engine is in-tab.
//
// SECURITY: the SW never caches or inspects WebRTC frames (those never traverse
// HTTP) and never touches the device wallet seed (that lives in localStorage /
// IndexedDB, owned by the page/worker, not the SW). It only caches static,
// public, content-addressable assets.

const APP_VERSION = "molgang-serverless-v2";
const PYODIDE_VERSION = "0.26.2";

const SHELL_CACHE = `${APP_VERSION}-shell`;
const WASM_CACHE = `molgang-pyodide-${PYODIDE_VERSION}`;

// The minimal shell needed to boot offline. `peer.js` pulls in qr.js / app-bridge.js
// dynamically; we add them defensively so a fully-offline cold boot still works.
const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./peer.js",
  "./qr.js",
  "./app-bridge.js",
  // Classic render layer, vendored from web/ (see serverless/README.md).
  "./app.js",
  "./config.js",
  "./i18n.js",
  "./style.css",
  "./locales/en.json",
  "./locales/nl.json",
  "./avatars/dao-delegate.svg",
  "./avatars/degen-ape.svg",
  "./avatars/diamond-hands.svg",
  "./avatars/faucet-fairy.svg",
  "./avatars/gas-goblin.svg",
  "./avatars/hoodie-hacker.svg",
  "./avatars/laser-maxi.svg",
  "./avatars/validator-owl.svg",
  "./manifest.webmanifest",
  // The molgang+knitweb engine, shipped as a wheel so the IDENTICAL .py bytes
  // import inside Pyodide (this is what makes byte-identity free), plus the
  // in-tab API bridge the worker runs on top of it.
  "./engine/molgang_engine-0.0.0-py3-none-any.whl",
  "./engine/serverless_api.py",
];

// Host that serves the pinned Pyodide runtime + packages. Cached aggressively
// and immutably (the version is in the cache name, so a version bump = new cache).
const PYODIDE_HOST = "cdn.jsdelivr.net";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // addAll is atomic-ish; tolerate individually-missing optional assets so a
      // partial bundle (e.g. before app-bridge.js exists) still installs.
      await Promise.allSettled(SHELL_ASSETS.map((u) => cache.add(u)));
      // Take over as soon as installed so the first navigation is controlled.
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Drop stale shell caches from prior app versions, but KEEP the Pyodide
      // WASM cache for the current pinned version (it is huge and immutable).
      const keys = await caches.keys();
      await Promise.all(
        keys.map((k) => {
          if (k === SHELL_CACHE || k === WASM_CACHE) return Promise.resolve();
          // Keep other versions' wasm caches only if they match a still-pinned
          // version; otherwise evict. Here we keep just the current two.
          return caches.delete(k);
        })
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  // Allow the page to trigger an immediate update activation (e.g. after the
  // conformance gate ships a new engine wheel).
  if (event.data === "skip-waiting") self.skipWaiting();
});

function isPyodideAsset(url) {
  return url.hostname === PYODIDE_HOST && url.pathname.includes("/pyodide/");
}

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only GET is cacheable; never intercept anything else (there is no POST API).
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // 1) Pyodide WASM/runtime/packages: stale-while-revalidate in the long-lived,
  //    version-keyed cache. Serves instantly from cache; refreshes in background.
  if (isPyodideAsset(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(WASM_CACHE);
        const cached = await cache.match(req);
        const network = fetch(req)
          .then((resp) => {
            // Cache opaque/cross-origin responses too (CDN is public, immutable).
            if (resp && (resp.ok || resp.type === "opaque")) {
              cache.put(req, resp.clone()).catch(() => {});
            }
            return resp;
          })
          .catch(() => cached);
        return cached || network;
      })()
    );
    return;
  }

  // 2) Same-origin shell: cache-first (small, versioned). Navigations fall back
  //    to the cached index.html so the app opens offline. There is NO /api/* to
  //    special-case — the engine answers every request in-tab.
  if (isSameOrigin(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(SHELL_CACHE);
        const cached = await cache.match(req, { ignoreSearch: true });
        if (cached) {
          // Revalidate quietly so the next load is fresh after a deploy.
          fetch(req)
            .then((resp) => { if (resp && resp.ok) cache.put(req, resp.clone()).catch(() => {}); })
            .catch(() => {});
          return cached;
        }
        try {
          const resp = await fetch(req);
          if (resp && resp.ok && resp.type === "basic") {
            cache.put(req, resp.clone()).catch(() => {});
          }
          return resp;
        } catch (err) {
          // Offline navigation fallback to the cached app shell.
          if (req.mode === "navigate") {
            const shell = await cache.match("./index.html");
            if (shell) return shell;
          }
          throw err;
        }
      })()
    );
    return;
  }

  // 3) Everything else (other cross-origin GETs, e.g. an optional bootstrap
  //    mailbox or a CDN script): network pass-through, no caching. STUN/TURN and
  //    WebRTC frames never reach here (not HTTP).
});
