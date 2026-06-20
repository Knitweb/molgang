"""Tier-graded curriculum progress — the bridge from chemistry tiers to the game layer.

Pure, derived state over the woven Fibers: given the molecules a player has woven, compute how far
they've come through each curriculum tier, which tier they're working on, and what to learn next.
Quests (#110), achievements (#111), and the seasonal ladder (#112) all read from this. The chemistry
ground truth (`chemistry.MOLECULES` + `chemistry.tier_of`) is the authority; the helpers accept those
as arguments so they stay pure and unit-testable, defaulting to the canonical tables when omitted.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

# Easiest → hardest. Mirrors chemistry.TIERS; kept here so this module can order tiers without
# importing chemistry (the molecule→tier *data* is still drawn from the injected ground truth).
TIER_ORDER: tuple[str, ...] = ("elementary", "middle", "high")


def _ground_truth(molecules, tier_of):
    """Resolve the (molecules, tier_of) ground truth, lazily falling back to the canonical tables.

    The lazy import keeps this module loadable on its own (no knitweb bootstrap) for unit tests that
    pass the data in explicitly; callers in the running game get the real chemistry tables for free.
    """
    if molecules is not None and tier_of is not None:
        return molecules, tier_of
    from . import chemistry  # lazy on purpose
    return (chemistry.MOLECULES if molecules is None else molecules,
            chemistry.tier_of if tier_of is None else tier_of)


def _tier_index(tier: str | None) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def tier_totals(molecules=None, tier_of: Callable[[str], str | None] | None = None) -> dict[str, int]:
    """How many known molecules live in each tier — the denominators for progress bars."""
    molecules, tier_of = _ground_truth(molecules, tier_of)
    totals = {t: 0 for t in TIER_ORDER}
    for formula in molecules:
        t = tier_of(formula)
        if t in totals:
            totals[t] += 1
    return totals


def _known_woven(woven_formulas: Iterable[str], molecules) -> set[str]:
    """Distinct, *known* molecules a player has woven (dedupe; drop anything off-curriculum)."""
    return {f for f in set(woven_formulas) if f in molecules}


def progress(woven_formulas: Iterable[str], molecules=None,
             tier_of: Callable[[str], str | None] | None = None) -> dict:
    """Per-tier and overall curriculum progress for one player.

    Returns ``{"tiers": {tier: {woven, total, pct}}, "woven", "total", "pct"}`` with ``pct`` a
    0..100 int. Unknown/duplicate woven formulas are ignored, so the numbers can't exceed the totals.

    ``pct`` is an integer *floor* (``100 * woven // total``), never a rounded float: a rounded
    percentage can read 100 with a molecule still missing (``round(100*199/200) == 100``), and that
    value drives a discrete completion decision (the Polymath badge / ``all_tiers_complete``). Floor
    keeps ``pct == 100`` exactly equivalent to ``woven == total`` and the value path integer-only.
    """
    molecules, tier_of = _ground_truth(molecules, tier_of)
    totals = tier_totals(molecules, tier_of)
    have = _known_woven(woven_formulas, molecules)
    per: dict[str, dict] = {}
    for t in TIER_ORDER:
        woven = sum(1 for f in have if tier_of(f) == t)
        total = totals[t]
        per[t] = {"woven": woven, "total": total, "pct": 100 * woven // total if total else 0}
    grand = sum(totals.values())
    return {"tiers": per, "woven": len(have), "total": grand,
            "pct": 100 * len(have) // grand if grand else 0}


def current_tier(woven_formulas: Iterable[str], molecules=None,
                 tier_of: Callable[[str], str | None] | None = None) -> str:
    """The tier a player is working through: the lowest tier they have not yet completed (or the
    hardest tier once every tier is done)."""
    per = progress(woven_formulas, molecules, tier_of)["tiers"]
    for t in TIER_ORDER:
        if per[t]["total"] and per[t]["woven"] < per[t]["total"]:
            return t
    return TIER_ORDER[-1]


def next_to_learn(woven_formulas: Iterable[str], molecules=None,
                  tier_of: Callable[[str], str | None] | None = None,
                  limit: int | None = 5) -> list[str]:
    """Known molecules the player has not woven yet, ordered easiest tier first then formula — the
    'what to learn next' list quests and the first-run tutorial surface. ``limit=None`` returns all."""
    molecules, tier_of = _ground_truth(molecules, tier_of)
    have = _known_woven(woven_formulas, molecules)
    todo = sorted((f for f in molecules if f not in have),
                  key=lambda f: (_tier_index(tier_of(f)), f))
    return todo if limit is None else todo[:limit]
