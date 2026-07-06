r"""Parse a brainstormed knit into a single **term** or a **link** between terms.

Players type free text. A knit that contains a connector (`=`, `→`/`->`, `is a`, `is`, `:`,
`has`, `contains`, `produces`, …) is a **link** — its two sides are woven as two term-nodes
joined by an edge, so related terms *combine* in the web instead of each becoming an isolated
junk string. The OBJECT side may be a one-to-many list (`X has A, B and C`) which weaves
multiple fibers that share one subject + relation. LaTeX/markup is stripped and unicode
sub/superscripts are folded (`CH₄` → `CH4`) so `(\(V_{2}O_{5}\))`, `V₂O₅` and `V2O5` resolve
to the **same** node, and `V205 = \(V_{2}O_{5}\)` links `V205 → V2O5`.
"""

from __future__ import annotations

import re

# (regex connector, relation label) — order matters: most specific first, so multi-word
# verbs and `is a/an` match before the bare `=`/`is`.
_CONNECTORS: list[tuple[str, str]] = [
    (r"\s*(?:->|=>|→|⇒|⟶)\s*", "yields"),
    (r"\s+is\s+an?\s+", "is-a"),
    (r"\s+is-an?\b\s*", "is-a"),
    (r"\s+(?:contains|consists?\s+of|comprises?|includes?|bevat)\s+", "contains"),
    (r"\s+(?:produces|yields|gives|forms|makes|generates|produceert|maakt)\s+", "produces"),
    (r"\s+(?:has|heeft)\s+", "has"),
    (r"\s*=\s*", "is"),
    (r"\s+(?:is|are|means|equals)\s+", "is"),
    (r"\s*[:≡]\s*", "is"),
]

# unicode subscript digits ₀..₉ (U+2080..U+2089) → '0'..'9'
_SUBS = {ord(c): str(i) for i, c in enumerate("₀₁₂₃₄₅₆₇₈₉")}
# unicode superscript digits ⁰..⁹ — NOT contiguous: ¹²³ are U+00B9/B2/B3, the rest U+2070-block
_SUPS = {
    ord("⁰"): "0", ord("¹"): "1", ord("²"): "2", ord("³"): "3", ord("⁴"): "4",
    ord("⁵"): "5", ord("⁶"): "6", ord("⁷"): "7", ord("⁸"): "8", ord("⁹"): "9",
}
# unicode minus → ASCII hyphen
_DASH = {ord("−"): "-"}

# the warp limit — a single knit may weave at most this many fibers (owner: max 256).
MAX_FIBERS = 256

# split an object list on commas and on the words and/en (Oxford comma supported); never on '+'
# so reaction stoichiometry "2H2 + O2" stays one object.
_LIST_SPLIT = re.compile(r"(?i)\s*,?\s+(?:and|en)\s+|\s*,\s*")


def clean(text: str) -> str:
    r"""Strip LaTeX/markup, fold unicode digits, normalise whitespace.

    `(\(V_{2}O_{5}\))` → `V2O5`, `CH₄` → `CH4`, `V₂O₅` → `V2O5`. Case is preserved
    (chemical formulas are case-significant: Co vs CO)."""
    t = text.strip()
    t = t.translate(_SUBS).translate(_SUPS).translate(_DASH)  # CH₄ -> CH4 (before CID cleanup)
    t = re.sub(r"\\[()\[\]]", "", t)          # \( \) \[ \]
    t = t.replace("$", "")
    t = re.sub(r"[_^]\{([^}]*)\}", r"\1", t)   # X_{2} -> X2,  X^{3} -> X3
    t = re.sub(r"[_^]", "", t)                  # stray _ ^
    t = t.replace("\\", "")                     # stray backslashes
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip("()[]·.,; ").strip()


def _split_objects(obj: str) -> list[str]:
    """Split the OBJECT side of a link into a one-to-many enumeration.

    `H, H and O` → ['H', 'O'] (cleaned, deduped case-insensitively, first-seen order).
    A plain `Y` returns ['Y']. The subject is never split."""
    out: list[str] = []
    seen: set[str] = set()
    for frag in _LIST_SPLIT.split(obj):
        c = clean(frag)
        if not c:
            continue
        key = c.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _link(subject: str, obj: str, rel: str) -> dict:
    return {"kind": "link", "subject": subject, "object": obj,
            "relation": rel, "label": f"{subject} {rel} {obj}"}


# a chemical species: optional stoichiometric coefficient + element groups (V2O5, 2 H2O)
_SPECIES = re.compile(r"^\d*\s*(?:[A-Z][a-z]?\d*)+$")
_ARROW = re.compile(r"\s*(?:->|=>|→|⇒|⟶)\s*")


