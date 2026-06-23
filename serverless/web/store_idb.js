"use strict";
/*
 * store_idb.js — local-first, content-addressed block store for the in-tab MOLGANG peer.
 *
 * Canonical server-free architecture (Variant A): every browser tab IS a full Knitweb peer.
 * The Pyodide engine worker runs the UNCHANGED molgang + knitweb Python bytes; THIS file is
 * the JS shell's persistence layer. It is a content-addressed blob map plus the woven-web
 * state document plus an offline outbox of signed relay frames — all in IndexedDB so a tab
 * boots and plays fully offline and reconciles on reconnect.
 *
 * SACRED INVARIANTS this module must never break:
 *   (a) INTEGER-ONLY on every economic / scoring / decision / ordering path. This file holds
 *       NO economic or scoring logic; the only numbers it owns are an integer monotone
 *       sequence counter and integer byte lengths. No `/`, no Math.round, no Number coercion
 *       of balances. Balances / faucet / quorum math live only in the Python engine.
 *   (b) NO wall-clock and NO randomness on any decision / ordering path. Insertion order is a
 *       persisted integer `seq` counter (NOT Date.now()). Nonces / ids use the WebCrypto
 *       CSPRNG (crypto.getRandomValues), NEVER Math.random.
 *   (c) BYTE-IDENTITY. JS NEVER computes a CID, a canonical-CBOR encoding, a signature, or a
 *       state_root. Those are produced by the Python engine and handed here as opaque bytes /
 *       strings. This store keys blocks by the CID STRING the engine produced and stores the
 *       engine's exact frame bytes verbatim — so the bytes that leave a peer are the bytes the
 *       engine signed. The 4-byte big-endian length prefix + canonical body framing and the
 *       8 MiB MAX_FRAME_BYTES ceiling are mirrored here ONLY for length validation of opaque
 *       frames; this file never decodes a canonical body.
 *
 * VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. (Never "loom".)
 */

// Wire contract mirrored from knitweb.p2p.wire — kept byte-identical with the Python engine.
// A frame = 4-byte big-endian length prefix + canonical CBOR body. The body is OPAQUE here.
const MAX_FRAME_BYTES = 8 * 1024 * 1024; // 8388608 — liveness-coupled to inventory.SERVE_BYTES_PER_WINDOW; do not change.
const FRAME_LEN_PREFIX = 4;

const DB_NAME = "molgang-knitweb";
const DB_VERSION = 1;

// Object stores:
//   blocks   — content-addressed Fiber/Knit blocks, keyed by the CID string (canonical.cid()).
//   state    — singleton documents keyed by a stable name: the woven World JSON, the device
//              registry, the engine seed, the saved balances, the relay pull cursor.
//   outbox   — the offline queue of OUTBOUND signed relay frames (opaque bytes), FIFO by seq.
//   inbox    — verified-but-not-yet-applied INBOUND items the engine will fold on next tick.
//   meta     — small counters (the monotone integer seq) and the schema marker.
const STORE_BLOCKS = "blocks";
const STORE_STATE = "state";
const STORE_OUTBOX = "outbox";
const STORE_INBOX = "inbox";
const STORE_META = "meta";

// Well-known singleton keys in the `state` store (keyed off the same DEVICE_ID the shell holds).
const STATE_WORLD = "world";          // the molgang World document {items:[...], open_spirals:[...]}
const STATE_REGISTRY = "registry";    // device -> wallet pubkey map (was sqlite registry.py)
const STATE_SEED = "seed";            // the engine identity seed (AccountNode.from_seed input)
const STATE_BALANCES = "balances";    // persisted device balances (no re-faucet on restart)
const STATE_CURSOR = "cursor";        // relay/anti-entropy high-water cursor (integer-ish opaque)

const META_SEQ = "seq";               // monotone integer insertion counter (NOT a clock)

// ---------------------------------------------------------------------------
// low-level IndexedDB plumbing (promise wrappers; no third-party deps)
// ---------------------------------------------------------------------------

