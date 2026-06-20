"""Achievements — milestone recognition over the woven web (#111).

Reputation / woven-knowledge badges only — never tokens or tradable items (the no-NFT rule). Pure,
deterministic predicates over a player's woven items + vote history; nothing here mutates fabric
state. Built on the #108 curriculum tiers and the `curriculum.py` progress substrate.

Inputs:
- ``woven``: the player's woven-item list — the shape `progression.collections()` consumes. Tolerant
  of both the canonical ``{"formula"}`` key and the bar's ``{"term"}`` key, with an optional
  ``{"kind": "reaction"}`` marker (forward-compatible with reactions #109).
- ``votes``: a vote history, each record at least ``{"by": <voter>, "honest": <bool>}`` where
  ``honest`` means the vote agreed with the settled-correct outcome. An empty list simply leaves the
  vote-based achievements locked (forward-compatible until the bar records per-voter honesty).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

# Each achievement: id, title, desc, and a pure predicate over the derived context below. Order is
# stable and is the display order. Thresholds mirror the progression XP scale's spirit (no tokens).
ACHIEVEMENTS: list[dict] = [
    {"id": "first-bond", "title": "First bond",
     "desc": "Weave your first peer-confirmed molecule.",
     "check": lambda c: c["distinct"] >= 1},
    {"id": "tier-elementary", "title": "Elementary mastery",
     "desc": "Weave every elementary-tier molecule.",
     "check": lambda c: c["tier_complete"].get("elementary", False)},
    {"id": "tier-middle", "title": "Middle mastery",
     "desc": "Weave every middle-tier molecule.",
     "check": lambda c: c["tier_complete"].get("middle", False)},
    {"id": "tier-high", "title": "High mastery",
     "desc": "Weave every high-school-tier molecule.",
     "check": lambda c: c["tier_complete"].get("high", False)},
    {"id": "polymath", "title": "Polymath",
     "desc": "Complete the whole curriculum — every tier.",
     "check": lambda c: c["all_tiers_complete"]},
    {"id": "collector-10", "title": "Collector",
     "desc": "Weave 10 different molecules.",
     "check": lambda c: c["distinct"] >= 10},
    {"id": "collector-25", "title": "Curator",
     "desc": "Weave 25 different molecules.",
     "check": lambda c: c["distinct"] >= 25},
    {"id": "first-reaction", "title": "First reaction",
     "desc": "Weave your first chemical reaction.",
     "check": lambda c: c["reactions"] >= 1},
    {"id": "honest-voter-10", "title": "Honest voter",
     "desc": "Cast 10 honest, peer-agreeing votes.",
     "check": lambda c: c["honest_votes"] >= 10},
    {"id": "honest-voter-100", "title": "Pillar of the web",
     "desc": "Cast 100 honest, peer-agreeing votes.",
     "check": lambda c: c["honest_votes"] >= 100},
]


def _resolve(molecules, tier_of, curriculum):
    if molecules is None or tier_of is None:
        from . import chemistry
        molecules = chemistry.MOLECULES if molecules is None else molecules
        tier_of = chemistry.tier_of if tier_of is None else tier_of
    if curriculum is None:
        from . import curriculum as curriculum
    return molecules, tier_of, curriculum


def _context(woven: Iterable[dict], votes: Iterable[dict], by: str | None,
             molecules, tier_of, curriculum) -> dict:
    woven, votes = list(woven), list(votes)
    formulas, reactions = set(), 0
    for item in woven:
        if by is not None and item.get("by") != by:
            continue
        if item.get("kind") == "reaction":
            reactions += 1
        formula = item.get("formula") or item.get("term")
        if formula in molecules:
            formulas.add(formula)
    prog = curriculum.progress(formulas, molecules=molecules, tier_of=tier_of)
    tier_complete = {t: (d["total"] > 0 and d["woven"] >= d["total"]) for t, d in prog["tiers"].items()}
    honest = sum(1 for v in votes
                 if (by is None or v.get("by") == by) and v.get("honest") is True)
    return {
        "distinct": prog["woven"],
        "tier_complete": tier_complete,
        "all_tiers_complete": prog["total"] > 0 and prog["pct"] == 100,
        "reactions": reactions,
        "honest_votes": honest,
    }


def evaluate(woven: Iterable[dict], votes: Iterable[dict] | None = None, by: str | None = None, *,
             molecules=None, tier_of: Callable[[str], str | None] | None = None,
             curriculum=None) -> list[dict]:
    """Pure: every achievement with an ``unlocked`` flag, in stable display order. Deterministic."""
    molecules, tier_of, curriculum = _resolve(molecules, tier_of, curriculum)
    ctx = _context(woven, votes or [], by, molecules, tier_of, curriculum)
    return [{"id": a["id"], "title": a["title"], "desc": a["desc"], "unlocked": bool(a["check"](ctx))}
            for a in ACHIEVEMENTS]


def unlocked_achievements(woven: Iterable[dict], votes: Iterable[dict] | None = None,
                          by: str | None = None, *, molecules=None,
                          tier_of: Callable[[str], str | None] | None = None,
                          curriculum=None) -> list[dict]:
    """The player's unlocked badges as a stable, ordered ``[{id, title, desc}]`` list. Pure."""
    return [{"id": a["id"], "title": a["title"], "desc": a["desc"]}
            for a in evaluate(woven, votes, by, molecules=molecules, tier_of=tier_of,
                              curriculum=curriculum) if a["unlocked"]]


def achievement_count(woven: Iterable[dict], votes: Iterable[dict] | None = None,
                      by: str | None = None, *, molecules=None,
                      tier_of: Callable[[str], str | None] | None = None,
                      curriculum=None) -> int:
    """How many achievements a player has unlocked — woven-knowledge proof for the PoUW certificate."""
    return sum(1 for a in evaluate(woven, votes, by, molecules=molecules, tier_of=tier_of,
                                   curriculum=curriculum) if a["unlocked"])
