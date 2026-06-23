# MOLGANG — Server-Free, Top-10 Dapp: Master Development Plan

*Substrate: Knitweb / pulse. A peer-to-peer chemistry (scheikunde) learning game where the learning act IS the protocol operation. No NFTs. Value = PLS utility + silk pacing + reputation (XP / levels / quests / leaderboard / woven Fiber CIDs / PoUW certificates).*

---

## 1. Executive Summary & The Unique Thesis

**Thesis (one line):** MOLGANG is the first education dapp where *learning chemistry IS operating a real peer-to-peer ledger* — every chemical **bond** you form is a real **Knit** (two-party ledger transfer), every **molecule** chain is a real **Fiber** (account-state commitment / CIDv1), every classmate **vote** is a real BFT **pouw.quorum** verdict at `default_threshold(n) = (2*n)//3 + 1` — delivered server-free at ~zero infrastructure cost, so it out-retains quest-farms and out-economizes gaming dapps on the only axis that defines top-10: **sustained active users**, not market cap.

**Why this can reach the top-10-by-usage band (~200k–1M+ active wallets, where ~60% of all dapp activity concentrates):** the market data says usage is decided by two levers — onboarding friction and retention — and MOLGANG's design is on the right side of both:

1. **Walletless onboarding.** Identity is `AccountNode.from_seed(sha256("knitweb:account:seed:"+seed))` minted in-tab with a faucet grant. No MetaMask / connect-wallet step, directly attacking the 68% connect-abandon and 85% connect-then-idle cliffs (walletless onboarding lifts completion 30–40%).
2. **Intrinsic, durable reward.** The reward (XP, levels, woven Fiber CIDs, PoUW certificates) survives the airdrop-cliff that collapsed Hamster/Notcoin, because there is nothing to dump — value is utility + reputation, not a tradable token. Education + incentive = 2–3x retention in the data.
3. **Zero marginal cost.** Every tab runs the unchanged integer-deterministic `molgang`+`knitweb` Python via Pyodide and peers connect over direct WebRTC, so there is no Fly/Render/Django/PHP/MySQL/5mart.ml bill. The faucet/reward economy stays solvent indefinitely where rivals' incentive budgets bleed out.

**The structural moat (inimitable):** running the *unchanged, integer-deterministic engine byte-identically in every tab* makes correctness **free-by-construction**. A competitor can copy the product behavior, but not the fact that a bond is a *real* Knit and a vote a *real* BFT verdict against the same engine. The growth graph — one teacher onboarding 30 students at once via a signature-gated classroom QR — is the built-in viral loop that replaces paid acquisition.

**Honest framing of "server-free":** "no required server" means **no required _trusted_ server**. Two QR-paired peers need no relay at all. Optional, swappable, untrusted volunteer relays (and stateless STUN) remain for first-contact and NAT-blocked peers. The realistic path to raw top-10 scale is a thin Telegram/World-App Mini-App distribution rail, kept rail-independent so the ledger/quorum/p2p substrate stays fully in-tab.

---

## 2. Where MOLGANG Is Today & The Exact Server-Dependence Gap

The peer is currently **server-side**. Four dependencies block "serverless-only" (all verified against `/tmp/molgang-plan` and `/tmp/pulse-rdet`):

| # | Dependency | Evidence (verified) | Why it's a server | Effort to remove |
|---|---|---|---|---|
| 1 | **Bar singleton behind `webserver.py`** | `web/app.js` is a thin client: `setInterval(refresh,1500)` polls `GET /api/state`, POSTs `/api/join\|sit\|propose\|vote\|spiral`. The real peer (Bar holding all sessions/proposals/woven/world/registry) lives server-side. | The tab is a viewer, not a peer. | HIGH (keystone) |
| 2 | **`pulse_host.py` subprocess** | `subprocess.run(...)` at `pulse_host.py:104` shells out to the Pulse CLI for identity. A pure `_local_fallback` (lines 21–44) already exists. | Spawns an external process. | LOW |
| 3 | **Central 5mart.ml PHP+MySQL relay** | `relay_sync.py` hops WAN p2p through `https://5mart.ml/...` because raw inbound TCP is firewalled on shared hosting. FabricNode is LAN-only. | Even "p2p" needs a central host. | MEDIUM |
| 4 | **Django / PHP / bridge / Fly / Render / Docker** | `molgang_web/` (Channels `WorldConsumer`), `php/` (`Bar.php`), `bridge/server.py`, `fly.toml` (`min_machines_running=1`, "state is in-process"), `render.yaml`, `Dockerfile`. | Stateful application hosts whose only job is hosting a central Bar. | MEDIUM |

