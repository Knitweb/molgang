"""The shared World — knits weave term nodes / link edges; instances share one file; solo play."""

from __future__ import annotations

from molgang.bar import Bar
from molgang.world import World


def test_weave_term_and_link_grow_the_web(tmp_path):
    w = World(str(tmp_path / "w.json"))
    assert w.size() == (0, 0)
    w.weave_knit({"kind": "term", "term": "H2O"}, "alice", "f1", 3)
    w.weave_knit({"kind": "link", "subject": "V205", "object": "V2O5", "relation": "is"}, "bob", "f2", 3)
    n, e = w.size()
    assert n >= 3 and e >= 1                       # H2O, V205, V2O5 nodes + 1 link edge
    a = w.anchor()
    assert a["ual"].startswith("did:dkg:knitweb/") and a["verified"]
    assert any(link["subject"] == "V205" for link in w.graph()["links"])


def test_two_instances_share_one_file(tmp_path):
    path = str(tmp_path / "shared.json")
    a, b = World(path), World(path)               # two "players" on the same world file
    a.weave_knit({"kind": "term", "term": "NaCl"}, "p1", "fx", 3)
    g = b.graph()                                  # b syncs from the file a just wrote
    assert any(r["label"] == "NaCl" for r in g["recent"])
    assert b.size() == a.size() and b.state_root() == a.state_root()


def test_bar_solo_play_confirms_and_combines(tmp_path):
    bar = Bar(str(tmp_path / "barworld.json"))      # NPC bots are auto-seated
    me = bar.join("Edwin", "laser-maxi", "periodic")
    a = bar.propose(me.sid, "H2O")
    b = bar.propose(me.sid, "V205 = V2O5")          # '=' must COMBINE into a link
    assert a.woven and b.woven                      # bots confirm → solo play works
    web = bar.web_view()
    assert web["edges"] >= 1 and any(link["subject"] == "V205" for link in web["links"])
    assert web["anchor"]["ual"].startswith("did:dkg:knitweb/")
