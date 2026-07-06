"""Regression contract for surviving server restarts (knitweb/molgang#225).

After a server restart every browser sid is stale. These tests pin the exact
server behaviours the web clients (web/app.js, web/lab-3d.html) rely on to
recover *without* user-visible errors:

  * GET  /api/state with a stale sid answers 200 with ``you: null`` — the client
    detects that and transparently re-joins (it must NOT be an error status).
  * POST /api/certificate with a stale sid answers 400 JSON (not a crash) — the
    client re-joins and retries once instead of surfacing "failed to fetch".
  * A device-id re-join restores the persisted PLS balance from the registry.
  * GET  /api/certificates lists every minted certificate with a sha256 that
    matches the served PDF bytes.
"""
import hashlib
import io
import json

from molgang.bar import Bar
from molgang.registry import Registry
from molgang.webserver import make_handler


class _FakeRequest(io.BytesIO):
    def makefile(self, *a, **k):
        return self


def _drive(Handler, raw: bytes) -> bytes:
    """Feed one raw HTTP request through the real handler; return the raw response."""
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


def _get(Handler, path: str) -> bytes:
    return _drive(Handler, f"GET {path} HTTP/1.1\r\n\r\n".encode())


def _post(Handler, path: str, obj: dict) -> bytes:
    body = json.dumps(obj).encode()
    return _drive(Handler, (f"POST {path} HTTP/1.1\r\n"
                            f"Content-Type: application/json\r\n"
                            f"Content-Length: {len(body)}\r\n\r\n").encode() + body)


def _status(out: bytes) -> int:
    return int(out.split(b"\r\n", 1)[0].split()[1])


def _json_body(out: bytes) -> dict:
    return json.loads(out.split(b"\r\n\r\n", 1)[1])


def test_state_is_200_with_you_null_for_stale_sid(tmp_path):
    """The auto-rejoin contract: a stale sid is NOT an error — it is you:null."""
    bar = Bar(str(tmp_path / "world.json"))
    Handler = make_handler(bar)
    out = _get(Handler, "/api/state?sid=stale-after-restart")
    assert _status(out) == 200
    assert _json_body(out)["you"] is None


def test_certificate_with_stale_sid_is_400_json_not_crash(tmp_path):
    """A stale-sid mint must be a clean 400 JSON the client can retry after re-join."""
    bar = Bar(str(tmp_path / "world.json"))
    Handler = make_handler(bar)
    out = _post(Handler, "/api/certificate", {"sid": "stale-after-restart"})
    assert _status(out) == 400
    assert "error" in _json_body(out)


def test_device_rejoin_restores_balance_like_after_a_restart(tmp_path):
    """The recovery path end-to-end: earn -> 'restart' (new Bar, same registry) ->
    device re-join -> the balance is back and a fresh certificate shows it."""
    reg = Registry(str(tmp_path / "reg.db"))
    bar1 = Bar(str(tmp_path / "world.json"), registry=reg)
    me = bar1.join("Builder", "laser-maxi", "periodic", device="dev-restart-1")
    bar1.propose(me.sid, "H2O")                       # earn a proposer reward
    earned = me.player.pulses
    assert reg.get_balance("dev-restart-1")["pulses"] == earned

    bar2 = Bar(str(tmp_path / "world.json"), registry=reg)   # the restart
    back = bar2.join("Builder", "laser-maxi", "periodic", device="dev-restart-1")
    assert back.player.pulses == earned               # balance survived
    d = bar2.certificate_data(back.sid)
    assert d["pls_balance"] == earned                 # and the certificate shows it


def test_certificates_list_endpoint_tracks_mints(tmp_path):
    """GET /api/certificates lists each mint; its sha256 matches the served PDF."""
    reg = Registry(str(tmp_path / "reg.db"))
    bar = Bar(str(tmp_path / "world.json"), registry=reg)
    me = bar.join("Lister", "laser-maxi", "periodic", device="dev-list-1")
    Handler = make_handler(bar)

    out = _post(Handler, "/api/certificate", {"sid": me.sid})
    assert _status(out) == 200
    pdf = out[out.index(b"%PDF-"):]

    out = _get(Handler, "/api/certificates")
    assert _status(out) == 200
    certs = _json_body(out)["certificates"]
    assert len(certs) == 1
    assert certs[0]["holder"] == "Lister"
    assert certs[0]["pls_balance"] == me.player.pulses
    assert certs[0]["sha256"] == hashlib.sha256(pdf).hexdigest()