def _try_reaction(raw: str) -> dict | None:
    """Recognise a REACTION knit: ``2H2 + O2 -> 2H2O @ spark`` (#109).

    A knit is a reaction (not a link) only when it has an arrow AND reaction
    signals — a ``+`` on either side, a stoichiometric coefficient, or an
    ``@ conditions`` tail — and every species parses as a chemical formula.
    Plain ``A -> B`` prose stays a link, so nothing existing changes meaning."""
    body, cond = (raw.split("@", 1) + [""])[:2] if "@" in raw else (raw, "")
    body, cond = body.strip(), clean(cond) or cond.strip()
    m = _ARROW.search(body)
    if not m:
        return None
    lhs, rhs = body[:m.start()], body[m.end():]
    if _ARROW.search(rhs):
        return None                                   # multi-arrow → not a single reaction
    def side(s):
        parts = [clean(x) for x in s.split("+")]
        return [p for p in parts if p]
    reactants, products = side(lhs), side(rhs)
    if not reactants or not products:
        return None
    has_signal = ("+" in body) or ("@" in raw) or any(
        re.match(r"^\d+\s*\S", sp) for sp in reactants + products)
    if not has_signal:
        return None                                   # bare A -> B stays a link
    if not all(_SPECIES.match(sp) for sp in reactants + products):
        return None                                   # prose sides → link/term path
    equation = " + ".join(reactants) + " -> " + " + ".join(products)
    label = equation + (f" @ {cond}" if cond else "")
    return {"kind": "reaction", "equation": equation, "conditions": cond,
            "reactants": reactants, "products": products, "term": label, "label": label}


def parse_knit(text: str) -> dict | list[dict]:
    """Parse a typed knit.

    Returns `{kind:'term'|'link', label, ...}` for a single term or single link (full
    back-compat), or a **list** of link dicts for a one-to-many object enumeration
    (`X has A, B and C` → three link dicts sharing subject + relation)."""
    raw = (text or "").strip()
    reaction = _try_reaction(raw)
    if reaction is not None:
        return reaction
    for pattern, rel in _CONNECTORS:
        m = re.search(pattern, raw)
        if m:
            subject = clean(raw[:m.start()])
            raw_objs = _split_objects(raw[m.end():])
            # drop self-links (subject == object after folding) so "CH₄ is CH4" dedupes to a term
            sub_cf = subject.casefold()
            objs = [o for o in raw_objs if o and o.casefold() != sub_cf]
            if not subject:
                continue
            if not objs:
                # every object equalled the subject after folding → one shared concept.
                # "CH₄ is CH4" → term 'CH4'. Only collapse when there really was an object.
                if raw_objs:
                    return {"kind": "term", "term": subject, "label": subject}
                continue
            if len(objs) > MAX_FIBERS:
                objs = objs[:MAX_FIBERS]            # stay within the warp limit
            if len(objs) == 1:
                return _link(subject, objs[0], rel)
            return [_link(subject, o, rel) for o in objs]
    term = clean(raw) or raw.strip()
    return {"kind": "term", "term": term, "label": term}


def parse_links(text: str) -> list[dict]:
    """Always return a list of link dicts. A bare term → `[]`; a single link → `[link]`;
    a one-to-many knit → all its links; a REACTION line (`O2 + C -> CO2`) expands into
    its reactant→product links (coefficients stripped), so spirals can thread real
    reactions (#109 follow-up). Lets callers handle multi-links uniformly."""
    parsed = parse_knit(text)
    if isinstance(parsed, list):
        return parsed
    if parsed.get("kind") == "link":
        return [parsed]
    if parsed.get("kind") == "reaction":
        strip = lambda s: re.sub(r"^\d+\s*", "", s)
        return [_link(strip(r), strip(pr), "reacts-to")
                for r in parsed["reactants"] for pr in parsed["products"]]
    return []


def spiral_links(lines) -> list[dict]:
    """Parse several brainstormed lines into ordered LINK dicts — the threads of a spiral.

    Each line must yield at least one link (``A = B`` / ``A -> B`` / ``Mg has Cl, O``);
    raises ValueError otherwise. A one-to-many line contributes all its links. Blank lines
    are skipped. (A spider weaves spirals, not chains.)
    """
    out: list[dict] = []
    for ln in lines:
        if not ln or not str(ln).strip():
            continue
        links = parse_links(str(ln))
        if not links:
            raise ValueError(f"a spiral is woven from links — use 'A = B' or 'A -> B': {ln!r}")
        out.extend(links)
    return out
