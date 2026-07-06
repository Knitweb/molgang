// MOLGANG serverless peer bootstrap (main-thread ES module).
//
// ARCHITECTURE (Variant A — "real engine in every tab"):
//   • The REAL Knitweb peer is the UNCHANGED molgang + knitweb Python bytes,
//     run inside a module-type Web Worker via Pyodide/WASM (engine.worker.js,
//     emitted inline below as a Blob so this module stays the single shell file).
//   • This main-thread module is a THIN shell. It does ONLY browser-native work
//     the worker cannot: it owns the RTCPeerConnection / RTCDataChannel objects,
//     draws/scans the wallet-signed onboarding QR, talks to the engine over a
//     postMessage RPC, and registers the offline-first service worker.
//   • JS NEVER computes a faucet grant, a canonical-CBOR frame, a CIDv1, or a
//     signature. Those are sacred invariant paths (integer-only, byte-identical)
//     and they live ONLY in the WASM engine. JS moves OPAQUE frame bytes between
//     a DataChannel and the engine, and forwards intents — nothing more.
//
// REPLACES: the legacy thin client's `setInterval(refresh,1500)` + `fetch('/api/*')`.
// Each former HTTP route becomes a direct in-worker Bar method call, surfaced
// here as `engine.api(path, method, body)` with the SAME shapes the render layer
// already expects, so the existing app.js render code runs unchanged on top.

const BOOT = {
  bar: document.getElementById("boot-bar"),
  phase: document.getElementById("boot-phase"),
  err: document.getElementById("boot-err"),
  splash: document.getElementById("boot"),
};

let bootFailed = false;
function bootProgress(pct, phase) {
  if (bootFailed) return; // an error phase is STICKY: later progress must never overwrite it
  if (BOOT.bar) BOOT.bar.style.width = Math.max(4, Math.min(100, pct)) + "%";
  if (phase && BOOT.phase) BOOT.phase.textContent = phase;
}
function bootError(message) {
  bootFailed = true;
  if (BOOT.err) BOOT.err.textContent = message;
  if (BOOT.phase) BOOT.phase.textContent = "boot failed";
}
function bootDone() {
  if (BOOT.splash) BOOT.splash.classList.add("done");
  document.getElementById("app-header")?.classList.remove("hidden");
}

// Pinned Pyodide build. Pinning the exact version is part of the byte-identity
// discipline: the secp256k1 backend (cryptography/OpenSSL in-WASM) must emit
// DER/low-S signatures byte-identical to native CPython, and that is asserted by
// the conformance corpus (see CONFORMANCE_TAG) before this build is trusted in
// production. Bump only behind a green corpus run.
const PYODIDE_VERSION = "0.26.2";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const CONFORMANCE_TAG = "molgang-wire-corpus/v1";

// ABSOLUTE URLs, computed on the MAIN thread. The engine worker runs from a
// blob: URL, and a blob URL cannot base relative fetches — micropip.install
// of "./engine/….whl" inside the worker threw "Failed to parse URL" and the
// engine never booted. Resolving against location.href here keeps the app
// path-relative (works at / or under any subpath on a dumb file host).
const ENGINE_WHEEL_URL = new URL(
  "engine/molgang_engine-0.0.0-py3-none-any.whl", location.href).href;
const BRIDGE_PY_URL = new URL("engine/serverless_api.py", location.href).href;

// ---------------------------------------------------------------------------
// Device seed (the ONLY secret JS handles, and it never leaves this origin).
// ---------------------------------------------------------------------------
// The engine derives identity as AccountNode.from_seed(seed) where
//   priv = sha256("knitweb:account:seed:" + seed)   (knitweb/ledger/node.py:61)
// so the seed is the root of the device wallet. We keep the SAME localStorage
// key the legacy shell used (molgang_device) so an upgrading tab keeps its
// account — no re-faucet, exactly as the persisted-device rule requires.
// Entropy is WebCrypto getRandomValues (CSPRNG), NEVER Math.random: a
// predictable seed would undermine the signature-gated QR onboarding.
function deviceSeed() {
  let d = localStorage.getItem("molgang_device");
  if (!d) {
    const buf = new Uint8Array(32);
    crypto.getRandomValues(buf);
    d = Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("molgang_device", d);
  }
  return d;
}

