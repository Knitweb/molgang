"""Sprint 7 (#7.1 groundwork) — enforce the documented 1:1 mirror.

`src/molgang/chemistry.py` is the chemistry ground truth; `roblox/Chemistry.lua` is documented
as mirroring its ELEMENTS/MOLECULES tables 1:1 so a Roblox player's vote means exactly what it
means on the Knitweb. Nothing enforced that, so the two drifted once when the Python table grew.
This test parses both files textually (pure, no imports, no knitweb) and asserts the element and
molecule tables are byte-for-byte equivalent — names, Dutch names, and atomic numbers included.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = (ROOT / "src/molgang/chemistry.py").read_text(encoding="utf-8")
LUA = (ROOT / "roblox/Chemistry.lua").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


def _py_elements() -> dict[str, tuple[str, str, int]]:
    blk = _slice(PY, "ELEMENTS:", "_TOKEN")
    return {m[0]: (m[1], m[2], int(m[3]))
            for m in re.findall(r'"(\w+)":\s*\("([^"]*)",\s*"([^"]*)",\s*(\d+)\)', blk)}


def _py_molecules() -> dict[str, tuple[str, str]]:
    blk = _slice(PY, "MOLECULES:", "_TOKEN")
    return {m[0]: (m[1], m[2])
            for m in re.findall(r'"(\w+)":\s*\("([^"]*)",\s*"([^"]*)"\)', blk)}


def _lua_elements() -> dict[str, tuple[str, str, int]]:
    blk = _slice(LUA, "Chemistry.ELEMENTS", "formula ->")
    return {m[0]: (m[1], m[2], int(m[3]))
            for m in re.findall(r'(\w+)\s*=\s*\{"([^"]*)",\s*"([^"]*)",\s*(\d+)\}', blk)}


def _lua_molecules() -> dict[str, tuple[str, str]]:
    blk = _slice(LUA, "Chemistry.MOLECULES", "Parse a flat")
    return {m[0]: (m[1], m[2])
            for m in re.findall(r'(\w+)\s*=\s*\{"([^"]*)",\s*"([^"]*)"\}', blk)}


def test_parsers_find_the_tables():
    # guard against a silently-empty regex match masking a real divergence
    assert len(_py_elements()) >= 10 and len(_py_molecules()) >= 10
    assert len(_lua_elements()) >= 10 and len(_lua_molecules()) >= 10


def test_elements_mirror_1to1():
    assert _lua_elements() == _py_elements()


def test_molecules_mirror_1to1():
    assert _lua_molecules() == _py_molecules()
