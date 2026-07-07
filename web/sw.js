/* MOLGANG service worker — offline-first app shell (#116).
 *
 * Strategy:
 *   • app shell (this directory's static assets)  → cache-first, refreshed in
 *     the background (stale-while-revalidate), so a cold load renders offline;
 *   • /api/*                                       → network-first with a cached
 *     fallback, so a network blip shows the last known state instead of nothing.
 *
 * Versioning: bump CACHE_VERSION on deploy — activate() drops every older cache,
 * so a new shell fully replaces a stale one on the next visit.
 */
"use strict";

const CACHE_VERSION = "v2";
const SHELL_CACHE = `molgang-shell-${CACHE_VERSION}`;
const API_CACHE = `molgang-api-${CACHE_VERSION}`;

// Relative to the SW scope → path-prefix-safe (works at / and /molgang/).
const SHELL = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "config.js",
  "i18n.js",
  "locales/en.json",
  "locales/nl.json",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-512-maskable.png",
  "icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys
        .filter((k) => k !== SHELL_CACHE && k !== API_CACHE)
        .map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                       // never cache mutations
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;             // same-origin only

  if (url.pathname.includes("/api/")) {
    // network-first: live state when online, last known state when not
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(API_CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // App CODE (HTML documents + JS) → NETWORK-FIRST so a deploy always loads fresh
  // (cache-first here served a stale lab-immersive.html — its heavy GPU path black-
  // screened after a fix had shipped). Cache is only the offline fallback.
  const isCode = req.destination === "document" || url.pathname.endsWith("/") ||
    /\.(html|mjs|js)$/.test(url.pathname);
  if (isCode) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) { const copy = res.clone(); caches.open(SHELL_CACHE).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Static assets (icons/css/json/fonts) → cache-first + background revalidate.
  e.respondWith(
    caches.match(req).then((hit) => {
      const refresh = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || refresh;
    })
  );
});