// ---------------------------------------------------------------------------
// Engine RPC client (main thread <-> Pyodide worker).
// ---------------------------------------------------------------------------
// A small correlation-id request/response shim over postMessage. The engine
// worker answers `api` calls (the former /api/* routes), `qr-mine` (produce the
// signed onboarding payload), `qr-verify` (crypto.verify a scanned payload
// BEFORE any channel opens), and `frame-in` (hand an inbound DataChannel frame
// to the in-worker WebRtcTransport). The worker calls back with `frame-out`
// (opaque bytes to send on a DataChannel) and `event` (push state changes).
class Engine {
  constructor(worker) {
    this.worker = worker;
    this.seq = 1;
    this.pending = new Map();
    this.listeners = { event: [], frameOut: [] };
    worker.addEventListener("message", (ev) => this._onMessage(ev.data));
  }

  _onMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.kind === "reply") {
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error));
      else p.resolve(msg.result);
      return;
    }
    if (msg.kind === "frame-out") {
      // Opaque, length-prefixed canonical-CBOR bytes the engine wants sent to a
      // peer DataChannel. We do not (and must not) inspect them.
      for (const fn of this.listeners.frameOut) fn(msg.peer, msg.frame);
      return;
    }
    if (msg.kind === "event") {
      for (const fn of this.listeners.event) fn(msg.event, msg.data);
      return;
    }
    if (msg.kind === "boot") {
      bootProgress(msg.pct, msg.phase);
      return;
    }
    if (msg.kind === "boot-error") {
      // Fatal engine-boot failure: surface it immediately (sticky) and let the
      // main() waiter reject NOW instead of sitting out the watchdog.
      bootError(msg.message);
      for (const fn of this.listeners.event) fn("boot-error", { message: msg.message });
      return;
    }
  }

  _call(kind, payload, transfer) {
    const id = this.seq++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ kind, id, ...payload }, transfer || []);
    });
  }

  // The /api/* compatibility surface. `path` is the legacy route (e.g.
  // "/api/state?sid=…"); `method`/`body` mirror the old fetch wrapper so the
  // render layer is unchanged. The engine dispatches to the in-worker Bar.
  api(path, method = "GET", body = null) {
    return this._call("api", { path, method, body });
  }

  // Produce THIS device's wallet-signed onboarding payload (engine signs it).
  myOnboarding() {
    return this._call("qr-mine", {});
  }

  // Verify a SCANNED peer's onboarding payload end-to-end (engine runs
  // crypto.verify over the domain-tagged pre-image). Returns
  // {ok, pubkey, multiaddr, fingerprint} — ok=false rejects admission.
  verifyOnboarding(payload) {
    return this._call("qr-verify", { payload });
  }

  // Register an authenticated WebRTC peer (pubkey already verified) so the
  // in-worker WebRtcTransport stamps frames from it as ENVELOPE_PEER_KEY.
  registerPeer(peerId, pubkey) {
    return this._call("peer-add", { peerId, pubkey });
  }
  dropPeer(peerId) {
    return this._call("peer-drop", { peerId });
  }

  // Hand one inbound DataChannel frame (opaque bytes) to the engine transport.
  // The bytes are transferred (zero-copy) — never parsed in JS.
  inboundFrame(peerId, frame) {
    return this._call("frame-in", { peerId, frame }, [frame.buffer ? frame.buffer : frame]);
  }

  on(event, fn) {
    if (event === "frame-out") this.listeners.frameOut.push(fn);
    else this.listeners.event.push(fn);
  }
}

// ---------------------------------------------------------------------------
// WebRTC plumbing (browser-native; lives in JS because the worker has no
// access to RTCPeerConnection). The DataChannel carries ONLY opaque frames the
// engine produced/consumes via write_frame_bytes/read_frame_bytes.
// ---------------------------------------------------------------------------
// Public STUN list — stateless and SWAPPABLE. We ship several and never
// hard-depend on one host (a STUN server only learns a reflexive host:port; it
// holds no app state). A symmetric-NAT pair that never hole-punches falls back
// to the optional relay carrier in the engine (encrypted/opaque frames only).
const STUN_SERVERS = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
  { urls: "stun:stun.cloudflare.com:3478" },
];

class WebRtcMesh {
  constructor(engine) {
    this.engine = engine;
    this.peers = new Map(); // peerId -> { pc, channel, pubkey }
    // When the engine wants to send a frame to a peer, route it to that peer's
    // DataChannel. The engine addresses peers by the same id we registered.
    engine.on("frame-out", (peerId, frame) => this._send(peerId, frame));
  }

