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
