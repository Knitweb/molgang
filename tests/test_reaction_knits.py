"""#109 — reactions with conditions as first-class, votable knits.

The Reaction model/balance/REACTIONS table already existed; these tests pin the
playable thread: knit-syntax parsing, honest bot ground truth, and weaving a
confirmed reaction into the shared web (+ explorer edges + JSON-LD).
"""
from molgang import game
from molgang.bar import Bar
from molgang.knit_parse import parse_knit
from knitweb.pouw import quorum


def test_reaction_knit_syntax_parses_with_conditions():
    p = parse_knit("2H2 + O2 -> 2H2O @ spark")
    assert p["kind"] == "reaction"
    assert p["equation"] == "2H2 + O2 -> 2H2O"
    assert p["conditions"] == "spark"
    assert p["reactants"] == ["2H2", "O2"] and p["products"] == ["2H2O"]
    # unicode arrow + subscripts fold like every other knit
    q = parse_knit("V₂O₃ + O₂ → V₂O₅ @ 850C roast")
    assert q["kind"] == "reaction" and q["equation"] == "V2O3 + O2 -> V2O5"


def test_prose_arrows_and_bare_terms_stay_links_and_terms():
    assert parse_knit("water -> steam")["kind"] == "link"        # no reaction signals
    assert parse_knit("H2O")["kind"] == "term"
    assert parse_knit("X has A, B and C")[0]["kind"] == "link"   # enumeration unchanged


def test_malformed_reactions_fall_back_instead_of_crashing():
    # prose species with a '+' falls back to the link path (object side keeps the text)
    p = parse_knit("acids + bases -> salt water")
    assert p["kind"] != "reaction"


def test_honest_reaction_verdict_is_hard_ground_truth():
    assert game.honest_reaction_verdict("2H2 + O2 -> 2H2O") is quorum.Verdict.CONFIRM
    assert game.honest_reaction_verdict("V2O3 + O2 -> V2O5") is quorum.Verdict.CONFIRM
    # unbalanced → mismatch
    assert game.honest_reaction_verdict("H2 + O2 -> H2O") is quorum.Verdict.MISMATCH
    # unknown element → mismatch, not a crash
    assert game.honest_reaction_verdict("Xx + O2 -> XxO2") is quorum.Verdict.MISMATCH


def test_confirmed_reaction_weaves_into_the_shared_web(tmp_path):
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Roaster", "laser-maxi", "periodic", device="dev-rxn-1")
    prop = bar.propose(me.sid, "V2O3 + O2 -> V2O5 @ 850C oxidative roast")
    assert prop.woven, "honest bots must confirm a balanced real reaction"

    items = [i for i in bar.world.items if i.kind == "reaction"]
    assert len(items) == 1
    it = items[0]
    assert it.term == "V2O3 + O2 -> V2O5 @ 850C oxidative roast"
    assert {"subject": "V2O3", "object": "V2O5", "relation": "reacts-to"} in it.links
    # explorer: the reaction wove a real edge into the shared web
    g = bar.world.graph()
    assert g["edges"] >= 1 and g["nodes"] >= 2
    # JSON-LD carries the equation + links
    doc = bar.world.to_jsonld()
    rx = [n for n in doc["@graph"] if n.get("knitweb:kind") == "reaction"]
    assert rx and rx[0]["knitweb:equation"].startswith("V2O3 + O2 -> V2O5")


def test_unbalanced_reaction_is_rejected_by_bots(tmp_path):
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Sloppy", "laser-maxi", "periodic", device="dev-rxn-2")
    prop = bar.propose(me.sid, "H2 + O2 -> H2O @ spark")   # not balanced
    assert not prop.woven
    assert not [i for i in bar.world.items if i.kind == "reaction"]
