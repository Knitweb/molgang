from __future__ import annotations

from molgang.bar import Bar
from molgang.world import World


def _no_bots(bar: Bar) -> Bar:
    bar.sessions = {sid: s for sid, s in bar.sessions.items() if not s.bot}
    return bar


def test_open_spiral_is_visible_backable_and_captured_across_shared_world(tmp_path):
    path = str(tmp_path / "world.json")
    a = _no_bots(Bar(path))
    b = _no_bots(Bar(path))
    c = _no_bots(Bar(path))
    d = _no_bots(Bar(path))

    alice = a.join("Alice", "laser-maxi", "periodic", device="alice-phone")
    spiral = a.propose_spiral(alice.sid, ["H2O -> O2", "O2 -> O3"])
    assert not spiral.settled

    bob = b.join("Bob", "validator-owl", "periodic", device="bob-phone")
    b_state = b.state(bob.sid)
    b_table = next(t for t in b_state["tables"] if t["id"] == "periodic")
    assert [sp["cid"] for sp in b_table["spirals"]] == [spiral.cid]
    assert b_table["spirals"][0]["backed"] is False

    b.vote_spiral(bob.sid, spiral.cid, "confirm")

    cara = c.join("Cara", "diamond-hands", "periodic", device="cara-phone")
    c_state = c.state(cara.sid)
    c_table = next(t for t in c_state["tables"] if t["id"] == "periodic")
    assert c_table["spirals"][0]["votes"]["confirm"] == 1
    c.vote_spiral(cara.sid, spiral.cid, "confirm")

    dex = d.join("Dex", "hoodie-hacker", "periodic", device="dex-phone")
    captured = d.vote_spiral(dex.sid, spiral.cid, "confirm")
    assert captured.settled and captured.captured

    shared = World(path)
    assert shared.size()[1] >= 2
    assert not shared.list_open_spirals()

    a_state = a.state(alice.sid)
    a_table = next(t for t in a_state["tables"] if t["id"] == "periodic")
    assert a_table["spirals"] == []
    assert a.web_view()["edges"] >= 2