**Crucially, the pulse substrate is already serverless-ready.** The gap is on the molgang side. `transport.py` defines a 5-method `Transport` Protocol (`tag`, `dial`, `listen`, `close`, `local_address`) + a `Dialer` that routes by `PeerAddress.transport` tag; `BaseNode` holds exactly one listening `Transport` + one `Dialer`, and `start()` wires `transport.listen(self._dispatch, self._on_frame_fault)`. The docstring (transport.py:181–190) names a **HOLE-PUNCH SEAM** anticipating exactly a WebRTC carrier. Verified: `TcpTransport` and `RelayTransport` are the only socket/server-bound transports; every other p2p module (kademlia, discovery, addrbook, inventory, reconcile, mesh, anti_entropy, identity, peer_identity_gate, reputation, policing, quorum) and all of `ledger/` + `core/` are pure, deterministic, transport-agnostic state machines.

---

## 3. The Canonical Server-Free Architecture (Variant A: "Real engine in every tab")

**Winner: Variant A** — the unchanged integer-deterministic `molgang`+`knitweb` Python IS the peer, run in-browser via Pyodide/WASM in a module-type Web Worker — with three best ideas grafted from Variant B. Rationale: byte-identity is the single highest-severity failure mode; Variant A makes it **free by construction** (it ships the exact `.py` bytes), whereas a TypeScript re-implementation carries a permanent drift tax. Variant A is also the smaller, reversible diff: the only genuinely new engine file is one `WebRtcTransport`.

### Layered design

