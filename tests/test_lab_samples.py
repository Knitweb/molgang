"""The analytical lab (web/lab-analyze.html) depends on web/data/lab-samples.json.

Guards the reference data so a bad edit fails CI, not the browser:
  - every sample composition uses only element symbols MOLGANG knows (or the
    'other' balance placeholder), with positive wt% summing to <= 100;
  - every emission-line entry is a real symbol with lines in the ICP-OES range;
  - XRF detectability is set for the low-Z elements a handheld gun cannot see.
"""

import json
from pathlib import Path

import pytest

from molgang.chemistry import ELEMENTS

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "web" / "data" / "lab-samples.json").read_text(encoding="utf-8"))

ALLOWED = set(ELEMENTS)
# 'other' is a documented non-element balance placeholder (Ni/Mo/Sn/… outside
# MOLGANG's element set); permitted in a sample composition, never a real line.
BALANCE = "other"
# Low-Z elements a handheld XRF cannot quantify (spectroscopist-verified list).
XRF_BLIND = {"H", "He", "Li", "B", "C", "N", "O", "F", "Ne", "Na", "Mg"}


def test_has_samples_and_lines():
    assert len(DATA["samples"]) >= 6
    assert set(DATA["lines"]) == ALLOWED  # a line entry for every known element


@pytest.mark.parametrize("s", DATA["samples"], ids=[s["id"] for s in DATA["samples"]])
def test_sample_composition_valid(s):
    total = 0.0
    for c in s["composition"]:
        sym = c["symbol"]
        assert sym == BALANCE or sym in ALLOWED, f"{s['id']}: unknown symbol {sym!r}"
        assert c["wt_pct"] > 0, f"{s['id']}: {sym} wt% must be positive"
        total += c["wt_pct"]
    assert total <= 100.01, f"{s['id']}: composition sums to {total} > 100"
    assert s["name"] and s["matrix"] and s["note"]


def test_emission_lines_in_range_and_real_symbols():
    for sym, info in DATA["lines"].items():
        assert sym in ALLOWED, f"line for unknown symbol {sym!r}"
        assert info["nm"], f"{sym}: no emission line"
        for nm in info["nm"]:
            assert 120.0 <= nm <= 800.0, f"{sym}: line {nm} nm outside ICP-OES range"
        assert isinstance(info["xrf"], bool)


def test_xrf_blindness_is_physically_correct():
    # Every low-Z element must be marked XRF-undetectable, and none of the
    # heavier analytical elements should be.
    assert set(DATA["xrf_undetectable"]) == XRF_BLIND
    for sym in XRF_BLIND:
        assert DATA["lines"][sym]["xrf"] is False, f"{sym} should be XRF-blind"
    # A representative heavy element the gun *can* see.
    for sym in ("Fe", "Cr", "V", "Cu", "Zn", "Pb", "Ca"):
        assert DATA["lines"][sym]["xrf"] is True, f"{sym} should be XRF-detectable"


def test_xrf_detectable_sample_exists_for_metals():
    # Steel/ferroalloy samples must contain at least one XRF-detectable element,
    # else the gun readout would be empty for a metal (a UX regression).
    for s in DATA["samples"]:
        if "metal" in s["matrix"].lower():
            seen = [c for c in s["composition"]
                    if c["symbol"] in ALLOWED and DATA["lines"].get(c["symbol"], {}).get("xrf")]
            assert seen, f"{s['id']}: metal sample has no XRF-detectable element"
