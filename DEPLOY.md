# Deploying MOLGANG (e.g. https://5mart.ml/molgang)

The bar is a single Python process (`molgang serve`) that serves the `web/` UI **and** the JSON
API. The browser client (`app.js`) is **path-prefix-safe** *and* can point at a **remote** API:
it reads `window.MOLGANG_API` from [`web/config.js`](web/config.js).

For the full p2p deployment there are two game hosts:

| Host | Role |
|------|------|
| **5mart.ml / TransIP** | PHP/MySQL dapp plus HTTPS relay/presence node (`/api/onboard/*`, `/api/relay/*`) |
| **Port-forwarded Python server** | Live `molgang serve` game API registered into the same relay fabric |

For the browser/backend split there are two parts:

| Part            | What                                   | Where it can live                               |
|-----------------|----------------------------------------|-------------------------------------------------|
| **Static UI**   | `web/` (html/js/css/avatars)           | any static/PHP webhost — incl. **TransIP shared hosting** |
| **Backend API** | `molgang serve` (long-lived Python)    | a small **always-on** box: Fly.io / Render / VPS / Pi |

> ⚠️ Plain shared webhosting (PHP/static only, no persistent Python, often **no `mod_proxy`**)
> **cannot** keep `molgang serve` running and usually **cannot reverse-proxy** to it.
> On such a host (e.g. TransIP shared hosting, where `5mart.ml` lives), serve the **static UI**
> there and point it **cross-origin** at the backend via `config.js` + CORS (below).

---

## A. Static UI on shared hosting (what's live at https://5mart.ml/molgang/)

Upload the `web/` folder into a subdir, e.g. `~/www/molgang/`:

```bash
git clone https://github.com/knitweb/molgang
rsync -a molgang/web/ user@host:~/www/molgang/      # index.html, app.js, style.css, config.js, avatars/
```

It serves immediately as static files (no rewrite rules needed). The UI loads, but the API
calls 404 until a backend exists and `config.js` points at it.

---

## B. Backend API on an always-on box

### Fly.io (one command after first launch)
```bash
fly launch --no-deploy --copy-config --name molgang   # first time only (reads fly.toml)
fly volume create molgang_data --size 1                # 1 GB persistent /data
fly deploy                                             # ← the command to (re)bring it up
# → https://molgang.fly.dev
```

### Render (Blueprint)
```bash
# Dashboard → New → Blueprint → this repo → Apply   (reads render.yaml)
# or with the Render CLI:
render blueprint launch
# → https://molgang.onrender.com
```

Both use the repo `Dockerfile` (python:3.12-slim → clones the knitweb engine
`github.com/knitweb/pulse` → `pip install -e /pulse -e .` →
`molgang serve --port 8080 --world /data/world.json --db /data/reg.db`).
State (shared world + device→wallet registry) lives on the mounted `/data` volume.

### Or any VPS / Pi (manual)
```bash
git clone https://github.com/knitweb/molgang && cd molgang
git clone https://github.com/knitweb/pulse ../pulse      # the knitweb engine (sibling)
python3 -m venv .venv && . .venv/bin/activate
pip install -e . -e ../pulse
molgang serve --port 8765 --world ~/.molgang/world.json --db ~/.molgang/registry.db
# keep alive with systemd / pm2 / tmux (see unit at the bottom)
```

### Always-on relay convergence
After TCP `8765` is forwarded to the Python server and reachable from the internet, point the
server at the 5mart relay:

```bash
molgang serve \
  --port 8765 \
  --world ~/.molgang/world.json \
  --db ~/.molgang/registry.db \
  --relay https://5mart.ml/molgang/api/relay \
  --relay-wallet ~/.molgang/server-node.cbor \
  --relay-interval 60 \
  --monitor \
  --monitor-nodes alice=8900,bob=8901
```

That process pulls relayed world items on startup, pushes each local woven knit back to the
relay, keeps `/api/monitor` available for the dashboard, and exposes `/api/relay` with the
local relay status. Use `POST /api/relay/pull` for an immediate manual pull.

---

## C. Point the static UI at the backend (config.js)

Edit `web/config.js` on the static host and set the backend origin, then re-upload it:

```js
window.MOLGANG_API = "https://molgang.fly.dev";   // or https://molgang.onrender.com
```

