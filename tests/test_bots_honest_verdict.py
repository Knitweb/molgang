"""Regression: seated NPC bots must vote an HONEST chemistry verdict on link knits, not
rubber-stamp them. Previously `_bots_act` hard-confirmed every proposal, so a solo player at a
bot-seeded table could auto-weave unsound knits into the shared web (the "peers validate" guarantee
was void). Bots now route link knits through the same `honest_spiral_verdict` the spiral path uses.

Scope note: `chemistry.link_is_sound` is lenient (any recognizable, distinct pair passes), so this
closes the rubber-stamp oversight for *unsound* links (empty/identical/malformed ends); catching
semantically-false-but-well-formed claims needs a stricter chemistry model (separate maintainer call).
"""

from __future__ import annotations

from knitweb.pouw import quorum
from molgang import game
from molgang.bar import Bar, Proposal


def _stage(bar: Bar, human, link: dict, pid: str) -> Proposal:
    rnd = game.Round(proposer=human.player, escrow=game.AccountNode(), term=link.get("object", "?"))
    prop = Proposal(pid=pid, table_id=human.table_id, by=human.sid, by_name="Human",
                    term="knit", round=rnd, parsed=link, links=[link], topic="t")
    bar.proposals[pid] = prop
    return prop


def test_bots_reject_unsound_link_instead_of_rubber_stamping(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")  # the periodic table is seeded with NPC bots

    bad = {"kind": "link", "subject": "water", "object": "", "relation": "is"}  # empty end → unsound
    prop = _stage(bar, human, bad, "pbad")
    bar._bots_act()

    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts, "a seated bot should have weighed in"
    assert all(v == quorum.Verdict.MISMATCH for v in verdicts), \
        "bots must reject an unsound link, not rubber-stamp it"


def test_bots_confirm_a_sound_link(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")

    good = {"kind": "link", "subject": "water", "object": "H2O", "relation": "is"}
    prop = _stage(bar, human, good, "pgood")
    bar._bots_act()

    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts, "a seated bot should have weighed in"
    assert all(v == quorum.Verdict.CONFIRM for v in verdicts), \
        "bots should still confirm a sound, recognizable link"


def test_bots_confirm_a_brainstorm_term(tmp_path):
    # A free term has no chemistry ground truth → consensus confirm is preserved.
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")

    rnd = game.Round(proposer=human.player, escrow=game.AccountNode(), term="electronegativity")
    prop = Proposal(pid="pterm", table_id=human.table_id, by=human.sid, by_name="Human",
                    term="electronegativity", round=rnd,
                    parsed={"kind": "term", "term": "electronegativity", "label": "electronegativity"},
                    links=[], topic="electronegativity")
    bar.proposals["pterm"] = prop
    bar._bots_act()

    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts and all(v == quorum.Verdict.CONFIRM for v in verdicts)


def test_bots_use_parsed_link_when_links_list_is_empty(tmp_path):
    # Single-link proposals carry the link in `parsed` with `links=[]`; _bots_act must derive the
    # link from `parsed` (not skip to a blind confirm). An unsound parsed link → mismatch.
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")
    bad = {"kind": "link", "subject": "water", "object": "", "relation": "is"}
    rnd = game.Round(proposer=human.player, escrow=game.AccountNode(), term="?")
    prop = Proposal(pid="pparsed", table_id=human.table_id, by=human.sid, by_name="Human",
                    term="knit", round=rnd, parsed=bad, links=[])  # links empty, parsed is the link
    bar.proposals["pparsed"] = prop
    bar._bots_act()
    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts and all(v == quorum.Verdict.MISMATCH for v in verdicts)


def _stage_bond(bar, human, formula: str, pid: str) -> Proposal:
    rnd = game.Round(proposer=human.player, escrow=game.AccountNode(),
                     bond=game.Bond.propose(formula, formula))
    prop = Proposal(pid=pid, table_id=human.table_id, by=human.sid, by_name="Human",
                    term=formula, round=rnd,
                    parsed={"kind": "term", "term": formula, "label": formula})
    bar.proposals[pid] = prop
    return prop


def test_bots_reject_a_false_chemistry_bond(tmp_path):
    # A round carrying a chemistry `bond` is judged by honest_verdict; a false bond (parseable but
    # not a known molecule, e.g. H3O) → mismatch.
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")
    prop = _stage_bond(bar, human, "H3O", "pbf")
    bar._bots_act()
    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts and all(v == quorum.Verdict.MISMATCH for v in verdicts)


def test_bots_confirm_a_real_chemistry_bond(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    human = bar.join("Human")
    bar.sit(human.sid, "periodic")
    prop = _stage_bond(bar, human, "H2O", "pbt")
    bar._bots_act()
    verdicts = [v.verdict for v in prop.round.votes]
    assert verdicts and all(v == quorum.Verdict.CONFIRM for v in verdicts)