- **L0 — App shell & UI (JS/TS, main thread).** Renders bar/world/ledger/leaderboard; draws & scans wallet-signed QR; **owns the `RTCPeerConnection`/`RTCDataChannel`** (a browser API the worker cannot reach); offline-first PWA. Replaces `app.js`'s poll+fetch with a `postMessage` correlation-id RPC. **JS NEVER does faucet math, CBOR, CID, or signing.** Nonces use WebCrypto `getRandomValues`, never `Math.random`.
- **L1 — Pyodide engine worker (the peer).** Runs the UNCHANGED `src/molgang/{bar,game,world,merge,presence,chemistry,certificate}.py` + ALL of `src/knitweb`. `/api/*` become in-worker Bar calls. Identity = `AccountNode.from_seed` (verified: `node.py:61`, `priv = sha256("knitweb:account:seed:"+seed)`), **eliminating `pulse_host.py`'s subprocess**. Module-type Worker keeps the UI responsive.
- **L2 — Wire/crypto/canonical byte-identity core (the keystone).** Same Python in every tab: `write_frame_bytes`/`read_frame_bytes` (4-byte BE length prefix + canonical CBOR; `MAX_FRAME_BYTES = 8388608`, verified `wire.py:40,169` — **kept identical, liveness-coupled to `inventory.SERVE_BYTES_PER_WINDOW`**); `canonical.encode/decode/cid` (RFC-8949 deterministic CBOR, **floats rejected**, keys sorted by *encoded-key bytes*, CIDv1 dag-cbor `0x71` + sha2-256, verified `canonical.py:6,118,25`); `crypto.sign/verify` (secp256k1/SHA-256, 33-byte compressed pubkey hex, DER sig hex); relay pre-image EXACTLY `"knitweb-relay:v1\n{to}\n{topic}\n{body}"` (verified `relay_sync.py:20,47`).
- **L3 — WebRtcTransport (the ONE new engine file) + Dialer registration.** A single `WebRtcTransport(tag="webrtc")` satisfying the 5-method Protocol; registered via `BaseNode.add_transport` with **ZERO edits to `node.py`/`base_node.py`**. `dial` opens/uses an `RTCDataChannel` and awaits one correlated reply using an **integer** `_relay_rid`/`_relay_reply_to` (mirroring relay.py; verified the `_relay_*` namespace is reserved and stripped by `_strip_envelope` **before any signed/business logic** runs — `relay.py:32–36,75`, so it never enters hashed bytes). `listen` registers `channel.onmessage -> read_frame_bytes -> self._dispatch` and stamps the verified pubkey as `ENVELOPE_PEER_KEY`. `TcpTransport` is simply not instantiated in-tab.
- **L4 — IndexedDB content-addressed store + event-sourced merge.** `canonical.cid()` already keys every Fiber/Knit, so identical bytes dedup for free. World JSON and the device→wallet registry move to IndexedDB keyed off the same `DEVICE_ID`. Convergence is the **domain** merge, not a generic CRDT: `relay_sync.pull()` verifies each signed item then folds by `item_keys()` (verified `relay_sync.py:130`) — re-applying a co-woven Fiber BUMPS confirmations/tension (integer SUM via `_bump`) instead of double-counting — so peers converge to the same `web_state_root`/UAL regardless of arrival order. Request `StorageManager.persist()`; signed-state/seed export for wiped-tab recovery without re-faucet.
- **L5 — Serverless signaling ladder + sybil resistance (auth-gated).** (a) wallet-signed QR/deep-link first-contact (zero infra, verify-before-connect); (b) public STUN (stateless, swappable, ship a list); (c) DHT/PEX-assisted signaling via `discovery.py` peer-exchange + `kademlia.py` once one peer is known; (d) an OPTIONAL anyone-can-run bootstrap peer replacing 5mart.ml — a generalized opaque store-and-forward mailbox (untrusted-by-construction), PEX-advertised as a multi-bootstrap list (no SPOF). In-protocol sybil defence: self-decaying integer faucet; PoW client-puzzle (fixed integer target) gating each new device-faucet mint; personhood `scope_nullifier` (one-person-one-scope); web-of-trust via PLS-staked quorum verdicts.
- **L6 — Conformance + UX gating (GRAFTED from Variant B).** A versioned **Python-generated golden-vector corpus** run in CI against Pyodide-in-headless-browser — (object→canonical-CBOR hex), (object→CIDv1), (message→DER-sig hex over sha256), (Knit→signing_bytes+id), (relay pre-image bytes+sig), `faucet_micropulses(day)` on a day-grid incl. day0/100/101/large-k, `default_threshold(n)` for n=1..many. **A single differing byte BLOCKS cutover.** Asserts no float / no `Date.now()` / no `Math.random` leaked onto any decision/scoring/ordering path. PWA service-worker cache + lazy-load + JS splash neutralize cold-start. Corpus is also published as a multi-runtime protocol spec.

### Transport stack
Carrier: browser-native WebRTC `RTCDataChannel`, exposed to the Python engine through one new `WebRtcTransport(tag="webrtc")`. Framing reused verbatim (`onmessage -> read_frame_bytes`; `channel.send(write_frame_bytes(msg))`). Request/reply correlation mirrors relay.py's transport-only integer `_relay_rid` (stripped before signed logic; never wall-clock). Injected seams from the worker: `sleep`=setTimeout, `now`=integer monotonic clock, `rng`=WebCrypto-seeded PRNG, kademlia `responder`=real find-node round-trip. Override `BaseNode._id_proof_now` (verified the only `time.time()`, at `base_node.py:364`, used only for identity-proof freshness, never a CID/ordering input) with an injected integer clock; map `os.urandom` nonces to WebCrypto `getRandomValues`. Degraded mode: symmetric-NAT/CGNAT pairs fall back to a TURN-like relay carrying encrypted/opaque frames.

### Serverless bootstrap / discovery
A layered ladder where no rung requires a trusted server (QR → STUN → DHT/PEX → optional opaque mailbox). The legacy relay (`relay.py`) is untrusted-by-construction: it carries opaque length-prefixed CBOR frames, strips `_relay_*` before any signed/business logic, never decodes payloads, and every reader re-verifies the exact pre-image end-to-end via `relay_sync.verify_message` (verified `relay_sync.py:88`) — so it can neither forge nor replay under another identity.

