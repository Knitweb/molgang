"""Curriculum seeder — weave the full chemistry ground truth into the real fabric (#56).

The shared Knitweb fabric shown by the ``:8990`` explorer starts empty. This
derives a comprehensive elementary-to-high-school chemistry knowledge graph
**purely from the existing ground truth** (:mod:`molgang.chemistry`: ELEMENTS,
MOLECULES, REACTIONS) and weaves it in through the **real** propose → NPC-quorum
path, so every seeded fact is a genuinely peer-confirmed :class:`Fiber`, not an
injected record. No invented chemistry: the knits are element/compound nodes,
``contains`` links a molecule really has (from ``parse_formula``), and the
balanced curriculum reactions.

Deterministic + machine-usable: :func:`curriculum_knits` is a pure, ordered list
of knit strings; :func:`seed_bar` proposes each on a bot-seeded Bar (so a solo
seeder reaches quorum) and returns how many wove. The CLI ``molgang seed`` writes
the woven fabric to a world file the explorer can open.
"""
from __future__ import annotations

from . import chemistry

__all__ = ["curriculum_knits", "seed_bar", "seed_world"]


def curriculum_knits() -> list[str]:
    """The ordered, deterministic set of knit strings that seed the curriculum.

    Order: element nodes, then compound nodes, then each compound's ``contains``
    links (molecule -> its elements), then the balanced curriculum reactions.
    Every string is derived from the ground truth — nothing invented.
    """
    knits: list[str] = []

    # 1) element nodes (symbol terms) — deterministic by atomic number then symbol
    for sym in sorted(chemistry.ELEMENTS, key=lambda s: (chemistry.ELEMENTS[s][2], s)):
        knits.append(sym)

    # 2) compound nodes (formula terms)
    for formula in chemistry.MOLECULES:
        knits.append(formula)

    # 3) molecule -> element composition links ("H2O has H, O"), from parse_formula
    for formula in chemistry.MOLECULES:
        try:
            elements = list(chemistry.parse_formula(formula).keys())
        except ValueError:
            continue
        if elements:
            knits.append(f"{formula} has {', '.join(elements)}")

    # 4) the balanced curriculum reactions (reaction knits, #109)
    for rid in chemistry.REACTIONS:
        knits.append(chemistry.REACTIONS[rid]["equation"])

    return knits


def seed_bar(bar, sid: str, knits: "list[str] | None" = None) -> dict:
    """Propose every curriculum knit on ``bar`` as player ``sid``; report the result.

    Each proposal runs the real settle: NPC table-mates vote, a quorum weaves.
    Returns ``{proposed, woven, rejected}`` — a seed is ``woven`` iff peers
    confirmed it, so this reports honest coverage rather than assuming success.
    """
    knits = curriculum_knits() if knits is None else knits
    woven = 0
    for term in knits:
        prop = bar.propose(sid, term)
        if getattr(prop, "woven", False):
            woven += 1
    return {"proposed": len(knits), "woven": woven, "rejected": len(knits) - woven}


def seed_world(world_path: "str | None" = None, *, name: str = "Curriculum",
               table: str = "periodic") -> dict:
    """Build a Bar, weave the whole curriculum, and (optionally) persist the fabric.

    Returns the seeding stats plus the final fabric size, so a caller/CLI can
    report coverage. When ``world_path`` is given the woven world is saved there
    for ``molgang explore --web <world_path>``.
    """
    from .bar import Bar

    bar = Bar(world_path=world_path)
    seeder = bar.join(name, avatar="laser-maxi", table_id=table, device="curriculum-seed")
    bar.sit(seeder.sid, table)
    stats = seed_bar(bar, seeder.sid)
    graph = bar.world.graph()
    stats.update(nodes=graph["nodes"], edges=graph["edges"])
    return stats
