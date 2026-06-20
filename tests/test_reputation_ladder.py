"""Sprint 7 #113 — reputation ladder perks + next-threshold math.

Pure tests: load `progression.py` by path (its only knitweb use is a lazy import inside
`reputation_threshold`). Covers perks_for over all 8 levels, next_threshold math + max handling,
and the existing reputation_threshold invariants (k <= n and 2k > n) still holding.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("molgang_progression", ROOT / "src/molgang/progression.py")
prog = importlib.util.module_from_spec(spec)
sys.modules["molgang_progression"] = prog
spec.loader.exec_module(prog)


def test_perks_for_every_level_1_to_8():
    assert len(prog.PERKS) == len(prog.TITLES) == 8
    assert prog.perks_for(0) == []
    for level in range(1, 9):
        perks = prog.perks_for(level)
        assert len(perks) == level                 # cumulative: one new perk per level
        assert perks == prog.PERKS[:level]
    assert prog.perks_for(99) == prog.PERKS        # clamps at max


def test_perks_are_reputation_only_no_token_language():
    blob = " ".join(prog.PERKS).lower()
    for forbidden in ("token", "nft", "buy", "sell", "tradable", "$"):
        assert forbidden not in blob


def test_next_threshold_math():
    n0 = prog.next_threshold(0)
    assert n0["level"] == 1 and n0["title"] == "Apprentice"
    assert n0["next_title"] == "Student" and n0["xp_to_next"] == 100 and not n0["at_max"]
    # one woven bond = 100 XP → level 2, 200 XP to Lab Assistant (threshold 300)
    n100 = prog.next_threshold(100)
    assert n100["level"] == 2 and n100["title"] == "Student"
    assert n100["next_title"] == "Lab Assistant" and n100["xp_to_next"] == 200


def test_next_threshold_caps_at_max_rank():
    top = prog.next_threshold(10_000)              # well past the last threshold
    assert top["title"] == "Laureate" and top["at_max"] is True
    assert top["next_title"] is None and top["xp_to_next"] == 0


def test_reputation_threshold_invariants_unchanged():
    # the ladder must not regress the reputation-weighted quorum: k <= n and 2k > n always hold
    import pytest
    quorum = pytest.importorskip("knitweb.pouw.quorum")  # CI has the engine; skip locally
    for n in range(1, 12):
        base = quorum.default_threshold(n)
        veteran = prog.reputation_threshold([7] * n, n)   # an all-Alchemist table
        for k in (base, veteran):
            assert 1 <= k <= n and 2 * k > n
        assert veteran >= base                              # reputation only ever raises k
