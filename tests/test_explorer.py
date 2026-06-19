"""Knowledge-graph explorer: building a DiGraph from a gateway.App store + its API helpers."""

from __future__ import annotations

import json

from molgang import explorer, graphx


def _store():
    """A tiny gateway.App store dump (the on-disk shape of a woven web)."""
    def lab(key, en, ru, zh, ar):
        return [{"t": "link", "subject": key, "object": en, "relation": "label:en", "weight": 1},
                {"t": "link", "subject": key, "object": ru, "relation": "label:ru", "weight": 1},
                {"t": "link", "subject": key, "object": zh, "relation": "label:zh", "weight": 1},
                {"t": "link", "subject": key, "object": ar, "relation": "label:ar", "weight": 1}]

    return {"name": "t", "balances": {}, "records": [
        {"t": "record", "data": {"kind": "concept", "key": "H2O", "formula": "H2O",
                                 "definition": "water compound", "by": "alice"}},
        {"t": "record", "data": {"kind": "concept", "key": "oxygen", "by": "alice"}},
        {"t": "record", "data": {"kind": "concept", "key": "hydrogen", "by": "alice"}},
        *lab("H2O", "water", "вода", "水", "ماء"),
        *lab("oxygen", "oxygen", "кислород", "氧", "أكسجين"),
        # a duplicate woven label (two peers) — must NOT be collapsed away in the count
        {"t": "link", "subject": "oxygen", "object": "oxygen", "relation": "label:en", "weight": 1},
        {"t": "link", "subject": "H2O", "object": "hydrogen", "relation": "contains", "weight": 2},
        {"t": "link", "subject": "H2O", "object": "oxygen", "relation": "contains", "weight": 1},
    ]}


def test_build_from_web_nodes_edges():
    g = graphx.build_from_web(_store())
    assert g.is_multigraph()
    # 3 concept records + label-target nodes (water, вода, 水, ماء, кислород, 氧, أكسجين) = 3 + 7
    assert g.number_of_nodes() == 10
    # 4+4 labels + 1 dup label + 2 contains = 11 woven edges (multigraph keeps the dup)
    assert g.number_of_edges() == 11
    assert g.nodes["H2O"]["concept"] is True
    assert g.nodes["H2O"]["definition"] == "water compound"


def test_web_stats_language_breakdown():
    s = graphx.web_stats(graphx.build_from_web(_store()))
    assert s["concepts"] == 3
    # 2 base en labels (H2O, oxygen) + 1 duplicate woven en label = 3 (the multigraph keeps
    # the parallel dup that a plain DiGraph would have collapsed); ru/zh/ar = 2 each.
    assert s["languages"] == {"en": 3, "ru": 2, "zh": 2, "ar": 2}
    assert set(s["languages"]) >= set(graphx.LANGS)


def test_concept_multilingual_labels_and_relations():
    g = graphx.build_from_web(_store())
    c = graphx.concept(g, "H2O")
    assert c["labels"] == {"en": "water", "ru": "вода", "zh": "水", "ar": "ماء"}
    assert c["formula"] == "H2O"
    rels = {(r["relation"], r["to"]) for r in c["relations"]}
    assert ("contains", "oxygen") in rels and ("contains", "hydrogen") in rels
    # label edges are NOT mixed into concept relations
    assert all(not r["relation"].startswith("label:") for r in c["relations"])
    assert graphx.concept(g, "does-not-exist") is None


def test_neighbors_path_subgraph():
    g = graphx.build_from_web(_store())
    nb = graphx.neighbors(g, "H2O")
    assert {(n["relation"], n["to"]) for n in nb["out"]} >= {
        ("label:en", "water"), ("contains", "oxygen"), ("contains", "hydrogen")}
    p = graphx.path(g, "hydrogen", "oxygen")
    assert p["path"][0] == "hydrogen" and p["path"][-1] == "oxygen"
    sg = graphx.subgraph(g, "H2O", depth=1)
    assert sg["center"] == "H2O"
    assert any(n["center"] for n in sg["nodes"])
    # language filter keeps only the requested label edges (relations always kept)
    sg_en = graphx.subgraph(g, "H2O", depth=1, langs={"en"})
    label_langs = {e["relation"] for e in sg_en["edges"] if e["kind"] == "label"}
    assert label_langs == {"label:en"}


def test_load_graph_falls_back_to_sample(tmp_path):
    g, source = explorer.load_graph(str(tmp_path / "missing.json"),
                                    str(tmp_path / "missing-world.json"))
    assert "sample" in source
    assert graphx.concept(g, "H2O")["labels"]["zh"] == "水"


