"""Sprint 3 #17 presence coverage.

The pure presence core stays importable without the knitweb engine. The Bar/webserver
regressions import lazily so this file still proves that boundary.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "molgang_presence",
    Path(__file__).resolve().parent.parent / "src/molgang/presence.py",
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
Presence, ONLINE, AWAY, GONE = m.Presence, m.ONLINE, m.AWAY, m.GONE


def test_status_transitions():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", now=1000.0)
    assert p.status("a", 1010.0) == ONLINE
    assert p.status("a", 1040.0) == AWAY
    assert p.status("a", 1100.0) == GONE
    assert p.status("unknown", 1000.0) == GONE


def test_beat_refreshes():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", 1000.0)
    p.beat("a", 1080.0)
    assert p.status("a", 1090.0) == ONLINE


def test_reap_returns_and_removes_gone():
    p = Presence(away_after=30, gone_after=90)
    p.beat("ghost", 1000.0)
    p.beat("live", 1000.0)
    p.beat("live", 1200.0)
    assert p.reap(now=1200.0) == ["ghost"]
    assert p.reap(now=1200.0) == []
    assert p.status("live", 1200.0) == ONLINE


def test_online_and_snapshot():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", 1000.0)
    p.beat("b", 940.0)
    assert set(p.online(1000.0)) == {"a", "b"}
    snap = p.snapshot(1000.0)
    assert snap["a"] == ONLINE and snap["b"] == AWAY


def test_drop_and_validation():
    p = Presence()
    p.beat("a", 1.0)
    p.drop("a")
    p.drop("a")
    assert p.status("a", 1.0) == GONE
    with pytest.raises(ValueError):
        Presence(away_after=90, gone_after=30)


def test_device_reconnect_reuses_live_session_and_table(tmp_path):
    from molgang.bar import Bar

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
    from molgang.bar import Bar

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
    raw = (
        f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n\r\n"
    ).encode() + payload
    return _request(handler, raw)


def test_presence_http_routes_heartbeat_stand_and_leave(tmp_path):
    from molgang.bar import Bar
    from molgang.webserver import make_handler

    bar = Bar(str(tmp_path / "w.json"))
    handler = make_handler(bar)

    status, joined = _post(
        handler,
        "/api/join",
        {
            "name": "Browser",
            "avatar": "laser-maxi",
            "table": "periodic",
            "device": "browser-1",
        },
    )
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
