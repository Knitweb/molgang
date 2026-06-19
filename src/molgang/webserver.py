"""MOLGANG browser bar — a stdlib HTTP server.

Serves the bar UI (the `web/` folder) AND a small JSON API over one live `Bar`. The SAME
endpoints are used by humans (the browser) and machines (bots/agents) — dual play:

    GET  /api/state?sid=…              full bar snapshot (tables, seats, avatars, open knits)
    POST /api/join     {name,avatar,table?}   walk in (free silk + pulses), optionally sit
    POST /api/sit      {sid,table}            take a seat at a table
    POST /api/propose  {sid,term}             brainstorm + knit a term (spends silk)
    POST /api/vote     {sid,pid,verdict}      vote with a pulse ('confirm'|'mismatch'|'abstain')
    POST /api/certificate {sid}               download a PoUW Certificate PDF (exposes priv key!)

    molgang serve --port 8765
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .bar import Bar, suggested_terms
from .pulse_host import bootstrap_host, default_wallet_path

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web")
_CTYPE = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
          ".json": "application/json", ".svg": "image/svg+xml"}


def make_handler(bar: Bar, pulse_host: dict | None = None, cors: str | None = "*",
                 monitor=None, relay=None):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            # Let the static UI (e.g. https://5mart.ml/molgang/) hit this API cross-origin.
            if cors:
                self.send_header("Access-Control-Allow-Origin", cors)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "86400")

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _pdf(self, body: bytes, filename: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(WEB_DIR) or not os.path.isfile(full):
                return self._json(404, {"error": "not found"})
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", _CTYPE.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            if path == "/api/state":
                from urllib.parse import parse_qs, urlparse
                sid = parse_qs(urlparse(self.path).query).get("sid", [None])[0]
                state = bar.state(sid)
                state["pulse_host"] = pulse_host
                return self._json(200, state)
            if path == "/api/pulse":
                return self._json(200, pulse_host or {})
            if path == "/api/suggested":
                return self._json(200, {"terms": suggested_terms()})
            if path == "/api/web":
                return self._json(200, bar.web_view())
            if path == "/api/device":
                from urllib.parse import parse_qs, urlparse
                did = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
                reg = bar.registry.get(did) if (bar.registry and did) else None
                return self._json(200, {"registered": bool(reg), "wallet": reg})
            if path == "/api/graph":
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                return self._json(200, bar.world.explore(
                    term=(q.get("term") or [None])[0],
                    frm=(q.get("from") or [None])[0],
                    to=(q.get("to") or [None])[0]))
            if path.startswith("/api/monitor"):
                return self._monitor(path)
            if path == "/api/relay":
                if relay is None:
                    return self._json(200, {"enabled": False})
                return self._json(200, {"enabled": True, "base": relay.base,
                                        "topic": relay.topic, "node": relay.signer.pub,
                                        "address": relay.signer.address, "cursor": relay.cursor})
            return self._static(path)

        # -- 📡 Monitor: node/p2p status + the local woven knitweb (#59 #60) ----
        def _monitor(self, path: str) -> None:
            from urllib.parse import parse_qs, urlparse
            if monitor is None:
                return self._json(503, {"error": "monitor unavailable"})
            q = parse_qs(urlparse(self.path).query)
            if path == "/api/monitor":                      # one compact poll for the tab
                return self._json(200, monitor.overview())
            if path == "/api/monitor/status":               # node/p2p liveness + provenance
                return self._json(200, monitor.node_status())
            if path == "/api/monitor/kg/stats":             # nodes/edges/concepts/languages
                return self._json(200, monitor.kg_stats())
            if path == "/api/monitor/kg/hubs":
                n = int((q.get("n") or ["12"])[0])
                return self._json(200, monitor.kg_hubs(n))
            if path == "/api/monitor/kg/tension":           # taut/slack/snapped bands
                return self._json(200, monitor.kg_tension())
            if path == "/api/monitor/kg/subgraph":          # focused graph for the viz
                term = (q.get("term") or [""])[0]
                depth = int((q.get("depth") or ["2"])[0])
                langs = q.get("lang")
                sg = monitor.kg_subgraph(term, depth, set(langs) if langs else None)
                if sg is None:
                    return self._json(404, {"error": f"term not in graph: {term!r}"})
                return self._json(200, sg)
            if path == "/api/monitor/kg/concept":
                key = (q.get("key") or [""])[0]
                c = monitor.kg_concept(key)
                if c is None:
                    return self._json(404, {"error": f"concept not in graph: {key!r}"})
                return self._json(200, c)
            return self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                b = self._body()
                if self.path == "/api/join":
                    s = bar.join(b.get("name", "guest"), b.get("avatar"), b.get("table"),
                                 device=b.get("device"))
                    return self._json(200, {"sid": s.sid, "avatar": s.avatar,
                                            "address": s.player.node.address})
                if self.path == "/api/sit":
                    bar.sit(b["sid"], b["table"]); return self._json(200, bar.state(b["sid"]))
                if self.path == "/api/propose":
                    p = bar.propose(b["sid"], b["term"]); return self._json(200, {"pid": p.pid})
                if self.path == "/api/vote":
                    p = bar.vote(b["sid"], b["pid"], b.get("verdict", "confirm"))
                    return self._json(200, {"pid": p.pid, "settled": p.settled,
                                            "outcome": p.outcome, "woven": p.woven})
                if self.path == "/api/spiral/propose":
                    links = b.get("links") or [x for x in (b.get("text", "")).splitlines() if x.strip()]
                    sv = bar.propose_spiral(b["sid"], links)
                    return self._json(200, {"cid": sv.cid, "length": sv.length,
                                            "state": sv.round.state})
                if self.path == "/api/spiral/vote":
                    sv = bar.vote_spiral(b["sid"], b["cid"], b.get("verdict", "confirm"))
                    return self._json(200, {"cid": sv.cid, "settled": sv.settled,
                                            "captured": sv.captured, "votes": sv.breakdown()})
                if self.path == "/api/relay/pull":
                    # on-demand drain of the shared web from the relay (knitweb/molgang#44)
                    if relay is None:
                        return self._json(400, {"error": "relay not enabled (start with --relay URL)"})
                    return self._json(200, relay.pull())
                if self.path == "/api/certificate":
                    import tempfile

                    from .certificate import make_pouw_certificate
                    d = bar.certificate_data(b["sid"])
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                        out = fh.name
                    make_pouw_certificate(
                        address=d["address"], public_key=d["public_key"],
                        private_key=d["private_key"], pulses_used=d["pulses_used"],
                        work_summary=d["work_summary"], provenance=d["provenance"],
                        holder=d["holder"], out_path=out)
                    with open(out, "rb") as fh:
                        body = fh.read()
                    os.unlink(out)
                    short = (d["address"] or "wallet")[:12]
                    return self._pdf(body, f"pouw-certificate-{short}.pdf")
                return self._json(404, {"error": "not found"})
            except (KeyError, RuntimeError, ValueError) as e:
                return self._json(400, {"error": str(e)})

        def log_message(self, *args) -> None:
            pass

    return Handler


def _start_relay(bar: Bar, base: str, wallet: str | None, interval: float):
    """Wire relay-sync onto the bar's shared World (knitweb/molgang#44).

    * a stable node identity (derived from the pulse-host wallet) signs every push;
    * each newly-woven knit/spiral is PUSHED to the relay via ``world.on_weave``;
    * an initial pull converges this fresh install on the shared web, then a daemon
      timer keeps pulling so writes from other installs land here too.
    """
    import threading

    from .relay_sync import RelaySync, signer_from_wallet

    signer = signer_from_wallet(wallet)
    relay = RelaySync(base, bar.world, signer)
    bar.world.on_weave = relay.push          # PUSH every confirmed knit/spiral as it is woven
    try:
        relay.pull()                         # converge on the existing shared web at startup
    except Exception as e:  # noqa: BLE001 — never let a relay outage block the bar opening
        print(f"  ⚠ relay initial pull failed (continuing local): {e}")

    def _loop() -> None:
        import time
        while True:
            time.sleep(max(1.0, interval))
            try:
                relay.pull()
            except Exception:  # noqa: BLE001 — transient relay errors must not kill the timer
                pass

    threading.Thread(target=_loop, daemon=True, name="relay-pull").start()
    return relay


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG browser bar")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--world", default=None, help="shared world file (default ~/.molgang/world.json)")
    ap.add_argument("--db", default=None, help="device→wallet registry sqlite (default ~/.molgang/registry.db)")
    ap.add_argument("--wallet", default=default_wallet_path(),
                    help="Pulse host identity wallet (default ~/.molgang/pulse-identity.cbor)")
    ap.add_argument("--host-genesis", type=int, default=0,
                    help="dev/test only: seed the host Pulse wallet if it is first created")
    ap.add_argument("--cors", default="*",
                    help="Access-Control-Allow-Origin for the API (default '*'; "
                         "set e.g. https://5mart.ml to restrict, or '' to disable)")
    ap.add_argument("--monitor-web", default=None,
                    help="gateway.App store JSON for the 📡 Monitor tab's local-knitweb graph "
                         "(default /tmp/chem_web.json if present, else the shared world)")
    ap.add_argument("--relay", default=None,
                    help="relay API base to share the growing web across machines, e.g. "
                         "https://5mart.ml/molgang/api/relay (OFF by default = local-only)")
    ap.add_argument("--relay-interval", type=float, default=20.0,
                    help="seconds between background relay pulls when --relay is set (default 20)")
    a = ap.parse_args([x for x in argv[1:] if x != "serve"])
    from .registry import Registry
    from .monitor import Monitor
    listen = f"0.0.0.0:{a.port}"
    pulse = bootstrap_host(a.wallet, listen=listen, genesis=a.host_genesis)
    bar = Bar(a.world, Registry(a.db))
    monitor = Monitor(bar, web=a.monitor_web, world=a.world, pulse_host=pulse)
    relay = _start_relay(bar, a.relay, a.wallet, a.relay_interval) if a.relay else None
    srv = ThreadingHTTPServer(("0.0.0.0", a.port),
                              make_handler(bar, pulse, cors=a.cors or None, monitor=monitor,
                                           relay=relay))
    print(f"  🍸 MOLGANG bar open at http://localhost:{a.port}  (shared web: "
          f"{a.world or '~/.molgang/world.json'}) (Ctrl-C to close)")
    print(f"  📡 Monitor: nodes {[n['label'] for n in monitor.nodes]} · "
          f"local knitweb {monitor.source}")
    print(f"  pulse host {pulse['account']['address']} · wallet {pulse['wallet']}")
    if relay is not None:
        print(f"  🌐 relay sync ON · {relay.base} · node {relay.signer.address} "
              f"· pull every {a.relay_interval:g}s")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  bar closed.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
