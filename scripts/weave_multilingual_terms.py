#!/usr/bin/env python3
"""Sprint 3 #33 — weave the multilingual chemistry dataset into the fabric.

Turns `data/chemistry/multilingual_terms.json` into knit **links** that alias every localized name
to its canonical formula/symbol, so `Water` / `Вода` / `水` / `ماء` all connect to the same `H2O`
concept in the woven knowledge graph. The link relation carries the language (`name:<lang>`); base
direction is recoverable from the dataset's `languages` table (see docs/MULTILINGUAL.md, #32).

`build_links()` is a pure function (no knitweb) and is unit-tested. By default this script EMITS the
ready-to-weave plan to `data/chemistry/multilingual_links.json` and prints a summary; pass `--weave`
to apply it to a live `World` (requires the knitweb engine).

    python3 scripts/weave_multilingual_terms.py            # emit the link plan + summary
    python3 scripts/weave_multilingual_terms.py --weave    # also weave into the local fabric
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data/chemistry/multilingual_terms.json"
PLAN_OUT = ROOT / "data/chemistry/multilingual_links.json"


def build_links(data: dict) -> list[dict]:
    """Pure: dataset -> [{subject, relation, object}] alias links (localized name -> canonical)."""
    langs = {l["lang"] for l in data["languages"]}
    links: list[dict] = []
    for group in ("elements", "molecules"):
        for canonical, entry in data[group].items():
            for lang, name in entry["names"].items():
                if lang not in langs or not name or name == canonical:
                    continue
                links.append({"subject": name, "relation": f"name:{lang}", "object": canonical})
    return links


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weave", action="store_true", help="apply the links to a live World (needs knitweb)")
    ap.add_argument("--world", default=None, help="World save path (with --weave)")
    args = ap.parse_args()

    data = json.loads(DATASET.read_text(encoding="utf-8"))
    links = build_links(data)
    PLAN_OUT.write_text(json.dumps({"schema": "molgang.multilingual.links/v1", "links": links},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    langs = ",".join(l["lang"] for l in data["languages"])
    print(f"[plan] {len(links)} alias links ({len(data['elements'])} elements + "
          f"{len(data['molecules'])} molecules x langs {langs}) -> {PLAN_OUT}")

    if args.weave:
        try:
            from molgang.world import World
        except Exception as e:  # knitweb engine absent
            print(f"[weave] skipped — World/knitweb unavailable ({e}). Plan was still written.")
            return 0
        world = World(args.world)
        world.weave_links(links, by="seed:multilingual", fiber_cid="seed-multilingual", confirmations=3)
        ne, _ = world.size()
        print(f"[weave] wove {len(links)} multilingual alias links into the fabric (web nodes now {ne}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