function _openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (ev) => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_BLOCKS)) {
        // keyed explicitly by the CID string the Python engine produced (no autoIncrement:
        // content-addressing means the key IS the content hash — identical bytes dedup for free).
        db.createObjectStore(STORE_BLOCKS, { keyPath: "cid" });
      }
      if (!db.objectStoreNames.contains(STORE_STATE)) {
        db.createObjectStore(STORE_STATE, { keyPath: "name" });
      }
      if (!db.objectStoreNames.contains(STORE_OUTBOX)) {
        // seq is a persisted monotone INTEGER (see META_SEQ) — FIFO ordering with no wall-clock.
        const ob = db.createObjectStore(STORE_OUTBOX, { keyPath: "seq" });
        ob.createIndex("by_topic", "topic", { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_INBOX)) {
        db.createObjectStore(STORE_INBOX, { keyPath: "seq" });
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: "k" });
      }
      // silence unused-var lint while keeping the event signature explicit
      void ev;
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("indexedDB.open failed"));
  });
}

function _txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error || new Error("transaction aborted"));
    tx.onerror = () => reject(tx.error || new Error("transaction error"));
  });
}

function _reqDone(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("request failed"));
  });
}

// ---------------------------------------------------------------------------
// frame helpers — OPAQUE-body validation only (never decode the canonical body)
// ---------------------------------------------------------------------------

/**
 * Validate that `frame` (Uint8Array) is a well-formed length-prefixed frame WITHOUT decoding
 * its canonical body. Mirrors knitweb.p2p.wire.read_frame_bytes' framing checks exactly: a
 * 4-byte big-endian length prefix, a non-empty body whose length matches the prefix, and a body
 * no larger than MAX_FRAME_BYTES. Returns the declared body length (an integer). Throws on any
 * malformed frame so a corrupt outbox entry is rejected rather than silently sent.
 */
function frameBodyLength(frame) {
  if (!(frame instanceof Uint8Array)) {
    throw new TypeError("frame must be a Uint8Array");
  }
  if (frame.length < FRAME_LEN_PREFIX) {
    throw new Error("truncated frame");
  }
  // 4-byte big-endian length prefix (matches len(raw).to_bytes(4,"big")).
  const n =
    (frame[0] << 24) | (frame[1] << 16) | (frame[2] << 8) | frame[3];
  // `>>> 0` forces an unsigned 32-bit integer (the top bit set would otherwise read negative).
  const declared = n >>> 0;
  if (declared <= 0) {
    throw new Error("empty frame");
  }
  if (declared > MAX_FRAME_BYTES) {
    throw new Error("frame too large: " + declared + " > " + MAX_FRAME_BYTES);
  }
  if (frame.length - FRAME_LEN_PREFIX !== declared) {
    throw new Error("frame length prefix does not match payload");
  }
  return declared;
}

// ---------------------------------------------------------------------------
// the store
// ---------------------------------------------------------------------------

class StoreIdb {
  constructor(db) {
    this._db = db;
  }