### Wallet-QR signature-gated onboarding
A challenge→sign→verify handshake, **never an unauthenticated backdoor**. The QR encodes `{33-byte compressed pubkey hex, reflexive/relay multiaddr, signed single-use challenge}`. **VERIFY-BEFORE-CONNECT:** the scanner runs `crypto.verify(pubkey, preimage, sig)` BEFORE opening any DataChannel; an invalid/missing signature is rejected (no channel, no admission). Anti-replay: single-use nonce + injected-integer freshness window. The wallet IS the identity; possession of the private key is proven by the signature; verification is mandatory before admission. The signed-QR is the bootstrap of the existing `peer_identity_gate`/`identity.py` proof, not a parallel trust-free path.

### Serverless faucet / economy
No central rate-limiter → defences live entirely in-protocol and integer-only: (1) self-decaying faucet (verified `game.py:54–77`: day0 = `10_000_000 * MICROPULSES_PER_PULSE`; phase-1 linear `FAUCET_GENESIS - span*day//100`; phase-2 geometric `... * 99**k // 100**k` floored at `FAUCET_MIN_MICROPULSES = 1` µPLS; uses `//` only, no `/`/`round`/`float`); (2) PoW mint-gate (fixed integer SHA-256 target, NOT time-based); (3) personhood scope-nullifier `sha256(canonical.encode([DOMAIN,scope,secret]))` (one-person-one-scope, PII-free); (4) PLS-staked quorum web-of-trust. NO mint/buy/sell/list/royalty/transfer flow is ever added.

### Security threat model (summary; full verdicts in §critic)
- **MITM/signaling:** SDP exchanged only after wallet-signed-QR auth or peer-relayed path; DataChannel identity bound to the verified `ENVELOPE_PEER_KEY`; every frame's pre-image re-verified end-to-end.
- **Malformed/oversized frames:** `read_frame_bytes` rejects > 8 MiB; strict canonical decoder rejects non-minimal int heads, unsorted/duplicate keys, trailing bytes, depth>64; `on_frame_fault` penalizes the identified sender.
- **DoS:** `inventory`/`reconcile` token-buckets driven by a real injected monotonic integer clock (policy, not a CID path).
- **Sybil (honest limit):** probabilistic — PoW only raises cost; scheme-0 nullifier is the trusted-RP construction; web-of-trust is collusion-gameable. Tune so a sybil's marginal faucet value < its PoW+trust cost.
- **Key custody:** seed in IndexedDB; request `StorageManager.persist()` + signed-state/seed export; all entropy from WebCrypto CSPRNG; no private key ever leaves the worker.

---

## 4. The Phased Roadmap to Top-10

**North-star metric: Weekly Active Weavers (WAW)** — a peer counts only if it wove ≥1 real signed Fiber/Knit AND cast/received ≥1 real quorum vote that week. Top-10 entry band ramp: 1k → 10k → 100k → 200k–1M+ WAW.

**Supporting KPIs:** onboarding completion (QR-scan → first signed Knit) >60% (beats 68% connect-abandon baseline); D7 >30% / D30 repeat-weaver >20%; classmates-per-teacher ≥25 and K-factor >1; Fiber-CIDs-per-weaver & PoUW-certs/week (intrinsic-value proxy); % zero-required-server sessions >90% and infra-cost-per-1k-WAW → ~$0.

**Growth engine:** teacher-distributed QR-classroom virality paced by seasonal leaderboards. One teacher projects a wallet-signed classroom QR; 30 students scan and become real peers in seconds (signature-gated, not a backdoor). PoUW certificates double as gradeable artifacts that pull the next teacher in. Seasonal leaderboards reset reputation into seasons (anchor_ts is seasonal/display metadata ONLY, never on a CID/ordering path). The decaying faucet is marketed as built-in anti-farm pacing.