  _newConnection(peerId, pubkey) {
    const pc = new RTCPeerConnection({ iceServers: STUN_SERVERS });
    const rec = { pc, channel: null, pubkey };
    this.peers.set(peerId, rec);

    pc.onconnectionstatechange = () => {
      if (["failed", "closed", "disconnected"].includes(pc.connectionState)) {
        this._teardown(peerId);
      }
      updatePeerStatus(this);
    };

    const wire = (channel) => {
      rec.channel = channel;
      channel.binaryType = "arraybuffer";
      channel.onopen = () => updatePeerStatus(this);
      channel.onclose = () => this._teardown(peerId);
      channel.onmessage = (ev) => {
        // Opaque frame from the peer -> straight into the engine transport.
        // We pass a fresh Uint8Array view and transfer its buffer; JS never
        // decodes a single byte of a signed/hashed frame.
        const buf = ev.data instanceof ArrayBuffer ? new Uint8Array(ev.data) : new Uint8Array(ev.data.buffer || ev.data);
        this.engine.inboundFrame(peerId, buf);
      };
    };
    pc.ondatachannel = (ev) => wire(ev.channel);
    return { pc, rec, wire };
  }

  // Offerer side: create the channel + SDP offer (after the peer's QR signature
  // has ALREADY been verified by the engine — verify-before-connect).
  async createOffer(peerId, pubkey) {
    const { pc, wire } = this._newConnection(peerId, pubkey);
    const channel = pc.createDataChannel("knitweb", { ordered: true });
    wire(channel);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await this._gatheringComplete(pc);
    await this.engine.registerPeer(peerId, pubkey);
    return pc.localDescription;
  }

  // Answerer side: accept a verified offer, return an answer.
  async acceptOffer(peerId, pubkey, offer) {
    const { pc } = this._newConnection(peerId, pubkey);
    await pc.setRemoteDescription(offer);
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await this._gatheringComplete(pc);
    await this.engine.registerPeer(peerId, pubkey);
    return pc.localDescription;
  }

  async acceptAnswer(peerId, answer) {
    const rec = this.peers.get(peerId);
    if (rec) await rec.pc.setRemoteDescription(answer);
  }

  _gatheringComplete(pc) {
    // Non-trickle: wait for ICE gathering so the SDP we put in the QR/relay is
    // complete and self-contained (simplest serverless signaling).
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const check = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", check);
      setTimeout(resolve, 4000); // bounded fallback; partial candidates still usable
    });
  }

  _send(peerId, frame) {
    const rec = this.peers.get(peerId);
    if (rec && rec.channel && rec.channel.readyState === "open") {
      rec.channel.send(frame);
    }
  }

  _teardown(peerId) {
    const rec = this.peers.get(peerId);
    if (!rec) return;
    try { rec.channel && rec.channel.close(); } catch (_) {}
    try { rec.pc.close(); } catch (_) {}
    this.peers.delete(peerId);
    this.engine.dropPeer(peerId);
    updatePeerStatus(this);
  }

  count() {
    let n = 0;
    for (const rec of this.peers.values()) {
      if (rec.channel && rec.channel.readyState === "open") n++;
    }
    return n;
  }
}

function updatePeerStatus(mesh) {
  const stateEl = document.getElementById("peer-state");
  const connsEl = document.getElementById("peer-conns");
  if (connsEl) connsEl.textContent = String(mesh.count());
  if (stateEl) {
    if (mesh.count() > 0) { stateEl.textContent = "live"; stateEl.className = "ok"; }
    else { stateEl.textContent = "solo"; stateEl.className = "warn"; }
  }
}

// ---------------------------------------------------------------------------
// QR onboarding UI (signature-gated). The payload that goes IN the QR is signed
// by the engine; a scanned payload is verified by the engine BEFORE connect.
// ---------------------------------------------------------------------------
async function showMyQr(engine, mesh) {
  const modal = document.getElementById("qr-modal");
  const canvas = document.getElementById("qr-canvas");
  const video = document.getElementById("qr-video");
  const fp = document.getElementById("qr-fingerprint");
  const title = document.getElementById("qr-title");
  const hint = document.getElementById("qr-hint");
  const scanStatus = document.getElementById("qr-scan-status");

  title.textContent = "📷 Your peer QR";
  hint.textContent = "Have another device scan this to open a direct, wallet-verified link.";
  scanStatus.textContent = "";
  canvas.classList.remove("hidden");
  video.classList.add("hidden");

  const onboarding = await engine.myOnboarding();
  // The payload is a compact JSON string the engine produced + signed. The QR
  // just transports it; the SCANNER re-verifies the signature before connecting.
  const text = JSON.stringify(onboarding);
  const { drawQr } = await import("./qr.js");
  drawQr(canvas, text);
  fp.textContent = "wallet " + (onboarding.fingerprint || onboarding.pubkey?.slice(0, 16) || "");
  modal.classList.remove("hidden");
}

