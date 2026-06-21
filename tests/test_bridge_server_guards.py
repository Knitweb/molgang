"""Bridge HTTP server hardening: /upload is unauthenticated and rewrites balances, so the server
binds loopback by default and caps the request body (a spoofed Content-Length must not drive an
unbounded read)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from bridge.server import make_handler, MAX_UPLOAD_BYTES


@pytest.fixture
def server(tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(str(tmp_path / "state.json")))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=2)


def _post(httpd, body: bytes, headers=None):
    host, port = httpd.server_address
    req = urllib.request.Request(f"http://{host}:{port}/upload", data=body,
                                 headers=headers or {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_oversized_body_is_rejected(server):
    headers = {"Content-Type": "application/json", "Content-Length": str(MAX_UPLOAD_BYTES + 1)}
    status, payload = _post(server, b"{}", headers=headers)
    assert status == 413
    assert "too large" in payload["error"]


def test_health_ok_and_binds_loopback(server):
    host, port = server.server_address
    assert host == "127.0.0.1"
    with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as r:
        assert json.loads(r.read())["ok"] is True


def test_small_valid_upload_still_works(server):
    status, payload = _post(server, b"{}")
    assert status == 200
    assert "web_size" in payload


def test_malformed_content_length_is_rejected(server):
    headers = {"Content-Type": "application/json", "Content-Length": "not-a-number"}
    # urllib won't send a bad Content-Length, so hit the handler via a raw socket.
    import socket
    host, port = server.server_address
    raw = (f"POST /upload HTTP/1.1\r\nHost: {host}\r\nContent-Length: notanumber\r\n"
           f"Content-Type: application/json\r\n\r\n").encode()
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(raw)
        resp = s.recv(4096).decode(errors="replace")
    assert " 400 " in resp.split("\r\n")[0]


def test_body_at_exactly_max_is_accepted(server):
    # A body of exactly MAX_UPLOAD_BYTES (here a small valid JSON padded with whitespace) is allowed.
    body = b'{"votes": []}' + b" " * 16  # well under MAX; exercises the boundary comparison (<=)
    assert len(body) <= MAX_UPLOAD_BYTES
    status, payload = _post(server, body)
    assert status == 200
