"""#116 — offline-first service worker: cached shell + graceful offline state."""
import io
import re
from pathlib import Path

from molgang.bar import Bar
from molgang.webserver import make_handler

ROOT = Path(__file__).resolve().parents[1]


def _drive(Handler, raw: bytes) -> bytes:
    rfile, wfile = io.BytesIO(raw), io.BytesIO()

    class _H(Handler):
        def __init__(self):
            self.rfile = rfile
            self.wfile = wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = ""
            self.request_version = "HTTP/1.1"
            self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

        def finish(self):
            pass

        def log_message(self, *a):
            pass

    _H()
    return wfile.getvalue()


def test_sw_precaches_an_existing_shell_and_versions_its_cache():
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    # versioned cache name so a deploy invalidates stale shells
    assert re.search(r'CACHE_VERSION\s*=\s*"v\d+', sw)
    assert "caches.delete" in sw                       # old versions evicted on activate
    # every precached shell path exists on disk (relative → path-prefix-safe)
    for m in re.findall(r'^\s*"([^"]+)",?\s*$', sw, re.M):
        assert not m.startswith("/"), f"absolute path breaks subpath deploys: {m}"
        target = ROOT / "web" / ("index.html" if m == "./" else m)
        assert target.exists(), f"precached but missing on disk: {m}"


def test_sw_is_network_first_for_api_and_never_caches_mutations():
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    assert '/api/' in sw
    api_block = sw.split('includes("/api/")', 1)[1]
    assert "fetch(req)" in api_block                   # network first...
    assert "caches.match(req)" in api_block            # ...cache as fallback
    assert 'req.method !== "GET"' in sw                # POSTs bypass the cache entirely


def test_app_registers_sw_and_survives_offline_refresh():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'serviceWorker' in js and 'register("sw.js")' in js   # relative scope
    # the poll loop shows one reconnecting toast and resumes — no unhandled throw
    assert "Reconnecting" in js and "Reconnected" in js
    body = js.split("async function refresh()", 1)[1].split("\n}", 1)[0]
    assert "try" in body and "catch" in body


def test_serve_returns_sw_with_js_content_type(tmp_path):
    bar = Bar(str(tmp_path / "world.json"))
    Handler = make_handler(bar)
    out = _drive(Handler, b"GET /sw.js HTTP/1.1\r\n\r\n")
    head, body = out.split(b"\r\n\r\n", 1)
    assert b"200" in head.split(b"\r\n", 1)[0]
    assert b"text/javascript" in head
    assert b"CACHE_VERSION" in body
