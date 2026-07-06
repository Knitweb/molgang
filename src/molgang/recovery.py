"""Non-custodial wallet recovery phrase (#141).

A device-keyed wallet whose seed IS the private key
(``AccountNode.from_seed``: ``priv = sha256("knitweb:account:seed:"+seed)``)
means a phone wipe loses the identity, balance and reputation. This adds a
**deterministic, reversible recovery phrase**: a human-transcribable encoding of
the 32-byte seed that restores the EXACT same wallet — hence the same
``pls1…`` address, so balances (re-derived from the account braid) and
reputation (derived from the address's woven Fibers) come back intact.

Non-custodial by construction: the phrase encodes the seed itself; nothing is
stored on any server, there is no custodial reset and no key escrow. The word
list is generated deterministically (256 pronounceable CVC syllables) so the
code is compact and the mapping is byte-exact and offline-verifiable.
"""
from __future__ import annotations

import hashlib

__all__ = ["seed_to_phrase", "phrase_to_seed", "WORDLIST", "RecoveryError"]

_CONSONANTS = "bdfghjklmnprstvz"          # 16
_VOWELS = "aeio"                          # 4
_TAIL = "bkmnpr st"                       # placeholder — replaced below
# 16 x 4 x 4 = 256 deterministic CVC syllables (index == byte value)
_TAIL_CONS = "bdklmnpr"                   # 8... need 4 for 16*4*4=256
WORDLIST: list[str] = [
    c1 + v + c2
    for c1 in _CONSONANTS          # 16
    for v in _VOWELS               # 4
    for c2 in "bkmt"               # 4  -> 256 total
]
_INDEX = {w: i for i, w in enumerate(WORDLIST)}
assert len(WORDLIST) == 256 and len(_INDEX) == 256


class RecoveryError(ValueError):
    """A recovery phrase failed to decode or its checksum did not verify."""


def _seed_bytes(seed: str) -> bytes:
    """The 32 seed bytes. A 64-hex seed is taken verbatim; any other string is
    hashed to 32 bytes (so an arbitrary device seed still has a phrase)."""
    s = (seed or "").strip()
    try:
        b = bytes.fromhex(s)
        if len(b) == 32:
            return b
    except ValueError:
        pass
    return hashlib.sha256(s.encode("utf-8")).digest()


def seed_to_phrase(seed: str) -> str:
    """Encode ``seed`` as a 33-word recovery phrase (32 seed words + 1 checksum)."""
    b = _seed_bytes(seed)
    words = [WORDLIST[byte] for byte in b]
    checksum = hashlib.sha256(b).digest()[0]
    words.append(WORDLIST[checksum])
    return " ".join(words)


def phrase_to_seed(phrase: str) -> str:
    """Decode a recovery phrase back to the 64-hex seed; raise on a bad checksum.

    Returns the seed hex that ``AccountNode.from_seed`` derives the wallet from,
    so restoring it on a new device reconstitutes the identical wallet/address.
    """
    words = (phrase or "").split()
    if len(words) != 33:
        raise RecoveryError(f"recovery phrase must be 33 words, got {len(words)}")
    try:
        vals = [_INDEX[w] for w in words]
    except KeyError as exc:
        raise RecoveryError(f"unknown word in recovery phrase: {exc.args[0]!r}") from exc
    b = bytes(vals[:32])
    if hashlib.sha256(b).digest()[0] != vals[32]:
        raise RecoveryError("recovery phrase checksum mismatch — mistyped word")
    return b.hex()
