# Multilingual chemistry terms (Sprint 3 · #32 / #33)

MOLGANG teaches chemistry to a global classroom, so a woven concept must be addressable in more
than one language — and rendered correctly in each. This document describes the committed
multilingual dataset and the W3C-correct way its terms are tagged.

## The dataset

`data/chemistry/multilingual_terms.json` (`schema: molgang.multilingual.terms/v1`) holds names for
the chemistry **ground truth** in `src/molgang/chemistry.py` — the 19 first-lesson elements and 30
molecules — in **EN, NL, RU, ZH, AR**. Translations are real reference terms (never synthetic), and
the element/molecule keys stay byte-for-byte in sync with `chemistry.py` (guarded by a test, below).

```jsonc
{
  "languages": [
    {"lang": "en", "name": "English", "dir": "ltr"},
    {"lang": "ar", "name": "العربية", "dir": "rtl"}    // …etc
  ],
  "elements":  { "O":  {"atomic_number": 8, "names": {"en": "Oxygen", "ru": "Кислород", "zh": "氧", "ar": "أكسجين", ...}} },
  "molecules": { "H2O": {"names": {"en": "Water", "ru": "Вода", "zh": "水", "ar": "ماء", ...}} }
}
```

## W3C string meta — `lang` + base-direction (#32)

Every term-node MUST carry two pieces of metadata, per the
[W3C *Strings on the Web: Language and Direction Metadata*](https://www.w3.org/TR/string-meta/) design:

- **`lang`** — a BCP-47 language tag (`en`, `ru`, `zh`, `ar`, …). It is the key under `names`, so the
  language of every string is explicit; there is no "untagged" string in the graph.
- **`dir`** — the **base direction** for display: `ltr` for EN/NL/RU/ZH, `rtl` for AR. Carried in the
  `languages` table and applied per term. Base direction is *not* inferable from the characters alone
  (a string can mix scripts), so it is stored explicitly — this is exactly the bug class W3C string
  meta exists to prevent. The Arabic terms are the project's RTL test case.

When a term-node is woven into the knowledge graph, it is keyed by its **canonical formula/symbol**
(language-independent, e.g. `H2O`, `O`) and carries the per-language `{lang, dir, name}` triples. This
lets the graph shard by language/topic instead of forcing every peer to hold one global, untagged
string table — and lets a client render each label with the correct directionality.

## How it is woven

`scripts/weave_multilingual_terms.py` turns the dataset into alias **links** — one per localized name,
`{subject: name, relation: "name:<lang>", object: <canonical>}` — so `Water` / `Вода` / `水` / `ماء`
all connect to the same `H2O` concept (245 links for the current set). `build_links()` is pure and
unit-tested; running the script emits the ready-to-weave plan, and `--weave` applies it to a live
`World` via `world.weave_links(...)` (requires the knitweb engine). The relation carries the language;
base direction is recovered from the `languages` table above.

## Conformance

`tests/test_multilingual_terms.py` asserts the dataset's element/molecule keys and EN/NL names match
`chemistry.py`, that every term carries all declared languages, and that each language has a valid
`dir`. Run via the normal `pytest -q`. Keep the dataset in sync when `chemistry.py` grows.

## Translating new content — the contributor workflow (#143)

Sprint 3 committed a 4+ language dataset, but the curriculum keeps growing (graded compounds, then
reactions #109 and quests #110). To stop the content graph from drifting ahead of the languages we
support, **every translatable content term must carry a label in each language MOLGANG commits to**,
and a CI gate enforces it. The committed floor is **EN, NL, RU, ZH, AR** (`CORE_LANGUAGES` in
`scripts/check_translations.py`); a source may declare *more*, and then every term in it must cover
those too.

**The gate / the tool.** `scripts/check_translations.py` is the single authority — used by both CI
and contributors:

```bash
python3 scripts/check_translations.py            # gate: exit 1 if any content lacks a required language
python3 scripts/check_translations.py --status    # coverage report (per content source × language)
```

CI runs it through `tests/test_content_translation_gate.py`, so **new content cannot merge while any
term is missing a language**. The gate also proves it has teeth (an adversarial test feeds it a term
with a blank label and asserts the gap is reported).

**To add a new content type (e.g. reactions, quests):**

1. Write its data file under `data/` using the **#32 term-node shape** — a `languages` table plus one
   or more groups of canonical → `{"names": {<lang>: <label>}}`:

   ```jsonc
   {
     "languages": [
       {"lang": "en", "name": "English", "dir": "ltr"},
       {"lang": "ar", "name": "العربية", "dir": "rtl"}   // …ru, zh, nl
     ],
     "reactions": {
       "2H2+O2->2H2O": {"names": {"en": "Combustion of hydrogen", "nl": "…", "ru": "…", "zh": "…", "ar": "…"}}
     }
   }
   ```

2. Register it with **one line** in `CONTENT_SOURCES` in `scripts/check_translations.py`
   (`content_type`, `path`, `groups`). It is now translation-gated automatically — no test changes.
3. Supply **real reference translations only** (machine-assist is fine, but a human verifies; never
   synthetic placeholder text). Run `--status` until coverage is clean, then open the PR.

This keeps the knowledge graph usable for a global, non-English-majority audience as it scales toward
a million concurrent peers.
