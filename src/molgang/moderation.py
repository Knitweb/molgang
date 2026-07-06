"""Content moderation for the public, child-facing term channel (#140).

Players propose arbitrary term strings that weave into a public knowledge graph
aimed at children. PoUW slashing handles *wrong chemistry*, not *abusive
content*. This adds the missing safety layer:

  * :func:`screen` — a pure, deterministic pre-weave filter that rejects PII
    (emails, phone/long digit runs) and a conservative profanity/slur denylist,
    returning a machine-checkable reason. No I/O, no network, no wall-clock.
  * :class:`ModerationError` — raised by the propose path when a term is blocked
    BEFORE any silk is spent or anything is woven.

Post-hoc report → takedown (tombstone/redaction against the append-only fabric)
lives on the Bar/World, which import :data:`REDACTED_LABEL` for the redaction
display. The filter is intentionally conservative and auditable — a wordlist +
regexes, not an opaque model — so a false positive is a one-line change and a
teacher can read exactly what is blocked.
"""
from __future__ import annotations

import re

__all__ = ["ModerationError", "screen", "REDACTED_LABEL", "PROFANITY"]

REDACTED_LABEL = "[redacted]"


class ModerationError(ValueError):
    """A proposed term was blocked by the content filter."""


# Conservative denylist — slurs/obvious profanity only. Chemistry terms and the
# protocol vocabulary are never matched (word-boundary, case-insensitive).
PROFANITY: frozenset[str] = frozenset({
    "fuck", "shit", "bitch", "cunt", "asshole", "bastard", "dick", "piss",
    "slut", "whore", "nigger", "faggot", "retard", "kike", "spic", "chink",
    # common Dutch equivalents (the owner/5mart context is NL)
    "kut", "lul", "hoer", "kanker", "tering", "godverdomme", "klootzak",
})

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 7+ digit run (phone numbers, BSNs) — chemistry formulas never carry these
_LONG_DIGITS = re.compile(r"\d{7,}")
_WORD = re.compile(r"[a-z]+")


def screen(text: str) -> "tuple[bool, str]":
    """Return ``(ok, reason)`` for a proposed term.

    ``ok`` is False for PII (email / 7+-digit run) or a denylisted profanity/slur
    token; ``reason`` is a stable machine code (``"pii:email"``, ``"pii:digits"``,
    ``"profanity"``) or ``""`` when clean. Pure and deterministic.
    """
    s = (text or "")
    if _EMAIL.search(s):
        return False, "pii:email"
    if _LONG_DIGITS.search(s):
        return False, "pii:digits"
    tokens = set(_WORD.findall(s.lower()))
    if tokens & PROFANITY:
        return False, "profanity"
    return True, ""
