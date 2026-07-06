"""#115 — the browser bar is an installable PWA (manifest + icons + serve types)."""
import io
import json
from pathlib import Path

from molgang.bar import Bar
from molgang.webserver import _CTYPE, make_handler

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


def test_manifest_is_valid_and_path_prefix_safe():
    m = json.loads((ROOT / "web" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["short_name"] == "MOLGANG"
    assert m["display"] == "standalone"
    # relative start_url/scope so it works at / AND under e.g. 5mart.ml/molgang/
    assert not m["start_url"].startswith("/") and not m["scope"].startswith("/")
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
    for i in m["icons"]:
        assert not i["src"].startswith("/")
        assert (ROOT / "web" / i["src"]).is_file()


def test_index_links_manifest_and_icons():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in html and "manifest.webmanifest" in html
    assert 'name="theme-color"' in html
    assert "apple-touch-icon" in html


def test_app_js_has_dismissible_install_affordance():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "beforeinstallprompt" in js
    assert "molgang_install_dismissed" in js       # dismissal persists
    assert "appinstalled" in js                    # button cleans up post-install


def test_serve_returns_manifest_and_png_content_types(tmp_path):
    """molgang serve self-hosts the install assets with correct Content-Types."""
    assert _CTYPE[".webmanifest"] == "application/manifest+json"
    assert _CTYPE[".png"] == "image/png"
    bar = Bar(str(tmp_path / "world.json"))
    Handler = make_handler(bar)
    out = _drive(Handler, b"GET /manifest.webmanifest HTTP/1.1\r\n\r\n")
    head = out.split(b"\r\n\r\n", 1)[0]
    assert b"200" in head.split(b"\r\n", 1)[0]
    assert b"application/manifest+json" in head
    out = _drive(Handler, b"GET /icons/icon-192.png HTTP/1.1\r\n\r\n")
    head, body = out.split(b"\r\n\r\n", 1)
    assert b"200" in head.split(b"\r\n", 1)[0]
    assert b"image/png" in head
    assert body[:8] == b"\x89PNG\r\n\x1a\n"       # a real PNG comes back
