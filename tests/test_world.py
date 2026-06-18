"""The shared World — confirmed knits extend it; two instances on one file see the same web."""

from __future__ import annotations

from molgang.bar import Bar
from molgang.world import World


def test_extend_grows_the_web_and_anchors(tmp_path):
    w = World(str(tmp_path / "w.json"))
    assert w.size() == (0, 0)
    w.extend("H2O", "alice", "bafyfiber", 3, topic="water")
    w.extend("CO2", "bob", "bafyfiber2", 3, topic="oxides")
    n, e = w.size()
    assert n >= 4 and e >= 2                      # 2 topic + 2 term nodes, 2 edges
    a = w.anchor()
    assert a["ual"].startswith("did:dkg:knitweb/") and a["verified"]


def test_two_instances_share_one_file(tmp_path):
    path = str(tmp_path / "shared.json")
    a, b = World(path), World(path)               # two "players" on the same world file
    a.extend("NaCl", "p1", "bafyx", 3, topic="salt")
    g = b.graph()                                  # b syncs from the file a just wrote
    assert any(r["term"] == "NaCl" for r in g["recent"])
    assert b.size() == a.size()                    # identical shared web
    assert b.state_root() == a.state_root()        # byte-identical fabric root


def test_bar_woven_knit_extends_the_world(tmp_path):
    bar = Bar(str(tmp_path / "barworld.json"))
    a = bar.join("Alice", table_id="periodic")
    voters = [bar.join(n, table_id="periodic") for n in ("B", "C", "D")]
    p = bar.propose(a.sid, "H2O")
    for v in voters:
        bar.vote(v.sid, p.pid, "confirm")
    web = bar.web_view()
    assert web["nodes"] >= 2 and any(r["term"] == "H2O" for r in web["recent"])
    assert web["anchor"]["ual"].startswith("did:dkg:knitweb/")