async function scanPeerQr(engine, mesh) {
  const modal = document.getElementById("qr-modal");
  const canvas = document.getElementById("qr-canvas");
  const video = document.getElementById("qr-video");
  const title = document.getElementById("qr-title");
  const hint = document.getElementById("qr-hint");
  const scanStatus = document.getElementById("qr-scan-status");

  title.textContent = "🔗 Scan a peer QR";
  hint.textContent = "Point the camera at another device's MOLGANG peer QR.";
  canvas.classList.add("hidden");
  video.classList.remove("hidden");
  modal.classList.remove("hidden");

  const { scanQr } = await import("./qr.js");
  let raw;
  try {
    raw = await scanQr(video, scanStatus);
  } catch (err) {
    scanStatus.textContent = "camera unavailable: " + err.message;
    return;
  }
  let payload;
  try { payload = JSON.parse(raw); } catch (_) {
    scanStatus.textContent = "not a MOLGANG peer QR.";
    return;
  }

  // VERIFY-BEFORE-CONNECT. The engine runs crypto.verify over the exact
  // domain-tagged signed pre-image. An invalid/missing signature = no channel.
  scanStatus.textContent = "verifying signature…";
  const v = await engine.verifyOnboarding(payload);
  if (!v.ok) {
    scanStatus.textContent = "✗ rejected: signature did not verify. No link opened.";
    return;
  }
  scanStatus.textContent = "✓ verified " + (v.fingerprint || v.pubkey.slice(0, 16)) + " — opening link…";

  // Authenticated. Open the WebRTC link. The role (offer/answer) is decided by
  // pubkey ordering so two peers don't both offer. The SDP answer is returned
  // to the user to relay back (or, once one peer is known, the engine's
  // discovery/PEX path brokers further handshakes peer-to-peer).
  const peerId = v.pubkey;
  const iAmOfferer = await engine.myOnboarding().then((m) => m.pubkey < v.pubkey);
  try {
    if (payload.sdp) {
      // The QR already carried an SDP offer -> we answer.
      const answer = await mesh.acceptOffer(peerId, v.pubkey, payload.sdp);
      scanStatus.textContent = "✓ linked. Share this answer back if prompted.";
      // Hand the answer to the engine relay path for delivery if available.
      engine.api("/peer/answer", "POST", { peerId, sdp: answer }).catch(() => {});
    } else if (iAmOfferer) {
      const offer = await mesh.createOffer(peerId, v.pubkey);
      engine.api("/peer/offer", "POST", { peerId, sdp: offer }).catch(() => {});
      scanStatus.textContent = "✓ verified. Offer sent over relay; waiting for answer…";
    } else {
      scanStatus.textContent = "✓ verified. Waiting for the other device to offer…";
    }
  } catch (err) {
    scanStatus.textContent = "link error: " + err.message;
  }
}

// ---------------------------------------------------------------------------
// Service worker (offline-first PWA). Caches the shell + Pyodide wasm so the
// SECOND load boots offline and near-instant. Best-effort; failure is non-fatal.
// ---------------------------------------------------------------------------
async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("./sw.js", { scope: "./" });
  } catch (err) {
    console.warn("service worker registration failed", err);
  }
  // Browser storage is evictable; ask for durability so the device wallet seed
  // and woven Fibers survive. Best-effort (grant rates vary by UA).
  if (navigator.storage && navigator.storage.persist) {
    try { await navigator.storage.persist(); } catch (_) {}
  }
}