  /** Open (and upgrade) the IndexedDB-backed store. Request durable storage best-effort. */
  static async open() {
    // Browser storage is evictable; ask for persistence so a tab's balance/seed survive.
    // This is best-effort: a denied grant only means we rely on signed-state export + peer
    // re-sync to restore a wiped tab (never a re-faucet).
    if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persist) {
      try {
        await navigator.storage.persist();
      } catch (_e) {
        // ignore — persistence is an optimisation, not a correctness requirement
      }
    }
    const db = await _openDb();
    return new StoreIdb(db);
  }

  // -- monotone integer sequence (insertion ordering with NO wall-clock) ----

  /**
   * Allocate the next integer sequence number. This is the ONLY ordering source for the
   * outbox/inbox: a persisted monotone counter, never Date.now(). Invariant (b): no clock on
   * an ordering path. Returns a JS number that is always a safe integer (a tab will not enqueue
   * 2^53 frames); callers treat it strictly as an integer key.
   */
  async _nextSeq() {
    const tx = this._db.transaction(STORE_META, "readwrite");
    const meta = tx.objectStore(STORE_META);
    const cur = await _reqDone(meta.get(META_SEQ));
    const next = (cur && Number.isInteger(cur.v) ? cur.v : 0) + 1;
    meta.put({ k: META_SEQ, v: next });
    await _txDone(tx);
    return next;
  }

  // -- content-addressed blocks --------------------------------------------

  /**
   * Put a content-addressed block. The CID string is produced by the Python engine
   * (canonical.cid()); JS treats it as an opaque key. `bytes` is the engine's canonical
   * encoding of the block (a Uint8Array), stored verbatim so re-reads are byte-identical.
   * Idempotent: re-putting the same CID overwrites with identical bytes (content-addressing
   * guarantees identical content -> identical key), so dedup is free.
   */
  async putBlock(cid, bytes) {
    if (typeof cid !== "string" || cid.length === 0) {
      throw new TypeError("cid must be a non-empty string from the engine");
    }
    if (!(bytes instanceof Uint8Array)) {
      throw new TypeError("block bytes must be a Uint8Array");
    }
    const tx = this._db.transaction(STORE_BLOCKS, "readwrite");
    tx.objectStore(STORE_BLOCKS).put({ cid, bytes });
    await _txDone(tx);
    return cid;
  }

  /** Get a block's bytes by CID (Uint8Array), or null if absent. */
  async getBlock(cid) {
    const tx = this._db.transaction(STORE_BLOCKS, "readonly");
    const rec = await _reqDone(tx.objectStore(STORE_BLOCKS).get(cid));
    await _txDone(tx);
    return rec ? rec.bytes : null;
  }

  /** True iff a block with this CID is already stored (cheap existence probe for reconcile). */
  async hasBlock(cid) {
    const tx = this._db.transaction(STORE_BLOCKS, "readonly");
    const key = await _reqDone(tx.objectStore(STORE_BLOCKS).getKey(cid));
    await _txDone(tx);
    return key !== undefined;
  }

  /**
   * All stored CIDs, sorted lexicographically. Used by anti-entropy / reconcile to advertise
   * the local inventory set. Sorting is a deterministic total order over opaque strings — it
   * touches no economic value, so it is invariant-safe.
   */
  async listCids() {
    const tx = this._db.transaction(STORE_BLOCKS, "readonly");
    const keys = await _reqDone(tx.objectStore(STORE_BLOCKS).getAllKeys());
    await _txDone(tx);
    return keys.slice().sort();
  }

  /** CIDs the engine knows about that this store is MISSING (the reconcile fetch set). */
  async missingCids(wantCids) {
    const have = new Set(await this.listCids());
    const out = [];
    for (const cid of wantCids) {
      if (!have.has(cid)) out.push(cid);
    }
    return out.sort();
  }

  // -- singleton state documents (the woven web, registry, seed, balances) --

  /** Read a singleton state document by name, or null. Value is whatever the engine stored. */
  async getState(name) {
    const tx = this._db.transaction(STORE_STATE, "readonly");
    const rec = await _reqDone(tx.objectStore(STORE_STATE).get(name));
    await _txDone(tx);
    return rec ? rec.value : null;
  }

  /** Write a singleton state document by name (overwrites). */
  async putState(name, value) {
    const tx = this._db.transaction(STORE_STATE, "readwrite");
    tx.objectStore(STORE_STATE).put({ name, value });
    await _txDone(tx);
    return name;
  }

  /**
   * Persist the molgang World document (the woven-web state). This is the {items, open_spirals}
   * JSON the engine's World._save() produces; it moves out of the filesystem into IndexedDB.
   * The engine remains the sole author — JS never edits items (which would touch CID/edge keys).
   */
  putWorld(worldDoc) {
    return this.putState(STATE_WORLD, worldDoc);
  }
  getWorld() {
    return this.getState(STATE_WORLD);
  }

  /** The device->wallet registry (was the sqlite registry.py) as a plain JSON map. */
  putRegistry(reg) {
    return this.putState(STATE_REGISTRY, reg);
  }
  getRegistry() {
    return this.getState(STATE_REGISTRY);
  }

  /**
   * The engine identity seed (AccountNode.from_seed input). Stored once and reused so the peer
   * keeps a stable PLS identity across sessions WITHOUT re-faucet. If absent, mint a fresh seed
   * from the WebCrypto CSPRNG (NEVER Math.random — a predictable seed would break the
   * signature-gated QR onboarding and ECDSA security) and persist it.
   */
  async getOrCreateSeed(deviceId) {
    const existing = await this.getState(STATE_SEED);
    if (existing && typeof existing.seed === "string" && existing.seed.length > 0) {
      return existing.seed;
    }
    // 32 bytes of CSPRNG entropy, domain-tagged with the device id for readability.
    const rnd = new Uint8Array(32);
    crypto.getRandomValues(rnd);
    let hex = "";
    for (let i = 0; i < rnd.length; i++) {
      hex += rnd[i].toString(16).padStart(2, "0");
    }
    const seed = "molgang:device:" + String(deviceId || "tab") + ":" + hex;
    await this.putState(STATE_SEED, { seed });
    return seed;
  }

  /** Persisted device balances (no re-faucet on restart — restore the saved balance). */
  putBalances(balances) {
    return this.putState(STATE_BALANCES, balances);
  }
  getBalances() {
    return this.getState(STATE_BALANCES);
  }

  /** The relay / anti-entropy pull cursor (opaque high-water value the engine advances). */
  putCursor(cursor) {
    return this.putState(STATE_CURSOR, cursor);
  }
  getCursor() {
    return this.getState(STATE_CURSOR);
  }

  // -- the offline outbox (OUTBOUND signed relay frames) --------------------

  /**
   * Enqueue an OUTBOUND signed relay frame for later delivery (offline-first). `frameBytes` is
   * the engine's EXACT write_frame_bytes() output — a 4-byte big-endian length prefix followed
   * by the canonical, already-signed body. We validate the framing (never decode the body) and
   * store the bytes verbatim so the peer that drains the queue sends precisely the bytes the
   * engine signed (byte-identity, invariant (c)). `topic` and `to` are opaque routing hints the
   * shell uses to pick a DataChannel; they are NOT part of the signed pre-image. Order is the
   * monotone integer seq, so the queue is strict FIFO with no wall-clock.
   */
  async enqueueOutbound(frameBytes, topic = "", to = "") {
    frameBodyLength(frameBytes); // throws on a malformed / oversized frame
    const seq = await this._nextSeq();
    const tx = this._db.transaction(STORE_OUTBOX, "readwrite");
    tx.objectStore(STORE_OUTBOX).put({
      seq,
      topic: String(topic || ""),
      to: String(to || ""),
      frame: frameBytes,
    });
    await _txDone(tx);
    return seq;
  }

  /**
   * Peek up to `limit` queued outbound frames in FIFO (ascending-seq) order. Does not remove
   * them — the caller acks each by seq once the DataChannel reports delivery, so a frame is
   * never lost if the channel drops mid-send.
   */
  async peekOutbound(limit = 64) {
    const tx = this._db.transaction(STORE_OUTBOX, "readonly");
    const all = await _reqDone(tx.objectStore(STORE_OUTBOX).getAll());
    await _txDone(tx);
    all.sort((a, b) => a.seq - b.seq); // integer seq compare — deterministic, no clock
    return all.slice(0, Math.max(0, limit | 0));
  }

  /** Acknowledge (remove) a delivered outbound frame by its seq. */
  async ackOutbound(seq) {
    const tx = this._db.transaction(STORE_OUTBOX, "readwrite");
    tx.objectStore(STORE_OUTBOX).delete(seq);
    await _txDone(tx);
  }

  /** Count of pending outbound frames (for a "N unsent" UI badge). */
  async outboxCount() {
    const tx = this._db.transaction(STORE_OUTBOX, "readonly");
    const n = await _reqDone(tx.objectStore(STORE_OUTBOX).count());
    await _txDone(tx);
    return n;
  }

  // -- the inbox (verified INBOUND items awaiting the engine's merge fold) ---

  /**
   * Stage a verified INBOUND relay message for the engine to fold on its next tick. The shell
   * receives a DataChannel frame, the engine verifies the signature end-to-end (the exact
   * "knitweb-relay:v1\n{to}\n{topic}\n{body}" pre-image), and the verified message body is
   * staged here. The engine drains it via takeInbound() and applies it through the
   * deterministic merge bridge (merge_bridge.apply_remote_item), which dedups by item_keys and
   * SUMs co-woven tension. JS performs NO verification or merge itself.
   */
  async stageInbound(message) {
    const seq = await this._nextSeq();
    const tx = this._db.transaction(STORE_INBOX, "readwrite");
    tx.objectStore(STORE_INBOX).put({ seq, message });
    await _txDone(tx);
    return seq;
  }

  /** Drain up to `limit` staged inbound messages in FIFO order and remove them. */
  async takeInbound(limit = 128) {
    const rtx = this._db.transaction(STORE_INBOX, "readonly");
    const all = await _reqDone(rtx.objectStore(STORE_INBOX).getAll());
    await _txDone(rtx);
    all.sort((a, b) => a.seq - b.seq);
    const batch = all.slice(0, Math.max(0, limit | 0));
    if (batch.length > 0) {
      const wtx = this._db.transaction(STORE_INBOX, "readwrite");
      const store = wtx.objectStore(STORE_INBOX);
      for (const row of batch) {
        store.delete(row.seq);
      }
      await _txDone(wtx);
    }
    return batch.map((row) => row.message);
  }

  // -- signed-state export / import (wiped-tab recovery, no re-faucet) -------

  /**
   * Export the full local state as a single transferable snapshot: the woven World document,
   * the registry, the persisted balances, and the cursor — but NOT the raw private seed (the
   * caller pairs that out-of-band via the wallet-signed QR). A wiped tab re-derives its identity
   * from the QR seed (AccountNode.from_seed) and re-applies this snapshot, restoring its saved
   * balance from peers/export rather than re-minting from the faucet (anti-farm).
   */
  async exportState() {
    const [world, registry, balances, cursor] = await Promise.all([
      this.getState(STATE_WORLD),
      this.getState(STATE_REGISTRY),
      this.getState(STATE_BALANCES),
      this.getState(STATE_CURSOR),
    ]);
    return { world, registry, balances, cursor };
  }

  /**
   * Import a snapshot produced by exportState() into a fresh tab. The engine re-folds the World
   * through the merge bridge on next boot so the imported state converges to the same
   * web_state_root/UAL as its peers. Does not touch the seed (identity comes from the QR).
   */
  async importState(snapshot) {
    if (!snapshot || typeof snapshot !== "object") {
      throw new TypeError("snapshot must be an object from exportState()");
    }
    if (snapshot.world != null) await this.putState(STATE_WORLD, snapshot.world);
    if (snapshot.registry != null) await this.putState(STATE_REGISTRY, snapshot.registry);
    if (snapshot.balances != null) await this.putState(STATE_BALANCES, snapshot.balances);
    if (snapshot.cursor != null) await this.putState(STATE_CURSOR, snapshot.cursor);
  }
}

// ---------------------------------------------------------------------------
// exports (ESM for the module-type worker; CommonJS fallback for Node test harness)
// ---------------------------------------------------------------------------

const _api = { StoreIdb, frameBodyLength, MAX_FRAME_BYTES, FRAME_LEN_PREFIX };

export { StoreIdb, frameBodyLength, MAX_FRAME_BYTES, FRAME_LEN_PREFIX };
export default StoreIdb;

// CommonJS interop so a Node-based conformance runner can require() this file unchanged.
if (typeof module !== "undefined" && module.exports) {
  module.exports = _api;
  module.exports.default = StoreIdb;
}
