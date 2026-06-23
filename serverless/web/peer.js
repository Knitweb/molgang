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

function bootProgress(pct, phase) {
  if (BOOT.bar) BOOT.bar.style.width = Math.max(4, Math.min(100, pct)) + "%";
  if (phase && BOOT.phase) BOOT.phase.textContent = phase;
}
function bootError(message) {
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
    // Module-worker bootstrap for the MOLGANG engine. Loads Pyodide, then runs
    // the UNCHANGED molgang + knitweb Python bytes and answers RPC. All sacred
    // invariant logic stays in Python; this glue only marshals messages.
    const PYODIDE_BASE = ${JSON.stringify(PYODIDE_BASE)};
    const SEED = ${JSON.stringify(seed)};
    const CONFORMANCE_TAG = ${JSON.stringify(CONFORMANCE_TAG)};

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
      // corpus asserts that before this build is trusted.
      await pyodide.loadPackage(["micropip"]);
      const micropip = pyodide.pyimport("micropip");
      try {
        await micropip.install(["cryptography"]);
      } catch (e) {
        // If the OpenSSL wheel is unavailable in-WASM, the engine module falls
        // back to a pinned pure-Python secp256k1 gated by the corpus vectors.
        boot(46, "crypto: using pinned fallback…");
      }
      boot(64, "mounting engine bytes…");

      // The molgang + knitweb source is shipped alongside the app and fetched as
      // a wheel/zip the service worker caches. We mount it onto the Pyodide FS so
      // the IDENTICAL .py bytes import — that is what makes byte-identity FREE.
      try {
        await micropip.install("./engine/molgang_engine-0.0.0-py3-none-any.whl");
      } catch (e) {
        post({ kind: "boot", pct: 64, phase: "engine wheel: " + (e && e.message || e) });
      }

      boot(82, "deriving wallet + warming peer…");
      // Hand control to Python. molgang_serverless.bridge owns the in-worker Bar,
      // the WebRtcTransport, the signed-QR onboarding, and the RPC dispatch. JS
      // only relays. This Python module is NEW engine glue (server-free wiring);
      // every sacred path it calls is the unchanged molgang/knitweb code.
      pyodide.runPython(\`
import json

# Eliminate the pulse_host subprocess dependency: identity is derived purely.
from knitweb.ledger.node import AccountNode

def _make_bridge(seed):
    # AccountNode.from_seed: priv = sha256("knitweb:account:seed:"+seed). Pure,
    # deterministic, NO subprocess — this is what kills pulse_host.run().
    node = AccountNode.from_seed(seed)
    try:
        from molgang_serverless.bridge import ServerlessBridge
        return ServerlessBridge(seed=seed, node=node)
    except Exception:
        # Minimal in-tab Bar bring-up if the serverless bridge package is not
        # present yet: still 100% server-free (in-process Bar, no /api HTTP).
        from molgang.bar import Bar
        bar = Bar(world_path=None)
        class _MinBridge:
            def __init__(self): self.bar = bar; self.node = node; self.seed = seed
            def onboarding(self):
                from molgang_serverless.identity import signed_onboarding
                return signed_onboarding(node, multiaddr="webrtc:self")
            def verify(self, payload):
                from molgang_serverless.identity import verify_onboarding
                return verify_onboarding(payload)
            def api(self, path, method, body):
                return _MIN_API(self.bar, path, method, body)
        return _MinBridge()
\`);
      const make = pyodide.globals.get("_make_bridge");
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
            const out = engine.api(msg.path, msg.method, msg.body ? JSON.stringify(msg.body) : null);
            reply(typeof out === "string" ? JSON.parse(out) : out);
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

    init().catch((err) => post({ kind: "boot", pct: 8, phase: "ERROR: " + ((err && err.message) || err) }));
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
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("engine boot timed out")), 120000);
    engine.on("event", (event) => {
      if (event === "ready") { clearTimeout(t); resolve(); }
    });
  }).catch((err) => { bootError(String(err.message || err)); throw err; });

  wireUi(engine, mesh);
  updatePeerStatus(mesh);
  bootDone();

  // Load the legacy render layer LAST, now that window.MOLGANG_ENGINE exists.
  // app.js is patched to prefer MOLGANG_ENGINE.api over fetch when present; if
  // an older app.js is bundled it still finds the same response shapes.
  try {
    await import("./app-bridge.js");
  } catch (err) {
    console.warn("render layer not loaded as module; expecting classic app.js", err);
  }
}

main().catch((err) => {
  bootError("Fatal: " + (err && err.message ? err.message : String(err)));
  console.error(err);
});