Leave it `""` for **same-origin** (root, `/molgang/` subpath via reverse-proxy, or self-served
by `molgang serve`). The backend already sends CORS headers (`Access-Control-Allow-Origin: *`)
so the cross-origin call from `5mart.ml` works out of the box. To restrict it:

```bash
molgang serve ... --cors https://5mart.ml      # or --cors '' to disable
```

---

## D. Same-origin instead (only if the host supports it)

If the host *can* reverse-proxy (nginx in front, or Apache with `mod_proxy`), put the API under
`/molgang/` and leave `MOLGANG_API` empty — no CORS needed:

```nginx
location /molgang/ {
    proxy_pass http://127.0.0.1:8765/;   # trailing slash strips the /molgang prefix
    proxy_set_header Host $host;
}
```
The client detects the `/molgang` base automatically — no rebuild. (TransIP **shared** hosting
does **not** offer this; use the cross-origin config.js path above.)

---

## E. Email subscription & daily digest (optional)

Players can opt-in to receive a **daily digest** email with their weaving stats and a redacted
PoUW certificate (proof of work, no private key). The implementation satisfies **security gate
#55**: subscriber copies receive the **public/redacted certificate** (address + public key +
work summary); only the operator BCC receives the bearer key (if any) for early-stage oversight.

### Setup

1. **Generate the encryption key** (required; 32 random bytes in hex):
   ```bash
   openssl rand -hex 32
   ```
   Copy the output and paste it into `php/config.php`:
   ```php
   'email_cipher_key' => 'YOUR_RANDOM_HEX_STRING_HERE',
   ```
   This key encrypts subscriber emails at-rest in the MySQL database. **Never commit this file.**

2. **Apply the schema update:**
   ```bash
   mysql -h HOST -u USER -p DBNAME < php/schema.sql
   ```
   This creates the `subscriber` table (device_id, email_enc, iv_hex, email_hmac, created).

3. **Configure email (optional SMTP; defaults to sendmail):**
   In `php/config.php`:
   ```php
   'email_from' => 'noreply@5mart.ml',
   'bcc_operator' => 'bug@5mart.ml',
   // 'email_smtp_host' => 'smtp.example.com',
   // 'email_smtp_port' => 587,
   ```

4. **Wire the cron job** to send digests daily (e.g., 09:00 UTC):
   ```bash
   0 9 * * * php /path/to/molgang/php/cron_digest.php >> /var/log/molgang_digest.log 2>&1
   ```

### How it works

- **Frontend**: A "📧 subscribe" box appears at the top of the page (hidden once subscribed).
  Players enter their email → POST `/api/subscribe {device, email}` → success hides the box.

- **Backend**: `Subscribe::subscribe()` normalizes the email, validates it, encrypts it with
  AES-256-CBC (random IV per record), and stores HMAC-SHA256 in a UNIQUE column for idempotent
  subscribe (same email twice = no error, no duplicate).

- **Cron**: `php/cron_digest.php` runs daily, fetches all subscribers, decrypts their emails,
  builds a summary (knits woven, votes cast, bar stats), and sends each an email with a
  **redacted PoUW certificate**. The operator BCC sees the same email (with bearer key if
  configured).

### Security (Refs #55)

- **Encryption**: AES-256-CBC with random IV. The 32-byte key is set in `config.php` (git-ignored).
- **Plaintext protection**: No plaintext email ever hits disk or the database. Queries use prepared
  statements.
- **Certificate redaction**: The subscriber's copy of the PoUW certificate strips any private key
  before mailing. The operator's BCC can hold a bounded, documented bearer key for custodial
  oversight during beta. See `php/cron_digest.php` for the redaction logic.
- **Testing**: Run `php php/tests/subscribe_test.php` to verify encryption/decryption,
  idempotence, input validation, and cert redaction.

---

## Phone play
Open `https://5mart.ml/molgang` on the phone → the browser mints a stable **device id**
(localStorage) → a deterministic **PLS wallet**, registered in the sqlite DB. Leave and rejoin
from the same phone and you're back in the same account.

## systemd unit (VPS keep-alive example)
```ini
[Unit]
Description=MOLGANG bar
[Service]
WorkingDirectory=/home/USER/molgang
ExecStart=/home/USER/molgang/.venv/bin/molgang serve --port 8765 --world %h/.molgang/world.json --db %h/.molgang/registry.db
Restart=always
[Install]
WantedBy=default.target
```
