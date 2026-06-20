"""Sprint 3 #33 — multilingual weave-plan builder (pure, no knitweb)."""
from __future__ import annotations
import json
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("weave_ml", ROOT / "scripts/weave_multilingual_terms.py")
weave_ml = importlib.util.module_from_spec(spec); spec.loader.exec_module(weave_ml)
DATA = json.loads((ROOT / "data/chemistry/multilingual_terms.json").read_text(encoding="utf-8"))


def test_links_cover_every_term_and_language():
    links = weave_ml.build_links(DATA)
    langs = {l["lang"] for l in DATA["languages"]}
    canon = set(DATA["elements"]) | set(DATA["molecules"])
    # every canonical term is an object of at least one alias link
    assert {l["object"] for l in links} == canon
    # every language appears as a relation tag
    assert {l["relation"].split(":")[1] for l in links} == langs
    # well-formed triples, localized name as subject, canonical as object
    for l in links:
        assert l["subject"] and l["relation"].startswith("name:") and l["object"] in canon
    # count sanity: 20 terms x 5 langs, minus any name==canonical no-ops
    assert 90 <= len(links) <= 100


def test_known_alias_present():
    links = weave_ml.build_links(DATA)
    triples = {(l["subject"], l["relation"], l["object"]) for l in links}
    assert ("Вода", "name:ru", "H2O") in triples
    assert ("水", "name:zh", "H2O") in triples
    assert ("ماء", "name:ar", "H2O") in triples
