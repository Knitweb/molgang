"""HTTP rate limiting for the canonical Molgang API."""
from __future__ import annotations

import io
import json

from molgang.bar import Bar
from molgang.webserver import (
    RateLimitConfig,
    RateLimitRule,
    RateLimiter,
    make_handler,
)


def _limits(*, read: int = 100, write: int = 100, costly: int = 100,
            certificate: int = 100, window: float = 60.0) -> RateLimitConfig:
    return RateLimitConfig(
        read=RateLimitRule(read, window),
        write=RateLimitRule(write, window),
        costly=RateLimitRule(costly, window),
        certificate=RateLimitRule(certificate, window),
    )


def _request(handler, raw: bytes, client=("127.0.0.1", 0)) -> tuple[bytes, dict, dict]:
    class _H(handler):
        def __init__(self, rfile, wfile):
            self.rfile = rfile
            self.wfile = wfile
            self.client_address = client
            self.requestline = self.request_version = self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

    wfile = io.BytesIO()
    _H(io.BytesIO(raw), wfile)
    out = wfile.getvalue()
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(b":")
        if k:
            headers[k.decode().lower()] = v.strip().decode()
    payload = json.loads(body) if body.strip() else {}
    return lines[0], headers, payload


def _post(handler, path: str, body: dict) -> tuple[bytes, dict, dict]:
    payload = json.dumps(body).encode()
    raw = (
        f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n\r\n"
    ).encode() + payload
    return _request(handler, raw)


def _get(handler, path: str) -> tuple[bytes, dict, dict]:
    return _request(handler, f"GET {path} HTTP/1.1\r\n\r\n".encode())


def test_write_rate_limit_trips_and_recovers(tmp_path):
    now = [1000.0]
    handler = make_handler(
        Bar(str(tmp_path / "w.json")),
        rate_limiter=RateLimiter(clock=lambda: now[0]),
        rate_config=_limits(write=1, window=60.0),
    )

    status, _, joined = _post(handler, "/api/join", {"name": "A", "device": "dev-a"})
    assert b"200" in status and "sid" in joined

    status, headers, limited = _post(handler, "/api/join", {"name": "B", "device": "dev-b"})
    assert b"429" in status
    assert headers["retry-after"] == "60"
    assert limited["retry_after"] == 60
    assert "Too Many Requests" not in limited["error"]

    now[0] += 60.0
    status, _, joined = _post(handler, "/api/join", {"name": "B", "device": "dev-b"})
    assert b"200" in status and "sid" in joined


def test_read_routes_have_separate_budget(tmp_path):
    handler = make_handler(
        Bar(str(tmp_path / "w.json")),
        rate_limiter=RateLimiter(clock=lambda: 2000.0),
        rate_config=_limits(read=2, write=1, window=60.0),
    )

    assert b"200" in _get(handler, "/api/version")[0]
    assert b"200" in _get(handler, "/api/version")[0]
    status, headers, limited = _get(handler, "/api/version")
    assert b"429" in status
    assert headers["retry-after"] == "30"
    assert limited["retry_after"] == 30

    status, _, joined = _post(handler, "/api/join", {"name": "A", "device": "dev-a"})
    assert b"200" in status and "sid" in joined


def test_costly_write_routes_use_tighter_budget(tmp_path):
    handler = make_handler(
        Bar(str(tmp_path / "w.json")),
        rate_limiter=RateLimiter(clock=lambda: 3000.0),
        rate_config=_limits(write=20, costly=1, window=60.0),
    )

    status, _, joined = _post(
        handler,
        "/api/join",
        {"name": "A", "avatar": "laser-maxi", "table": "periodic", "device": "dev-a"},
    )
    assert b"200" in status

    status, _, proposed = _post(handler, "/api/propose", {"sid": joined["sid"], "term": "H2O"})
    assert b"200" in status and "pid" in proposed

    status, headers, limited = _post(handler, "/api/propose", {"sid": joined["sid"], "term": "CO2"})
    assert b"429" in status
    assert headers["retry-after"] == "60"
    assert limited["retry_after"] == 60


def test_rate_limits_read_from_environment(monkeypatch):
    monkeypatch.setenv("MOLGANG_RATE_READ", "7")
    monkeypatch.setenv("MOLGANG_RATE_READ_WINDOW", "11")
    monkeypatch.setenv("MOLGANG_RATE_WRITE", "5")
    monkeypatch.setenv("MOLGANG_RATE_COSTLY", "3")
    monkeypatch.setenv("MOLGANG_RATE_CERTIFICATE", "2")

    cfg = RateLimitConfig.from_env()

    assert cfg.read == RateLimitRule(7, 11.0)
    assert cfg.write.limit == 5
    assert cfg.costly.limit == 3
    assert cfg.certificate.limit == 2
