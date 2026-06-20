"""Integer-exact completion & consensus gates — no float ``round()`` or true-division decides a
discrete game outcome (the sacred integer-only invariant on value/decision paths).

Three decision points used to read a float and are pinned here:

  * ``curriculum.progress()`` computed ``pct`` via ``round(100 * woven / total)``. ``round(99.5)``
    is 100, so at a 200-molecule curriculum a player one molecule short reads ``pct == 100`` — a
    rounded float claiming completion before completion. Now floored (``100 * woven // total``), so
    ``pct == 100`` is exactly equivalent to ``woven == total``.
  * achievements' ``all_tiers_complete`` (which gates the **Polymath** badge, fed into the PoUW
    certificate's ``achievements_unlocked`` row) was decided from that rounded ``pct == 100``. Now
    decided from the integer-exact ``woven >= total`` — mirroring the per-tier check beside it.
  * ``progression.reputation_threshold`` bumped the BFT quorum on ``sum(levels) / len >= 6`` (float
    average) on the spiral-capture/reward path. Now ``sum(levels) >= 6 * len`` — float-free.

The first two tests fail on the old rounded-float forms; the third pins the integer boundary on the
consensus gate.
"""
from __future__ import annotations

from molgang import achievements, curriculum, progression

# A 200-molecule single-tier curriculum: exactly the size where round(100*199/200) == round(99.5)
# == 100 under banker's rounding — i.e. the float form claims completion one molecule early.
_MOLS = {f"X{i:04d}" for i in range(200)}


def _tier_of(formula):
    return "elementary" if formula in _MOLS else None


def test_progress_pct_floors_and_never_reads_complete_before_the_last_molecule():
    near = sorted(_MOLS)[:199]  # one molecule short of the whole 200-molecule curriculum
    p = curriculum.progress(near, molecules=_MOLS, tier_of=_tier_of)
    assert p["woven"] == 199 and p["total"] == 200
    # round(100*199/200) == round(99.5) == 100 (the float bug). Floor keeps it honest at 99.
    assert p["pct"] == 99, "pct must floor — never round up to a complete-looking 100"

    full = curriculum.progress(sorted(_MOLS), molecules=_MOLS, tier_of=_tier_of)
    assert full["woven"] == full["total"] == 200 and full["pct"] == 100  # exact boundary still 100


def test_polymath_locks_until_the_last_molecule_and_unlocks_exactly_at_full():
    def badges(woven):
        return {a["id"]: a["unlocked"] for a in achievements.evaluate(
            woven, molecules=_MOLS, tier_of=_tier_of, curriculum=curriculum)}

    near = [{"formula": f} for f in sorted(_MOLS)[:199]]
    assert badges(near)["polymath"] is False, "Polymath must not unlock with a molecule still missing"

    full = [{"formula": f} for f in sorted(_MOLS)]
    assert badges(full)["polymath"] is True, "Polymath unlocks exactly when the curriculum is whole"


def test_reputation_threshold_bumps_on_integer_exact_mean_level():
    # The Catalyst+ bump fires iff the integer-exact mean level >= 6 (sum >= 6*n), float-free.
    # n_voters=5 -> base quorum 4; a valid bump is 5 (5 <= 5 and 2*5 > 5).
    assert progression.reputation_threshold([6, 6, 6, 6, 6], 5) == 5  # sum 30 == 6*5, mean 6 -> bump
    assert progression.reputation_threshold([5, 6, 6, 6, 6], 5) == 4  # sum 29 < 30, mean 5.8 -> no bump
    assert progression.reputation_threshold([7, 7, 7, 7, 7], 5) == 5  # well above -> bump
    assert progression.reputation_threshold([], 5) == 4               # empty table -> never bumps
