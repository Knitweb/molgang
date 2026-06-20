"""Sprint 7 #109 (part 1) — reaction model + mass-balance ground truth.

Pure tests: load `chemistry.py` by path (no knitweb) and exercise the Reaction model, the equation
parser, and `reaction_is_balanced` over the canonical `REACTIONS` set and adversarial inputs.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("molgang_chemistry", ROOT / "src/molgang/chemistry.py")
chem = importlib.util.module_from_spec(spec)
sys.modules["molgang_chemistry"] = chem
spec.loader.exec_module(chem)


def test_every_canonical_reaction_is_balanced_and_well_tagged():
    assert len(chem.REACTIONS) >= 5
    for rid, entry in chem.REACTIONS.items():
        rx = chem.reaction(rid)
        assert chem.reaction_is_balanced(rx), f"{rid} is not mass-balanced: {entry['equation']}"
        assert entry["tier"] in chem.TIERS
        assert entry["type"] in chem.REACTION_TYPES
        assert chem.reaction_tier(rid) == entry["tier"]


def test_unbalanced_reaction_is_rejected():
    assert chem.reaction_is_balanced(chem.parse_equation("2 H2 + O2 -> 2 H2O")) is True
    assert chem.reaction_is_balanced(chem.parse_equation("H2 + O2 -> H2O")) is False     # O not conserved
    assert chem.reaction_is_balanced(chem.parse_equation("N2 + H2 -> 2 NH3")) is False   # H not conserved


def test_parse_equation_extracts_coefficients_conditions_and_arrows():
    rx = chem.parse_equation("N2 + 3 H2 -> 2 NH3 @ 450C, 200atm, Fe catalyst")
    assert rx.reactants == ((1, "N2"), (3, "H2"))
    assert rx.products == ((2, "NH3"),)
    assert rx.conditions == ("450C", "200atm", "Fe catalyst")
    # alternative arrows + no-coefficient + no-conditions
    assert chem.parse_equation("C + O2 → CO2").products == ((1, "CO2"),)
    assert chem.parse_equation("C + O2 => CO2").conditions == ()


@pytest.mark.parametrize("bad", [
    "H2 O2 H2O",            # no arrow
    "-> H2O",               # empty reactants
    "H2 ->",                # empty products
    "2 Zz -> 2 Yq",         # unknown elements
    "",                     # empty
])
def test_malformed_equations_raise(bad):
    with pytest.raises(ValueError):
        chem.parse_equation(bad)


def test_reaction_is_frozen_and_hashable():
    rx = chem.reaction("combustion-hydrogen")
    assert isinstance(hash(rx), int)            # frozen dataclass → hashable
    with pytest.raises(Exception):
        rx.reactants = ()                       # frozen → immutable
