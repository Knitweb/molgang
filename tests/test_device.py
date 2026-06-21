"""Device-bound wallets + the sqlite registry (phone ↔ stable PLS wallet)."""
import io
import json

from molgang.bar import Bar
from molgang.game import Player
from molgang.registry import Registry


def test_device_wallet_is_stable():
    a, b = Player.from_device("phone-XYZ"), Player.from_device("phone-XYZ")
    assert a.node.address == b.node.address
    assert Player.from_device("other-phone").node.address != a.node.address


def test_registry_register_and_get(tmp_path):
    r = Registry(str(tmp_path / "r.db"))
    out = r.register("dev1", "pls1abc", "Edwin")
    assert out["new"] and out["address"] == "pls1abc" and r.count() == 1
    again = r.register("dev1", "pls1abc", "Edwin")
    assert not again["new"] and again["visits"] == 2
    assert r.get("dev1")["name"] == "Edwin" and r.get("missing") is None


def test_bar_join_with_device_registers_and_persists(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    s1 = Bar(str(tmp_path / "w.json"), reg).join("Edwin", "laser-maxi", "periodic", device="phone-1")
    addr = s1.player.node.address
    assert reg.get("phone-1")["address"] == addr
    s2 = Bar(str(tmp_path / "w.json"), reg).join("Edwin", "laser-maxi", "periodic", device="phone-1")
    assert s2.player.node.address == addr and reg.get("phone-1")["visits"] == 2


def test_faucet_claim_source_cap_is_idempotent_per_device(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    first = reg.claim_faucet("dev1", "203.0.113.5", cap=1, now=1.0)
    again = reg.claim_faucet("dev1", "203.0.113.5", cap=1, now=2.0)
    assert first["new"] is True
    assert again["new"] is False
    assert again["claimed"] == 1.0

    try:
        reg.claim_faucet("dev2", "203.0.113.5", cap=1, now=3.0)
    except RuntimeError as e:
        assert "faucet source cap" in str(e)
    else:
        raise AssertionError("new device from saturated source should be rejected")

    other_source = reg.claim_faucet("dev2", "203.0.113.6", cap=1, now=4.0)
    assert other_source["new"] is True


def test_bar_join_blocks_new_faucet_after_source_cap_but_allows_returning_device(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    bar = Bar(str(tmp_path / "w.json"), reg, faucet_source_cap=1)

    first = bar.join("Edwin", "laser-maxi", "periodic", device="phone-1", source="203.0.113.7")
    returning = bar.join("Edwin", "laser-maxi", "periodic", device="phone-1", source="203.0.113.7")
    assert returning.player.node.address == first.player.node.address

    try:
        bar.join("New", "hoodie-hacker", "periodic", device="phone-2", source="203.0.113.7")
    except RuntimeError as e:
        assert "faucet source cap" in str(e)
    else:
        raise AssertionError("second fresh device from the same source should be rejected")


def test_api_join_returns_clear_error_when_faucet_source_cap_is_reached(tmp_path):
    from molgang.webserver import make_handler

    reg = Registry(str(tmp_path / "r.db"))
    bar = Bar(str(tmp_path / "w.json"), reg, faucet_source_cap=1)
    Handler = make_handler(bar)

    def post(device: str) -> tuple[bytes, dict]:
        body = json.dumps({"name": "Browser", "avatar": "laser-maxi", "device": device}).encode()
        raw = (
            b"POST /api/join HTTP/1.1\r\n"
            b"Content-Type: application/json\r\n"
            b"X-Forwarded-For: 203.0.113.8\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )

        class _H(Handler):
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
        head, _, payload = out.partition(b"\r\n\r\n")
        return head.split(b"\r\n", 1)[0], json.loads(payload)

    status, joined = post("browser-1")
    assert b"200" in status and "sid" in joined

    status, rejected = post("browser-2")
    assert b"400" in status
    assert "faucet source cap" in rejected["error"]


def test_join_source_only_trusts_forwarded_for_from_proxy_hosts():
    from molgang.webserver import _trust_forwarded_for

    assert _trust_forwarded_for("127.0.0.1")
    assert _trust_forwarded_for("10.0.0.5")
    assert not _trust_forwarded_for("8.8.8.8")
    assert not _trust_forwarded_for("not-an-ip")
