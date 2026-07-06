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
    "F": ("Fluorine", "Fluor", 9),
    "Si": ("Silicon", "Silicium", 14),
    "Zn": ("Zinc", "Zink", 30),
    "Br": ("Bromine", "Broom", 35),
    "I": ("Iodine", "Jood", 53),
    # steel-slag metals — the SmartSlag/VANELEX valorisation set (#108)
    "Ti": ("Titanium", "Titaan", 22),
    "V": ("Vanadium", "Vanadium", 23),
    "Cr": ("Chromium", "Chroom", 24),
    "Mn": ("Manganese", "Mangaan", 25),
    # remaining school main-group + common transition set (#108 final)
    "Li": ("Lithium", "Lithium", 3),
    "B": ("Boron", "Boor", 5),
    "Ne": ("Neon", "Neon", 10),
    "Ar": ("Argon", "Argon", 18),
    "Cu": ("Copper", "Koper", 29),
    "Ag": ("Silver", "Zilver", 47),
    "Ba": ("Barium", "Barium", 56),
    "Pb": ("Lead", "Lood", 82),
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
    "H2O2": ("Hydrogen peroxide", "Waterstofperoxide"),
    "HNO3": ("Nitric acid", "Salpeterzuur"),
    "H2S": ("Hydrogen sulfide", "Waterstofsulfide"),
    "NO2": ("Nitrogen dioxide", "Stikstofdioxide"),
    "KOH": ("Potassium hydroxide", "Kaliumhydroxide"),
    "SiO2": ("Silicon dioxide", "Siliciumdioxide"),
    "ZnO": ("Zinc oxide", "Zinkoxide"),
    "NaF": ("Sodium fluoride", "Natriumfluoride"),
    "KBr": ("Potassium bromide", "Kaliumbromide"),
    "KI": ("Potassium iodide", "Kaliumjodide"),
    # steel-slag oxides + the vanadium recovery ladder (#108, Slag Run quest)
    "FeO": ("Iron(II) oxide", "IJzer(II)oxide"),
    "Fe2O3": ("Iron(III) oxide", "IJzer(III)oxide"),
    "TiO2": ("Titanium dioxide", "Titaandioxide"),
    "MnO": ("Manganese(II) oxide", "Mangaan(II)oxide"),
    "Cr2O3": ("Chromium(III) oxide", "Chroom(III)oxide"),
    "V2O3": ("Vanadium(III) oxide", "Vanadium(III)oxide"),
    "V2O5": ("Vanadium(V) oxide", "Vanadium(V)oxide"),
    # everyday acids/bases/salts/organics rounding out the school set (#108 final)
    "O3": ("Ozone", "Ozon"),
    "NaHCO3": ("Sodium bicarbonate", "Natriumbicarbonaat"),
    "CH3COOH": ("Acetic acid", "Azijnzuur"),
    "C2H5OH": ("Ethanol", "Ethanol"),
    "CuO": ("Copper(II) oxide", "Koper(II)oxide"),
    "CuSO4": ("Copper(II) sulfate", "Koper(II)sulfaat"),
    "AgNO3": ("Silver nitrate", "Zilvernitraat"),
    "BaSO4": ("Barium sulfate", "Bariumsulfaat"),
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
    "F": "middle", "Zn": "middle",
    "S": "high", "Al": "high", "P": "high", "K": "high", "Si": "high", "Br": "high", "I": "high",
    # molecules
    "H2O": "elementary", "O2": "elementary", "CO2": "elementary", "H2": "elementary",
    "NaCl": "middle", "CH4": "middle", "NH3": "middle", "HCl": "middle", "CaCO3": "middle",
    "N2": "middle", "CO": "middle", "SiO2": "middle", "NaF": "middle",
    "C6H12O6": "high", "SO2": "high", "H2SO4": "high", "NaOH": "high", "CaO": "high",
    "MgO": "high", "Al2O3": "high", "KCl": "high", "H3PO4": "high",
    "H2O2": "high", "HNO3": "high", "H2S": "high", "NO2": "high", "KOH": "high",
    "ZnO": "high", "KBr": "high", "KI": "high",
    # steel-slag set — all high tier
    "Ti": "high", "V": "high", "Cr": "high", "Mn": "high",
    "FeO": "high", "Fe2O3": "high", "TiO2": "high", "MnO": "high",
    "Cr2O3": "high", "V2O3": "high", "V2O5": "high",
    # school-set completion (#108 final)
    "Ne": "elementary", "Ar": "elementary",
    "Li": "middle", "Cu": "middle", "Ag": "middle",
    "B": "high", "Ba": "high", "Pb": "high",
    "O3": "middle", "NaHCO3": "middle",
    "CH3COOH": "high", "C2H5OH": "high", "CuO": "high",
    "CuSO4": "high", "AgNO3": "high", "BaSO4": "high",
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


