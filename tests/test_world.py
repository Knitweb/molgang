"""The shared World — knits weave term nodes / link edges; instances share one file; solo play."""

from __future__ import annotations

import time

import pytest

from molgang.bar import Bar
from molgang import tension as T
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


def test_world_save_is_atomic_if_serialization_fails(tmp_path, monkeypatch):
    import molgang.world as world_mod

    path = tmp_path / "shared.json"
    w = World(str(path))
    w.weave_knit({"kind": "term", "term": "NaCl"}, "p1", "fx", 3)
    before = path.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(world_mod.json, "dump", boom)
    with pytest.raises(RuntimeError, match="serialization failed"):
        w.weave_knit({"kind": "term", "term": "H2O"}, "p2", "fy", 3)

    assert path.read_text(encoding="utf-8") == before
    assert list(tmp_path.glob(".shared.json.*.tmp")) == []
    reloaded = World(str(path))
    assert [item.term for item in reloaded.items] == ["NaCl"]


def test_weave_knit_sets_anchor_fields():
    w = World()
    now = int(time.time()) - 1
    w.weave_knit({"kind": "term", "term": "H2O"}, "alice", "f1", 1)
    item = w.items[-1]
    assert item.anchor_rel > 0
    assert item.anchor_ts >= now
    assert item.anchor_ts <= int(time.time())


def test_anchor_reliability_grows_with_more_confirmations():
    w = World()
    w.weave_links([{"subject": "A", "object": "B", "relation": "is"}], "alice", "f1", 1)
    low = w.items[-1].anchor_rel
    w.weave_links([{"subject": "C", "object": "D", "relation": "is"}], "alice", "f2", 3)
    high = w.items[-1].anchor_rel
    assert low >= 5 * T.DEFAULT_ANCHOR_REL
    assert high > low


def test_bar_solo_play_confirms_and_combines(tmp_path):
    bar = Bar(str(tmp_path / "barworld.json"))      # NPC bots are auto-seated
    me = bar.join("Edwin", "laser-maxi", "periodic")
    a = bar.propose(me.sid, "H2O")
    b = bar.propose(me.sid, "V205 = V2O5")          # '=' must COMBINE into a link
    assert a.woven and b.woven                      # bots confirm → solo play works
    web = bar.web_view()
    assert web["edges"] >= 1 and any(link["subject"] == "V205" for link in web["links"])
    assert web["anchor"]["ual"].startswith("did:dkg:knitweb/")


def test_weave_links_one_to_many_makes_multiple_edges(tmp_path):
    w = World(str(tmp_path / "w.json"))
    w.weave_links([
        {"subject": "repo", "object": "molgang", "relation": "has"},
        {"subject": "repo", "object": "monitor", "relation": "has"},
        {"subject": "repo", "object": "pulse", "relation": "has"},
    ], "alice", "f1", 3)
    n, e = w.size()
    assert e == 3 and n == 4                          # repo + 3 objects, 3 edges
    subs = [l["subject"] for l in w.graph()["links"]]
    assert subs.count("repo") == 3


def test_ch4_unicode_dedupes_to_one_node(tmp_path):
    w = World(str(tmp_path / "w.json"))
    w.weave_knit({"kind": "term", "term": "CH₄"}, "a", "f1", 3)  # clean() folds ₄ -> 4
    w.weave_knit({"kind": "term", "term": "CH4"}, "b", "f2", 3)
    assert w.size()[0] == 1                            # one canonical node, not two


def test_bar_proposes_one_to_many_weaves_all_links(tmp_path):
    bar = Bar(str(tmp_path / "barworld.json"))
    me = bar.join("Edwin", "laser-maxi", "periodic")
    p = bar.propose(me.sid, "the repo has molgang, monitor and pulse")
    assert p.woven
    web = bar.web_view()
    repo_links = [l for l in web["links"] if l["subject"] == "the repo"]
    assert len(repo_links) == 3
    assert {l["object"] for l in repo_links} == {"molgang", "monitor", "pulse"}
