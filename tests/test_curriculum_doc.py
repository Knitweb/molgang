"""Sprint 7 #114 — keep docs/CURRICULUM.md faithful to the chemistry ground truth.

The teacher curriculum doc publishes a per-tier roster of elements/molecules. This test re-derives
those rosters from `src/molgang/chemistry.py` (loaded by path, no knitweb) and asserts the doc's
"Tier rosters" table lists EXACTLY those — so the doc cannot silently drift as content grows, and
no tier/topic in the doc lacks a corresponding chemistry.py entry (acceptance criterion #114).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs/CURRICULUM.md").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("molgang_chemistry", ROOT / "src/molgang/chemistry.py")
chem = importlib.util.module_from_spec(spec)
sys.modules["molgang_chemistry"] = chem
spec.loader.exec_module(chem)


def _doc_row(tier: str) -> tuple[set[str], set[str]]:
    """Parse the `| <tier> | `elements…` | `molecules…` |` row into (elements, molecules) sets."""
    m = re.search(rf"^\|\s*{tier}\s*\|(.+?)\|(.+?)\|\s*$", DOC, re.M)
    assert m, f"no roster row for tier {tier!r} in CURRICULUM.md"
    els = set(re.findall(r"`([^`]+)`", m.group(1)))
    mols = set(re.findall(r"`([^`]+)`", m.group(2)))
    return els, mols


def _truth(tier: str) -> tuple[set[str], set[str]]:
    els = {s for s in chem.ELEMENTS if chem.tier_of(s) == tier}
    mols = {m for m in chem.MOLECULES if chem.tier_of(m) == tier}
    return els, mols


def test_every_tier_roster_matches_ground_truth():
    for tier in chem.TIERS:
        doc_els, doc_mols = _doc_row(tier)
        truth_els, truth_mols = _truth(tier)
        assert doc_els == truth_els, f"{tier} elements drift: doc-only={doc_els - truth_els}, missing={truth_els - doc_els}"
        assert doc_mols == truth_mols, f"{tier} molecules drift: doc-only={doc_mols - truth_mols}, missing={truth_mols - doc_mols}"


def test_doc_covers_all_tiers_and_nothing_extra():
    rows = set(re.findall(r"^\|\s*(elementary|middle|high)\s*\|", DOC, re.M))
    assert rows == set(chem.TIERS)


def test_no_token_or_nft_value_is_promised():
    # the doc must state the reputation-only / no-NFT framing (acceptance #114)
    low = DOC.lower()
    assert "no tokens, no nfts" in low or ("no nft" in low and "reputation" in low)