# -- Reactions (#109) ----------------------------------------------------------------------------
# A reaction is reactants -> products under optional conditions (temperature/pressure/catalyst).
# Ground truth is mass balance: every element is conserved across the arrow. Pure, mirrored 1:1 in
# roblox/Chemistry.lua and php/src/Chemistry.php. `REACTIONS` is the canonical curriculum set.
_SPECIES = re.compile(r"^\s*(\d*)\s*([A-Za-z0-9]+)\s*$")
_ARROWS = ("->", "→", "=>")


@dataclass(frozen=True)
class Reaction:
    """A balanced-or-not claim: ``reactants`` -> ``products`` under ``conditions``.

    ``reactants``/``products`` are tuples of ``(coefficient, formula)``; ``conditions`` is a tuple of
    free-text qualifiers (e.g. ``("spark",)`` or ``("450C", "200atm", "Fe catalyst")``).
    """

    reactants: tuple[tuple[int, str], ...]
    products: tuple[tuple[int, str], ...]
    conditions: tuple[str, ...] = ()


def _parse_side(side: str) -> tuple[tuple[int, str], ...]:
    out: list[tuple[int, str]] = []
    for chunk in side.split("+"):
        m = _SPECIES.match(chunk)
        if not m:
            raise ValueError(f"unparseable reaction species {chunk!r}")
        parse_formula(m.group(2))                       # validate elements (raises on unknown)
        out.append((int(m.group(1)) if m.group(1) else 1, m.group(2)))
    if not out:
        raise ValueError("reaction side has no species")
    return tuple(out)


def parse_equation(text: str) -> Reaction:
    """Parse ``"2 H2 + O2 -> 2 H2O @ spark"`` into a :class:`Reaction`.

    Accepts ``->``, ``→`` or ``=>`` as the arrow and an optional ``@ cond1, cond2`` suffix.
    Raises ``ValueError`` on a malformed equation (missing arrow, empty side, bad species).
    """
    text = (text or "").strip()
    conditions: tuple[str, ...] = ()
    if "@" in text:
        text, _, cond = text.partition("@")
        conditions = tuple(c.strip() for c in cond.split(",") if c.strip())
    arrow = next((a for a in _ARROWS if a in text), None)
    if arrow is None:
        raise ValueError("reaction needs an arrow (->) between reactants and products")
    left, _, right = text.partition(arrow)
    return Reaction(reactants=_parse_side(left), products=_parse_side(right), conditions=conditions)


def _tally(species: tuple[tuple[int, str], ...]) -> dict[str, int]:
    total: dict[str, int] = {}
    for coeff, formula in species:
        for el, n in parse_formula(formula).items():
            total[el] = total.get(el, 0) + coeff * n
    return total


def reaction_is_balanced(reaction: Reaction) -> bool:
    """Ground truth an honest peer votes on: is every element conserved across the arrow?"""
    try:
        return _tally(reaction.reactants) == _tally(reaction.products)
    except ValueError:
        return False


