// serverless/web/transport_webrtc.js
//
// MOLGANG — WebRTC DataChannel carrier for the pulse wire protocol.
//
// Canonical server-free architecture (Variant A): every browser tab IS a full
// Knitweb peer running the *unchanged* molgang + knitweb Python bytes via Pyodide
// in a module-type Web Worker. JS is only the shell. A browser cannot expose an
// RTCPeerConnection / RTCDataChannel to WASM directly, so this file owns those
// browser-native objects and hands the Python engine a single seam:
//
//   * outbound: the Python WebRtcTransport.dial() posts an opaque, already-framed
//     request (the exact bytes write_frame_bytes() produced) tagged with an
//     integer rid; we channel.send() it and resolve when the correlated reply
//     frame returns.
//   * inbound:  a peer's channel.onmessage hands us an opaque framed request; we
//     post it (with its rid + the verified sender pubkey) up to the worker, which
//     calls read_frame_bytes() + _dispatch, and posts the framed reply back down
//     for us to channel.send() to the originating peer.
//
// BYTE-IDENTITY (sacred invariant c): this module is a DUMB PIPE. It never
// constructs, parses, mutates, re-orders, or re-encodes the canonical-CBOR body
// of a frame, and it never touches a signed / hashed / CID / faucet / economic
// byte. The frame bytes it carries are produced and consumed only by the Python
// wire layer (knitweb.p2p.wire). The two framing helpers below exist solely so
// the JS shell can sanity-check the 4-byte length prefix and enforce the SAME
// MAX_FRAME_BYTES ceiling before a frame crosses the worker boundary — they are
// byte-for-byte compatible with wire.py, never an alternative encoder.
//
// INVARIANTS honored here:
//   (a) integer-only: rid is an integer counter (incremented, never a clock).
//   (b) no wall-clock / no randomness on any decision/ordering path. The only
//       randomness is WebCrypto getRandomValues for mailbox/nonce ids (transport
//       routing only, never a hashed/signed/ordering input) — NEVER Math.random.
//   (c) byte-identity: opaque carriage only; see above.
//
// VOCABULARY: this is the Knitweb. Knit / Fiber / Pulse / spiders / PLS.

"use strict";

// ---------------------------------------------------------------------------
// Framing constants — MUST stay byte-identical to knitweb/p2p/wire.py.
// ---------------------------------------------------------------------------

// Hard per-frame byte ceiling for every wire envelope. LIVENESS COUPLING: this
// MUST equal wire.MAX_FRAME_BYTES (8 MiB) which is itself coupled to
// inventory.SERVE_BYTES_PER_WINDOW — lowering it would silently starve large
// record fetches. We keep the identical constant so a frame the Python layer
// accepted is never rejected by the shell and vice-versa.
export const MAX_FRAME_BYTES = 8 * 1024 * 1024; // 8388608

// Length-prefix width (4-byte big-endian), matching len.to_bytes(4, "big").
const LENGTH_PREFIX_BYTES = 4;

// A DataChannel "message" carries exactly one whole frame. WebRTC SCTP delivers
// messages atomically (no stream re-assembly needed), so unlike a TCP stream we
// never have to buffer partial frames — but we still validate the prefix so a
// malformed/oversized frame is dropped at the shell with the same ceiling the
// Python read_frame_bytes() enforces.

export class WireFrameError extends Error {}

// Read the big-endian length prefix and return the body byte-view, validating
// the same way wire.read_frame_bytes does: prefix present, n > 0, n <=
// MAX_FRAME_BYTES, and the declared length matches the payload exactly. Returns
// the raw frame Uint8Array unchanged (we hand the WHOLE frame, prefix included,
// to the worker so Python re-validates from the same bytes — belt and braces).
export function validateFrame(frame) {
  if (!(frame instanceof Uint8Array)) {
    throw new WireFrameError("frame must be a Uint8Array");
  }
  if (frame.length < LENGTH_PREFIX_BYTES) {
    throw new WireFrameError("truncated frame");
  }
  // Big-endian 4-byte length (mirrors int.from_bytes(frame[:4], "big")).
  const n =
    (frame[0] << 24) | (frame[1] << 16) | (frame[2] << 8) | frame[3];
  // (<<24) can produce a negative int32 for the top bit; coerce to unsigned.
  const length = n >>> 0;
  if (length <= 0) {
    throw new WireFrameError("empty frame");
  }
  if (length > MAX_FRAME_BYTES) {
    throw new WireFrameError(
      "frame too large: " + length + " > " + MAX_FRAME_BYTES
    );
  }
  if (frame.length - LENGTH_PREFIX_BYTES !== length) {
    throw new WireFrameError("frame length prefix does not match payload");
  }
  return frame;
}

