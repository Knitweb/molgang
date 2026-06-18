r"""Parse a brainstormed knit into a single **term** or a **link** between terms.

Players type free text. A knit that contains a connector (`=`, `→`/`->`, `is a`, `is`, `:`)
is a **link** — its two sides are woven as two term-nodes joined by an edge, so related
terms *combine* in the web instead of each becoming an isolated junk string. LaTeX/markup is
stripped so `(\(V_{2}O_{5}\))` and `V2O5` resolve to the **same** node, and
`V205 = \(V_{2}O_{5}\)` links `V205 → V2O5`.
"""

from __future__ import annotations

import re

# (regex connector, relation label) — order matters: most specific first.
_CONNECTORS: list[tuple[str, str]] = [
    (r"\s*(?:->|=>|→|⇒|⟶)\s*", "yields"),
    (r"\s*=\s*", "is"),
    (r"\s+is\s+an?\s+", "is-a"),
    (r"\s+(?:is|are|means|equals)\s+", "is"),
    (r"\s*[:≡]\s*", "is"),
]


def clean(text: str) -> str:
    """Strip LaTeX/markup and normalise whitespace. `(\\(V_{2}O_{5}\\))` → `V2O5`."""
    t = text.strip()
    t = re.sub(r"\\[()\[\]]", "", t)          # \( \) \[ \]
    t = t.replace("$", "")
    t = re.sub(r"[_^]\{([^}]*)\}", r"\1", t)   # X_{2} -> X2,  X^{3} -> X3
    t = re.sub(r"[_^]", "", t)                  # stray _ ^
    t = t.replace("\\", "")                     # stray backslashes
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip("()[]·.,; ").strip()


def parse_knit(text: str) -> dict:
    """Return `{kind:'term'|'link', label, ...}` for a typed knit."""
    raw = (text or "").strip()
    for pattern, rel in _CONNECTORS:
        m = re.search(pattern, raw)
        if m:
            subject, obj = clean(raw[:m.start()]), clean(raw[m.end():])
            if subject and obj and subject.casefold() != obj.casefold():
                return {"kind": "link", "subject": subject, "object": obj,
                        "relation": rel, "label": f"{subject} {rel} {obj}"}
    term = clean(raw) or raw.strip()
    return {"kind": "term", "term": term, "label": term}


def spiral_links(lines) -> list[dict]:
    """Parse several brainstormed lines into ordered LINK dicts — the threads of a spiral.

    Each line must be a link (``A = B`` / ``A -> B``); raises ValueError otherwise. Blank
    lines are skipped. (A spider weaves spirals, not chains.)
    """
    out: list[dict] = []
    for ln in lines:
        if not ln or not str(ln).strip():
            continue
        parsed = parse_knit(str(ln))
        if parsed.get("kind") != "link":
            raise ValueError(f"a spiral is woven from links — use 'A = B' or 'A -> B': {ln!r}")
        out.append(parsed)
    return out
