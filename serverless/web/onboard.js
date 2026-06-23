// MOLGANG -- wallet-signed QR node onboarding (browser side), SIGNATURE-GATED auth.
//
// This is the in-tab counterpart of serverless/src/molgang/webnode/onboard_verify.py and
// the server-free replacement for the central PHP `Onboard.php` challenge-response. A new
// node proves possession of its secp256k1 wallet key by SIGNING a fresh challenge; the
// admitting peer VERIFIES that signature BEFORE it opens any WebRTC DataChannel or admits
// the peer. There is NO code path here that admits a node without a valid wallet signature.
//
// Byte-identity is the whole point: `onboardPreimage()` below builds the EXACT same bytes
// as `onboard_preimage()` in onboard_verify.py, and signs/verifies with secp256k1 ECDSA
// over SHA-256 producing 33-byte compressed pubkey hex + DER signature hex -- so a challenge
// signed in this tab verifies in the Python peer and vice-versa. The wire/crypto contract:
//
//   * identity/signing = secp256k1 ECDSA over SHA-256; pubkey = 33-byte COMPRESSED hex;
//     signature = DER-encoded hex (knitweb.core.crypto; mirrored in relay_sync.py).
//   * the signed pre-image is a fixed, domain-tagged, newline-joined UTF-8 byte string --
//     exactly the discipline of relay_sync's "knitweb-relay:v1\n{to}\n{topic}\n{body}".
//     Here the tag is "knitweb-onboard:v1" and the joined fields are the challenge's
//     (scope, audience, nonce, issued, expires, device).
//
// SACRED INVARIANTS this file is careful NOT to break:
//   (a) INTEGER-ONLY on the decision/freshness path: `issued`/`expires`/`now_s` are integer
//       seconds compared with `<`/`>=` only -- never `/`, never `Date.now()/1000` without a
//       floor, never a float. The nonce/expiry math uses BigInt-safe integers (well within
//       Number's 2^53 for second-resolution time, but kept integral via `Math.trunc`).
//   (b) NO randomness on the DECISION path; the only randomness is the challenge NONCE, which
//       is sourced from WebCrypto `crypto.getRandomValues` (a CSPRNG) -- NEVER `Math.random`.
//       A predictable nonce would let a captured QR be replayed, so this is load-bearing.
//   (c) BYTE-IDENTITY: the pre-image, pubkey-hex, and DER-sig-hex are produced to match the
//       Python reference exactly. JS NEVER touches a faucet/CBOR/CID path -- only this signed
//       onboarding pre-image, which is plain UTF-8 bytes (no canonical CBOR needed here).
//
// Crypto backend: @noble/secp256k1 + @noble/hashes/sha256 -- the audited, dependency-light
// browser secp256k1. NOTE on low-S: Python's `cryptography` does NOT force low-S, while noble
// defaults to low-S on sign. That asymmetry does not break VERIFICATION (both libraries accept
// high- and low-S DER on verify), and onboarding only needs the signature to verify under the
// stated pubkey + pre-image -- so cross-runtime onboarding is sound. The golden-vector
// conformance gate (L6) pins exact DER bytes for the faucet/Knit/relay paths separately.
//
// VOCABULARY: this is the Knitweb. A node ONBOARDS onto the Web. Never say "loom".

import * as secp from "@noble/secp256k1";
import { sha256 } from "@noble/hashes/sha256";
import { hmac } from "@noble/hashes/hmac";
import { utf8ToBytes, bytesToHex, hexToBytes, concatBytes } from "@noble/hashes/utils";

// @noble/secp256k1 v2 is the minimal micro-package: its synchronous `sign` needs an
// HMAC-SHA256 implementation wired in (RFC-6979 deterministic-k), and it exposes only the
// COMPACT signature encoding. We wire the sync HMAC here and DER-(en/de)code ourselves below
// so the on-the-wire signature is DER hex -- byte-identical to Python `cryptography`'s output.
// (Wiring is idempotent; safe to import this module more than once.)
if (typeof secp.etc.hmacSha256Sync !== "function" || secp.etc.hmacSha256Sync.length === 0) {
  secp.etc.hmacSha256Sync = (key, ...msgs) => hmac(sha256, key, concatBytes(...msgs));
}

