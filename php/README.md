# MOLGANG — PHP/MySQL dapp (shared-hosting build)

A **request-driven** PHP + MySQL port of the MOLGANG bar, for hosts that **can't run a
long-lived Python process** (e.g. TransIP shared hosting). Every request is a fresh PHP
process — no daemon — so it deploys anywhere PHP 8 + MySQL exist. It serves the **same 3D
frontend** and the **same `/api/*` JSON** a bot (or the desktop client) drives.

Reuses the canonical web client unchanged (`app.js` is path-prefix-safe), so it works served
at `https://5mart.ml/molgang/` or at the root.

## What it implements
- Walk-in → **device→PLS wallet** (deterministic, no stored key), faucet 50 PLS / 10 silk.
- Sit at a table (Periodic Bar / Organic Lounge / Noble Corner), **knit a term** (1 silk).
- NPC table-mates + human peers **vote with a pulse**; a **BFT confirm-quorum** weaves the
  term into the table's fabric as a content-addressed **Fiber**.
- The shared **Knitweb** view: woven terms + links (`A = B` → `A —is→ B`), a `state_root`,
  an OriginTrail-style **anchor**, and a NetworkX-free **graph explorer** (hubs / neighbors /
  shortest path) — all in PHP.
- **Cross-client presence:** the browser shows whether the **desktop** app is active / was
  used before, and the desktop reads the same `/api/presence` to see the browser — keyed by
  the shared device→wallet identity (see `desktop_bridge.py`).

## Layout
```
php/
  public/            ← web root for the /molgang sub-site
    index.php        front controller (routes /api/*; Apache serves static directly)
    .htaccess        static passthrough + /api routing + blocks config/src
    index.html app.js style.css avatars/   ← the 3D frontend
  src/               Bar.php · Db.php · Parse.php · Chemistry.php · Progression.php
  schema.sql         MySQL DDL
  config.example.php → copy to config.php on the host (gitignored; never committed)
  desktop_bridge.py  desktop ↔ dapp presence bridge (optional)
  tests/smoke.php    full-engine smoke test (SQLite, no server needed)
```

## Deploy on shared hosting (e.g. TransIP / 5mart.ml/molgang)
1. **Create the DB** in the control panel (e.g. `5martm_ED`) and a DB user.
2. **Apply the schema:**
   ```bash
   mysql -h localhost -u <dbuser> -p <dbname> < php/schema.sql
   ```
3. **Configure:** copy `php/config.example.php` → `php/config.php` and fill in the real
   `host/name/user/pass`. `config.php` is gitignored and `.htaccess`-blocked from HTTP.
4. **Publish:** upload the contents of `php/` so that `php/public/` is reachable at
   `https://5mart.ml/molgang/` (point the subdir/docroot there, or rsync `public/` into
   `~/www/molgang/` and keep `src/` + `config.php` one level up, outside the web root).
5. Open `https://5mart.ml/molgang/` — walk in and knit. Phones get a stable wallet via
   `localStorage`; rejoin = same account.

### PHP settings
Needs only PHP core + **pdo_mysql**. Recommended toggles: `opcache` on,
`opcache.validate_timestamps` on, `log_errors` on; `display_errors` **off**,
`allow_url_include`/`allow_url_fopen` **off**.

## Desktop ↔ browser awareness
The desktop client beats the dapp so the two see each other:
```bash
KNODE_DAPP=https://5mart.ml/molgang MOLGANG_DEVICE=<device-id> python3 php/desktop_bridge.py --watch
```
The browser then shows **🖥️ desktop active**; the desktop prints whether the **browser** is
active/used-before. Both resolve to the same device→wallet identity.

## Live knitweb node — HTTP relay + signed onboarding (Refs #61 #62 #63)

5mart.ml also runs as an **always-on knitweb presence + relay node**. Because shared hosting
**blocks all inbound TCP** (a process can `bind()` but the perimeter firewall drops inbound from
the internet — see [`PORTCHECK.md`](PORTCHECK.md)), the transport is **HTTP through the
always-on nginx**, request-driven like the rest of the dapp. Peers rendezvous via 5mart.ml: a
node POSTs a **signed** message, the relay stores it (MySQL), and the recipient polls for it.

