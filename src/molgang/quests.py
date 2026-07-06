"""Quests & missions — explicit, tier-graded goals over the woven Fibers (#110).

`progression.py` tracks XP/levels but offers no *goals*; this layer derives objectives from a
player's woven items and the curriculum tiers, so every peer has a reason to come back tomorrow.
It is pure derived game state — the knitweb (Fibers + quorum) stays the only authority; nothing
here mutates fabric state. Rewards are XP only (no new tokens, no NFTs), on the `progression`
scale (XP_PER_WOVEN = 100).

Quests are computed over a player's woven-item list — the shape `progression.collections()`
consumes — and are tolerant of both the canonical `{"formula", "by"}` shape and the bar's
`{"term", "by"}` shape. Off-curriculum terms (e.g. spirals) are ignored because only known
molecules count. Each quest is tier-aware: an elementary quest only ever counts elementary-tier
molecules, so it can never require a high-school compound.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

# id, title, desc, tier, scope, need, xp. scope "tier" counts distinct known molecules of `tier`;
# scope "any" counts distinct known molecules across all tiers. need "all" (tier scope only)
# resolves to that tier's full size. XP is awarded only on completion, deterministically.
QUESTS: list[dict] = [
    {"id": "first-bond", "title": "First bond", "tier": "elementary", "scope": "any",
     "need": 1, "xp": 50, "desc": "Weave your first peer-confirmed molecule."},
    {"id": "elementary-3", "title": "Elementary chemist", "tier": "elementary", "scope": "tier",
     "need": 3, "xp": 150, "desc": "Weave 3 different elementary molecules."},
    {"id": "elementary-all", "title": "Elementary mastery", "tier": "elementary", "scope": "tier",
     "need": "all", "xp": 300, "desc": "Weave every elementary molecule."},
    {"id": "middle-3", "title": "Stepping up", "tier": "middle", "scope": "tier",
     "need": 3, "xp": 200, "desc": "Weave 3 different middle-tier molecules."},
    {"id": "middle-all", "title": "Middle mastery", "tier": "middle", "scope": "tier",
     "need": "all", "xp": 400, "desc": "Weave every middle-tier molecule."},
    {"id": "high-3", "title": "Advanced synthesis", "tier": "high", "scope": "tier",
     "need": 3, "xp": 300, "desc": "Weave 3 different high-school molecules."},
    {"id": "high-all", "title": "High mastery", "tier": "high", "scope": "tier",
     "need": "all", "xp": 600, "desc": "Weave every high-school molecule."},
    {"id": "collector-10", "title": "Collector", "tier": "high", "scope": "any",
     "need": 10, "xp": 400, "desc": "Weave 10 different molecules."},
    # Slag Run — the SmartSlag/VANELEX story chain (#108): recover vanadium from
    # steel slag. scope "set" counts woven formulas from an explicit list, so the
    # quest tells a real process story instead of a generic tally.
    {"id": "slag-prospector", "title": "Slag prospector", "tier": "high", "scope": "set",
     "set": ["FeO", "Fe2O3", "CaO", "SiO2", "MgO"],
     "need": 3, "xp": 250, "silk": 5, "desc": "Weave 3 of the oxides that make up steel slag (FeO, Fe2O3, CaO, SiO2, MgO)."},
    {"id": "slag-run", "title": "Slag Run — vanadium recovery", "tier": "high", "scope": "set",
     "set": ["FeO", "Fe2O3", "Cr2O3", "V2O3", "V2O5"],
     "need": "all", "xp": 500, "silk": 10, "desc": "Weave the full recovery chain from steel slag to battery-grade "
                                       "vanadium: FeO, Fe2O3, Cr2O3, V2O3 and V2O5 (the VRFB electrolyte precursor)."},
    # Story tracks beyond Slag Run (#owner: "veel meer levels uit het script") — each a
    # themed chain over the graded ground truth, easiest first.
    {"id": "waterworks", "title": "Waterworks", "tier": "elementary", "scope": "set",
     "set": ["H2", "O2", "H2O", "H2O2", "O3"],
     "need": 3, "xp": 150, "silk": 3, "desc": "The water track: weave 3 of H2, O2, H2O, H2O2 and O3."},
    {"id": "combustion-track", "title": "Fire & smoke", "tier": "middle", "scope": "set",
     "set": ["CH4", "O2", "CO2", "CO", "H2O"],
     "need": "all", "xp": 300, "silk": 6, "desc": "The combustion track: methane, oxygen and every product "
                                       "of clean and dirty burning (CO2, CO, H2O)."},
    {"id": "kitchen-lab", "title": "Kitchen lab", "tier": "middle", "scope": "set",
     "set": ["NaCl", "NaHCO3", "CH3COOH", "C6H12O6", "C2H5OH"],
     "need": 4, "xp": 350, "silk": 7, "desc": "Chemistry from your own kitchen: salt, baking soda, vinegar, "
                                   "glucose and ethanol — weave any 4."},
    {"id": "acid-base", "title": "Acids & bases", "tier": "high", "scope": "set",
     "set": ["HCl", "NaOH", "H2SO4", "KOH", "HNO3", "CH3COOH"],
     "need": 4, "xp": 450, "silk": 9, "desc": "The neutralisation track: weave 4 of the classic acids and bases."},
    {"id": "noble-lab", "title": "Copper, silver & barium", "tier": "high", "scope": "set",
     "set": ["CuO", "CuSO4", "AgNO3", "BaSO4"],
     "need": "all", "xp": 400, "silk": 8, "desc": "The wet-lab classics: copper oxide and sulfate, silver "
                                       "nitrate and the barium sulfate precipitate."},
    {"id": "air-atmosphere", "title": "Air & atmosphere", "tier": "middle", "scope": "set",
     "set": ["N2", "O2", "CO2", "O3", "NO2"],
     "need": 4, "xp": 250, "silk": 5, "desc": "What you breathe (and what you shouldn't): weave 4 of "
                                              "N2, O2, CO2, O3 and NO2."},
    {"id": "haber-nitrogen", "title": "The nitrogen cycle", "tier": "high", "scope": "set",
     "set": ["N2", "H2", "NH3", "HNO3", "NO2"],
     "need": "all", "xp": 450, "silk": 9, "desc": "From air to fertiliser: N2 and H2 through the Haber "
                                                  "process to NH3, and on to HNO3 and NO2."},
    {"id": "sulfur-line", "title": "The sulfur line", "tier": "high", "scope": "set",
     "set": ["H2S", "SO2", "H2SO4"],
     "need": "all", "xp": 350, "silk": 7, "desc": "Volcano to factory: hydrogen sulfide, sulfur dioxide "
                                                  "and the acid that industry runs on."},
    {"id": "builders-yard", "title": "Builder's yard", "tier": "middle", "scope": "set",
     "set": ["CaCO3", "CaO", "SiO2", "Al2O3", "MgO"],
     "need": 4, "xp": 300, "silk": 6, "desc": "Limestone, quicklime, sand, alumina and magnesia — the "
                                              "chemistry of cement, glass and ceramics. Weave 4."},
    {"id": "salt-family", "title": "The salt family", "tier": "middle", "scope": "set",
     "set": ["NaCl", "KCl", "NaF", "KBr", "KI"],
     "need": 4, "xp": 300, "silk": 6, "desc": "Halide salts from table salt to toothpaste fluoride and "
                                              "iodised salt. Weave 4 of the family."},
    {"id": "pigments", "title": "Pigments & coatings", "tier": "high", "scope": "set",
     "set": ["TiO2", "ZnO", "MnO", "Cr2O3", "Fe2O3"],
     "need": 4, "xp": 400, "silk": 8, "desc": "The oxides that colour the world: titanium white, zinc "
                                              "white, manganese, chrome green and iron red. Weave 4."},
    {"id": "npk-fertiliser", "title": "NPK fertiliser", "tier": "high", "scope": "set",
     "set": ["NH3", "HNO3", "H3PO4", "KCl"],
     "need": "all", "xp": 400, "silk": 8, "desc": "Feed the world: nitrogen (NH3/HNO3), phosphorus "
                                                  "(H3PO4) and potassium (KCl) — the N-P-K of every fertiliser bag."},
]

_TIER_ORDER = ("elementary", "middle", "high")


def _resolve(molecules, tier_of, curriculum):
    """Resolve the ground truth + curriculum module, lazily defaulting to the canonical ones."""
    if molecules is None or tier_of is None:
        from . import chemistry
        molecules = chemistry.MOLECULES if molecules is None else molecules
        tier_of = chemistry.tier_of if tier_of is None else tier_of
    if curriculum is None:
        from . import curriculum as curriculum
    return molecules, tier_of, curriculum


def _player_formulas(woven: Iterable[dict], by: str | None, molecules) -> set[str]:
    """Distinct, known molecule formulas a player has woven. Accepts both the `formula` and the
    bar's `term` key; filters by owner `by` (None = all players); drops anything off-curriculum."""
    out: set[str] = set()
    for item in woven:
        if by is not None and item.get("by") != by:
            continue
        formula = item.get("formula") or item.get("term")
        if formula in molecules:
            out.add(formula)
    return out