// ---------------------------------------------------------------------------
// Contract constants -- MUST byte-match onboard_verify.py
// ---------------------------------------------------------------------------

// Pre-image tag -- byte-identical to ONBOARD_PREIMAGE_TAG in onboard_verify.py.
export const ONBOARD_PREIMAGE_TAG = "knitweb-onboard:v1";

// The signature scheme the challenge commits to (matches crypto.SCHEME_SECP256K1_ECDSA).
export const ONBOARD_SCHEME = "secp256k1-ecdsa-sha256";

// Freshness window, in WHOLE SECONDS (integer). Mirrors onboard_verify.py.
export const DEFAULT_TTL_S = 600;
export const MAX_TTL_S = 3600;

// Nonce width -- 18 bytes == 36 lowercase-hex chars, matching NONCE_BYTES in the verifier.
export const NONCE_BYTES = 18;
export const NONCE_HEX_LEN = NONCE_BYTES * 2;

// QR / deep-link shape -- matches build_qr_uri / parse_qr_uri in onboard_verify.py.
const QR_SCHEME = "knitweb";
const QR_PATH = "onboard";
// Fixed field order so the URI is byte-stable across runtimes.
const QR_FIELDS = ["scope", "audience", "nonce", "issued", "expires", "device", "scheme"];

export class OnboardError extends Error {
  constructor(message) {
    super(message);
    this.name = "OnboardError";
  }
}

// ---------------------------------------------------------------------------
// Identity: deterministic wallet derived from the device seed (no subprocess,
// no server) -- the SAME derivation as AccountNode.from_seed in the Python peer:
//   priv = sha256("knitweb:account:seed:" + seed)
//   pub  = 33-byte compressed secp256k1 point of priv (hex)
// The seed is the DEVICE_ID already in localStorage; the private key never leaves
// this scope (in the real app it lives only inside the Pyodide worker).
// ---------------------------------------------------------------------------

const SEED_DOMAIN = "knitweb:account:seed:";

/** Derive the wallet private-key hex (32-byte scalar) from a device seed. */
export function privFromSeed(seed) {
  if (typeof seed !== "string" || seed.length === 0) {
    throw new OnboardError("seed must be a non-empty string");
  }
  const priv = sha256(utf8ToBytes(SEED_DOMAIN + seed)); // 32 bytes
  return bytesToHex(priv);
}

/** Derive the 33-byte COMPRESSED public-key hex from a private-key hex. */
export function publicFromPrivate(privHex) {
  const pub = secp.getPublicKey(hexToBytes(privHex), /* compressed */ true);
  return bytesToHex(pub);
}

/** Convenience: the full wallet identity {seed, priv, pub} for this device. */
export function walletFromSeed(seed) {
  const priv = privFromSeed(seed);
  return { seed, priv, pub: publicFromPrivate(priv) };
}

// ---------------------------------------------------------------------------
// Low-level crypto (secp256k1 ECDSA over SHA-256, DER sig hex) -- mirrors
// knitweb.core.crypto.sign / verify byte-for-byte on the hashing + encoding.
// ---------------------------------------------------------------------------

/** Sign a message (bytes) -> DER signature hex. Hashes with SHA-256 first, like the peer. */
export function signMessage(privHex, messageBytes) {
  const digest = sha256(messageBytes);
  // Sign the prehashed digest (the peer signs `Prehashed(SHA256)` over sha256(message)).
  // noble v2 returns a compact (r||s) signature; we DER-encode it ourselves so the wire form
  // is DER hex, identical in shape to Python `cryptography`'s `.hex()` DER output.
  const sig = secp.sign(digest, hexToBytes(privHex));
  const compact = sig.toCompactRawBytes(); // 64 bytes: 32-byte r || 32-byte s
  return derEncodeRS(compact.slice(0, 32), compact.slice(32, 64));
}

