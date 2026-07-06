#!/usr/bin/env python3
"""Generate 3D molecular geometry for the MOLGANG 3D lab.

There is no 3D structure anywhere in the repo — only composition
(``chemistry.MOLECULES``) and a handful of 2D sim coordinates. This script
produces real 3D coordinates for every molecule in ``chemistry.MOLECULES`` using
**VSEPR** (valence-shell electron-pair repulsion) idealised geometries, keyed by
a small hand-authored connectivity table (central atom, ligands, bond orders,
lone pairs). No RDKit / SciPy — the 30 school-level molecules are small enough to
place from ideal bond angles and covalent-radius bond lengths.

Outputs (static-served by webserver.py from ``web/`` — we write to ``data/`` and
copy into ``web/data/`` so ``lab-3d.html`` can fetch them same-origin):
  data/molecules-3d.json  : {formula: {name, name_nl, tier, atoms:[{el,x,y,z}],
                                       bonds:[[i,j,order]]}}
  data/elements-cpk.json  : {symbol: {name, z, color, radius}}

Coordinates are in ångström, centred on the molecule's centroid.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from molgang.chemistry import ELEMENTS, MOLECULES, parse_formula, tier_of  # noqa: E402

# --- CPK colours + covalent radii (Å) ---------------------------------------
# Standard CPK colours (Jmol) and single-bond covalent radii (Cordero 2008,
# rounded). Covers every element in ELEMENTS (guarded by test_every_element_has_cpk).
CPK: dict[str, tuple[str, float]] = {
    "H": ("#ffffff", 0.31), "C": ("#2b2b2b", 0.76), "N": ("#3050f8", 0.71),
    "O": ("#ff0d0d", 0.66), "Na": ("#ab5cf2", 1.66), "Cl": ("#1ff01f", 1.02),
    "S": ("#ffff30", 1.05), "Ca": ("#3dff00", 1.76), "Fe": ("#e06633", 1.32),
    "He": ("#d9ffff", 0.28), "Mg": ("#8aff00", 1.41), "Al": ("#bfa6a6", 1.21),
    "P": ("#ff8000", 1.07), "K": ("#8f40d4", 2.03), "F": ("#90e050", 0.57),
    "Si": ("#f0c8a0", 1.11), "Zn": ("#7d80b0", 1.22), "Br": ("#a62929", 1.20),
    "I": ("#940094", 1.39),
    "Li": ("#cc80ff", 1.28), "B": ("#ffb5b5", 0.84), "Ne": ("#b3e3f5", 0.58),
    "Ar": ("#80d1e3", 1.06), "Ti": ("#bfc2c7", 1.60), "V": ("#a6a6ab", 1.53),
    "Cr": ("#8a99c7", 1.39), "Mn": ("#9c7ac7", 1.39), "Cu": ("#c88033", 1.32),
    "Ag": ("#c0c0c0", 1.45), "Ba": ("#00c900", 2.15), "Pb": ("#575961", 1.46),
}


def bond_len(a: str, b: str, order: int = 1) -> float:
    """Covalent bond length from radii, shortened for multiple bonds."""
    base = CPK[a][1] + CPK[b][1]
    return base * {1: 1.0, 2: 0.90, 3: 0.83}.get(order, 1.0)


# --- VSEPR ligand direction sets (unit vectors) -----------------------------
def _dirs(shape: str) -> list[tuple[float, float, float]]:
    t = math.tau
    if shape == "linear":
        return [(1, 0, 0), (-1, 0, 0)]
    if shape == "bent":  # ~104.5°, two ligands in xy
        a = math.radians(104.5 / 2)
        return [(math.sin(a), math.cos(a), 0), (-math.sin(a), math.cos(a), 0)]
    if shape == "bent_120":  # ~120° bent (SO2, NO2, O3-like)
        a = math.radians(119 / 2)
        return [(math.sin(a), math.cos(a), 0), (-math.sin(a), math.cos(a), 0)]
    if shape == "trigonal":  # trigonal planar, 120°
        return [(math.cos(t * k / 3 + math.pi / 2),
                 math.sin(t * k / 3 + math.pi / 2), 0) for k in range(3)]
    if shape == "pyramidal":  # 3 ligands, ~107° (NH3)
        z = -0.35
        r = math.sqrt(1 - z * z)
        return [(r * math.cos(t * k / 3), r * math.sin(t * k / 3), z)
                for k in range(3)]
    if shape == "tetrahedral":
        return [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    if shape == "terminal":  # single ligand
        return [(1, 0, 0)]
    raise ValueError(shape)


def _norm(v):
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


# --- Connectivity table -----------------------------------------------------
# Each entry: central atom + list of (ligand_symbol, bond_order) + VSEPR shape.
# Ionic/lattice formula units are laid out as separated ions (shape by count).
# Only structure that a school curriculum states as fact — no invented isomers.
C = "C"
SPEC: dict[str, dict] = {
    "H2O":  {"center": "O",  "shape": "bent",        "lig": [("H", 1), ("H", 1)]},
    "CO2":  {"center": "C",  "shape": "linear",      "lig": [("O", 2), ("O", 2)]},
    "O2":   {"center": "O",  "shape": "terminal",    "lig": [("O", 2)]},
    "CH4":  {"center": "C",  "shape": "tetrahedral", "lig": [("H", 1)] * 4},
    "NH3":  {"center": "N",  "shape": "pyramidal",   "lig": [("H", 1)] * 3},
    "HCl":  {"center": "Cl", "shape": "terminal",    "lig": [("H", 1)]},
    "H2":   {"center": "H",  "shape": "terminal",    "lig": [("H", 1)]},
    "N2":   {"center": "N",  "shape": "terminal",    "lig": [("N", 3)]},
    "CO":   {"center": "C",  "shape": "terminal",    "lig": [("O", 3)]},
    "SO2":  {"center": "S",  "shape": "bent_120",    "lig": [("O", 2), ("O", 2)]},
    "H2S":  {"center": "S",  "shape": "bent",        "lig": [("H", 1), ("H", 1)]},
    "NO2":  {"center": "N",  "shape": "bent_120",    "lig": [("O", 2), ("O", 1)]},
    "SO3_unit": {},  # placeholder guard (not in set)
    # oxoacids / hydroxides: central atom, O ligands, H on an O
    "H2SO4": {"center": "S", "shape": "tetrahedral",
              "lig": [("O", 2), ("O", 2), ("O", 1), ("O", 1)], "oh": [2, 3]},
    "H3PO4": {"center": "P", "shape": "tetrahedral",
              "lig": [("O", 2), ("O", 1), ("O", 1), ("O", 1)], "oh": [1, 2, 3]},
    "HNO3":  {"center": "N", "shape": "trigonal",
              "lig": [("O", 2), ("O", 2), ("O", 1)], "oh": [2]},
    "NaOH":  {"center": "O", "shape": "bent",  "lig": [("Na", 1), ("H", 1)]},
    "KOH":   {"center": "O", "shape": "bent",  "lig": [("K", 1), ("H", 1)]},
    "H2O2":  {"center": "O", "shape": "bent",  "lig": [("O", 1), ("H", 1)],
              "chain_h": True},
    # diatomic ionic salts + simple oxides: two separated ions
    "NaCl": {"ionic": [("Na", 1), ("Cl", -1)]},
    "KCl":  {"ionic": [("K", 1), ("Cl", -1)]},
    "NaF":  {"ionic": [("Na", 1), ("F", -1)]},
    "KBr":  {"ionic": [("K", 1), ("Br", -1)]},
    "KI":   {"ionic": [("K", 1), ("I", -1)]},
    "CaO":  {"ionic": [("Ca", 2), ("O", -2)]},
    "MgO":  {"ionic": [("Mg", 2), ("O", -2)]},
    "ZnO":  {"ionic": [("Zn", 2), ("O", -2)]},
    "FeO":  {"ionic": [("Fe", 2), ("O", -2)]},
    "MnO":  {"ionic": [("Mn", 2), ("O", -2)]},
    "CuO":  {"ionic": [("Cu", 2), ("O", -2)]},
    "SiO2": {"center": "Si", "shape": "linear", "lig": [("O", 2), ("O", 2)]},
    "TiO2": {"center": "Ti", "shape": "linear", "lig": [("O", 2), ("O", 2)]},
    "O3":   {"center": "O", "shape": "bent_120", "lig": [("O", 2), ("O", 1)]},
    "Al2O3": {"lattice": [("Al", 2), ("O", 3)]},
    "Fe2O3": {"lattice": [("Fe", 2), ("O", 3)]},
    "Cr2O3": {"lattice": [("Cr", 2), ("O", 3)]},
    "V2O3":  {"lattice": [("V", 2), ("O", 3)]},
    "V2O5":  {"lattice": [("V", 2), ("O", 5)]},
    "KCl_guard": {},
    "CaCO3": {"carbonate": True, "cation": "Ca"},
    # oxoanion salts: cation (with charge) + the anion's VSEPR unit
    "AgNO3":  {"oxo": ("N", "trigonal", [("O", 2), ("O", 1), ("O", 1)]),
               "cation": ("Ag", 1)},
    "CuSO4":  {"oxo": ("S", "tetrahedral", [("O", 2), ("O", 2), ("O", 1), ("O", 1)]),
               "cation": ("Cu", 2)},
    "BaSO4":  {"oxo": ("S", "tetrahedral", [("O", 2), ("O", 2), ("O", 1), ("O", 1)]),
               "cation": ("Ba", 2)},
    "NaHCO3": {"oxo": ("C", "trigonal", [("O", 2), ("O", 1), ("O", 1)]),
               "cation": ("Na", 1), "oxo_oh": [2]},
    "C6H12O6": {"glucose": True},
    "C2H5OH": {"ethanol": True},
    "CH3COOH": {"acetic": True},
}


def place(formula: str) -> list[dict]:
    """Return atoms [{el,x,y,z}] and bonds [[i,j,order]] for a formula."""
    spec = SPEC.get(formula)
    atoms: list[dict] = []
    bonds: list[list[int]] = []
    if spec is None:
        # fallback: chain the parsed atoms in a line (keeps the lab robust)
        seq = []
        for el, n in parse_formula(formula).items():
            seq += [el] * n
        for k, el in enumerate(seq):
            atoms.append({"el": el, "x": (k - (len(seq) - 1) / 2) * 1.4,
                          "y": 0.0, "z": 0.0})
            if k:
                bonds.append([k - 1, k, 1])
        return atoms, bonds

    if "ionic" in spec:
        (a, ca), (b, cb) = spec["ionic"]
        d = bond_len(a, b) * 1.15
        atoms = [{"el": a, "x": -d / 2, "y": 0, "z": 0, "charge": ca},
                 {"el": b, "x": d / 2, "y": 0, "z": 0, "charge": cb}]
        bonds = [[0, 1, 0]]  # order 0 = ionic (dashed in the viewer)
        return atoms, bonds

    if "lattice" in spec:  # Al2O3 — show the 5-ion formula unit in a row
        seq = []
        for el, n in spec["lattice"]:
            seq += [el] * n
        for k, el in enumerate(seq):
            atoms.append({"el": el, "x": (k - (len(seq) - 1) / 2) * 1.7,
                          "y": (0.4 if el == "O" else -0.4), "z": 0.0})
        for k in range(len(seq) - 1):
            bonds.append([k, k + 1, 0])
        return atoms, bonds

    if spec.get("carbonate"):  # CaCO3: Ca(2+) + planar CO3(2-)
        atoms.append({"el": "C", "x": 0, "y": 0, "z": 0})
        for k, v in enumerate(_dirs("trigonal")):
            order = 2 if k == 0 else 1
            d = bond_len("C", "O", order)
            atoms.append({"el": "O", "x": v[0] * d, "y": v[1] * d, "z": v[2] * d})
            bonds.append([0, k + 1, order])
        atoms.append({"el": spec["cation"], "x": 0, "y": -2.6, "z": 0,
                      "charge": 2})
        return atoms, bonds

    if spec.get("glucose"):  # simplified open-chain C6 backbone with OH/H
        atoms, bonds = _glucose()
        return atoms, bonds

    if spec.get("ethanol"):
        return _ethanol()

    if spec.get("acetic"):
        return _acetic()

    if "oxo" in spec:  # oxoanion salt: cation + VSEPR anion unit (CaCO3 pattern)
        center, shape, ligs = spec["oxo"]
        oh = set(spec.get("oxo_oh", []))
        atoms.append({"el": center, "x": 0, "y": 0, "z": 0})
        for k, (lig, order) in enumerate(ligs):
            v = _norm(_dirs(shape)[k])
            d = bond_len(center, lig, order)
            idx = len(atoms)
            atoms.append({"el": lig, "x": v[0] * d, "y": v[1] * d, "z": v[2] * d})
            bonds.append([0, idx, order])
            if k in oh and lig == "O":  # e.g. bicarbonate's O–H
                dh = bond_len("O", "H")
                hv = _norm((v[0] + 0.4, v[1] + 0.6, v[2] + 0.3))
                atoms.append({"el": "H",
                              "x": atoms[idx]["x"] + hv[0] * dh,
                              "y": atoms[idx]["y"] + hv[1] * dh,
                              "z": atoms[idx]["z"] + hv[2] * dh})
                bonds.append([idx, len(atoms) - 1, 1])
        cat, charge = spec["cation"]
        atoms.append({"el": cat, "x": 0, "y": -2.6, "z": 0, "charge": charge})
        return atoms, bonds

    # generic VSEPR: central atom + ligands, optional O–H hydroxyls
    center = spec["center"]
    atoms.append({"el": center, "x": 0, "y": 0, "z": 0})
    dirs = _dirs(spec["shape"])
    oh = set(spec.get("oh", []))
    for k, (lig, order) in enumerate(spec["lig"]):
        v = _norm(dirs[k])
        d = bond_len(center, lig, order)
        idx = len(atoms)
        atoms.append({"el": lig, "x": v[0] * d, "y": v[1] * d, "z": v[2] * d})
        bonds.append([0, idx, order])
        if k in oh and lig == "O":  # attach an H to this O (hydroxyl)
            dh = bond_len("O", "H")
            hv = _norm((v[0] + 0.4, v[1] + 0.6, v[2] + 0.3))
            atoms.append({"el": "H",
                          "x": atoms[idx]["x"] + hv[0] * dh,
                          "y": atoms[idx]["y"] + hv[1] * dh,
                          "z": atoms[idx]["z"] + hv[2] * dh})
            bonds.append([idx, len(atoms) - 1, 1])
    if spec.get("chain_h"):  # H2O2: H on the second O, dihedral out of plane
        dh = bond_len("O", "H")
        o2 = 1  # index of the second O (first ligand)
        atoms.append({"el": "H",
                      "x": atoms[o2]["x"] + dh * 0.5,
                      "y": atoms[o2]["y"] + dh * 0.6,
                      "z": atoms[o2]["z"] + dh * 0.7})
        bonds.append([o2, len(atoms) - 1, 1])
    return atoms, bonds


def _glucose():
    """Open-chain D-glucose skeleton (C1..C6) with OH and H — teaching shape."""
    atoms, bonds = [], []
    # zig-zag carbon backbone in xy
    for i in range(6):
        atoms.append({"el": "C", "x": i * 1.3 - 3.2,
                      "y": 0.5 if i % 2 else -0.5, "z": 0.0})
        if i:
            bonds.append([i - 1, i, 1])
    # C1 aldehyde =O, others get an -OH; add H to fill (schematic, not exhaustive)
    def add(el, cx, dx, dy, dz, order=1):
        ci = len(atoms)
        atoms.append({"el": el, "x": atoms[cx]["x"] + dx,
                      "y": atoms[cx]["y"] + dy, "z": atoms[cx]["z"] + dz})
        bonds.append([cx, ci, order])
        return ci
    # C1: aldehyde =O + one H  → CHO
    add("O", 0, 0.0, 0.0, 1.2, 2)
    add("H", 0, 0.0, 0.9, -0.6, 1)
    # C2..C5: one carbon-H + a hydroxyl (–OH)   → CHOH
    for c in range(1, 5):
        add("H", c, 0.0, 0.9, 0.5, 1)
        oi = add("O", c, 0.0, 0.0, 1.2, 1)
        add("H", oi, 0.3, 0.0, 0.8, 1)
    # C6: two carbon-H + a hydroxyl  → CH2OH
    add("H", 5, 0.0, 0.9, 0.5, 1)
    add("H", 5, 0.0, 0.9, -0.5, 1)
    oi = add("O", 5, 0.0, 0.0, 1.2, 1)
    add("H", oi, 0.3, 0.0, 0.8, 1)
    return atoms, bonds


def _chain2(extra):
    """Two sp3-ish carbons on the x-axis + caller-supplied substituents.

    Shared skeleton for the two-carbon organics (teaching shape, like _glucose):
    ``extra(add, c0, c1)`` attaches the functional group + hydrogens.
    """
    atoms, bonds = [], []

    def add(el, x, y, z, parent=None, order=1):
        i = len(atoms)
        atoms.append({"el": el, "x": x, "y": y, "z": z})
        if parent is not None:
            bonds.append([parent, i, order])
        return i

    c0 = add("C", -0.76, 0.0, 0.0)
    c1 = add("C", 0.76, 0.0, 0.0, c0)
    # methyl hydrogens on C0 (tetrahedral-ish fan away from C1)
    add("H", -1.15, 0.55, 0.85, c0)
    add("H", -1.15, 0.55, -0.85, c0)
    add("H", -1.15, -1.00, 0.00, c0)
    extra(add, c0, c1)
    return atoms, bonds


def _ethanol():
    """CH3–CH2–OH: ethanol as an open chain with a hydroxyl (teaching shape)."""
    def extra(add, c0, c1):
        # methylene hydrogens on C1
        add("H", 1.15, -0.55, 0.85, c1)
        add("H", 1.15, -0.55, -0.85, c1)
        # hydroxyl
        o = add("O", 1.45, 1.20, 0.0, c1)
        add("H", 2.35, 1.35, 0.30, o)
    return _chain2(extra)


def _acetic():
    """CH3–COOH: acetic acid — carboxyl C with =O and –OH (teaching shape)."""
    def extra(add, c0, c1):
        add("O", 1.35, 1.10, 0.0, c1, 2)      # carbonyl =O
        o2 = add("O", 1.50, -1.15, 0.0, c1)   # hydroxyl O
        add("H", 2.45, -1.05, 0.25, o2)
    return _chain2(extra)


def centre(atoms):
    n = len(atoms)
    cx = sum(a["x"] for a in atoms) / n
    cy = sum(a["y"] for a in atoms) / n
    cz = sum(a["z"] for a in atoms) / n
    for a in atoms:
        a["x"] = round(a["x"] - cx, 4)
        a["y"] = round(a["y"] - cy, 4)
        a["z"] = round(a["z"] - cz, 4)
    return atoms


def main():
    mols = {}
    for formula, (en, nl) in MOLECULES.items():
        atoms, bonds = place(formula)
        centre(atoms)
        mols[formula] = {"name": en, "name_nl": nl, "tier": tier_of(formula),
                         "atoms": atoms, "bonds": bonds}
    elements = {sym: {"name": ELEMENTS[sym][0], "z": ELEMENTS[sym][2],
                      "color": CPK[sym][0], "radius": CPK[sym][1]}
                for sym in ELEMENTS}

    for base in (ROOT / "data", ROOT / "web" / "data"):
        base.mkdir(parents=True, exist_ok=True)
        (base / "molecules-3d.json").write_text(
            json.dumps(mols, indent=2, ensure_ascii=False))
        (base / "elements-cpk.json").write_text(
            json.dumps(elements, indent=2, ensure_ascii=False))
    print(f"wrote {len(mols)} molecules, {len(elements)} elements "
          f"→ data/ and web/data/")


if __name__ == "__main__":
    main()