def _vweb():
    """A store with a mixed-case key (``V2O5``) + its multilingual labels, for resolution tests."""
    return {"name": "v", "balances": {}, "records": [
        {"t": "record", "data": {"kind": "concept", "key": "V2O5", "formula": "V2O5",
                                 "definition": "Vanadium(V) oxide.", "by": "seed"}},
        {"t": "link", "subject": "V2O5", "object": "Vanadium pentoxide", "relation": "label:en", "weight": 1},
        {"t": "link", "subject": "V2O5", "object": "Оксид ванадия(V)", "relation": "label:ru", "weight": 1},
        {"t": "link", "subject": "V2O5", "object": "五氧化二钒", "relation": "label:zh", "weight": 1},
        {"t": "link", "subject": "V2O5", "object": "أكسيد الفناديوم", "relation": "label:ar", "weight": 1},
        {"t": "link", "subject": "V2O5", "object": "oxygen", "relation": "contains", "weight": 1},
        {"t": "record", "data": {"kind": "concept", "key": "oxygen", "by": "seed"}},
    ]}


def test_resolve_is_case_insensitive_and_trims():
    g = graphx.build_from_web(_vweb())
    # exact, lower, mixed, and surrounding whitespace all hit the real node V2O5
    assert graphx.resolve(g, "V2O5") == "V2O5"
    assert graphx.resolve(g, "v2o5") == "V2O5"
    assert graphx.resolve(g, "V2o5") == "V2O5"
    assert graphx.resolve(g, "  v2o5  ") == "V2O5"
    # a genuine miss / blank input resolves to None
    assert graphx.resolve(g, "nope") is None
    assert graphx.resolve(g, "") is None
    assert graphx.resolve(g, None) is None


def test_neighbors_path_concept_resolve_case_insensitively():
    g = graphx.build_from_web(_vweb())
    # neighbours of the lowercase term land on the real node and its real out-edges
    nb = graphx.neighbors(g, " v2o5 ")
    assert nb["term"] == "V2O5"
    assert {(n["relation"], n["to"]) for n in nb["out"]} >= {
        ("contains", "oxygen"), ("label:en", "Vanadium pentoxide")}
    # path resolves both endpoints case-insensitively
    p = graphx.path(g, "v2o5", "OXYGEN")
    assert p["from"] == "V2O5" and p["to"] == "oxygen"
    assert p["path"] == ["V2O5", "oxygen"]
    # concept lookup is case-insensitive and returns the multilingual labels
    c = graphx.concept(g, "v2o5")
    assert c["key"] == "V2O5"
    assert c["labels"]["en"] == "Vanadium pentoxide" and c["labels"]["zh"] == "五氧化二钒"
    # subgraph centres on the resolved node
    assert graphx.subgraph(g, "v2o5", depth=1)["center"] == "V2O5"


def test_suggest_on_miss_prefix_then_substring():
    g = graphx.build_from_web(_vweb())
    # a bare 'v' surfaces V2O5 (Vanadium…) — prefix matches lead, shortest-first
    sugg = graphx.suggest(g, "v")
    assert "V2O5" in sugg
    assert all(s.casefold() != "v" for s in sugg)          # the term itself is excluded
    assert len(sugg) <= 8
    # substring-only matches are found too ('xy' is inside 'oxygen')
    assert "oxygen" in graphx.suggest(g, "xy")
    # a resolvable term needs no suggestion path, and blank input yields none
    assert graphx.suggest(g, "") == []


def test_node_names_sorted_caseless():
    g = graphx.build_from_web(_vweb())
    names = graphx.node_names(g)
    assert "V2O5" in names and "oxygen" in names
    assert names == sorted(names, key=str.casefold)


def test_explore_returns_suggestions_on_miss():
    """The in-game Graph tab path: graphx.explore (used by world.explore) suggests on a miss."""
    class _It:                          # a minimal WovenItem stand-in for graphx.build()
        def __init__(self, **k):
            self.__dict__.update(k)
            self.confirmations = k.get("confirmations", 1)

    items = [_It(kind="link", subject="V2O5", object="oxygen", relation="contains")]
    res = graphx.explore(items, term="v")               # missed term → suggestions
    assert res["neighbors"] is None
    assert res["missing"] == ["v"] and "V2O5" in res["suggestions"]
    res2 = graphx.explore(items, frm="v2o5", to="zzz")  # one endpoint resolves, one misses
    assert res2["path"] is None
    assert res2["missing"] == ["zzz"]                   # v2o5 resolved to V2O5; only zzz missing


def test_world_to_store_roundtrips(tmp_path):
    world = {"items": [
        {"kind": "term", "by": "x", "fiber_cid": "f", "confirmations": 1, "term": "acid"},
        {"kind": "link", "by": "x", "fiber_cid": "f", "confirmations": 3,
         "subject": "acid", "object": "base", "relation": "reacts-with"},
    ]}
    p = tmp_path / "world.json"
    p.write_text(json.dumps(world), encoding="utf-8")
    g = graphx.build_from_web(explorer._world_to_store(str(p)))
    assert "acid" in g and "base" in g
    assert graphx.neighbors(g, "acid")["out"][0] == {"to": "base", "relation": "reacts-with"}