// Guard an outbound frame the worker handed down: it was produced by
// write_frame_bytes() (which already prefixed + checked the ceiling), so this is
// a defensive re-check before it leaves the tab. We do NOT build the prefix here
// — the worker already did — so no JS encoder ever sits on the signed path.
export function guardOutbound(frame) {
  return validateFrame(frame);
}

// ---------------------------------------------------------------------------
// Identifiers — WebCrypto CSPRNG only (never Math.random). These are transport
// routing tokens (a per-tab inbound "mailbox" id and SDP/handshake nonces); they
// never enter a canonical / hashed / signed / ordering byte. A predictable nonce
// would weaken the signed-QR onboarding handshake, so all entropy is CSPRNG.
// ---------------------------------------------------------------------------

function randomHex(nBytes) {
  const buf = new Uint8Array(nBytes);
  (globalThis.crypto || self.crypto).getRandomValues(buf);
  let out = "";
  for (let i = 0; i < buf.length; i++) {
    out += buf[i].toString(16).padStart(2, "0");
  }
  return out;
}

// ---------------------------------------------------------------------------
// A single peer connection: one RTCPeerConnection + one reliable, ordered
// RTCDataChannel carrying length-prefixed canonical-CBOR frames.
// ---------------------------------------------------------------------------

const DEFAULT_ICE_SERVERS = [
  // STUN is stateless and swappable: ship a LIST, never hard-depend on one host.
  // (Reflexive-address discovery only; STUN holds no app state.) A symmetric-NAT
  // / CGNAT pair that cannot hole-punch falls back to a TURN-like relay carrying
  // OPAQUE frames — configured by the caller, documented, not the norm.
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];

class PeerConnection {
  // @param {string} peerKey  verified 33-byte compressed pubkey hex of the
  //                          remote peer (from the wallet-signed QR handshake).
  //                          Bound here so every inbound frame is attributed to
  //                          the AUTHENTICATED identity, never a self-asserted one.
  constructor(peerKey, opts, transport) {
    this.peerKey = peerKey;
    this.transport = transport;
    this.iceServers = (opts && opts.iceServers) || DEFAULT_ICE_SERVERS;
    this.pc = new RTCPeerConnection({ iceServers: this.iceServers });
    this.channel = null;
    this.ready = false;
    this._readyWaiters = [];
    this._closed = false;
    this.pc.ondatachannel = (ev) => this._attachChannel(ev.channel);
    this.pc.onconnectionstatechange = () => {
      const st = this.pc.connectionState;
      if (st === "failed" || st === "closed" || st === "disconnected") {
        this.close();
      }
    };
  }

  // Caller (offerer) opens the channel; the answerer receives it via
  // ondatachannel. Reliable + ordered so the framed request/reply RPC sees a
  // clean message stream (we never have to re-assemble a frame).
  createChannel() {
    const ch = this.pc.createDataChannel("knitweb", {
      ordered: true,
      // omitting maxRetransmits/maxPacketLifeTime => fully reliable.
    });
    this._attachChannel(ch);
    return ch;
  }

  _attachChannel(ch) {
    this.channel = ch;
    ch.binaryType = "arraybuffer";
    ch.onopen = () => {
      this.ready = true;
      const waiters = this._readyWaiters;
      this._readyWaiters = [];
      for (const w of waiters) w();
    };
    ch.onclose = () => this.close();
    ch.onmessage = (ev) => this._onMessage(ev.data);
  }

  whenReady() {
    if (this.ready) return Promise.resolve();
    if (this._closed) return Promise.reject(new Error("peer connection closed"));
    return new Promise((resolve) => this._readyWaiters.push(resolve));
  }

