"""Geometry data covers every molecule/element and stays internally consistent.

Mirrors the guard style of test_3d_graph_static.py: the 3D lab depends on
data/molecules-3d.json + data/elements-cpk.json, so regressions in the
generator must fail CI, not the browser.
"""

import json
import math
from pathlib import Path

import pytest

from molgang.chemistry import ELEMENTS, MOLECULES, parse_formula

ROOT = Path(__file__).resolve().parent.parent
MOLS = json.loads((ROOT / "data" / "molecules-3d.json").read_text())
CPK = json.loads((ROOT / "data" / "elements-cpk.json").read_text())


def test_every_molecule_has_geometry():
    assert set(MOLS) == set(MOLECULES)


def test_every_element_has_cpk():
    assert set(CPK) == set(ELEMENTS)
    for sym, e in CPK.items():
        assert e["color"].startswith("#") and len(e["color"]) == 7
        assert e["radius"] > 0
        assert e["z"] == ELEMENTS[sym][2]


@pytest.mark.parametrize("formula", list(MOLECULES))
def test_atom_counts_match_formula(formula):
    got: dict[str, int] = {}
    for a in MOLS[formula]["atoms"]:
        got[a["el"]] = got.get(a["el"], 0) + 1
    assert got == parse_formula(formula)


@pytest.mark.parametrize("formula", list(MOLECULES))
def test_coords_finite_and_bonds_in_range(formula):
    atoms = MOLS[formula]["atoms"]
    for a in atoms:
        for k in ("x", "y", "z"):
            assert math.isfinite(a[k])
        assert a["el"] in CPK  # every atom is renderable
    for i, j, order in MOLS[formula]["bonds"]:
        assert 0 <= i < len(atoms)
        assert 0 <= j < len(atoms)
        assert i != j
        assert order in (0, 1, 2, 3)  # 0 = ionic


def test_centred_on_origin():
    for formula, d in MOLS.items():
        n = len(d["atoms"])
        cx = sum(a["x"] for a in d["atoms"]) / n
        assert abs(cx) < 1e-3, formula
