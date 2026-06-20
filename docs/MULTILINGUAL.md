# Multilingual chemistry terms (Sprint 3 · #32 / #33)

MOLGANG teaches chemistry to a global classroom, so a woven concept must be addressable in more
than one language — and rendered correctly in each. This document describes the committed
multilingual dataset and the W3C-correct way its terms are tagged.

## The dataset

`data/chemistry/multilingual_terms.json` (`schema: molgang.multilingual.terms/v1`) holds names for
the chemistry **ground truth** in `src/molgang/chemistry.py` — the 10 first-lesson elements and 10
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
all connect to the same `H2O` concept (100 links for the current set). `build_links()` is pure and
unit-tested; running the script emits the ready-to-weave plan, and `--weave` applies it to a live
`World` via `world.weave_links(...)` (requires the knitweb engine). The relation carries the language;
base direction is recovered from the `languages` table above.

## Conformance

`tests/test_multilingual_terms.py` asserts the dataset's element/molecule keys and EN/NL names match
`chemistry.py`, that every term carries all declared languages, and that each language has a valid
`dir`. Run via the normal `pytest -q`. Keep the dataset in sync when `chemistry.py` grows.
