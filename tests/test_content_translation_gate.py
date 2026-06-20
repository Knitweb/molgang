"""Sprint 7 #143 (gap G6) — CI enforcement of the content-translation gate.

This is the test that makes 'new content cannot merge without all required-language labels' real:
it runs `scripts/check_translations.py`'s pure `find_gaps()` over every registered content source
and fails if any term is missing a language. Because the checker reads its sources from
`CONTENT_SOURCES`, new content (reactions/quests in Sprint 7) inherits this gate the moment it is
registered — no test changes needed. Pure (no knitweb), so it runs anywhere `pytest` runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_translations", ROOT / "scripts/check_translations.py")
check_translations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_translations)


def test_every_registered_content_term_is_fully_translated():
    gaps = check_translations.find_gaps()
    assert gaps == [], "content missing required-language labels: " + "; ".join(
        f"{g['content_type']}/{g['group']}/{g['key']}→{g['missing']}" for g in gaps)


def test_core_languages_floor_is_enforced():
    # The gate must require at least the project's committed language set, so a source can't
    # quietly ship fewer languages than promised.
    assert {"en", "nl", "ru", "zh", "ar"} <= check_translations.CORE_LANGUAGES


def test_gate_catches_a_missing_translation():
    # Adversarial: a synthetic source with a blank label MUST be reported as a gap, proving the
    # gate has teeth (and isn't vacuously passing). Uses an inline source, not a committed file.
    fake = [{"content_type": "test", "path": "data/chemistry/multilingual_terms.json",
             "groups": ["__does_not_exist__"]}]
    # real source, non-existent group → no terms → no gaps (sanity: gate doesn't false-positive)
    assert check_translations.find_gaps(fake) == []

    # Now prove a genuinely missing language is caught via a temp file written in the test dir.
    import json, tempfile, os
    payload = {
        "languages": [{"lang": l, "name": l, "dir": "rtl" if l == "ar" else "ltr"}
                      for l in ("en", "nl", "ru", "zh", "ar")],
        "things": {"X1": {"names": {"en": "Ex", "nl": "Ex", "ru": "Ex", "zh": "Ex"}}},  # missing ar
    }
    with tempfile.TemporaryDirectory() as d:
        rel = "frag.json"
        (Path(d) / rel).write_text(json.dumps(payload), encoding="utf-8")
        gaps = check_translations.find_gaps(
            [{"content_type": "test", "path": rel, "groups": ["things"]}], root=Path(d))
    assert gaps and gaps[0]["missing"] == ["ar"]
