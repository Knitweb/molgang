# MOLGANG — serverless PWA (the real engine in every tab)

This directory builds the **server-free** MOLGANG: every browser tab runs the
**unchanged** `molgang` + `knitweb` Python as a full Knitweb peer, inside a Pyodide
module-Worker. There is **no backend** — no `molgang serve`, no Django, no PHP, no
Fly/Render/Docker, no central relay. The static files here can be hosted on *any* dumb
file host (or opened from disk) and the classroom still works peer-to-peer.

> Vocabulary: this is the Knitweb — **Web · Knitweb · Knit · Pulse · Fiber**, workers are
> **spiders**, the pay-token is **PLS**. We never say "loom".

## Why "the engine in every tab"

The single highest-severity failure in this system is a **one-byte divergence** in
canonical-CBOR / CIDv1 / DER-signature / integer-faucet output between peers — it silently
forks the classroom (CIDs and signatures stop matching, a quorum can't tally a shared
verdict). Every load-bearing rule lives in pure Python:

| Invariant keystone | Where (unchanged) |
|---|---|
| deterministic float-free CBOR + CIDv1 | `knitweb.core.canonical` |
| secp256k1 ECDSA / SHA-256, 33-byte compressed pubkey hex, DER sig hex | `knitweb.core.crypto` |
| 4-byte BE length prefix + canonical body, `MAX_FRAME_BYTES = 8388608` | `knitweb.p2p.wire` |
| BFT quorum `default_threshold(n) = (2*n)//3 + 1` | `knitweb.pouw.quorum` |
| integer-only decaying faucet (1 PLS = 1,000,000 µPLS) | `molgang.game.faucet_micropulses` |
| relay pre-image `"knitweb-relay:v1\n{to}\n{topic}\n{body}"` | `molgang.relay_sync.signed_preimage` |

Shipping those **exact `.py` bytes** into Pyodide makes byte-identity *free by
construction*. The JS shell never does faucet math, CBOR, CID, signing, or quorum tallying.

The only genuinely new code is **one transport** — `molgang/webnode/peer.py`'s
`WebRtcTransport(tag="webrtc")` — which satisfies the 5-method `Transport` Protocol and
slots into the documented **HOLE-PUNCH SEAM** in `knitweb.p2p.transport` with **zero edits**
to `node.py` / `base_node.py`.

## Files

```
serverless/
  src/molgang/webnode/__init__.py   # WebNodeRuntime + Pyodide postMessage bridge (this entrypoint)
  src/molgang/webnode/peer.py       # WebPeer (the in-tab node) + WebRtcTransport (the 1 new file)
  src/molgang/webnode/contract.py   # canonical JS<->Python RPC/state contract + version
  README.md                         # this file
  web/                              # the thin JS shell (app shell, worker.js, service worker) — see below
```

