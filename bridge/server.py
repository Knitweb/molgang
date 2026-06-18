"""MOLGANG bridge HTTP server — the live endpoint `roblox/Sync.lua` talks to.

    POST /upload          ingest a Roblox votes export → weave into the knitweb (returns summary)
    GET  /snapshot.json   the canonical knitweb snapshot (download) for molgang/Roblox
    GET  /health          liveness

Stdlib only. The 30-minute alternation lives in the client (`Sync.lua`) / cron; this server
just serves both directions on demand, persisting to the shared state file.

    PYTHONPATH=src:/path/to/pulse/src python3 bridge/server.py --port 8787 --state .molgang/state.json
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge.ingest import ingest
from bridge.snapshot import snapshot
from bridge.state import load_state, save_state


def make_handler(state_path: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/snapshot.json", "/snapshot"):
                self._send(200, snapshot(load_state(state_path)))
            elif path == "/health":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/upload":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                export = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError as e:
                return self._send(400, {"error": f"bad json: {e}"})

            state = load_state(state_path)
            pb = {rid: p["pulses"] for rid, p in state["players"].items()}
            ps = {rid: p["silk"] for rid, p in state["players"].items()}
            summ = ingest(export, prior_balances=pb, prior_silk=ps)
            for rid, addr in summ["knitweb_addresses"].items():
                state["players"][rid] = {"address": addr, "pulses": summ["balances"][rid],
                                         "silk": summ["silk"][rid]}
            for w in summ["bonds_woven"]:
                state["web"][w["formula"]] = {"name": w["name"], "fiber_cid": w["fiber_cid"],
                                              "by": w["by"], "confirmations": w["confirmations"]}
            save_state(state_path, state)
            self._send(200, {"woven": len(summ["bonds_woven"]),
                             "wallets": summ["roblox_wallets_ingested"],
                             "web_size": len(state["web"])})

        def log_message(self, *args) -> None:  # quiet
            pass

    return Handler


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG bridge HTTP server")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--state", default=".molgang/state.json")
    a = ap.parse_args(argv[1:])
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(a.state))
    print(f"MOLGANG bridge on :{a.port}  (POST /upload · GET /snapshot.json · GET /health)")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
