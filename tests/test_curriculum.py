"""Sprint 7 — tier-graded curriculum progress (the substrate quests/achievements/ladder read).

Pure tests: load `curriculum.py` and `chemistry.py` by path (no knitweb), feed curriculum the real
chemistry ground truth, and drive it with synthetic per-player woven lists.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass(Bond) in chemistry needs the module registered
    spec.loader.exec_module(mod)
    return mod


chem = _load("molgang_chemistry", "src/molgang/chemistry.py")
curr = _load("molgang_curriculum", "src/molgang/curriculum.py")
MOL = chem.MOLECULES
TIER_OF = chem.tier_of


def _p(woven):
    return curr.progress(woven, molecules=MOL, tier_of=TIER_OF)


def test_tier_totals_cover_every_molecule():
    totals = curr.tier_totals(MOL, TIER_OF)
    assert set(totals) == {"elementary", "middle", "high"}
    assert sum(totals.values()) == len(MOL)  # every molecule is tiered


def test_empty_player_is_zeroed_and_starts_at_elementary():
    p = _p([])
    assert p["woven"] == 0 and p["pct"] == 0
    assert all(t["woven"] == 0 for t in p["tiers"].values())
    assert curr.current_tier([], molecules=MOL, tier_of=TIER_OF) == "elementary"
    # the first things to learn are all elementary-tier
    nxt = curr.next_to_learn([], molecules=MOL, tier_of=TIER_OF, limit=4)
    assert nxt and all(TIER_OF(f) == "elementary" for f in nxt)


def test_full_player_is_100_and_nothing_left():
    everything = list(MOL)
    p = _p(everything)
    assert p["pct"] == 100 and p["woven"] == len(MOL)
    assert all(t["woven"] == t["total"] for t in p["tiers"].values())
    assert curr.current_tier(everything, molecules=MOL, tier_of=TIER_OF) == "high"
    assert curr.next_to_learn(everything, molecules=MOL, tier_of=TIER_OF) == []


def test_current_tier_advances_when_a_tier_is_complete():
    elementary = [f for f in MOL if TIER_OF(f) == "elementary"]
    assert curr.current_tier(elementary, molecules=MOL, tier_of=TIER_OF) == "middle"
    # progress reflects the completed elementary tier
    p = _p(elementary)
    assert p["tiers"]["elementary"]["pct"] == 100
    assert p["tiers"]["middle"]["woven"] == 0


def test_unknown_and_duplicate_formulas_are_ignored():
    woven = ["H2O", "H2O", "H2O", "NOT_A_MOLECULE", "ZzZ9"]
    p = _p(woven)
    assert p["woven"] == 1  # only the one distinct, known molecule counts
    assert p["tiers"]["elementary"]["woven"] == 1


def test_next_to_learn_is_ordered_easiest_first_and_capped():
    # a player who only knows one elementary molecule still gets elementary suggestions first
    nxt = curr.next_to_learn(["H2O"], molecules=MOL, tier_of=TIER_OF, limit=3)
    assert len(nxt) == 3
    tiers = [curr.TIER_ORDER.index(TIER_OF(f)) for f in nxt]
    assert tiers == sorted(tiers)  # non-decreasing tier order
    assert "H2O" not in nxt
