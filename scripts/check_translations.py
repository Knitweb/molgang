#!/usr/bin/env python3
"""Sprint 7 #143 (gap G6) — the content-translation gate.

MOLGANG teaches a global classroom, so every piece of woven CONTENT (chemistry terms today;
reactions and quests as Sprint 7 grows) must carry a label in each language the project commits to.
This is the single authority for that rule — used both by CI (via the conformance test) and by
contributors locally:

    python3 scripts/check_translations.py            # gate: exit 1 if any content lacks a required language
    python3 scripts/check_translations.py --status    # coverage report (per content source + language)

A content source is one JSON file using the #32 term-node shape — a `languages` table (each
`{lang, dir}`) plus one or more groups of `{<canonical key>: {"names": {<lang>: <label>}}}`.
To bring NEW content under the gate, drop its file in `data/` with that shape and add one entry to
`CONTENT_SOURCES` below; it is then translation-gated automatically. No synthetic data — real
reference translations only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The languages MOLGANG commits to for all content. A source may declare MORE (and then every term
# in that source must cover them too), but never fewer than this floor.
CORE_LANGUAGES: frozenset[str] = frozenset({"en", "nl", "ru", "zh", "ar"})

# Registry of translatable content sources. One line per content file. As Sprint 7 adds reactions
# (#109) and quests (#110), add their dataset here and they inherit the gate for free.
CONTENT_SOURCES: list[dict] = [
    {"content_type": "chemistry", "path": "data/chemistry/multilingual_terms.json",
     "groups": ["elements", "molecules"]},
]


def declared_languages(data: dict) -> set[str]:
    """The languages a source's `languages` table declares (each must carry a valid base dir)."""
    langs: set[str] = set()
    for entry in data.get("languages", []):
        if entry.get("dir") not in {"ltr", "rtl"}:
            raise ValueError(f"language {entry.get('lang')!r} has invalid dir {entry.get('dir')!r}")
        langs.add(entry["lang"])
    return langs


def find_gaps(sources: list[dict] | None = None, root: Path = ROOT) -> list[dict]:
    """Pure: return one gap record per content term missing a required-language label.

    A gap is ``{content_type, group, key, missing}`` where ``missing`` is the sorted list of
    required languages whose label is absent or blank. ``missing == []`` is never returned.
    """
    sources = CONTENT_SOURCES if sources is None else sources
    gaps: list[dict] = []
    for src in sources:
        path = root / src["path"]
        data = json.loads(path.read_text(encoding="utf-8"))
        declared = declared_languages(data)
        missing_floor = CORE_LANGUAGES - declared
        if missing_floor:
            gaps.append({"content_type": src["content_type"], "group": "(source)",
                         "key": src["path"], "missing": sorted(missing_floor)})
        required = declared | CORE_LANGUAGES
        for group in src["groups"]:
            for key, entry in data.get(group, {}).items():
                names = entry.get("names", {})
                missing = sorted(lang for lang in required if not (names.get(lang) or "").strip())
                if missing:
                    gaps.append({"content_type": src["content_type"], "group": group,
                                 "key": key, "missing": missing})
    return gaps


def _status(root: Path = ROOT) -> int:
    for src in CONTENT_SOURCES:
        data = json.loads((root / src["path"]).read_text(encoding="utf-8"))
        declared = sorted(declared_languages(data))
        n = sum(len(data.get(g, {})) for g in src["groups"])
        print(f"{src['content_type']}: {n} terms across {src['groups']} × langs {declared}")
    gaps = find_gaps(root=root)
    if gaps:
        print(f"\n⚠ {len(gaps)} translation gap(s):")
        for g in gaps:
            print(f"  - {g['content_type']}/{g['group']}/{g['key']} missing {g['missing']}")
    else:
        print("\n✓ every content term carries all required-language labels")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="MOLGANG content-translation gate (#143)")
    ap.add_argument("--status", action="store_true", help="print a coverage report instead of gating")
    args = ap.parse_args()
    if args.status:
        return _status()
    gaps = find_gaps()
    if gaps:
        print(f"FAIL: {len(gaps)} content term(s) missing required-language labels:")
        for g in gaps:
            print(f"  - {g['content_type']}/{g['group']}/{g['key']} missing {g['missing']}")
        print("\nAdd the missing translations (real reference terms only) and re-run. "
              "See docs/MULTILINGUAL.md → 'Translating new content'.")
        return 1
    print(f"PASS: all content terms carry every required language ({sorted(CORE_LANGUAGES)}+).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