def quest_progress(woven: Iterable[dict], by: str | None = None, *, molecules=None,
                   tier_of: Callable[[str], str | None] | None = None, curriculum=None) -> list[dict]:
    """Pure: every quest's progress for player `by`, deterministic from the woven list.

    Each row: ``{id, title, desc, tier, scope, need, done, pct, complete, xp_reward, xp_awarded}``.
    Never mutates fabric state. ``done`` may exceed ``need`` (over-completion); ``pct`` is capped at 100.
    """
    woven = list(woven)
    molecules, tier_of, curriculum = _resolve(molecules, tier_of, curriculum)
    formulas = _player_formulas(woven, by, molecules)
    prog = curriculum.progress(formulas, molecules=molecules, tier_of=tier_of)
    per, have_total = prog["tiers"], prog["woven"]

    rows: list[dict] = []
    for q in QUESTS:
        if q["scope"] == "tier":
            tier = q["tier"]
            done = per[tier]["woven"]
            need = per[tier]["total"] if q["need"] == "all" else q["need"]
        elif q["scope"] == "set":
            wanted = q["set"]
            done = sum(1 for f in wanted if f in formulas)
            need = len(wanted) if q["need"] == "all" else q["need"]
        else:  # "any"
            done = have_total
            need = q["need"]
        complete = need > 0 and done >= need
        rows.append({
            "id": q["id"], "title": q["title"], "desc": q["desc"], "tier": q["tier"],
            "scope": q["scope"], "need": need, "done": done,
            "pct": min(100, round(100 * done / need)) if need else 100,
            "complete": complete, "xp_reward": q["xp"], "xp_awarded": q["xp"] if complete else 0,
            "silk_reward": q.get("silk", 0),
        })
    return rows


def active_quests(woven: Iterable[dict], by: str | None = None, *, molecules=None,
                  tier_of: Callable[[str], str | None] | None = None, curriculum=None) -> list[dict]:
    """The not-yet-complete quests, easiest tier first then smallest target — the 'what to do next'
    list a client renders. Same purity guarantees as `quest_progress`."""
    rows = quest_progress(woven, by, molecules=molecules, tier_of=tier_of, curriculum=curriculum)
    todo = [r for r in rows if not r["complete"]]
    todo.sort(key=lambda r: (_TIER_ORDER.index(r["tier"]) if r["tier"] in _TIER_ORDER else 9, r["need"]))
    return todo


def quest_xp(woven: Iterable[dict], by: str | None = None, *, molecules=None,
             tier_of: Callable[[str], str | None] | None = None, curriculum=None) -> int:
    """Total XP a player has earned from completed quests (deterministic; integration-ready)."""
    return sum(r["xp_awarded"] for r in
               quest_progress(woven, by, molecules=molecules, tier_of=tier_of, curriculum=curriculum))
