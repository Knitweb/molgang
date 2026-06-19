"""Tests for molgang.merge — normalise + dedup + union many woven sources into ONE knitweb."""

from __future__ import annotations

import json

from molgang import merge


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_dedup_nodes_casefold_and_formula_fold(tmp_path):
    """CH₄ / CH4 / ch4 collapse to ONE node (casefold + clean fold)."""
    a = _write(tmp_path, "a_web.json", {"records": [
        {"t": "record", "data": {"kind": "concept", "key": "CH₄"}}]})
    b = _write(tmp_path, "b_world.json", {"items": [
        {"kind": "term", "by": "x", "fiber_cid": "", "confirmations": 1, "term": "CH4"},
        {"kind": "term", "by": "x", "fiber_cid": "", "confirmations": 1, "term": "ch4"}]})
    m = merge.merge_files([a, b])
    assert len(m.terms) == 1                       # one node for all three spellings


def test_union_edges_sum_confirmations(tmp_path):
    """Same (subject, relation, object) from two sources → one edge, SUMMED weight."""
    a = _write(tmp_path, "a_world.json", {"items": [
        {"kind": "link", "by": "p", "fiber_cid": "", "confirmations": 2,
         "subject": "H2O", "object": "oxygen", "relation": "contains"}]})
    b = _write(tmp_path, "b_world.json", {"items": [
        {"kind": "link", "by": "q", "fiber_cid": "", "confirmations": 3,
         "subject": "h2o", "object": "Oxygen", "relation": "contains"}]})
    m = merge.merge_files([a, b])
    assert len(m.edges) == 1
    (edge,) = m.edges.values()
    assert edge["weight"] == 5                      # 2 + 3 co-woven fibers → higher tension


def test_multilingual_and_spiral_preserved(tmp_path):
    """label:<lang> edges and spiral reaction-chain links survive the merge."""
    a = _write(tmp_path, "a_web.json", {"records": [
        {"t": "link", "subject": "H2O", "object": "water", "relation": "label:en", "weight": 1},
        {"t": "link", "subject": "H2O", "object": "вода", "relation": "label:ru", "weight": 1}]})
    b = _write(tmp_path, "b_world.json", {"items": [
        {"kind": "spiral", "by": "s", "fiber_cid": "", "confirmations": 3, "links": [
            {"subject": "H2", "object": "H2O", "relation": "yields"},
            {"subject": "O2", "object": "H2O", "relation": "yields"}]}]})
    m = merge.merge_files([a, b])
    rels = {e["relation"] for e in m.edges.values()}
    assert {"label:en", "label:ru", "yields"} <= rels


def test_roundtrip_world_and_app_store(tmp_path):
    """world_items() and app_records() both re-load into the same graph size."""
    from molgang import graphx
    from molgang.world import World

    src = _write(tmp_path, "src_world.json", {"items": [
        {"kind": "link", "by": "p", "fiber_cid": "", "confirmations": 2,
         "subject": "A", "object": "B", "relation": "is-a"}]})
    m = merge.merge_files([src])

    out = tmp_path / "combined.json"
    out.write_text(json.dumps({"items": m.world_items()}, ensure_ascii=False), encoding="utf-8")
    assert World(str(out)).size() == (2, 1)

    g = graphx.build_from_web({"records": m.app_records()})
    assert g.number_of_nodes() == 2 and g.number_of_edges() == 1


def test_stats_and_anchor(tmp_path):
    """stats() reports nodes/edges/languages and anchor() yields a verifiable UAL."""
    src = _write(tmp_path, "s_web.json", {"records": [
        {"t": "record", "data": {"kind": "concept", "key": "H2O", "definition": "water"}},
        {"t": "link", "subject": "H2O", "object": "water", "relation": "label:en", "weight": 1},
        {"t": "link", "subject": "H2O", "object": "oxygen", "relation": "contains", "weight": 1}]})
    m = merge.merge_files([src])
    s = merge.stats(m)
    assert s["nodes"] >= 2 and s["edges"] >= 2
    assert s["languages"]["en"] == 1
    assert s["distinct_concepts"] >= 1
    anc = merge.anchor(m)
    assert anc["ual"] and anc["ual"].startswith("did:dkg:")
    assert anc["verified"] is True


def test_skips_missing_and_unknown(tmp_path):
    """A missing path and an unrecognised doc are skipped, not fatal."""
    junk = _write(tmp_path, "junk.json", {"nope": 1})
    m = merge.merge_files(["/no/such/file_web.json", junk])
    assert m.terms == {} and m.edges == {}
