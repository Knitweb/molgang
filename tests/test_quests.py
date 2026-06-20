"""Sprint 7 #110 — quests/missions over the woven Fibers.

Pure tests: load `quests.py`, `curriculum.py`, `chemistry.py` by path (no knitweb), inject the real
ground truth + curriculum, and drive with synthetic per-player woven lists. Covers completion,
deterministic XP, idempotent progress, tier gating, owner filtering, and dual woven-item shapes.
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
quests = _load("molgang_quests", "src/molgang/quests.py")
MOL, TIER_OF = chem.MOLECULES, chem.tier_of
KW = dict(molecules=MOL, tier_of=TIER_OF, curriculum=curr)


def _woven(formulas, by="alice"):
    """Build a bar-shaped woven list (uses the `term` key, like bar.woven)."""
    return [{"term": f, "by": by, "fiber_cid": f"cid-{i}"} for i, f in enumerate(formulas)]


def _rows(woven, by="alice"):
    return {r["id"]: r for r in quests.quest_progress(woven, by, **KW)}


def test_empty_player_has_no_completions_and_zero_xp():
    rows = _rows(_woven([]))
    assert all(not r["complete"] for r in rows.values())
    assert all(r["xp_awarded"] == 0 for r in rows.values())
    assert quests.quest_xp(_woven([]), "alice", **KW) == 0
    # everything is still "active"
    assert len(quests.active_quests(_woven([]), "alice", **KW)) == len(quests.QUESTS)


def test_first_bond_completes_on_one_known_molecule_and_awards_xp():
    rows = _rows(_woven(["H2O"]))
    assert rows["first-bond"]["complete"] is True
    assert rows["first-bond"]["xp_awarded"] == rows["first-bond"]["xp_reward"] == 50
    assert quests.quest_xp(_woven(["H2O"]), "alice", **KW) == 50


def test_progress_is_idempotent_under_duplicates():
    once = _rows(_woven(["H2O"]))
    many = _rows(_woven(["H2O", "H2O", "H2O"]))
    assert once["first-bond"]["done"] == many["first-bond"]["done"] == 1
    assert once == many  # duplicate weaves never change quest state


def test_tier_quests_are_tier_gated():
    # weaving 3 HIGH-tier molecules must NOT advance the elementary/middle tier quests
    highs = [f for f in MOL if TIER_OF(f) == "high"][:3]
    rows = _rows(_woven(highs))
    assert rows["high-3"]["complete"] is True
    assert rows["elementary-3"]["done"] == 0 and not rows["elementary-3"]["complete"]
    assert rows["middle-3"]["done"] == 0 and not rows["middle-3"]["complete"]


def test_tier_all_resolves_to_full_tier_size():
    elem = [f for f in MOL if TIER_OF(f) == "elementary"]
    rows = _rows(_woven(elem))
    assert rows["elementary-all"]["need"] == len(elem)
    assert rows["elementary-all"]["complete"] is True
    assert rows["elementary-all"]["pct"] == 100


def test_off_curriculum_and_owner_filtering():
    woven = _woven(["H2O"], by="alice") + _woven(["CO2"], by="bob") + [
        {"term": "🕸 some/spiral/path", "by": "alice"},          # not a molecule
        {"term": "NOT_A_MOLECULE", "by": "alice"},               # unknown
    ]
    a = _rows(woven, by="alice")
    b = _rows(woven, by="bob")
    assert a["first-bond"]["done"] == 1   # only alice's H2O, spirals/unknowns ignored
    assert b["first-bond"]["done"] == 1   # only bob's CO2


def test_active_quests_ordered_easiest_tier_first():
    rows = quests.active_quests(_woven([]), "alice", **KW)
    order = [quests._TIER_ORDER.index(r["tier"]) for r in rows]
    assert order == sorted(order)
    # within reach: first-bond (need 1) comes before collector-10 (need 10) in the elementary band
    ids = [r["id"] for r in rows]
    assert ids.index("first-bond") < ids.index("collector-10")


def test_canonical_formula_shape_also_works():
    # progression.collections() shape uses `formula`, not `term`
    woven = [{"formula": "H2O", "by": "alice"}, {"formula": "CO2", "by": "alice"}]
    rows = _rows(woven)
    # first-bond (scope "any", need 1) is complete; done reflects total distinct (2), pct caps at 100
    assert rows["first-bond"]["complete"] and rows["first-bond"]["done"] == 2
    assert rows["first-bond"]["pct"] == 100
    assert rows["elementary-3"]["done"] == 2
