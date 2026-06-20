"""Sprint 7 #111 — achievements (milestone recognition over the woven web).

Pure tests: load `achievements.py`, `curriculum.py`, `chemistry.py` by path (no knitweb), inject the
real ground truth, and drive with synthetic woven/vote histories. Covers deterministic unlocks, no
double-unlock, the required first-reaction / tier-complete / honest-voter achievements, and that
badges carry no token value (data shape is id/title/desc only).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


chem = _load("molgang_chemistry", "src/molgang/chemistry.py")
curr = _load("molgang_curriculum", "src/molgang/curriculum.py")
ach = _load("molgang_achievements", "src/molgang/achievements.py")
MOL, TIER_OF = chem.MOLECULES, chem.tier_of
KW = dict(molecules=MOL, tier_of=TIER_OF, curriculum=curr)


def _woven(formulas, by="alice", kind=None):
    return [{"term": f, "by": by, **({"kind": kind} if kind else {})} for f in formulas]


def _ids(woven, votes=None, by="alice"):
    return {a["id"] for a in ach.unlocked_achievements(woven, votes, by, **KW)}


def test_empty_player_unlocks_nothing():
    assert _ids(_woven([])) == set()
    assert ach.achievement_count(_woven([]), [], "alice", **KW) == 0


def test_first_bond_unlocks_on_one_molecule():
    ids = _ids(_woven(["H2O"]))
    assert "first-bond" in ids
    assert "tier-elementary" not in ids  # one molecule != whole tier


def test_tier_complete_achievements_are_deterministic():
    elem = [f for f in MOL if TIER_OF(f) == "elementary"]
    ids = _ids(_woven(elem))
    assert "tier-elementary" in ids
    assert "tier-middle" not in ids and "tier-high" not in ids and "polymath" not in ids


def test_polymath_requires_every_tier():
    ids = _ids(_woven(list(MOL)))
    assert {"tier-elementary", "tier-middle", "tier-high", "polymath"} <= ids
    assert "collector-25" in ids  # 30 molecules ≥ 25


def test_first_reaction_is_forward_compatible():
    # reactions (#109) aren't produced yet, but the predicate fires on a reaction-kind woven item
    assert "first-reaction" not in _ids(_woven(["H2O"]))
    assert "first-reaction" in _ids(_woven(["H2O"]) + [{"term": "2H2+O2=2H2O", "by": "alice", "kind": "reaction"}])


def test_honest_voter_thresholds():
    woven = _woven(["H2O"])
    votes_9 = [{"by": "alice", "honest": True}] * 9
    votes_10 = [{"by": "alice", "honest": True}] * 10
    assert "honest-voter-10" not in _ids(woven, votes_9)
    assert "honest-voter-10" in _ids(woven, votes_10)
    # dishonest / other players' votes don't count
    mixed = [{"by": "alice", "honest": False}] * 50 + [{"by": "bob", "honest": True}] * 50
    assert "honest-voter-10" not in _ids(woven, mixed)


def test_no_double_unlock_and_stable_shape():
    woven = _woven(["H2O", "H2O", "H2O"])  # duplicates
    unlocked = ach.unlocked_achievements(woven, [], "alice", **KW)
    ids = [a["id"] for a in unlocked]
    assert len(ids) == len(set(ids))  # no achievement appears twice
    # badges are reputation only — id/title/desc, never a token/amount/value field
    for a in unlocked:
        assert set(a) == {"id", "title", "desc"}


def test_evaluate_is_full_ordered_list_with_flags():
    full = ach.evaluate(_woven(["H2O"]), [], "alice", **KW)
    assert [a["id"] for a in full] == [a["id"] for a in ach.ACHIEVEMENTS]  # stable order
    assert all("unlocked" in a for a in full)