// ---------------------------------------------------------------------------
// Build the engine worker. We emit a tiny module-Worker bootstrap inline (as a
// Blob) whose ONLY job is to importScripts-free `import` the real worker module
// engine.worker.js. Keeping it a Blob means peer.js is the single shell file the
// page references while the worker is still a proper module worker (required:
// Pyodide cannot run under a classic worker's importScripts in this design).
// ---------------------------------------------------------------------------
function spawnEngineWorker() {
  const seed = deviceSeed();
  const bootstrap = `
    // Worker bootstrap for the MOLGANG engine. Loads Pyodide, installs the
    // UNCHANGED molgang + knitweb Python bytes (the wheel), runs the serverless
    // API bridge (engine/serverless_api.py) and answers RPC. All sacred
    // invariant logic stays in Python; this glue only marshals messages.
    // NOTE: this file runs from a blob: URL, so every URL below arrives
    // pre-resolved (absolute) from the main thread — a blob URL cannot base
    // relative fetches, which is exactly the bug that used to kill the boot.
    const PYODIDE_BASE = ${JSON.stringify(PYODIDE_BASE)};
    const SEED = ${JSON.stringify(seed)};
    const CONFORMANCE_TAG = ${JSON.stringify(CONFORMANCE_TAG)};
    const ENGINE_WHEEL_URL = ${JSON.stringify(ENGINE_WHEEL_URL)};
    const BRIDGE_PY_URL = ${JSON.stringify(BRIDGE_PY_URL)};

    function post(m, t) { self.postMessage(m, t || []); }
    function boot(pct, phase) { post({ kind: "boot", pct, phase }); }

    let pyodide = null;
    let engine = null; // the Python bridge object (PyProxy)

    async function init() {
      boot(8, "fetching WASM runtime…");
      importScripts(PYODIDE_BASE + "pyodide.js");
      boot(28, "starting Python…");
      pyodide = await self.loadPyodide({ indexURL: PYODIDE_BASE });
      boot(46, "loading crypto backend…");
      // secp256k1/SHA-256 lives in the 'cryptography' package (OpenSSL in-WASM).
      // It MUST emit DER/low-S bytes identical to native CPython; the conformance
      // corpus asserts that before this build is trusted. knitweb.core.crypto
      // hard-imports it, so a failure here is FATAL (fail fast, no watchdog).
      // "hashlib" is Pyodide's unvendored OpenSSL stdlib piece — without it
      // hashlib.pbkdf2_hmac (the device→wallet KDF in molgang.game) is missing.
      await pyodide.loadPackage(["micropip", "hashlib"]);
      const micropip = pyodide.pyimport("micropip");
      await micropip.install(["cryptography"]);
      boot(56, "loading graph tools…");
      // networkx powers the Web-tab graph explorer + the p2p simulation. It is
      // OPTIONAL: the bridge degrades those routes gracefully when absent
      // (e.g. a fully offline boot from the service-worker cache).
      try { await micropip.install(["networkx"]); }
      catch (e) { boot(56, "graph tools unavailable — continuing…"); }
      boot(64, "mounting engine bytes…");

      // The molgang + knitweb source is shipped alongside the app as ONE wheel
      // the service worker caches. Installing it makes the IDENTICAL .py bytes
      // import — that is what makes byte-identity FREE. Fatal on failure:
      // everything downstream imports molgang/knitweb.
      await micropip.install(ENGINE_WHEEL_URL);

      boot(78, "wiring the in-tab bar…");
      // The serverless API bridge is plain Python shipped next to the wheel
      // (engine/serverless_api.py): one Bar + the legacy /api/* dispatch +
      // the wallet-signed QR onboarding. Every sacred path it calls is the
      // unchanged molgang/knitweb code from the wheel.
      const bridgeResp = await fetch(BRIDGE_PY_URL);
      if (!bridgeResp.ok) throw new Error("bridge fetch failed: HTTP " + bridgeResp.status);
      pyodide.runPython(await bridgeResp.text());

      boot(88, "deriving wallet + warming peer…");
      // AccountNode.from_seed: priv = sha256("knitweb:account:seed:"+seed).
      // Pure, deterministic, NO subprocess — this is what kills pulse_host.run().
      const make = pyodide.globals.get("make_bridge");
      engine = make(SEED);
      make.destroy();

      boot(100, "ready");
      post({ kind: "event", event: "ready", data: { conformance: CONFORMANCE_TAG } });
    }

    // RPC dispatch. Each message maps to a bridge method; results are JSON-able.
    self.onmessage = async (ev) => {
      const msg = ev.data || {};
      const reply = (result, error) => post({ kind: "reply", id: msg.id, result, error });
      try {
        if (!engine) { reply(null, "engine not ready"); return; }
        switch (msg.kind) {
          case "api": {
            // Python returns json.dumps({status, body}) — the HTTP-shaped
            // envelope the fetch interceptor (app-bridge.js) wraps back into a
            // real Response for the unchanged render layer.
            const out = engine.api(msg.path, msg.method || "GET", msg.body ? JSON.stringify(msg.body) : null);
            reply(JSON.parse(out));
            break;
          }
          case "qr-mine": {
            const out = engine.onboarding();
            reply(typeof out === "string" ? JSON.parse(out) : out);
            break;
          }
          case "qr-verify": {
            const out = engine.verify(JSON.stringify(msg.payload));
            reply(typeof out === "string" ? JSON.parse(out) : out);
            break;
          }
          case "peer-add": { engine.add_peer(msg.peerId, msg.pubkey); reply({ ok: true }); break; }
          case "peer-drop": { engine.drop_peer(msg.peerId); reply({ ok: true }); break; }
          case "frame-in": {
            // Hand the opaque inbound frame to the engine transport. If it has a
            // reply frame to emit, the engine returns it and we ship it out.
            const u8 = msg.frame instanceof Uint8Array ? msg.frame : new Uint8Array(msg.frame);
            const out = engine.inbound_frame(msg.peerId, u8);
            if (out) {
              const bytes = out.toJs ? out.toJs() : out;
              post({ kind: "frame-out", peer: msg.peerId, frame: bytes }, [bytes.buffer]);
            }
            reply({ ok: true });
            break;
          }
          default: reply(null, "unknown rpc: " + msg.kind);
        }
      } catch (err) {
        reply(null, (err && err.message) || String(err));
      }
    };

    // A boot failure is FATAL and immediate: post a dedicated boot-error so the
    // main thread surfaces it (sticky) and stops waiting — no 120s watchdog.
    init().catch((err) => post({ kind: "boot-error", message: (err && err.message) || String(err) }));
  `;
  const blob = new Blob([bootstrap], { type: "text/javascript" });
  const url = URL.createObjectURL(blob);
  // Classic worker is fine for THIS bootstrap (it uses importScripts to load
  // pyodide.js); Pyodide itself runs its own module loading inside. We pick the
  // type that the pinned Pyodide build supports for in-worker use.
  return new Worker(url);
}

