from __future__ import annotations

import io
import json

from molgang.bar import Bar
from molgang.webserver import make_handler


def test_device_reconnect_reuses_live_session_and_table(tmp_path):
    now = [1000.0]
    bar = Bar(str(tmp_path / "w.json"), stale_session_s=30, clock=lambda: now[0])

    first = bar.join("Alice", "laser-maxi", "periodic", device="phone-1")
    again = bar.join("Alice Reloaded", "validator-owl", device="phone-1")

    assert again.sid == first.sid
    assert again.table_id == "periodic"
    assert again.name == "Alice Reloaded"
    assert again.avatar == "validator-owl"
    assert bar.state(again.sid)["you"]["sid"] == first.sid


def test_stale_human_session_is_reaped_and_frees_table_owner(tmp_path):
    now = [1000.0]
    bar = Bar(str(tmp_path / "w.json"), stale_session_s=10, clock=lambda: now[0])
    player = bar.join("Owner", "laser-maxi", "periodic", device="phone-2")
    bar.rename_table(player.sid, "periodic", "Owner Table")

    now[0] += 11
    removed = bar.reap_stale()

    assert removed == [player.sid]
    assert player.sid not in bar.sessions
    assert bar.tables["periodic"].owner_sid is None
    assert bar.tables["periodic"].name == "Periodic Bar"
    assert all(not s.device for s in bar.sessions.values() if s.table_id == "periodic")


def _request(handler, raw: bytes) -> tuple[bytes, dict]:
    class _H(handler):
        def __init__(self, rfile, wfile):
            self.rfile = rfile
            self.wfile = wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = self.request_version = self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

    wfile = io.BytesIO()
    _H(io.BytesIO(raw), wfile)
    out = wfile.getvalue()
    head, _, body = out.partition(b"\r\n\r\n")
    return head.split(b"\r\n", 1)[0], json.loads(body) if body.strip() else {}


def _post(handler, path: str, body: dict) -> tuple[bytes, dict]:
    payload = json.dumps(body).encode()
    raw = (f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
           f"Content-Length: {len(payload)}\r\n\r\n").encode() + payload
    return _request(handler, raw)


def test_presence_http_routes_heartbeat_stand_and_leave(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    handler = make_handler(bar)

    status, joined = _post(handler, "/api/join", {
        "name": "Browser",
        "avatar": "laser-maxi",
        "table": "periodic",
        "device": "browser-1",
    })
    assert b"200" in status
    sid = joined["sid"]
    assert bar.sessions[sid].table_id == "periodic"

    status, hb = _post(handler, "/api/heartbeat", {"sid": sid})
    assert b"200" in status
    assert hb["sid"] == sid
    assert hb["table"] == "periodic"

    status, stood = _post(handler, "/api/stand", {"sid": sid})
    assert b"200" in status
    assert stood["you"]["table"] is None
    assert bar.sessions[sid].table_id is None

    status, left = _post(handler, "/api/leave", {"sid": sid})
    assert b"200" in status
    assert left["ok"] is True
    assert sid not in bar.sessions
