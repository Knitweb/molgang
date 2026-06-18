"""MOLGANG browser bar — a stdlib HTTP server.

Serves the bar UI (the `web/` folder) AND a small JSON API over one live `Bar`. The SAME
endpoints are used by humans (the browser) and machines (bots/agents) — dual play:

    GET  /api/state?sid=…              full bar snapshot (tables, seats, avatars, open knits)
    POST /api/join     {name,avatar,table?}   walk in (free silk + pulses), optionally sit
    POST /api/sit      {sid,table}            take a seat at a table
    POST /api/propose  {sid,term}             brainstorm + knit a term (spends silk)
    POST /api/vote     {sid,pid,verdict}      vote with a pulse ('confirm'|'mismatch'|'abstain')

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


def make_handler(bar: Bar, pulse_host: dict | None = None):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            return self._static(path)

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
                return self._json(404, {"error": "not found"})
            except (KeyError, RuntimeError, ValueError) as e:
                return self._json(400, {"error": str(e)})

        def log_message(self, *args) -> None:
            pass

    return Handler


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG browser bar")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--world", default=None, help="shared world file (default ~/.molgang/world.json)")
    ap.add_argument("--db", default=None, help="device→wallet registry sqlite (default ~/.molgang/registry.db)")
    ap.add_argument("--wallet", default=default_wallet_path(),
                    help="Pulse host identity wallet (default ~/.molgang/pulse-identity.cbor)")
    ap.add_argument("--host-genesis", type=int, default=0,
                    help="dev/test only: seed the host Pulse wallet if it is first created")
    a = ap.parse_args([x for x in argv[1:] if x != "serve"])
    from .registry import Registry
    listen = f"0.0.0.0:{a.port}"
    pulse = bootstrap_host(a.wallet, listen=listen, genesis=a.host_genesis)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(Bar(a.world, Registry(a.db)), pulse))
    print(f"  🍸 MOLGANG bar open at http://localhost:{a.port}  (shared web: "
          f"{a.world or '~/.molgang/world.json'}) (Ctrl-C to close)")
    print(f"  pulse host {pulse['account']['address']} · wallet {pulse['wallet']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  bar closed.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