### Wallet-signed QR onboarding (#63)
A node joins by proving control of its **knitweb wallet** (secp256k1 / the exact
`knitweb.core.crypto` scheme: ECDSA over SHA-256, 33-byte compressed pubkey hex, DER sig hex).

1. `GET /api/onboard/challenge` → `{ challenge, endpoint, qr, qr_image, … }`. The **QR** encodes
   `knitweb://onboard?endpoint=…&challenge=…` so a phone/desktop wallet can scan it.
2. The wallet **signs the exact `challenge` string** and `POST`s
   `/api/onboard/register` `{ pubkey, sig, device_fp, challenge, endpoint? }`.
3. PHP **verifies the signature** (`src/Crypto.php`, via the bundled OpenSSL — a compressed
   secp256k1 point is wrapped into an SPKI PEM, no GMP/native lib needed). **Only on a valid
   signature** is the node's `(pubkey, derived pls1 address, device_fp)` written to the new
   **`node_registry`** table. Missing/forged/expired/replayed signatures are rejected (`400`),
   and the challenge is one-time-use (burned in `node_challenge`). **Signature-gated writes only.**

### HTTP relay + presence (#61)
Registered nodes talk through 5mart.ml. Every relayed message carries the sender's signature so
the reader re-verifies it end-to-end (the relay is dumb store-and-forward).

| route | method | purpose |
|---|---|---|
| `/api/relay/info`   | GET  | node identity/health card (online count, etc.) |
| `/api/relay/online` | GET  | roster of currently-live nodes |
| `/api/relay/ping`   | POST | `{pubkey, endpoint?}` heartbeat (registered only) |
| `/api/relay/send`   | POST | `{from, to?, topic?, body, sig}` store a **signed** message |
| `/api/relay/fetch`  | GET  | `?to=&topic=&since=` poll for messages (broadcast + addressed) |

The signed preimage for relay is `"knitweb-relay:v1\n<to>\n<topic>\n<body>"`.

### Schema + tests
```bash
mysql -h HOST -u USER -p DBNAME < php/node_registry.sql   # additive: node_registry, node_challenge, relay_message
php php/tests/relay_smoke.php    # signature-gate proof (SQLite, no server): onboard/relay accept-valid, reject-forged/replayed
```

> **Why OpenSSL and not a pure-PHP secp256k1 lib:** PHP 8.1's bundled OpenSSL supports secp256k1,
> ECDSA-SHA256 and DER signatures, and parses **compressed** SEC1 points directly into an SPKI
> PEM. A real signature produced by Python's `cryptography` (the same lib `knitweb.core.crypto`
> uses) verifies under this PHP path, and the PHP-derived `pls1` address byte-matches
> `knitweb.core.crypto.address`. No native build, no vendored lib.

### Monitor — read-only health dashboard (#59 #60)
A request-driven health lens over the live node, served by the always-on PHP/nginx (no daemon).
`public/monitor.html` is a self-contained dashboard (inline CSS+JS, no external deps) that polls
one endpoint every 4s and renders the node roster, the woven Knitweb (knowledge graph), relay
throughput and game liveness.

| route | method | purpose |
|---|---|---|
| `/api/monitor`   | GET | one read-only snapshot: `node`, `registry`, `relay`, `web`, `game`, `health` |
| `monitor.html`   | GET | the dashboard (static; path-prefix-safe, works under `/molgang/`) |

`Monitor::summary()` is **strictly read-only** — only `SELECT`/`COUNT`, never an
`INSERT`/`UPDATE`/`DELETE` — so polling it can never mutate node, relay or game state. It reuses the
canonical read methods (`Relay::info`/`Relay::online`, `Bar::web`) so it can't drift from what those
endpoints report, and it surfaces relay **envelopes only** — never message bodies.
```bash
php php/tests/monitor_smoke.php   # 13 checks incl. the read-only proof (row counts unchanged) + no-body-leak guard
```

## Test
```bash
php php/tests/smoke.php     # join → sit → knit → quorum → woven → web → presence (SQLite, no DB needed)
```
