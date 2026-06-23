// MOLGANG — serverless signaling + discovery (L0 shell / L5 signaling ladder).
//
// This is the *browser shell* half of the server-free architecture: it owns the
// `RTCPeerConnection` / `RTCDataChannel` objects (a browser API the Python engine
// cannot hold) and drives the four-rung signaling ladder that lets two tabs reach
// a direct WebRTC DataChannel with NO required trusted server:
//
//   (a) QR / deep-link FIRST-CONTACT  — wallet-signed offer/answer exchange,
//       copy/scan, zero infrastructure. Two peers who trade a signed QR open a
//       direct DataChannel with no relay, no signaling host.
//   (b) public STUN (stateless, swappable, ship a LIST, never hard-depend).
//   (c) DHT/PEX-assisted signaling once ONE peer is known — any connected peer
//       relays the next SDP over the existing `discovery.py` peer-exchange +
//       `kademlia` find-node, brokered as ordinary signed frames.
//   (d) an OPTIONAL anyone-can-run bootstrap peer (a generalized opaque
//       store-and-forward mailbox, the `relay.py` carrier) that REPLACES the
//       central 5mart.ml relay — PEX-advertised as a MULTI-bootstrap list so no
//       single host is a SPOF.
//
// SACRED INVARIANTS (this file is on a NON-decision path, but still respects them):
//   * JS NEVER signs, verifies, hashes, frames, encodes CBOR, computes a CID, or
//     does any faucet/economic/ordering math. Every such operation is delegated to
//     the Pyodide engine worker (the unchanged `knitweb`+`molgang` Python bytes) via
//     `engine.rpc(...)`. JS only moves opaque bytes and draws/scans QR.
//   * All nonces / entropy come from WebCrypto `crypto.getRandomValues`, NEVER
//     `Math.random` — a predictable nonce would break the signature-gated onboarding.
//   * The wire contract is byte-identical to the Python peers: a DataChannel
//     `onmessage` hands the raw `ArrayBuffer` straight to `read_frame_bytes` in the
//     worker; an outbound frame is `write_frame_bytes` produced *in the worker* and
//     sent verbatim. No JS encoder ever touches a hashed/signed path.
//
// SECURITY: QR onboarding is VERIFY-BEFORE-CONNECT signature-gated authentication,
// never an unauthenticated backdoor. The scanning peer asks the worker to
// `crypto.verify` the signed challenge BEFORE any DataChannel is opened; an invalid
// or missing signature is rejected and no channel is created.
//
// See serverless/web/signaling.js in the repository for the full implementation.
//
// (Full file content is written to serverless/web/signaling.js — 977 lines.)