| Phase | Horizon | Goal | Metrics gate | Stays serverless how |
|---|---|---|---|---|
| **0 — Server-free MVP** | 0–8 wk | Unchanged engine runs IN the tab as a full peer; two QR-paired tabs weave a real Knit over direct WebRTC, no backend in the data path. | Recorded-session parity: server-mode vs tab-mode byte-identical `web_state_root`/UAL + DER sigs (zero corpus diff). Two physical tabs converge to the same Fiber CID with no server. Cold-start-to-playable < agreed budget. 10+ pilot pairs. | Two QR-paired peers need no relay/signaling/STUN; engine+ledger+quorum+persistence all in-tab; only static CDN hosts the shell. |
| **1 — Real classroom** | 2–5 mo | ~30 peers run real BFT verdicts among remote classmates; serverless signaling ladder + optional anyone-can-run relay. | A real 30-peer classroom reaches a shared `(2*n)//3+1` verdict and a single `web_state_root`. >90% direct WebRTC. Onboarding completion >50%. 5+ external teacher pilots. | Signaling degrades down a ladder bottoming out at QR; only optional host is a redundant untrusted opaque mailbox; classroom peers ARE the DHT/PEX fabric. |
| **2 — Serverless sybil economy + retire central stack** | 4–9 mo | Faucet/economy abuse-resistant with no central rate-limiter; delete every required server. | Zero required trusted server in data path for >90% of sessions; infra-cost-per-1k-WAW ~$0. Sybil cost model validated (marginal faucet value < PoW+trust cost). 1k–10k WAW with D30 repeat >20%. Django/PHP/bridge/Fly/Render/Docker deleted. | Abuse defence entirely in-protocol & integer-only (decaying faucet + PoW + nullifier + staked quorum); all economic math is original Python — no JS float on an economic path. |
| **3 — Distribution-rail scale to top-10 band** | 9–18 mo | Reach 200k–1M+ WAW via a thin Telegram/World-App Mini-App rail without surrendering serverless purity. | WAW into 100k → 200k–1M+ with D7 >30% / D30 repeat >20% HELD at scale. Mini-App stays thin (substrate converges with rail offline). >90% zero-server sessions at scale. | Rail is onboarding/notification only; consensus/ledger/faucet/persistence stay in-tab over direct WebRTC + optional volunteer relays; published multi-runtime spec lets non-Pyodide peers join without molgang infra. |

---

## 5. The Source-Code Deliverable (Manifest & Integration)

**STATUS WARNING (verified on disk, 2026-06-21):** the intended deliverable is ~18 files, but only **4 exist** in `/tmp/molgang-plan/serverless/`. The rest are designed/manifested but **not yet written**. See §Gaps. The manifest also contains a self-conflict: two distinct files are both named `webnode/__init__.py` (one a thin re-export marker, one the `WebNodeRuntime` entrypoint + PWA glue) — they cannot coexist; the runtime must move to e.g. `webnode/runtime.py`.

### Files that EXIST on disk (verified, invariant-clean)
- `serverless/src/molgang/webnode/merge_bridge.py` (332 lines) — in-tab deterministic merge bridge. *Wraps, does not re-implement*: dedups by `relay_sync.item_keys`, verifies via `verify_message` (exact pre-image), folds through the World's `weave_*` (co-woven Fiber BUMPS integer confirmations/tension). Provides `account_from_seed` (pure `AccountNode.from_seed`, retires `pulse_host.py` subprocess) and `MergeBridge.from_seed`. Verified: integer-only, no `time.time()`/`random`, all CID/CBOR/state_root bytes produced by unchanged modules.
- `serverless/src/molgang/webnode/__init__.py` — package marker re-exporting `MergeBridge, account_from_seed, WEB_TOPIC`.
- `serverless/web/signaling.js` (977 lines) — signaling ladder + WebRTC ownership. Verified: verify-before-connect signature gate, `crypto.getRandomValues` only (never `Math.random`), byte-identical wire contract, domain-tag separation so an onboarding sig can never be replayed as an identity proof.
- `serverless/web/store_idb.js` (463 lines) — content-addressed IndexedDB block store + outbox. Verified: monotone integer `seq` (NOT `Date.now()`), `getRandomValues` (never `Math.random`), `MAX_FRAME_BYTES = 8388608` mirrored for length-validation only, JS never computes a CID/CBOR/signature/state_root.