/** Verify a DER signature hex over a message (bytes) against a compressed pubkey hex. */
export function verifyMessage(pubHex, messageBytes, sigHex) {
  try {
    const digest = sha256(messageBytes);
    const { r, s } = derDecodeRS(hexToBytes(sigHex)); // accepts high- or low-S DER
    const compact = concatBytes(leftPad32(r), leftPad32(s));
    // lowS:false so a high-S DER signature minted by Python's `cryptography` (which does NOT
    // force low-S) still verifies -- onboarding only needs the proof to verify under the key.
    return secp.verify(compact, digest, hexToBytes(pubHex), { lowS: false });
  } catch (_e) {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Minimal DER (en/de)coder for an ECDSA (r, s) pair -- matches the ASN.1
// `SEQUENCE { INTEGER r, INTEGER s }` shape Python's `cryptography` emits, with
// minimal-length, sign-bit-safe INTEGER encoding (leading 0x00 only when the high
// bit is set; no superfluous leading zeros otherwise).
// ---------------------------------------------------------------------------

function derEncodeInt(bytes32) {
  let i = 0;
  while (i < bytes32.length - 1 && bytes32[i] === 0x00) i++; // strip leading zeros
  let body = bytes32.slice(i);
  if (body[0] & 0x80) body = concatBytes(Uint8Array.of(0x00), body); // sign bit -> pad
  return concatBytes(Uint8Array.of(0x02, body.length), body);
}

function derEncodeRS(r32, s32) {
  const rEnc = derEncodeInt(r32);
  const sEnc = derEncodeInt(s32);
  const seqBody = concatBytes(rEnc, sEnc);
  if (seqBody.length > 0x7f) {
    // A two-INTEGER secp256k1 signature is always < 128 bytes, so a long-form length here
    // means malformed input -- refuse rather than silently mis-frame.
    throw new OnboardError("DER signature body unexpectedly long");
  }
  return bytesToHex(concatBytes(Uint8Array.of(0x30, seqBody.length), seqBody));
}

function derDecodeRS(der) {
  let p = 0;
  if (der[p++] !== 0x30) throw new OnboardError("DER: expected SEQUENCE");
  const seqLen = der[p++];
  if (seqLen & 0x80) throw new OnboardError("DER: long-form length unsupported");
  if (p + seqLen !== der.length) throw new OnboardError("DER: trailing bytes");
  const readInt = () => {
    if (der[p++] !== 0x02) throw new OnboardError("DER: expected INTEGER");
    const len = der[p++];
    if (len & 0x80) throw new OnboardError("DER: long-form integer length unsupported");
    const v = der.slice(p, p + len);
    if (v.length !== len) throw new OnboardError("DER: truncated INTEGER");
    p += len;
    return v;
  };
  const r = readInt();
  const s = readInt();
  if (p !== der.length) throw new OnboardError("DER: trailing bytes after s");
  return { r, s };
}

/** Left-pad a big-endian integer's bytes to exactly 32 bytes (drops a DER sign-pad 0x00). */
function leftPad32(bytes) {
  let b = bytes;
  while (b.length > 32 && b[0] === 0x00) b = b.slice(1); // drop sign-padding
  if (b.length > 32) throw new OnboardError("integer wider than 32 bytes");
  const out = new Uint8Array(32);
  out.set(b, 32 - b.length);
  return out;
}

// ---------------------------------------------------------------------------
// The signed pre-image -- byte-identical to onboard_verify.onboard_preimage
// ---------------------------------------------------------------------------

/**
 * Build the EXACT bytes a node signs to answer a challenge. Layout:
 *   "knitweb-onboard:v1\n{scope}\n{audience}\n{nonce}\n{issued}\n{expires}\n{device}"
 * UTF-8 encoded. `issued`/`expires` are rendered as base-10 integers (no separators, no
 * float) so there is exactly one byte-string per challenge and the Python encoder agrees.
 * The pubkey is NOT in the pre-image -- it is the verifying key itself.
 */
export function onboardPreimage(ch) {
  const parts = [
    ONBOARD_PREIMAGE_TAG,
    ch.scope,
    ch.audience,
    ch.nonce,
    intStr(ch.issued),
    intStr(ch.expires),
    ch.device,
  ];
  return utf8ToBytes(parts.join("\n"));
}

// ---------------------------------------------------------------------------
// Issuing a challenge -- injected integer clock + WebCrypto CSPRNG nonce
// ---------------------------------------------------------------------------

/** Mint a CSPRNG hex nonce of exactly NONCE_BYTES bytes. NEVER uses Math.random. */
export function freshNonceHex() {
  const buf = new Uint8Array(NONCE_BYTES);
  globalThis.crypto.getRandomValues(buf); // WebCrypto CSPRNG -- load-bearing for anti-replay
  return bytesToHex(buf);
}

/**
 * Mint a fresh challenge for `device` onboarding into `scope`.
 * @param {object} opts
 * @param {string} opts.scope
 * @param {string} opts.device                onboarding node's DEVICE_ID
 * @param {number} opts.nowS                   current time as an INJECTED integer (seconds)
 * @param {string} [opts.audience=""]          admitting peer's compressed pubkey hex, or ""
 * @param {number} [opts.ttlS=DEFAULT_TTL_S]   window in whole seconds
 * @param {string} [opts.nonce]                override nonce (tests/golden vectors); else CSPRNG
 * @returns {object} challenge record
 */
export function issueChallenge({ scope, device, nowS, audience = "", ttlS = DEFAULT_TTL_S, nonce } = {}) {
  const now = requireInt(nowS, "nowS");
  if (now < 0) throw new OnboardError("nowS must be non-negative");
  const ttl = requireInt(ttlS, "ttlS");
  if (ttl <= 0) throw new OnboardError("ttlS must be a positive integer");
  if (ttl > MAX_TTL_S) throw new OnboardError(`ttlS exceeds MAX_TTL_S=${MAX_TTL_S}`);
  if (audience !== "" && !isCompressedPubkey(audience)) {
    throw new OnboardError("audience must be a 33-byte compressed pubkey hex or empty");
  }
  const n = nonce ?? freshNonceHex();
  if (n.length !== NONCE_HEX_LEN || !/^[0-9a-f]+$/.test(n)) {
    throw new OnboardError("nonce must be a fixed-length lowercase-hex string");
  }
  return {
    scope: String(scope),
    audience,
    nonce: n,
    issued: now,
    expires: now + ttl,
    device: String(device),
    scheme: ONBOARD_SCHEME,
  };
}

/** Sign a challenge with this node's wallet key -> proof {pubkey, sig, challenge}. */
export function signChallenge(privHex, ch) {
  const pubkey = publicFromPrivate(privHex);
  const sig = signMessage(privHex, onboardPreimage(ch));
  return { pubkey, sig, challenge: ch };
}

// ---------------------------------------------------------------------------
// QR / deep-link encode + decode + draw/scan helpers
// ---------------------------------------------------------------------------

/**
 * Encode a challenge as a compact `knitweb://onboard?...` deep link for a QR/link.
 * `multiaddr` is transport routing the scanner dials AFTER verifying -- it is NEVER part
 * of the signed pre-image. Field order is fixed so the URI bytes are stable.
 */
export function buildQrUri(ch, { multiaddr = "" } = {}) {
  const pairs = QR_FIELDS.map((k) => `${k}=${encodeURIComponent(String(ch[k]))}`);
  if (multiaddr) pairs.push(`multiaddr=${encodeURIComponent(multiaddr)}`);
  return `${QR_SCHEME}://${QR_PATH}?` + pairs.join("&");
}

/** Parse a `knitweb://onboard?...` deep link -> { challenge, multiaddr }. */
export function parseQrUri(uri) {
  let url;
  try {
    url = new URL(uri);
  } catch (_e) {
    throw new OnboardError("not a valid URI");
  }
  // `new URL("knitweb://onboard?...")` -> protocol "knitweb:", host "onboard".
  if (url.protocol !== `${QR_SCHEME}:` || url.host !== QR_PATH) {
    throw new OnboardError("not a knitweb://onboard QR/deep-link");
  }
  const q = url.searchParams;
  const one = (key, required = true) => {
    const all = q.getAll(key);
    if (all.length === 0) {
      if (required) throw new OnboardError(`QR missing field: ${key}`);
      return "";
    }
    if (all.length > 1) throw new OnboardError(`QR has duplicate field: ${key}`);
    return all[0];
  };
  const rec = {
    scope: one("scope"),
    audience: one("audience", false),
    nonce: one("nonce"),
    issued: toInt(one("issued")),
    expires: toInt(one("expires")),
    device: one("device"),
    scheme: one("scheme"),
  };
  const ch = parseChallengeRecord(rec); // validates fields the same way the verifier does
  return { challenge: ch, multiaddr: one("multiaddr", false) };
}

/**
 * Render a challenge as a scannable QR onto a <canvas>, given a QR library `qr` exposing
 * `qr.toCanvas(canvas, text, opts, cb)` (e.g. the `qrcode` package). Kept injectable so this
 * module has no hard UI/QR dependency and JS never touches a signed path while drawing.
 */
export function drawChallengeQr(qr, canvas, ch, { multiaddr = "" } = {}) {
  const uri = buildQrUri(ch, { multiaddr });
  return new Promise((resolve, reject) => {
    qr.toCanvas(canvas, uri, { errorCorrectionLevel: "M", margin: 1, width: 240 }, (err) =>
      err ? reject(err) : resolve(uri)
    );
  });
}

// ---------------------------------------------------------------------------
// THE GATE: verify a scanned peer's signed onboarding BEFORE admitting it
// ---------------------------------------------------------------------------

/**
 * A minimal one-time-nonce store interface for anti-replay. The app backs this with an
 * IndexedDB object store in the worker; tests use InMemorySeenNonces below.
 * Must expose `has(nonce) -> bool` and `add(nonce) -> void`.
 */
export class InMemorySeenNonces {
  constructor(initial) {
    this._seen = new Set(initial || []);
  }
  has(nonce) {
    return this._seen.has(nonce);
  }
  add(nonce) {
    this._seen.add(nonce);
  }
  get size() {
    return this._seen.size;
  }
}

/**
 * Authenticate a node's onboarding and return its admitted compressed-pubkey hex.
 *
 * This is the ONLY admission path on the JS side. It rejects anything unsigned, malformed,
 * scope-mismatched, audience-mismatched, expired, future-dated, or replayed, and ONLY on a
 * valid wallet signature does it burn the nonce and return the admitted pubkey. The caller
 * opens the RTCDataChannel / admits the peer IFF this resolves (it throws otherwise), and
 * stamps the returned pubkey as the verified peer identity for the reputation gate.
 *
 * @param {object} proof                {pubkey, sig, challenge}
 * @param {object} opts
 * @param {number} opts.nowS            current time as an INJECTED integer (seconds)
 * @param {string} opts.expectedScope   scope this verifier admits into
 * @param {{has:function,add:function}} opts.seen   one-time-nonce store
 * @param {string|null} [opts.localPubkey=null]     this verifier's compressed pubkey hex
 * @returns {string} admitted node's 33-byte compressed pubkey hex
 * @throws {OnboardError} on ANY failure -- a throw means NO admission.
 */
export function verifyOnboarding(proof, { nowS, expectedScope, seen, localPubkey = null } = {}) {
  const now = requireInt(nowS, "nowS");
  const pr = parseProofRecord(proof);
  const ch = pr.challenge;

  // 1) scope binding.
  if (ch.scope !== expectedScope) {
    throw new OnboardError("challenge scope does not match this peer's scope");
  }
  // 2) audience binding -- if the challenge names a verifier, it must be us.
  if (ch.audience !== "") {
    if (localPubkey == null) {
      throw new OnboardError("audience-bound challenge but no local pubkey to match");
    }
    if (ch.audience !== localPubkey) {
      throw new OnboardError("challenge audience is a different peer");
    }
  }
  // 3) freshness -- integer-second window, no wall-clock read here, no float.
  if (now < ch.issued) {
    throw new OnboardError("challenge is not yet valid (issued in the future)");
  }
  if (now >= ch.expires) {
    throw new OnboardError("challenge has expired");
  }
  // 4) anti-replay -- a burned nonce can never be admitted again.
  if (seen.has(ch.nonce)) {
    throw new OnboardError("challenge nonce already used (replay)");
  }
  // 5) THE SIGNATURE GATE -- verify the wallet signature over the exact pre-image.
  if (!verifyMessage(pr.pubkey, onboardPreimage(ch), pr.sig)) {
    throw new OnboardError("onboarding signature does not verify for this pubkey");
  }
  // Admission granted -- burn the nonce LAST so a bad-signature replay can't grief a retry.
  seen.add(ch.nonce);
  return pr.pubkey;
}

/**
 * End-to-end helper: scan a QR URI from a peer, verify it, and (only on success) return the
 * routing the caller needs to open the DataChannel: `{ pubkey, multiaddr }`. Throws on any
 * failure -- so a tab can wire `verifyScannedQr(...).then(openDataChannel)` knowing the
 * channel is opened ONLY for a wallet-authenticated peer.
 *
 * NOTE: a bare QR carries the challenge the *issuer* wants signed; the SCANNER must obtain the
 * issuer's signed proof over it (the issuer signs its own challenge as proof-of-key before
 * advertising, or signs on connect). This helper accepts the proof the issuer published
 * alongside the routing; an unsigned QR yields no proof and therefore no admission.
 */
export function admitScannedProof(proof, { nowS, expectedScope, seen, localPubkey = null, multiaddr = "" } = {}) {
  const pubkey = verifyOnboarding(proof, { nowS, expectedScope, seen, localPubkey });
  return { pubkey, multiaddr };
}

// ---------------------------------------------------------------------------
// Strict field parsing/validation (reject BEFORE any crypto runs)
// ---------------------------------------------------------------------------

function parseChallengeRecord(rec) {
  if (rec == null || typeof rec !== "object") throw new OnboardError("challenge must be a map");
  const scheme = reqStr(rec, "scheme");
  if (scheme !== ONBOARD_SCHEME) throw new OnboardError(`unsupported onboarding scheme: ${scheme}`);
  const nonce = reqStr(rec, "nonce");
  if (nonce.length !== NONCE_HEX_LEN || !/^[0-9a-f]+$/.test(nonce)) {
    throw new OnboardError("nonce must be a fixed-length lowercase-hex string");
  }
  const audience = reqStr(rec, "audience");
  if (audience !== "" && !isCompressedPubkey(audience)) {
    throw new OnboardError("audience must be a 33-byte compressed pubkey hex or empty");
  }
  const issued = reqInt(rec, "issued");
  const expires = reqInt(rec, "expires");
  if (issued < 0 || expires < 0) throw new OnboardError("issued/expires must be non-negative");
  if (expires <= issued) throw new OnboardError("expires must be strictly after issued");
  if (expires - issued > MAX_TTL_S) throw new OnboardError("challenge window exceeds MAX_TTL_S");
  return {
    scope: reqStr(rec, "scope"),
    audience,
    nonce,
    issued,
    expires,
    device: reqStr(rec, "device"),
    scheme,
  };
}

function parseProofRecord(rec) {
  if (rec == null || typeof rec !== "object") throw new OnboardError("proof must be a map");
  const pubkey = reqStr(rec, "pubkey");
  if (!isCompressedPubkey(pubkey)) {
    throw new OnboardError("pubkey must be a 33-byte compressed secp256k1 hex");
  }
  const sig = reqStr(rec, "sig");
  if (sig.length === 0 || !/^[0-9a-fA-F]+$/.test(sig) || sig.length % 2 !== 0) {
    throw new OnboardError("sig must be non-empty DER-encoded hex");
  }
  const challenge = parseChallengeRecord(rec.challenge);
  return { pubkey, sig, challenge };
}

// ---------------------------------------------------------------------------
// Integer / hex helpers (INTEGER-ONLY discipline)
// ---------------------------------------------------------------------------

/** Render an integer as base-10 with no separators (byte-identical to Python str(int)). */
function intStr(n) {
  const i = requireInt(n, "integer field");
  return String(i);
}

function requireInt(value, name) {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new OnboardError(`${name} must be an integer`);
  }
  return value;
}

function reqStr(rec, key) {
  const v = rec[key];
  if (typeof v !== "string") throw new OnboardError(`${key} must be a string`);
  return v;
}

function reqInt(rec, key) {
  const v = rec[key];
  if (typeof v !== "number" || !Number.isInteger(v)) throw new OnboardError(`${key} must be an integer`);
  return v;
}

/** Parse a base-10 integer field from a URI; reject anything non-integer (no float). */
function toInt(text) {
  const s = String(text).trim();
  if (!/^-?\d+$/.test(s)) throw new OnboardError(`expected an integer, got ${text}`);
  return Number(s);
}

/** True iff `pubHex` is a 33-byte compressed secp256k1 point hex (0x02/0x03 prefix). */
function isCompressedPubkey(pubHex) {
  return typeof pubHex === "string" && /^(02|03)[0-9a-fA-F]{64}$/.test(pubHex);
}
