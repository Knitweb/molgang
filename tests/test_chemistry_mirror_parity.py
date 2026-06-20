"""Sprint 7 #108 — enforce the chemistry ground truth's 1:1 mirrors + curriculum tiers.

`src/molgang/chemistry.py` is the authority. `roblox/Chemistry.lua` and `php/src/Chemistry.php`
are documented as mirroring its ELEMENTS / MOLECULES / TIER_OF tables 1:1, so a vote cast on a
Roblox or PHP node means exactly what it means on the canonical Python bar. Nothing enforced that
across all three engines (a Lua-only check existed; PHP had silently drifted to the old 10-molecule
set with no element table). This parses all three files textually (pure — no imports, no knitweb)
and asserts the element, molecule, and tier tables are identical everywhere. It also exercises the
pure `tier_of()` accessor on the canonical module.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = (ROOT / "src/molgang/chemistry.py").read_text(encoding="utf-8")
LUA = (ROOT / "roblox/Chemistry.lua").read_text(encoding="utf-8")
PHP = (ROOT / "php/src/Chemistry.php").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


# --- element tables: key -> (name_en, name_nl, Z) ---
def _py_elements():
    blk = _slice(PY, "ELEMENTS:", "MOLECULES:")
    return {m[0]: (m[1], m[2], int(m[3]))
            for m in re.findall(r'"(\w+)":\s*\("([^"]*)",\s*"([^"]*)",\s*(\d+)\)', blk)}


def _lua_elements():
    blk = _slice(LUA, "Chemistry.ELEMENTS", "Chemistry.MOLECULES")
    return {m[0]: (m[1], m[2], int(m[3]))
            for m in re.findall(r'(\w+)\s*=\s*\{"([^"]*)",\s*"([^"]*)",\s*(\d+)\}', blk)}


def _php_elements():
    blk = _slice(PHP, "const ELEMENTS", "const MOLECULES")
    return {m[0]: (m[1], m[2], int(m[3]))
            for m in re.findall(r"'(\w+)'\s*=>\s*\['([^']*)',\s*'([^']*)',\s*(\d+)\]", blk)}


# --- molecule tables: key -> (name_en, name_nl) ---
def _py_molecules():
    blk = _slice(PY, "MOLECULES:", "TIERS:")
    return {m[0]: (m[1], m[2])
            for m in re.findall(r'"(\w+)":\s*\("([^"]*)",\s*"([^"]*)"\)', blk)}


def _lua_molecules():
    blk = _slice(LUA, "Chemistry.MOLECULES", "Chemistry.TIERS")
    return {m[0]: (m[1], m[2])
            for m in re.findall(r'(\w+)\s*=\s*\{"([^"]*)",\s*"([^"]*)"\}', blk)}


def _php_molecules():
    blk = _slice(PHP, "const MOLECULES", "const TIERS")
    return {m[0]: (m[1], m[2])
            for m in re.findall(r"'(\w+)'\s*=>\s*\['([^']*)',\s*'([^']*)'\]", blk)}


# --- tier maps: key -> tier ---
def _py_tiers():
    blk = _slice(PY, "_TIER_OF", "def tier_of")
    return {m[0]: m[1] for m in re.findall(r'"(\w+)":\s*"(\w+)"', blk)}


def _lua_tiers():
    blk = _slice(LUA, "Chemistry.TIER_OF", "function Chemistry.tierOf")
    return {m[0]: m[1] for m in re.findall(r'(\w+)\s*=\s*"(\w+)"', blk)}


def _php_tiers():
    blk = _slice(PHP, "const TIER_OF", "public static function tierOf")
    return {m[0]: m[1] for m in re.findall(r"'(\w+)'\s*=>\s*'(\w+)'", blk)}


def test_parsers_find_the_tables():
    # guard against a silently-empty regex match masking a real divergence
    assert len(_py_elements()) >= 10 and len(_py_molecules()) >= 10 and len(_py_tiers()) >= 20
    for fn in (_lua_elements, _lua_molecules, _lua_tiers, _php_elements, _php_molecules, _php_tiers):
        assert len(fn()) >= 10, fn.__name__


def test_elements_mirror_across_all_engines():
    py = _py_elements()
    assert _lua_elements() == py
    assert _php_elements() == py


def test_molecules_mirror_across_all_engines():
    py = _py_molecules()
    assert _lua_molecules() == py
    assert _php_molecules() == py


def test_tiers_mirror_across_all_engines():
    py = _py_tiers()
    assert _lua_tiers() == py
    assert _php_tiers() == py


def test_every_element_and_molecule_has_a_valid_tier():
    tiers = _py_tiers()
    keys = set(_py_elements()) | set(_py_molecules())
    assert set(tiers) == keys, "every element/molecule must carry exactly one tier"
    assert set(tiers.values()) <= {"elementary", "middle", "high"}


def _load_chemistry():
    spec = importlib.util.spec_from_file_location("molgang_chemistry", ROOT / "src/molgang/chemistry.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["molgang_chemistry"] = mod  # dataclass(Bond) needs the module registered
    spec.loader.exec_module(mod)
    return mod


def test_tier_of_accessor():
    chem = _load_chemistry()
    # a valid tier for every known molecule, None (clean) for unknowns
    for formula in chem.MOLECULES:
        assert chem.tier_of(formula) in chem.TIERS, formula
    assert chem.tier_of("H2O") == "elementary"
    assert chem.tier_of("H2SO4") == "high"
    assert chem.tier_of("Fe") == "middle"     # element symbols resolve too
    assert chem.tier_of("NotAThing") is None
    assert chem.tier_of("") is None
