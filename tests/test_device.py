"""Device-bound wallets + the sqlite registry (phone ↔ stable PLS wallet)."""
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