// ---------------------------------------------------------------------------
// Wire UI events to the engine + mesh. Replaces app.js's fetch('/api/*') glue.
// ---------------------------------------------------------------------------
function wireUi(engine, mesh) {
  document.getElementById("qr-show")?.addEventListener("click", () => showMyQr(engine, mesh));
  document.getElementById("qr-scan")?.addEventListener("click", () => scanPeerQr(engine, mesh));
  document.getElementById("qr-close")?.addEventListener("click", () => {
    document.getElementById("qr-modal")?.classList.add("hidden");
    const v = document.getElementById("qr-video");
    if (v && v.srcObject) { v.srcObject.getTracks().forEach((t) => t.stop()); v.srcObject = null; }
  });

  // Expose the SAME `api()` the legacy render layer expects, so app.js runs
  // unchanged on top of the in-tab engine instead of an HTTP backend. We install
  // a global shim that the (separately loaded) app.js will call.
  window.MOLGANG_ENGINE = {
    api: (path, method = "GET", body = null) => engine.api(path, method, body),
    seed: () => deviceSeed(),
    peers: () => mesh.count(),
  };
}

// ---------------------------------------------------------------------------
// Boot sequence.
// ---------------------------------------------------------------------------
async function main() {
  registerServiceWorker();
  bootProgress(4, "spawning engine worker…");

  const worker = spawnEngineWorker();
  const engine = new Engine(worker);
  const mesh = new WebRtcMesh(engine);

  // Wait for the engine to report ready (its Python bridge is constructed).
  // A worker boot-error rejects IMMEDIATELY — the watchdog is only for hangs.
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("engine boot timed out")), 120000);
    engine.on("event", (event, data) => {
      if (event === "ready") { clearTimeout(t); resolve(); }
      else if (event === "boot-error") {
        clearTimeout(t);
        reject(new Error((data && data.message) || "engine boot failed"));
      }
    });
  }).catch((err) => { bootError(String(err.message || err)); throw err; });

  wireUi(engine, mesh);
  updatePeerStatus(mesh);

  // Load the render bridge, now that window.MOLGANG_ENGINE exists. It installs
  // the fetch→engine interceptor, then loads the classic render layer
  // (config.js → i18n.js → app.js, vendored from web/) which runs unchanged on
  // top of the in-tab engine instead of an HTTP backend. The splash stays up
  // until the render layer is in — and stays (sticky) if it fails.
  try {
    await import("./app-bridge.js");
  } catch (err) {
    bootError("render layer failed to load: " + ((err && err.message) || err));
    throw err;
  }
  bootDone();
}

main().catch((err) => {
  bootError("Fatal: " + (err && err.message ? err.message : String(err)));
  console.error(err);
});