  // An inbound DataChannel message is exactly one frame (request OR reply). We
  // never parse the body; we read only the transport-envelope correlation keys
  // the Python layer placed at the front-of-band via a tiny fixed header the
  // worker prepends/strips. To keep JS off the CBOR path entirely, correlation
  // travels in a 1-byte kind tag + 4-byte big-endian rid PREFIXED ahead of the
  // opaque frame by the worker on send, and stripped by the worker on receive.
  // Here we only split that fixed header so we can route reply<->request without
  // ever decoding canonical CBOR.
  _onMessage(data) {
    let bytes;
    if (data instanceof ArrayBuffer) bytes = new Uint8Array(data);
    else if (data instanceof Uint8Array) bytes = data;
    else if (typeof data === "string") {
      // We only ever send binary; a string message is malformed — drop it.
      return;
    } else {
      return;
    }
    if (bytes.length < TRANSPORT_HEADER_BYTES) return; // too short to route
    const kind = bytes[0]; // KIND_REQUEST | KIND_REPLY
    const rid =
      ((bytes[1] << 24) | (bytes[2] << 16) | (bytes[3] << 8) | bytes[4]) >>> 0;
    const frame = bytes.subarray(TRANSPORT_HEADER_BYTES);
    try {
      validateFrame(frame);
    } catch (e) {
      // Malformed/oversized frame from this identified peer. Report a frame
      // fault upward so the worker can record the graded reputation penalty
      // against this.peerKey, exactly as the TCP/relay carriers do.
      this.transport._onFrameFault(this.peerKey, String(e && e.message));
      return;
    }
    if (kind === KIND_REPLY) {
      this.transport._resolveReply(rid, frame);
    } else if (kind === KIND_REQUEST) {
      this.transport._dispatchInbound(this.peerKey, rid, frame);
    }
  }

  // Send a frame with its fixed transport header (kind + rid). The frame body is
  // the OPAQUE bytes write_frame_bytes() produced — unchanged.
  send(kind, rid, frame) {
    if (this._closed || !this.channel || this.channel.readyState !== "open") {
      throw new Error("peer channel not open");
    }
    const out = new Uint8Array(TRANSPORT_HEADER_BYTES + frame.length);
    out[0] = kind & 0xff;
    out[1] = (rid >>> 24) & 0xff;
    out[2] = (rid >>> 16) & 0xff;
    out[3] = (rid >>> 8) & 0xff;
    out[4] = rid & 0xff;
    out.set(frame, TRANSPORT_HEADER_BYTES);
    this.channel.send(out.buffer);
  }

  close() {
    if (this._closed) return;
    this._closed = true;
    this.ready = false;
    try {
      if (this.channel) this.channel.close();
    } catch (e) {
      /* already gone */
    }
    try {
      this.pc.close();
    } catch (e) {
      /* already gone */
    }
    const waiters = this._readyWaiters;
    this._readyWaiters = [];
    for (const w of waiters) {
      // Reject pending whenReady() callers — they resolve to nothing; callers
      // race against a dial timeout enforced in the worker.
      try {
        w();
      } catch (e) {
        /* noop */
      }
    }
    this.transport._dropPeer(this.peerKey, this);
  }
}

// Fixed transport header: 1-byte kind tag + 4-byte big-endian integer rid.
// rid is an INTEGER COUNTER (never a wall-clock value), so it touches no
// decision/ordering path — it only correlates a reply to its request, exactly
// like relay.py's _relay_rid.
const TRANSPORT_HEADER_BYTES = 5;
const KIND_REQUEST = 1;
const KIND_REPLY = 2;

// ---------------------------------------------------------------------------
// WebRtcTransport (JS side) — the shell half of the Python WebRtcTransport.
//
// It is driven over a postMessage RPC from the Pyodide worker. Conceptually:
//
//   worker -> shell : { op: "dial",  peerKey, rid, frame }   // outbound request
//   shell  -> worker: { op: "reply", rid, frame }            // correlated reply
//   shell  -> worker: { op: "inbound", peerKey, rid, frame } // inbound request
//   worker -> shell : { op: "respond", peerKey, rid, frame } // inbound reply
//   shell  -> worker: { op: "frame_fault", peerKey, error }  // malformed frame
//
// All `frame` payloads are OPAQUE length-prefixed canonical-CBOR bytes produced
// or consumed only by the Python wire layer.
// ---------------------------------------------------------------------------