The `web/` shell is intentionally thin and native: it owns the `RTCPeerConnection` /
`RTCDataChannel` objects (a browser API), IndexedDB/OPFS handles, QR draw/scan, and the
service-worker cache. It **never** touches a hashed/signed/economic path — only the engine
(WASM) does. (The existing `web/index.html` + `web/style.css` are reused as the visual
shell; `web/app.js`'s `fetch('/api/*')` polling is replaced by `postMessage` RPC.)

## Build: a static PWA with zero backend

You produce three static assets and drop them next to the existing `web/` shell:

1. **The engine wheel.** Build the `molgang` package (which now includes `molgang.webnode`)
   and have `knitweb` available, then load both into Pyodide at runtime via `micropip`.

   ```bash
   # 1. build the molgang wheel (includes src/molgang/webnode/*)
   python -m build --wheel            # -> dist/molgang-0.1.0-py3-none-any.whl
   # 2. build (or fetch) the knitweb wheel the same way from the pulse checkout
   ( cd /path/to/pulse && python -m build --wheel )   # -> dist/knitweb-*.whl
   # 3. copy both wheels into the static site so the Worker can micropip-install them
   mkdir -p web/wheels
   cp dist/molgang-*.whl /path/to/pulse/dist/knitweb-*.whl web/wheels/
   ```

2. **The Worker.** `web/worker.js` is a **module** worker (`new Worker(url, {type:"module"})`
   — classic `importScripts` is unsupported for the engine). It:
   - loads Pyodide (`loadPyodide`) from a service-worker-cached CDN or a vendored copy,
   - `micropip.install`s the two wheels (and the `cryptography` package for secp256k1),
   - runs `import molgang.webnode as wn; wn.install_worker_bridge()`.

   ```js
   // web/worker.js  (sketch)
   import { loadPyodide } from "./pyodide/pyodide.mjs";
   const py = await loadPyodide();
   await py.loadPackage("micropip");
   const micropip = py.pyimport("micropip");
   await micropip.install("cryptography");                 // secp256k1 backend
   await micropip.install("./wheels/knitweb-0.6-py3-none-any.whl");
   await micropip.install("./wheels/molgang-0.1.0-py3-none-any.whl");
   await py.runPythonAsync("import molgang.webnode as wn; wn.install_worker_bridge()");
   // the bridge posts {type:"loaded"} when ready; the shell then sends hello.
   ```

3. **The PWA shell + service worker.** `web/index.html` boots `web/app.js` (the thin shell),
   which spawns the Worker and registers `web/sw.js`. The service worker caches the app
   shell **and** the Pyodide wasm + the two wheels for **offline-first, instant-feel**
   second loads (this is the grafted UX discipline that neutralizes Pyodide cold-start).
   Show a JS splash while the Worker boots; call `navigator.storage.persist()` so the
   IndexedDB-backed identity/world is not evicted.

Serve it with *any* static server (none of these is required at runtime — pick one):

```bash
python -m http.server -d web 8000        # or: npx serve web , or: just open web/index.html
```

Open `http://localhost:8000/`. The tab boots Pyodide, derives its identity, and is a live
peer. No API host, no `MOLGANG_API` — `web/config.js` is obsolete here.

## The JS <-> Python boundary (the contract)

The shell and engine talk **only** through `postMessage`, framed by
`molgang/webnode/contract.py` (`CONTRACT_VERSION = "webnode/1"`):

```
shell  -> worker : {type:"hello", contract:"webnode/1", seed:<idb-seed>, seams:{now, id_proof_now, nonce_hex}}
worker -> shell  : {type:"loaded"}            # engine module imported
worker -> shell  : {type:"ready", identity:{pubkey, address, fiber_cid}}
shell  -> worker : {type:"rpc", id:<int>, method:"join", args:{name, ...}, seams:{...}}
worker -> shell  : {type:"result", id:<int>, ok:true, payload:{...}}
worker -> shell  : {type:"event", kind:"woven", payload:{...}}   # unsolicited (redraw web)
```

Every `/api/*` route from the old `webserver.py` becomes a direct in-worker `Bar` call
(`state`, `join`, `sit`, `propose`, `vote`, `spiral_propose`, `spiral_vote`,
`certificate`, ...). The boundary is float-checked (`assert_jsonsafe` rejects `float`
exactly like canonical CBOR), so no JS number can smuggle a float onto an economic path.

### Injected seams (sacred invariant: no wall-clock / no randomness on decision paths)

The shell pushes **integer** seams in `hello` and on each `rpc`:

- `now` — an integer **monotonic** clock (drives session staleness + liveness token-buckets),
- `id_proof_now` — an integer **seconds** clock used ONLY for identity-proof freshness
  (it overrides the node's sole `time.time()` seam, `BaseNode._id_proof_now`, which never
  feeds a CID or ordering decision),
- `nonce_hex` — CSPRNG bytes from `crypto.getRandomValues` (**never** `Math.random`), used
  only for the single-use QR challenge nonce.

The engine never calls `time.time()` or `random` on a decision path.

## Serverless first-contact (no required server)

A layered signaling ladder, each rung needing less infrastructure, **no rung trusted**:

1. **QR / deep-link (zero infra).** Two devices scan each other's **wallet-signed** QR
   `{pubkey, multiaddr, nonce, exp, sig}`. The scanner calls `qr_admit` which runs
   `crypto.verify` over the exact pre-image
   `"molgang-webnode-qr:v1\n{pubkey}\n{multiaddr}\n{nonce}\n{exp}"`
   **before any DataChannel opens** — this is signature-gated **authentication**, never an
   unauthenticated backdoor. A bad/missing signature or an expired `exp` (checked against
   the injected integer clock) → no admission. Then a direct WebRTC DataChannel opens with
   **no relay**.
2. **STUN** (stateless, swappable) — ship a *list* of public STUN servers for reflexive
   address discovery; never hard-depend on one.
3. **DHT/PEX-assisted signaling** — once one peer is known, any peer relays the next SDP via
   `knitweb.p2p.discovery` peer-exchange + `knitweb.p2p.kademlia`.
4. **Optional bootstrap peer (replaces 5mart.ml).** An *anyone-can-run* opaque
   store-and-forward mailbox — `relay_pull(base=...)` re-verifies every item end-to-end with
   the **same** signed relay pre-image, so the carrier is untrusted-by-construction (it can
   drop but never forge/replay). PEX-advertised as a **multi-bootstrap list** (no SPOF),
   used only for first-contact + NAT-blocked mailboxing. Direct WebRTC takes over after the
   handshake.

### Run the optional bootstrap peer (one command, anyone)

It is a dumb opaque mailbox — it carries length-prefixed canonical-CBOR frames it never
decodes, strips the reserved `_relay_*` envelope before any logic, and readers re-verify the
exact pre-image. Any volunteer can host one and advertise its URL over PEX; nodes treat it as
one of many bootstraps. (The legacy `php/` relay satisfies this contract; a minimal
single-file mailbox does too.)

## Identity, persistence, faucet

- **Identity** is `AccountNode.from_seed(seed)` — deterministic, no subprocess (this retires
  `pulse_host.py`'s `subprocess.run`), `priv = sha256("knitweb:account:seed:"+seed)`. The
  seed lives in IndexedDB and **never leaves the Worker**; the shell holds only the public
  key + address. The same seed signs the QR challenge.
- **Persistence** is content-addressed and local-first: `canonical.cid()` already keys every
  Fiber/Knit, so the store dedups identical bytes for free. The World and the device→wallet
  registry move into IndexedDB (optionally OPFS + SQLite-WASM). Convergence is the existing
  **domain** merge — `relay_sync.pull()` verifies each signed item then folds by
  `item_keys()`, re-applying a co-woven Fiber **bumps** confirmations/tension (a monotone
  integer sum) instead of double-counting — so peers reach the same `state_root` regardless
  of arrival order. `anchor_ts` stays display/seasonal metadata only and never reaches a
  CID/ordering path. A wiped tab re-derives its identity from the seed/QR and re-syncs from
  peers **without re-faucet abuse** (saved balance is restored, never re-minted).
- **Faucet** is the integer-only decaying schedule in `molgang.game`: day 0 = 10,000,000
  PLS, day 100 = 10,000 PLS, then −1%/day, floored at 1 µPLS. Serverless sybil defence is
  in-protocol: the decaying faucet, a fixed-integer-target PoW mint-gate (no wall-clock), the
  personhood scope-nullifier (one-person-one-scope), and PLS-staked quorum web-of-trust.

## Conformance gate (the cutover insurance)

Even though every tab runs identical `.py`, the one residual drift surface is
CPython-vs-Pyodide **secp256k1** (DER / low-S) and any accidental `float`/`Date.now` in the
WASM build. Before cutover, run a **Python-generated golden-vector corpus** in CI against
Pyodide-in-headless-browser:

- object → canonical-CBOR hex, object → CIDv1 string,
- message → DER-sig hex over `sha256`, Knit → signing-bytes + id,
- relay pre-image bytes + sig, `faucet_micropulses(day)` on a day-grid (day 0/100/101/large-k),
- `default_threshold(n)` for `n = 1..many`.

**A single differing byte blocks cutover.** The corpus doubles as a published protocol spec
so a future Rust/TS peer can join the same Web by passing the identical vectors — without
molgang ever maintaining a second engine. The `molgang.webnode.main()` stdin/stdout harness
drives the exact same dispatch the Worker uses, so server-mode and tab-mode `state_root`s can
be diffed without a browser.
