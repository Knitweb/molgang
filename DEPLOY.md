# Deploying MOLGANG (e.g. https://5mart.ml/molgang)

The bar is a single Python process (`molgang serve`) that serves the `web/` UI **and** the JSON
API. The browser client (`app.js`) is **path-prefix-safe** *and* can point at a **remote** API:
it reads `window.MOLGANG_API` from [`web/config.js`](web/config.js).

So there are two parts:

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
