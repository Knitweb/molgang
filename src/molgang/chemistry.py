"""MOLGANG chemistry (scheikunde) — the ground truth that gives peer votes meaning.

A player proposes a **bond**: a claim that a compound has a given formula and atom
composition (e.g. water = ``H2O`` = {H: 2, O: 1}). Peers who know their chemistry can
then validate it. This module is the small, school-level knowledge base + a formula
parser, kept pure (no I/O) so it is trivially testable and portable to the Roblox/Lua
counterpart (`roblox/Chemistry.lua` mirrors this table 1:1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A compact, school-level (scheikunde) element table: symbol -> (name_en, name_nl, Z).
ELEMENTS: dict[str, tuple[str, str, int]] = {
    "H": ("Hydrogen", "Waterstof", 1),
    "C": ("Carbon", "Koolstof", 6),
    "N": ("Nitrogen", "Stikstof", 7),
    "O": ("Oxygen", "Zuurstof", 8),
    "Na": ("Sodium", "Natrium", 11),
    "Cl": ("Chlorine", "Chloor", 17),
    "S": ("Sulfur", "Zwavel", 16),
    "Ca": ("Calcium", "Calcium", 20),
    "Fe": ("Iron", "IJzer", 26),
    "He": ("Helium", "Helium", 2),
    "Mg": ("Magnesium", "Magnesium", 12),
    "Al": ("Aluminium", "Aluminium", 13),
    "P": ("Phosphorus", "Fosfor", 15),
    "K": ("Potassium", "Kalium", 19),
}

# Known molecules: formula -> (name_en, name_nl). The lesson set newcomers learn first.
MOLECULES: dict[str, tuple[str, str]] = {
    "H2O": ("Water", "Water"),
    "CO2": ("Carbon dioxide", "Koolstofdioxide"),
    "O2": ("Oxygen gas", "Zuurstofgas"),
    "NaCl": ("Table salt", "Keukenzout"),
    "CH4": ("Methane", "Methaan"),
    "NH3": ("Ammonia", "Ammoniak"),
    "HCl": ("Hydrochloric acid", "Zoutzuur"),
    "C6H12O6": ("Glucose", "Glucose"),
    "CaCO3": ("Calcium carbonate", "Calciumcarbonaat"),
    "H2": ("Hydrogen gas", "Waterstofgas"),
    "N2": ("Nitrogen gas", "Stikstofgas"),
    "CO": ("Carbon monoxide", "Koolmonoxide"),
    "SO2": ("Sulfur dioxide", "Zwaveldioxide"),
    "H2SO4": ("Sulfuric acid", "Zwavelzuur"),
    "NaOH": ("Sodium hydroxide", "Natriumhydroxide"),
    "CaO": ("Calcium oxide", "Calciumoxide"),
    "MgO": ("Magnesium oxide", "Magnesiumoxide"),
    "Al2O3": ("Aluminium oxide", "Aluminiumoxide"),
    "KCl": ("Potassium chloride", "Kaliumchloride"),
    "H3PO4": ("Phosphoric acid", "Fosforzuur"),
}

# Curriculum tiers (scheikunde), ordered easiest → hardest, so quests, missions, and the
# seasonal ladder can grade content (#108). `tier_of()` queries a symbol/formula's level without
# touching `is_correct()` semantics. Mirrored 1:1 in roblox/Chemistry.lua and php/src/Chemistry.php.
TIERS: tuple[str, ...] = ("elementary", "middle", "high")

# symbol/formula -> curriculum tier. Covers every key in ELEMENTS and MOLECULES.
_TIER_OF: dict[str, str] = {
    # elements
    "H": "elementary", "O": "elementary", "C": "elementary", "N": "elementary", "He": "elementary",
    "Na": "middle", "Cl": "middle", "Ca": "middle", "Fe": "middle", "Mg": "middle",
    "S": "high", "Al": "high", "P": "high", "K": "high",
    # molecules
    "H2O": "elementary", "O2": "elementary", "CO2": "elementary", "H2": "elementary",
    "NaCl": "middle", "CH4": "middle", "NH3": "middle", "HCl": "middle", "CaCO3": "middle",
    "N2": "middle", "CO": "middle",
    "C6H12O6": "high", "SO2": "high", "H2SO4": "high", "NaOH": "high", "CaO": "high",
    "MgO": "high", "Al2O3": "high", "KCl": "high", "H3PO4": "high",
}


def tier_of(key: str) -> str | None:
    """Curriculum tier of an element symbol or molecule formula, or ``None`` if unknown.

    Pure lookup — does not parse or validate; ``is_correct()`` stays the authority on correctness.
    Every entry in ``ELEMENTS`` and ``MOLECULES`` has a tier in ``TIERS``.
    """
    return _TIER_OF.get((key or "").strip())


_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula(formula: str) -> dict[str, int]:
    """Parse a flat chemical formula (e.g. ``C6H12O6``) into ``{element: count}``.

    Supports element symbols (one upper + optional lower case) with optional counts.
    Raises ``ValueError`` on an unknown element or on stray characters.
    """
    formula = formula.strip()
    if not formula:
        raise ValueError("empty formula")
    atoms: dict[str, int] = {}
    pos = 0
    for m in _TOKEN.finditer(formula):
        if m.start() != pos:
            raise ValueError(f"unparseable formula near {formula[pos:]!r}")
        sym, num = m.group(1), m.group(2)
        if sym not in ELEMENTS:
            raise ValueError(f"unknown element {sym!r}")
        atoms[sym] = atoms.get(sym, 0) + (int(num) if num else 1)
        pos = m.end()
    if pos != len(formula):
        raise ValueError(f"trailing characters in formula: {formula[pos:]!r}")
    return atoms


@dataclass(frozen=True)
class Bond:
    """A proposed bond: 'compound `formula` (`name`) is made of `atoms`.'"""

    formula: str
    name: str
    atoms: dict[str, int]

    @classmethod
    def propose(cls, formula: str, name: str) -> "Bond":
        return cls(formula=formula, name=name, atoms=parse_formula(formula))


def is_correct(bond: Bond) -> bool:
    """Ground truth an honest peer uses to vote: is the proposed bond real chemistry?

    A bond is correct iff its formula is a known molecule AND the claimed atom
    composition matches the formula it parses to (so a player can't pass off a real
    formula with a wrong atom story).
    """
    if bond.formula not in MOLECULES:
        return False
    try:
        return bond.atoms == parse_formula(bond.formula)
    except ValueError:
        return False


def _term_recognized(term: str) -> bool:
    t = (term or "").strip()
    if not t:
        return False
    if t in MOLECULES:
        return True
    try:
        parse_formula(t)            # a structurally valid chemical formula
        return True
    except ValueError:
        return bool(re.fullmatch(r"[A-Za-z][\w'’ +/-]{1,}", t))   # a plausible word/phrase


def link_is_sound(link: dict) -> bool:
    """Ground truth for one spiral link: both ends are recognizable (a known molecule, a valid
    formula, or a plausible word) and distinct — so NPC peers can vote on a spiral honestly."""
    if not isinstance(link, dict) or link.get("kind") != "link":
        return False
    s, o = link.get("subject", ""), link.get("object", "")
    return _term_recognized(s) and _term_recognized(o) and s.casefold() != o.casefold()