# Canonical curriculum reactions: id -> {name, type, tier, equation}. Each equation is balanced
# (a test asserts it) and tier-tagged like the molecule table. Mirrored 1:1 into Lua/PHP.
REACTIONS: dict[str, dict] = {
    "combustion-hydrogen": {"name": "Combustion of hydrogen", "type": "combustion", "tier": "middle",
                            "equation": "2 H2 + O2 -> 2 H2O @ spark"},
    "combustion-methane": {"name": "Combustion of methane", "type": "combustion", "tier": "middle",
                           "equation": "CH4 + 2 O2 -> CO2 + 2 H2O @ spark"},
    "combustion-carbon": {"name": "Combustion of carbon", "type": "combustion", "tier": "middle",
                          "equation": "C + O2 -> CO2"},
    "synthesis-ammonia": {"name": "Haber synthesis of ammonia", "type": "synthesis", "tier": "high",
                          "equation": "N2 + 3 H2 -> 2 NH3 @ 450C, 200atm, Fe catalyst"},
    "synthesis-sulfur-dioxide": {"name": "Burning sulfur", "type": "synthesis", "tier": "high",
                                 "equation": "S + O2 -> SO2 @ burn"},
    "neutralisation-hcl-naoh": {"name": "Neutralisation of hydrochloric acid", "type": "neutralisation",
                                "tier": "high", "equation": "HCl + NaOH -> NaCl + H2O"},
    "roast-vanadium": {"name": "Oxidative roast of vanadium oxide", "type": "synthesis", "tier": "high",
                       "equation": "V2O3 + O2 -> V2O5 @ 850C oxidative roast"},
    "thermite-iron": {"name": "Thermite reduction of iron oxide", "type": "redox", "tier": "high",
                      "equation": "Fe2O3 + 2 Al -> 2 Fe + Al2O3 @ ignition"},
    "decomposition-limestone": {"name": "Decomposition of limestone", "type": "decomposition",
                                "tier": "high", "equation": "CaCO3 -> CaO + CO2 @ heat"},
}

REACTION_TYPES: tuple[str, ...] = ("combustion", "synthesis", "neutralisation", "decomposition", "redox")


def reaction(rid: str) -> Reaction:
    """The parsed :class:`Reaction` for a canonical ``REACTIONS`` id."""
    return parse_equation(REACTIONS[rid]["equation"])


def reaction_tier(rid: str) -> str | None:
    """Curriculum tier of a canonical reaction id, or ``None`` if unknown."""
    entry = REACTIONS.get(rid)
    return entry["tier"] if entry else None


class ChemistryLens:
    """Knitweb L5 lens plugin: query the molecular knowledge base.

    ``react(query)`` returns a list of matching nodes (molecules, elements, or
    reactions) enriched with bilingual labels, neighbor formulas, and tier.
    Returns ``[]`` for unknown terms — never raises on bad input.
    """

    def react(self, query: str) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []
        results: list[dict] = []
        # Exact molecule match
        if q in MOLECULES:
            name_en, name_nl = MOLECULES[q]
            atoms = {}
            try:
                atoms = parse_formula(q)
            except ValueError:
                pass
            results.append({
                "node": q,
                "formula": q,
                "name_en": name_en,
                "name_nl": name_nl,
                "tier": _TIER_OF.get(q),
                "atoms": atoms,
                "neighbors": self._molecule_neighbors(q),
                "type": "molecule",
            })
        # Exact element match
        if q in ELEMENTS:
            name_en, name_nl, z = ELEMENTS[q]
            results.append({
                "node": q,
                "formula": q,
                "name_en": name_en,
                "name_nl": name_nl,
                "tier": _TIER_OF.get(q),
                "atoms": {q: 1},
                "neighbors": [],
                "type": "element",
                "atomic_number": z,
            })
        # Reactions containing this formula
        for rid, rdata in REACTIONS.items():
            rxn = parse_equation(rdata["equation"])
            species = [f for _, f in rxn.reactants] + [f for _, f in rxn.products]
            if q in species:
                results.append({
                    "node": rid,
                    "formula": rdata["equation"],
                    "name_en": rdata["name"],
                    "name_nl": rdata["name"],
                    "tier": rdata.get("tier"),
                    "neighbors": species,
                    "type": "reaction",
                    "reaction_type": rdata.get("type"),
                })
        return results

    def _molecule_neighbors(self, formula: str) -> list[str]:
        """Molecules that share at least one element with ``formula``."""
        try:
            atoms = set(parse_formula(formula).keys())
        except ValueError:
            return []
        return [
            mol for mol in MOLECULES
            if mol != formula and bool(set(parse_formula(mol).keys()) & atoms)
        ]
