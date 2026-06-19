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

## Test
```bash
php php/tests/smoke.php     # join → sit → knit → quorum → woven → web → presence (SQLite, no DB needed)
```
