// MOLGANG serverless render bridge (ES module, imported by peer.js AFTER the
// in-tab engine reports 'ready' and window.MOLGANG_ENGINE exists).
//
// The classic render layer (app.js, vendored verbatim from web/) speaks HTTP:
// its api() helper does fetch(BASE + "/api/…") and it opens a world WebSocket.
// This module makes that work with NO server:
//   1. a fetch interceptor routes every same-origin request whose path contains
//      "/api/" into window.MOLGANG_ENGINE.api(path, method, body) and wraps the
//      engine's {status, body} answer back into a real Response (engine failure
//      → non-2xx JSON {"error": …}, so app.js's error handling stays on its
//      normal path);
//   2. the world WebSocket is stubbed inert (there is no /ws/world server; the
//      poll fallback in app.js drives refreshes against the in-tab engine);
//   3. the classic scripts are then loaded IN ORDER (config.js → i18n.js →
//      app.js) as classic scripts — app.js is not a module and expects its
//      top-level state on the page scope.
//
// Sacred-invariant discipline: nothing here parses or produces protocol bytes;
// it only moves JSON between the render layer and the engine RPC.

function installFetchBridge() {
  if (window.__MOLGANG_FETCH_BRIDGED) return;
  window.__MOLGANG_FETCH_BRIDGED = true;
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    let url;
    try {
      url = new URL(
        typeof input === "string" ? input : (input && input.url) || String(input),
        location.href);
    } catch (e) {
      return nativeFetch(input, init);
    }
    const idx = url.pathname.indexOf("/api/");
    if (url.origin !== location.origin || idx === -1 || !window.MOLGANG_ENGINE) {
      return nativeFetch(input, init); // not an engine route — pass through untouched
    }

    // Path-prefix-safe: keep everything from "/api/" on, INCLUDING the query
    // tail, so "/openchem/molgang/api/state?sid=…" → "/api/state?sid=…".
    const path = url.pathname.slice(idx) + url.search;
    const method = String(
      init.method || (typeof input === "object" && input && input.method) || "GET"
    ).toUpperCase();

    let body = null;
    const raw = init.body != null ? init.body
      : (typeof input === "object" && input && typeof input.text === "function" && input.body != null ? input : null);
    if (raw != null) {
      try {
        const text = typeof raw === "string" ? raw
          : typeof raw.text === "function" ? await raw.clone().text()
          : await new Response(raw).text();
        body = text ? JSON.parse(text) : null;
      } catch (e) {
        body = null; // non-JSON body: the engine routes only take JSON anyway
      }
    }

    try {
      const r = await window.MOLGANG_ENGINE.api(path, method, body);
      // Serverless envelope: {status, body}. Tolerate a bare legacy object too.
      const shaped = r && typeof r === "object" && typeof r.status === "number" && "body" in r;
      const status = shaped ? r.status : 200;
      const payload = shaped ? r.body : r;
      return new Response(JSON.stringify(payload == null ? {} : payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      // Engine-level failure (worker gone, bridge exception): non-2xx JSON so
      // every `if (r.error) showToast(...)` call site surfaces it. Only the
      // message's first line crosses the boundary — never a stack trace.
      const msg = String((err && err.message) || err).split("\n", 1)[0].slice(0, 200);
      console.error("engine api error:", err);
      return new Response(
        JSON.stringify({ error: msg }),
        { status: 500, headers: { "Content-Type": "application/json" } });
    }
  };
}

function installWorldSocketStub() {
  if (window.__MOLGANG_WS_BRIDGED) return;
  window.__MOLGANG_WS_BRIDGED = true;
  const NativeWebSocket = window.WebSocket;
  if (!NativeWebSocket) return;

  function BridgedWebSocket(url, protocols) {
    if (!String(url).includes("/ws/world/")) return new NativeWebSocket(url, protocols);
    // Inert world socket: there is no push server — the engine is in-tab and
    // app.js's 1.5s poll drives refreshes. Staying CONNECTING forever means
    // app.js neither treats it as open nor reconnect-spams the console.
    return {
      url: String(url),
      readyState: NativeWebSocket.CONNECTING,
      binaryType: "blob",
      send() {},
      close() { this.readyState = NativeWebSocket.CLOSED; },
      onopen: null, onmessage: null, onerror: null, onclose: null,
      addEventListener() {}, removeEventListener() {},
      dispatchEvent() { return false; },
    };
  }
  for (const k of ["CONNECTING", "OPEN", "CLOSING", "CLOSED"]) {
    BridgedWebSocket[k] = NativeWebSocket[k];
  }
  BridgedWebSocket.prototype = NativeWebSocket.prototype;
  window.WebSocket = BridgedWebSocket;
}

function loadClassicScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-molgang-classic="${src}"]`)) return resolve();
    const s = document.createElement("script"); // classic script, NOT a module
    s.src = src;
    s.dataset.molgangClassic = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load " + src));
    document.body.appendChild(s);
  });
}

installFetchBridge();
installWorldSocketStub();

// Classic render layer, same order as web/index.html. config.js must precede
// app.js (BASE resolution) and i18n.js must precede it (window.I18N).
if (!("MOLGANG_API" in window)) await loadClassicScript("./config.js");
if (!window.I18N) await loadClassicScript("./i18n.js");
await loadClassicScript("./app.js");