export class WebRtcTransport {
  // @param {object} opts
  //   opts.postToWorker(msg, [transferList])  send an RPC up to the Pyodide worker
  //   opts.selfKey      this tab's 33-byte compressed pubkey hex (its identity)
  //   opts.iceServers   optional STUN/TURN list (defaults to public STUN list)
  //   opts.dialTimeoutMs optional integer ms ceiling for a correlated reply
  constructor(opts) {
    if (!opts || typeof opts.postToWorker !== "function") {
      throw new Error("WebRtcTransport requires opts.postToWorker");
    }
    this.postToWorker = opts.postToWorker;
    this.selfKey = opts.selfKey || "";
    this.iceServers = opts.iceServers || DEFAULT_ICE_SERVERS;
    this.dialTimeoutMs = opts.dialTimeoutMs || 30000; // matches relay _DIAL_TIMEOUT_S
    // Authenticated peers keyed by their verified 33-byte compressed pubkey hex.
    this._peers = new Map(); // peerKey -> PeerConnection
    // Pending inbound-reply waiters keyed by the integer rid we minted on dial.
    this._replyWaiters = new Map(); // rid -> { resolve, timer }
    // A per-tab inbound mailbox id, CSPRNG-minted (routing only, never hashed).
    this.mailbox = opts.mailbox || randomHex(16);
  }

  // ---- signaling (SDP offer/answer + ICE) --------------------------------
  //
  // First contact is established out-of-band: two peers exchange a wallet-signed
  // QR / deep-link carrying {pubkey, signed challenge, SDP}. The signature is
  // verified IN THE WORKER (crypto.verify) BEFORE any of these methods run — a
  // QR with an invalid/missing signature never reaches here, so admission is
  // signature-gated, never an unauthenticated backdoor. peerKey is therefore the
  // already-AUTHENTICATED identity of the remote peer.

  // Offerer side: create a connection + channel, return the local SDP offer to
  // embed in our outbound QR / signaling payload.
  async createOffer(peerKey) {
    const peer = this._ensurePeer(peerKey);
    peer.createChannel();
    const offer = await peer.pc.createOffer();
    await peer.pc.setLocalDescription(offer);
    await this._gatherIce(peer);
    return peer.pc.localDescription;
  }

  // Answerer side: accept a verified offer, return our SDP answer.
  async acceptOffer(peerKey, offer) {
    const peer = this._ensurePeer(peerKey);
    await peer.pc.setRemoteDescription(offer);
    const answer = await peer.pc.createAnswer();
    await peer.pc.setLocalDescription(answer);
    await this._gatherIce(peer);
    return peer.pc.localDescription;
  }

  // Offerer side: apply the peer's verified answer.
  async acceptAnswer(peerKey, answer) {
    const peer = this._peers.get(peerKey);
    if (!peer) throw new Error("no pending connection for peer");
    await peer.pc.setRemoteDescription(answer);
  }

  // Wait out ICE gathering so the SDP we hand back is complete (simplest path:
  // non-trickle, suitable for QR/store-and-forward signaling).
  _gatherIce(peer) {
    if (peer.pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const check = () => {
        if (peer.pc.iceGatheringState === "complete") {
          peer.pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      peer.pc.addEventListener("icegatheringstatechange", check);
    });
  }

  _ensurePeer(peerKey) {
    let peer = this._peers.get(peerKey);
    if (!peer || peer._closed) {
      peer = new PeerConnection(peerKey, { iceServers: this.iceServers }, this);
      this._peers.set(peerKey, peer);
    }
    return peer;
  }

  _dropPeer(peerKey, peer) {
    if (this._peers.get(peerKey) === peer) this._peers.delete(peerKey);
  }

  // ---- RPC: outbound dial (request -> correlated reply) ------------------
  //
  // Called by the worker. `frame` is the OPAQUE request frame; `rid` is the
  // integer correlation id the worker minted (mirrors relay.py _relay_rid). We
  // send it and resolve when the matching reply frame returns, or reject on the
  // integer-ms dial timeout.
  async dial(peerKey, rid, frame) {
    const peer = this._ensurePeer(peerKey);
    await peer.whenReady();
    guardOutbound(frame);
    const replyPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._replyWaiters.delete(rid);
        reject(new Error("webrtc dial timed out waiting for reply"));
      }, this.dialTimeoutMs);
      this._replyWaiters.set(rid, { resolve, reject, timer });
    });
    peer.send(KIND_REQUEST, rid, frame);
    return replyPromise; // resolves to the opaque reply frame (Uint8Array)
  }

  _resolveReply(rid, frame) {
    const waiter = this._replyWaiters.get(rid);
    if (!waiter) return; // unknown/expired rid — drop (no decode, no side effect)
    this._replyWaiters.delete(rid);
    clearTimeout(waiter.timer);
    waiter.resolve(frame);
  }

  // ---- RPC: inbound request -> hand to worker -> mail reply back ---------

  _dispatchInbound(peerKey, rid, frame) {
    // Hand the opaque request frame + the AUTHENTICATED peerKey up to the worker.
    // The worker calls read_frame_bytes(), stamps ENVELOPE_PEER_KEY = peerKey,
    // runs _dispatch, frames the response, and posts it back via respond().
    this.postToWorker(
      {
        op: "webrtc_inbound",
        peerKey: peerKey,
        rid: rid,
        frame: frame,
      },
      [frame.buffer]
    );
  }

  // Called by the worker with the framed reply to an inbound request.
  respond(peerKey, rid, frame) {
    const peer = this._peers.get(peerKey);
    if (!peer) return; // peer vanished mid-request — nothing to reply to
    guardOutbound(frame);
    try {
      peer.send(KIND_REPLY, rid, frame);
    } catch (e) {
      /* channel closed under us — drop the reply */
    }
  }

  _onFrameFault(peerKey, error) {
    this.postToWorker({ op: "webrtc_frame_fault", peerKey: peerKey, error: error });
  }

  // ---- lifecycle ---------------------------------------------------------

  // The address peers should use to reach this listener. transport="webrtc";
  // params carry the routing/identity the signaling ladder needs.
  localAddress() {
    return {
      transport: "webrtc",
      params: { pubkey: this.selfKey, mailbox: this.mailbox },
    };
  }

  close() {
    for (const peer of this._peers.values()) peer.close();
    this._peers.clear();
    for (const waiter of this._replyWaiters.values()) {
      clearTimeout(waiter.timer);
      waiter.reject(new Error("transport closed"));
    }
    this._replyWaiters.clear();
  }
}

