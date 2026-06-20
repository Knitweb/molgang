"""Sprint 3 #32/#33 — multilingual chemistry dataset conformance.

`data/chemistry/multilingual_terms.json` must stay faithful to the chemistry ground truth in
`src/molgang/chemistry.py`: same element/molecule keys, same EN/NL names (the languages the code
already ships), every term tagged in all declared languages, and every language carrying a valid base
direction (W3C `dir`). Textual parse of chemistry.py — no knitweb import — so it runs anywhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    data = json.loads((ROOT / "data/chemistry/multilingual_terms.json").read_text(encoding="utf-8"))
    src = (ROOT / "src/molgang/chemistry.py").read_text(encoding="utf-8")

    def block(name: str) -> str:
        return re.search(name + r"[^=]*=\s*\{(.*?)\n\}", src, re.S).group(1)

    elements = {m[0]: (m[1], m[2]) for m in re.findall(
        r'"([A-Za-z]{1,2})":\s*\("([^"]+)",\s*"([^"]+)",\s*\d+\)', block("ELEMENTS"))}
    molecules = {m[0]: (m[1], m[2]) for m in re.findall(
        r'"([A-Za-z0-9]+)":\s*\("([^"]+)",\s*"([^"]+)"\)', block("MOLECULES"))}
    return data, elements, molecules


def test_keys_match_ground_truth():
    data, elements, molecules = _load()
    assert set(data["elements"]) == set(elements), "element keys drifted from chemistry.py"
    assert set(data["molecules"]) == set(molecules), "molecule keys drifted from chemistry.py"


def test_en_nl_names_match_ground_truth():
    data, elements, molecules = _load()
    for k, (en, nl) in elements.items():
        names = data["elements"][k]["names"]
        assert names["en"] == en and names["nl"] == nl, f"element {k} en/nl drift"
    for k, (en, nl) in molecules.items():
        names = data["molecules"][k]["names"]
        assert names["en"] == en and names["nl"] == nl, f"molecule {k} en/nl drift"


def test_every_term_has_all_languages_and_valid_dir():
    data, _, _ = _load()
    langs = {lang["lang"] for lang in data["languages"]}
    for lang in data["languages"]:
        assert lang["dir"] in {"ltr", "rtl"}, f"{lang['lang']}: bad dir {lang['dir']!r}"
    assert {"en", "nl", "ru", "zh", "ar"} <= langs, "expected EN/NL/RU/ZH/AR coverage"
    assert any(l["dir"] == "rtl" for l in data["languages"]), "need an RTL language as the base-direction test case"
    for group in ("elements", "molecules"):
        for key, entry in data[group].items():
            assert langs <= set(entry["names"]), f"{group}/{key} missing languages {langs - set(entry['names'])}"
