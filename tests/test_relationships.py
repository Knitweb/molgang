"""Relationship recognition: has/contains/produces/is-a connectors, one-to-many object
lists, and unicode sub/superscript folding in clean()."""

from molgang.knit_parse import (
    clean, parse_knit, parse_links, spiral_links, _split_objects,
)


# -- new word-verb connectors ------------------------------------------------
def test_has_connector():
    p = parse_knit("water has hydrogen")
    assert p == {"kind": "link", "subject": "water", "object": "hydrogen",
                 "relation": "has", "label": "water has hydrogen"}


def test_contains_connector():
    assert parse_knit("water contains oxygen")["relation"] == "contains"
    assert parse_knit("alkane comprises carbon")["relation"] == "contains"
    assert parse_knit("set includes a")["relation"] == "contains"


def test_produces_connector():
    assert parse_knit("combustion produces CO2")["relation"] == "produces"
    assert parse_knit("reaction forms water")["relation"] == "produces"


def test_is_a_link():
    p = parse_knit("Methane is-a compound")
    assert p["kind"] == "link" and p["relation"] == "is-a"
    assert p["subject"] == "Methane" and p["object"] == "compound"
    p2 = parse_knit("Methane is a compound")
    assert p2["relation"] == "is-a" and p2["object"] == "compound"


def test_is_a_beats_has_and_is():
    # "X is a Y" must stay is-a, never fall through to has/is
    assert parse_knit("CH4 is an alkane")["relation"] == "is-a"


# -- the headline case from the task -----------------------------------------
def test_repo_has_three_modules():
    links = parse_links("the repo has molgang, monitor and pulse")
    assert len(links) == 3
    assert all(l["subject"] == "the repo" and l["relation"] == "has" for l in links)
    assert [l["object"] for l in links] == ["molgang", "monitor", "pulse"]


def test_one_to_many_dedup_object():
    links = parse_links("water contains H, H and O")  # H deduped
    assert [l["object"] for l in links] == ["H", "O"]
    assert all(l["relation"] == "contains" for l in links)


def test_glucose_produces_three():
    links = parse_links("glucose produces CO2, H2O and energy")
    assert len(links) == 3
    assert all(l["relation"] == "produces" for l in links)
    assert [l["object"] for l in links] == ["CO2", "H2O", "energy"]


def test_single_object_stays_dict():
    # back-compat: a plain link is still a single dict, not a list
    assert isinstance(parse_knit("a has b"), dict)
    assert isinstance(parse_knit("water"), dict)


def test_no_split_on_plus():
    # reaction stoichiometry must stay ONE object
    links = parse_links("burn produces 2H2 + O2")
    assert len(links) == 1
    assert links[0]["object"] == "2H2 + O2"


# -- unicode subscript / superscript folding ---------------------------------
def test_subscript_fold():
    assert clean("CH₄") == "CH4"
    assert clean("V₂O₅") == "V2O5"


def test_superscript_fold():
    assert clean("x²") == "x2"
    assert clean("Ca²⁺".replace("⁺", "")) == "Ca2"


def test_ch4_dedupes_to_one_node():
    # "CH₄ is CH4": after folding both sides are CH4 → self-link rejected → bare term
    p = parse_knit("CH₄ is CH4")
    assert p["kind"] == "term"
    assert p["term"] == "CH4"


def test_v2o5_unicode_dedupes_to_term():
    p = parse_knit("V₂O₅ = V2O5")
    assert p["kind"] == "term" and p["term"] == "V2O5"


def test_latex_and_unicode_converge():
    assert clean(r"\(V_{2}O_{5}\)") == clean("V₂O₅") == "V2O5"


# -- helpers / spiral integration --------------------------------------------
def test_split_objects_oxford_and_dedup():
    assert _split_objects("A, B, and C") == ["A", "B", "C"]
    assert _split_objects("a and A") == ["a"]  # case-insensitive dedup, first-seen kept


def test_warp_limit_truncates():
    big = "x has " + ", ".join(f"n{i}" for i in range(300))
    links = parse_links(big)
    assert len(links) == 256


def test_spiral_flattens_one_to_many():
    links = spiral_links(["Mg has Cl, Cl, O"])  # Cl deduped → 2 edges
    assert [l["object"] for l in links] == ["Cl", "O"]
    assert all(l["subject"] == "Mg" and l["relation"] == "has" for l in links)
