# Deploying MOLGANG (e.g. https://5mart.ml/molgang)

The bar is a single Python process (`molgang serve`) that serves the `web/` UI **and** the JSON
API. The browser client is **path-prefix-safe** (`BASE` in `app.js`), so it works served at the
root *or* under a subpath like `/molgang/`.

## What the host needs
A box that can run a **long-lived Python 3.10+ process** and listen on a port.
> ⚠️ Plain shared webhosting (PHP/static only, no persistent processes) **cannot** keep
> `molgang serve` running. Options, cheapest first:
> 1. A small always-on VPS / container (TransIP VPS, Fly.io, Railway, Render, a Pi).
> 2. Then point `5mart.ml/molgang` at it with a reverse proxy (below) or a redirect.

## Run it (on the host)
```bash
git clone https://github.com/knitweb/molgang && cd molgang
git clone https://github.com/febuz/pulse ../pulse        # the knitweb engine (sibling)
python3 -m venv .venv && . .venv/bin/activate
pip install -e . -e ../pulse
molgang serve --port 8765 \
  --world ~/.molgang/world.json \
  --db    ~/.molgang/registry.db        # device → PLS-wallet registry (sqlite)
# keep it alive with systemd / pm2 / tmux
```

## Serve it at /molgang (nginx in front)
```nginx
location /molgang/ {
    proxy_pass http://127.0.0.1:8765/;   # trailing slash strips the /molgang prefix
    proxy_set_header Host $host;
}
```
The client detects the `/molgang` base automatically — no rebuild needed.

## Phone play
Open `https://5mart.ml/molgang` on the phone → the browser mints a stable **device id**
(localStorage) → a deterministic **PLS wallet**, registered in the sqlite DB. Leave and rejoin
from the same phone and you're back in the same account.

## systemd unit (keep-alive example)
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
