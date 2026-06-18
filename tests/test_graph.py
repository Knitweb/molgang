"""NetworkX exploration over the woven knitweb graph."""

from __future__ import annotations

from molgang import graphx
from molgang.world import WovenItem


def _items():
    return [
        WovenItem("link", "a", "f1", 3, subject="V2O5", object="vanadium pentoxide", relation="is"),
        WovenItem("link", "a", "f2", 2, subject="vanadium pentoxide", object="catalyst", relation="is-a"),
        WovenItem("term", "b", "f3", 3, term="H2O"),
    ]


def test_build_and_stats():
    g = graphx.build(_items())
    s = graphx.stats(g)
    assert s["nodes"] == 4 and s["edges"] == 2 and s["clusters"] == 2


def test_hubs_rank_central_terms():
    hubs = graphx.hubs(graphx.build(_items()))
    assert hubs and hubs[0]["term"] == "vanadium pentoxide"   # highest degree (in+out)


def test_neighbors_and_path():
    g = graphx.build(_items())
    nb = graphx.neighbors(g, "vanadium pentoxide")
    assert {n["to"] for n in nb["out"]} == {"catalyst"}
    assert {n["from"] for n in nb["in"]} == {"V2O5"}
    p = graphx.path(g, "V2O5", "catalyst")
    assert p["path"] == ["V2O5", "vanadium pentoxide", "catalyst"] and p["hops"] == 2


def test_explore_bundles_it():
    out = graphx.explore(_items(), term="H2O", frm="V2O5", to="catalyst")
    assert "stats" in out and "hubs" in out and out["neighbors"]["term"] == "H2O"
    assert out["path"]["hops"] == 2