// ---------------------------------------------------------------------------
// Worker-side message router glue. Wire this into the Pyodide worker's
// onmessage so RPCs from the Python WebRtcTransport reach the shell transport,
// and inbound requests reach the worker. Exported so the app shell can install
// it without re-implementing the op switch.
// ---------------------------------------------------------------------------

export function installWorkerBridge(transport, worker) {
  // Messages the worker (Python WebRtcTransport adapter) posts DOWN to the shell.
  worker.addEventListener("message", async (ev) => {
    const msg = ev.data;
    if (!msg || typeof msg.op !== "string") return;
    switch (msg.op) {
      case "webrtc_dial": {
        // { op, peerKey, rid, frame }  -> resolve with the reply frame
        try {
          const reply = await transport.dial(
            msg.peerKey,
            msg.rid >>> 0,
            asU8(msg.frame)
          );
          worker.postMessage(
            { op: "webrtc_dial_result", rid: msg.rid, frame: reply },
            [reply.buffer]
          );
        } catch (e) {
          worker.postMessage({
            op: "webrtc_dial_error",
            rid: msg.rid,
            error: String(e && e.message),
          });
        }
        break;
      }
      case "webrtc_respond": {
        // { op, peerKey, rid, frame }  -> reply to an inbound request
        transport.respond(msg.peerKey, msg.rid >>> 0, asU8(msg.frame));
        break;
      }
      case "webrtc_create_offer": {
        try {
          const sdp = await transport.createOffer(msg.peerKey);
          worker.postMessage({ op: "webrtc_offer", reqId: msg.reqId, sdp: sdp });
        } catch (e) {
          worker.postMessage({
            op: "webrtc_offer",
            reqId: msg.reqId,
            error: String(e && e.message),
          });
        }
        break;
      }
      case "webrtc_accept_offer": {
        try {
          const sdp = await transport.acceptOffer(msg.peerKey, msg.sdp);
          worker.postMessage({ op: "webrtc_answer", reqId: msg.reqId, sdp: sdp });
        } catch (e) {
          worker.postMessage({
            op: "webrtc_answer",
            reqId: msg.reqId,
            error: String(e && e.message),
          });
        }
        break;
      }
      case "webrtc_accept_answer": {
        try {
          await transport.acceptAnswer(msg.peerKey, msg.sdp);
        } catch (e) {
          /* surfaced to worker only if it asked; signaling races are tolerated */
        }
        break;
      }
      case "webrtc_close": {
        transport.close();
        break;
      }
      default:
        break;
    }
  });
}

function asU8(frame) {
  if (frame instanceof Uint8Array) return frame;
  if (frame instanceof ArrayBuffer) return new Uint8Array(frame);
  // A plain array of byte values (postMessage structured-clone fallback).
  if (Array.isArray(frame)) return Uint8Array.from(frame);
  throw new WireFrameError("frame must be bytes");
}