### Files DESIGNED but NOT YET on disk (must be written)
- `serverless/web/index.html` — PWA shell; no `/api/*` referenced; keeps every legacy DOM id; boot splash; signature-gated QR modal; loads `peer.js` as `type=module`.
- `serverless/web/peer.js` — Pyodide loader + thin shell; correlation-id postMessage RPC replacing `fetch('/api/*')` (keeps legacy response shapes on `window.MOLGANG_ENGINE`); owns RTCPeerConnection; verify-before-connect; derives seed from CSPRNG in localStorage; registers SW; `StorageManager.persist()`.
- `serverless/web/manifest.webmanifest` — installable PWA manifest (inline SVG icons; no token/NFT framing).
- `serverless/web/sw.js` — offline-first SW (GRAFT 2): cache-first versioned shell + stale-while-revalidate Pyodide CDN; only GET intercepted; no `/api/*`; never caches signed frames or the seed.
- `serverless/web/transport_webrtc.js` — browser-side DataChannel transport; exact 4-byte BE framing + 8 MiB guard; integer `_relay_rid` RPC; moves opaque pre-framed bytes only; `getRandomValues` only.
- `serverless/web/onboard.js` — browser counterpart of the onboarding gate; builds byte-identical pre-image + DER sig (`@noble/secp256k1` + `@noble/hashes` + minimal DER codec matching Python `cryptography`'s DER shape); CSPRNG nonces.
- `serverless/src/molgang/webnode/transport.py` — Python `WebRtcTransport(tag="webrtc")` adapter (the ONE new engine file); satisfies the 5-method Protocol; bridges to `transport_webrtc.js` over postMessage; reuses `write_frame_bytes`/`read_frame_bytes` verbatim; integer rid; `ENVELOPE_PEER_KEY` stamping.
- `serverless/src/molgang/webnode/onboard_verify.py` — stateless challenge→sign→verify; `verify_onboarding()` is the only admission path; rejects unsigned/malformed/expired/future/replayed/wrong-scope/wrong-audience; integer freshness; injected clock + injected nonce bytes; uses unchanged `knitweb.core.crypto`.
- `serverless/src/molgang/webnode/contract.py` — versioned `CONTRACT_VERSION='webnode/1'` source of truth for the RPC + state contract; mirrors frozen constants read-only; per-method allowed-arg tuples (unknown arg fails closed); `assert_jsonsafe` float-rejecting boundary guard (the only float that may cross is an integral injected-clock timestamp).
- `serverless/src/molgang/webnode/peer.py` — the in-browser peer composed from unchanged modules + the one new `WebRtcTransport`; deterministic `from_seed` identity (no subprocess); injected integer clock; `qr_offer`/`qr_admit` verify-before-connect.
- `serverless/src/molgang/webnode/runtime.py` *(resolve the `__init__.py` name conflict here)* — `WebNodeRuntime` owning the single `WebPeer`; `on_hello` version-gate (fail-closed), `on_rpc` parse/validate/refresh-seams/await/post; `install_worker_bridge` Pyodide wiring; `main()` stdin/stdout JSON-line harness so server-mode vs tab-mode `state_root`s diff in CI without a browser.
- `serverless/README.md` — build/serve the static zero-backend PWA; optional bootstrap peer; injected-seam discipline; conformance gate.

### How the pieces integrate (data flow)
`index.html` → loads `peer.js` (module) → boots Pyodide worker → installs `runtime.py`'s bridge → worker hosts `peer.py` (the WebPeer) which is the unchanged Bar + knitweb over the new `webnode/transport.py`. UI intents → `contract.py`-validated postMessage RPC → in-worker Bar calls (replacing `/api/*`). Outbound frames: Python `write_frame_bytes` → opaque bytes → `transport_webrtc.js`/`signaling.js` → DataChannel. Inbound: DataChannel → `read_frame_bytes` → `_dispatch` → `merge_bridge.py` fold → `store_idb.js` persists by CID. Onboarding: `onboard.js`/`onboard_verify.py` verify-before-connect gate every new peer. CI: `runtime.py main()` + the L6 golden-vector corpus prove byte-identity before any cutover.

---

## 6. Risks, Open Questions & Migration / Compatibility Plan

### Migration (lowest-risk first; each step demoable & reversible)
1. **LOW** — kill `pulse_host.py` subprocess: always `AccountNode.from_seed`, seed in IndexedDB (the `_local_fallback` already proves the no-subprocess path). One server dependency gone, zero protocol change.
2. **HIGH (keystone)** — boot the unchanged engine in a Pyodide module-Worker; lift the Bar in-worker; replace `fetch('/api/*')` with postMessage RPC. **Gate on the L6 conformance corpus + a recorded-session `state_root`/UAL diff between server-mode and tab-mode to PROVE parity before cutover.**
3. **HIGH** — implement the single `WebRtcTransport` + `add_transport`; wire injected seams from the worker; **keep `relay.py` as an optional opaque fallback carrier** so a mixed web (server nodes on tcp/relay, browser peers on webrtc) converges over identical frame bytes with no protocol fork.
4. **MEDIUM** — serverless signaling ladder + PoW/nullifier/stake sybil layer; retire Django/PHP/bridge/Fly/Render/Docker.

### Compatibility plan for the existing engine & 5mart.ml relay
The 5mart.ml relay is **degraded to an optional bootstrap peer**, not deleted: it stays an untrusted opaque store-and-forward mailbox (it cannot forge or replay), generalized from one hard-coded URL to a PEX-advertised multi-bootstrap list. Direct WebRTC takes over after handshake and the relay drops out of the data path. Because dedup is content-addressed (`item_keys`) and the signed pre-image is transport-agnostic, server-side nodes still talking to 5mart.ml and in-tab WebRTC peers converge on the same World. No flag-day; the migration is incremental and each step reversible.

### Top risks (with mitigations)
- **Byte-identity drift (highest severity).** One differing byte in canonical-CBOR/CID/DER/faucet output silently forks the classroom. Mitigation: ship unchanged `.py` bytes; gate every cutover on the L6 corpus in CI. Residual surface = CPython-vs-Pyodide secp256k1 DER/**low-S** — pin the backend and a known-answer vector. **Note the trap: Python `cryptography` does NOT force low-S; the in-tab signer must match Python's exact DER/S behavior, not "standard" low-S.**
- **WebRTC is not fully relay-free.** Symmetric-NAT/CGNAT pairs may need a TURN-like relay in the data path. Keep multi-bootstrap opaque-frame relays as documented degraded mode; "no required server" = no required *trusted* server; target >90% direct, not 100%.
- **Serverless sybil resistance is probabilistic.** Layer all four defences and tune economic params; revisit EC-VRF scheme-1 for trustless uniqueness.
- **Retention-without-speculation unproven at scale.** Lean on the intrinsic education+incentive loop; teacher-cohort distribution is the primary cold-start hedge.
- **Distribution-rail paradox.** The Mini-App reintroduces a central onboarding/notification gatekeeper; keep it thin and rail-independent.
- **Browser storage is evictable.** `StorageManager.persist()` + signed-state/seed export + peer re-sync; restore saved balance, never re-mint.
- **Onboarding-as-backdoor regression.** Keep verify-before-connect; single-use nonce + injected-integer freshness; no admission path without a valid signature.
- **Invariant leak across the WASM boundary.** JS shell never touches a hashed/signed/economic path; conformance asserts float-free + no wall-clock/randomness on decision paths + `anchor_ts` display-only; keep `MAX_FRAME_BYTES = 8388608` identical.

### Open questions
1. secp256k1 in Pyodide: confirm `cryptography` (cffi/OpenSSL) loads in-WASM AND emits byte-identical DER/low-S vs native CPython; else pin a coincurve-wasm/pure-Python fallback gated by a known-answer vector.
2. Pyodide cold-start + tens-of-MB wasm download and JS↔WASM bridge cost on the hot DataChannel path must be profiled.
3. NPC quorum bots (`bar.py _seed_bots`/`_bots_act`): decide local-only-UX vs deterministic/shared to avoid per-tab divergence before convergence.
4. Sybil economic tuning (faucet decay / PoW difficulty / stake weights); whether to implement EC-VRF scheme-1.
5. Distribution-rail purity: keep the Mini-App rail-independent.
6. `StorageManager.persist()` grant rates; verify wiped-tab restore without re-faucet abuse.
7. kademlia lookup-recall (flagged open in the prior Track-P audit, owner's call) — confirm before relying on DHT-assisted signaling.

---

## 7. Definition of Done — The Serverless MVP

The serverless MVP is DONE when **all** hold:

1. **Engine in the tab.** The unchanged `molgang`+`knitweb` Python runs in a Pyodide module-Worker; `webserver.py`/Django/PHP are no longer REQUIRED; `app.js`'s `fetch('/api/*')` is fully replaced by postMessage RPC.
2. **No subprocess.** Identity is `AccountNode.from_seed` from an IndexedDB seed; `pulse_host.py`'s `subprocess.run` is gone.
3. **Two physically-separate, QR-paired tabs weave a real Knit over a direct WebRTC DataChannel with NO server in the data path** and converge to the **same Fiber CID** and **same `web_state_root`/UAL**.
4. **Byte-identity proven.** The L6 golden-vector corpus passes byte-for-byte in CI against Pyodide-in-headless-browser, AND a recorded-session `state_root`/UAL + DER-sig diff between server-mode and tab-mode shows **zero differing bytes**. A single differing byte blocks DONE.
5. **Onboarding is signature-gated.** `crypto.verify` of the signed challenge runs BEFORE any DataChannel opens; single-use nonce + injected-integer freshness; no admission path exists without a valid signature.
6. **Invariants assert-tested.** CI asserts float-free + no `time.time()`/`Math.random`/`Date.now()` on any decision/scoring/ordering path; `anchor_ts` excluded from CID/state-root; `MAX_FRAME_BYTES = 8388608` unchanged.
7. **Persistence + recovery.** State is content-addressed in IndexedDB keyed by `canonical.cid()`; `StorageManager.persist()` requested; a wiped tab re-derives identity from the seed/QR and re-syncs from peers **without re-faucet abuse**.
8. **5mart.ml is optional.** The relay is degraded to an optional, untrusted, multi-bootstrap opaque mailbox; QR-paired peers transact with it absent.
9. **No forbidden constructs.** No NFT/mint/buy/sell/list/royalty/transfer flow; no "loom" in any shipped artifact.

---

## Adversarial Critic — Verdicts & Remaining Gaps

(Full verdict strings are returned in the structured fields. Summary below.)

**Hidden required central server?** None *required*. The relay is untrusted-by-construction and optional; STUN is stateless/swappable; QR-paired peers need nothing. Caveats (honest): (i) a static CDN still serves the shell — but it is stateless and any host works, not a trusted source of state; (ii) symmetric-NAT/CGNAT pairs need a TURN-like relay *in the data path* (carrying only opaque/encrypted frames) — "no required server" means "no required *trusted* server," target >90% direct; (iii) the Phase-3 Telegram/World Mini-App rail is a central onboarding/notification gatekeeper — acceptable ONLY while it stays thin and the substrate converges with the rail offline.

**Sacred-invariant violations?** None found in the code that exists. Integer-only verified (`game.py` faucet `//`-only, `quorum.py (2*n)//3+1`, `merge_bridge` integer SUM). No wall-clock/randomness on decision paths: the only `time.time()` is `base_node.py:364 _id_proof_now` (identity-proof freshness, overridable, never a CID/ordering input); RNG is `os.urandom`/`secrets.token_hex` nonces (injectable). One float to flag (NOT a violation): `relay_sync.py:203/241` uses `float` for the relay-fetch pagination **cursor/since** — a transport-layer high-water mark, never on a CID/economic/ordering path; it must stay off any decision path (the in-tab transport should carry it as an opaque integer/string). Byte-identity is free-by-construction (unchanged `.py` bytes); the only residual surface is CPython-vs-Pyodide secp256k1 DER/low-S, closed by the L6 gate.

**Forbidden "loom" usage?** None. The only `loom` occurrences are in `Never "loom"` guard comments — compliant, not violations.

**Onboarding backdoor / key-custody hole?** No backdoor in the design or existing code: verify-before-connect is the only admission path; single-use nonce + injected-integer freshness blocks replay; `signaling.js` uses domain-tag separation so an onboarding sig can never be replayed as an identity proof; no private key leaves the worker. Honest residual: `StorageManager.persist()` is best-effort (evictable storage) — mitigated by signed-state/seed export. Sybil resistance is probabilistic, not absolute.

**Top remaining gap (must be stated plainly):** the **source-code deliverable is materially incomplete** — only 4 of ~18 manifested files exist on disk. The plan is sound and the existing 4 files are invariant-clean, but the keystone files (`peer.py`, `webnode/transport.py`, `contract.py`, `onboard_verify.py`, `runtime.py`, and the entire `web/` shell beyond `signaling.js`/`store_idb.js`) plus the L6 golden-vector corpus are **not yet written**. The DONE criteria in §7 cannot be met until they are. Additionally, the manifest's two-`__init__.py` conflict must be resolved (move `WebNodeRuntime` to `runtime.py`).