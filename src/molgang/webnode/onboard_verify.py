"""Stateless, signature-GATED wallet-QR node onboarding for the in-tab Knitweb peer.

This is the peer-to-peer, server-free replacement for the central PHP ``Onboard.php``
challenge-response (``php/src/Onboard.php``): a new node proves possession of its
secp256k1 wallet key by *signing a fresh challenge*, and the admitting peer **verifies
that signature before it opens any DataChannel or admits the peer**. There is no code
path here that admits a node without a valid wallet signature.

It mirrors the exact crypto + pre-image discipline of :mod:`molgang.relay_sync`:

* identity / signing = ``knitweb.core.crypto`` -- secp256k1 ECDSA over SHA-256, 33-byte
  compressed pubkey hex, DER signature hex.
* the signed pre-image is a *fixed, domain-tagged, newline-joined byte string* -- exactly
  as ``relay_sync.signed_preimage`` builds ``"knitweb-relay:v1\n{to}\n{topic}\n{body}"``.
  Here the tag is ``"knitweb-onboard:v1"`` and the joined fields are the challenge's
  ``(scope, audience, nonce, issued, expires, device)`` so a captured signature can be
  replayed neither onto another peer (audience-bound) nor after expiry (window-bound) nor
  twice (nonce burned).

SACRED INVARIANTS honoured here:

* (a) INTEGER-ONLY -- every freshness / expiry / window comparison is integer second
  arithmetic (``//`` only, never ``/``/``round``/``float``); ``issued``/``expires`` are
  ``int``.
* (b) NO wall-clock and NO randomness on the decision path -- the verifier takes the
  current time as an *injected integer* ``now_s`` and the nonce as *injected bytes*; it
  never calls ``time.time()`` or ``os.urandom`` itself. (The challenge *issuer* is given
  injectable ``now_s`` + ``nonce`` seams too, so a test/Pyodide build feeds a monotonic
  integer clock and a WebCrypto CSPRNG nonce -- never ``Math.random``.)
* (c) BYTE-IDENTITY -- the pre-image is built byte-for-byte identically to the JS encoder
  in ``serverless/web/onboard.js`` (``onboardPreimage``), so a challenge signed in the
  browser verifies here and vice-versa. The crypto bytes come from the unchanged
  ``knitweb.core.crypto`` Python.

The challenge is **stateless to issue** (no row needed) and **single-use to accept**:
the verifier records the burned nonce in a caller-supplied :class:`SeenNonces` set so a
replay of an already-accepted challenge is rejected. State is the caller's (e.g. an
IndexedDB-backed set in the worker); this module stays pure.

NEVER say "loom" -- this is the Knitweb; a node onboards onto the Web.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from knitweb.core import crypto

__all__ = [
    "ONBOARD_PREIMAGE_TAG",
    "ONBOARD_SCHEME",
    "DEFAULT_TTL_S",
    "MAX_TTL_S",
    "NONCE_HEX_LEN",
    "OnboardError",
    "OnboardChallenge",
    "OnboardProof",
    "SeenNonces",
    "InMemorySeenNonces",
    "onboard_preimage",
    "issue_challenge",
    "sign_challenge",
    "build_qr_uri",
    "parse_qr_uri",
    "verify_onboarding",
]

# Pre-image tag -- must byte-match ``ONBOARD_PREIMAGE_TAG`` in serverless/web/onboard.js.
# Versioned so the signed-field layout can soft-fork without colliding with v1 signatures.
ONBOARD_PREIMAGE_TAG = "knitweb-onboard:v1"

# The signature scheme the challenge commits to (matches crypto.SCHEME_SECP256K1_ECDSA /
# the "pls1" scheme-0 address). A QR carrying any other scheme is rejected.
ONBOARD_SCHEME = "secp256k1-ecdsa-sha256"

# Freshness window, in WHOLE SECONDS (integer). A challenge is valid for ``[issued, expires)``
# with ``expires = issued + ttl_s``. Default 10 minutes mirrors Onboard.php's CHALLENGE_TTL_S;
# MAX_TTL_S is a hard ceiling so a forged/over-long window can never widen the replay surface.
DEFAULT_TTL_S = 600
MAX_TTL_S = 3600

# Challenge nonces are random bytes rendered as lowercase hex. 18 bytes == 36 hex chars,
# matching Onboard.php's NONCE_BYTES; we require an exact length so a degenerate/empty nonce
# (a predictable-nonce footgun) is rejected at parse time.
NONCE_BYTES = 18
NONCE_HEX_LEN = NONCE_BYTES * 2


class OnboardError(ValueError):
    """Raised when an onboarding challenge/proof is malformed, unsigned, expired or replayed."""


# ---------------------------------------------------------------------------
# Anti-replay seen-nonce store (caller owns the state; this module stays pure)
# ---------------------------------------------------------------------------

class SeenNonces(Protocol):
    """The minimal interface the verifier needs to burn a one-time challenge nonce.

    The caller supplies the backing store (e.g. an IndexedDB object store in the Pyodide
    worker, or a process-local set). The verifier only ever *checks then adds* -- it never
    iterates or trusts wall-clock for expiry; stale nonces age out naturally because an
    expired challenge is rejected on the freshness check before the nonce is even consulted.
    """

    def __contains__(self, nonce: str) -> bool: ...

    def add(self, nonce: str) -> None: ...


class InMemorySeenNonces:
    """A trivial process-local :class:`SeenNonces`. Tests and single-tab runs use this."""

    def __init__(self, initial: Iterable[str] | None = None) -> None:
        self._seen: set[str] = set(initial or ())

    def __contains__(self, nonce: str) -> bool:
        return nonce in self._seen

    def add(self, nonce: str) -> None:
        self._seen.add(nonce)

    def __len__(self) -> int:
        return len(self._seen)


# ---------------------------------------------------------------------------
# The challenge + proof records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OnboardChallenge:
    """A fresh, time-boxed onboarding challenge a new node must sign to be admitted.

    All time fields are WHOLE SECONDS (integer). ``audience`` is the compressed-pubkey hex
    of the *admitting* peer (or ``""`` for an open challenge that any peer may verify); it
    binds the signature to one verifier so a captured proof can't be replayed at a third
    peer. ``device`` is the new node's own device fingerprint (its ``DEVICE_ID``), folded
    into the pre-image so the signature also attests which device is onboarding.
    """

    scope: str          # logical namespace, e.g. "molgang:classroom:default"
    audience: str       # admitting peer's 33-byte compressed pubkey hex, or "" (open)
    nonce: str          # NONCE_HEX_LEN lowercase-hex chars; single-use
    issued: int         # integer seconds (injected clock at issue time)
    expires: int        # integer seconds; == issued + ttl_s
    device: str         # onboarding node's device fingerprint (DEVICE_ID)
    scheme: str = ONBOARD_SCHEME

    def to_record(self) -> dict:
        """Canonical dict form (stable key set) for QR/JSON transport."""
        return {
            "scope": self.scope,
            "audience": self.audience,
            "nonce": self.nonce,
            "issued": self.issued,
            "expires": self.expires,
            "device": self.device,
            "scheme": self.scheme,
        }

    @classmethod
    def from_record(cls, rec: dict) -> "OnboardChallenge":
        """Parse a challenge record, rejecting any malformed/missing/typed-wrong field."""
        if not isinstance(rec, dict):
            raise OnboardError("challenge must be a map")
        scheme = _req_str(rec, "scheme")
        if scheme != ONBOARD_SCHEME:
            raise OnboardError(f"unsupported onboarding scheme: {scheme!r}")
        nonce = _req_str(rec, "nonce")
        if len(nonce) != NONCE_HEX_LEN or not crypto.is_valid_hex(nonce, NONCE_BYTES):
            raise OnboardError("nonce must be a fixed-length lowercase-hex string")
        if nonce != nonce.lower():
            raise OnboardError("nonce must be lowercase hex (byte-identity with the signer)")
        audience = _req_str(rec, "audience")
        if audience != "" and not _is_compressed_pubkey(audience):
            raise OnboardError("audience must be a 33-byte compressed pubkey hex or empty")
        issued = _req_int(rec, "issued")
        expires = _req_int(rec, "expires")
        if issued < 0 or expires < 0:
            raise OnboardError("issued/expires must be non-negative integer seconds")
        if expires <= issued:
            raise OnboardError("expires must be strictly after issued")
        if expires - issued > MAX_TTL_S:
            raise OnboardError("challenge window exceeds MAX_TTL_S")
        return cls(
            scope=_req_str(rec, "scope"),
            audience=audience,
            nonce=nonce,
            issued=issued,
            expires=expires,
            device=_req_str(rec, "device"),
            scheme=scheme,
        )


@dataclass(frozen=True)
class OnboardProof:
    """A new node's signed answer to a challenge: ``{pubkey, sig, challenge}``.

    ``pubkey`` is the onboarding node's 33-byte compressed pubkey hex; ``sig`` is the DER
    signature hex over :func:`onboard_preimage` of ``challenge``. Admission requires this
    to verify -- there is no unsigned path.
    """

    pubkey: str
    sig: str
    challenge: OnboardChallenge

    def to_record(self) -> dict:
        return {
            "pubkey": self.pubkey,
            "sig": self.sig,
            "challenge": self.challenge.to_record(),
        }

    @classmethod
    def from_record(cls, rec: dict) -> "OnboardProof":
        if not isinstance(rec, dict):
            raise OnboardError("proof must be a map")
        pubkey = _req_str(rec, "pubkey")
        if not _is_compressed_pubkey(pubkey):
            raise OnboardError("pubkey must be a 33-byte compressed secp256k1 hex")
        sig = _req_str(rec, "sig")
        if not crypto.is_valid_hex(sig) or len(sig) == 0:
            raise OnboardError("sig must be non-empty DER-encoded hex")
        ch = OnboardChallenge.from_record(rec.get("challenge"))
        return cls(pubkey=pubkey, sig=sig, challenge=ch)


# ---------------------------------------------------------------------------
# The signed pre-image (byte-identical to onboard.js `onboardPreimage`)
# ---------------------------------------------------------------------------

def onboard_preimage(ch: OnboardChallenge) -> bytes:
    """The EXACT bytes a node signs to answer a challenge -- recompute identically on verify.

    Layout (mirrors ``relay_sync.signed_preimage``'s tag + newline-joined fields):

        "knitweb-onboard:v1\n{scope}\n{audience}\n{nonce}\n{issued}\n{expires}\n{device}"

    encoded as UTF-8. ``issued``/``expires`` are rendered as base-10 integers (``str(int)``)
    so there is exactly one byte-string per challenge -- no float, no locale, no padding --
    and the JS encoder produces the same bytes (it formats the same integers with no
    separators). The pubkey is NOT in the pre-image: it is the verifying key itself, exactly
    as ``from`` is omitted from the relay pre-image.
    """
    parts = (
        ONBOARD_PREIMAGE_TAG,
        ch.scope,
        ch.audience,
        ch.nonce,
        str(int(ch.issued)),
        str(int(ch.expires)),
        ch.device,
    )
    return "\n".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Issuing (issuer side) -- injectable integer clock + injected nonce bytes
# ---------------------------------------------------------------------------

def issue_challenge(
    *,
    scope: str,
    device: str,
    now_s: int,
    nonce_bytes: bytes,
    audience: str = "",
    ttl_s: int = DEFAULT_TTL_S,
) -> OnboardChallenge:
    """Mint a fresh challenge for ``device`` onboarding into ``scope``.

    ``now_s`` is the current time as an INJECTED integer (seconds) -- this function never
    reads a wall-clock. ``nonce_bytes`` is INJECTED random bytes (the worker passes
    WebCrypto ``getRandomValues``; CPython passes ``secrets.token_bytes`` at the edge,
    never inside a decision path) and must be exactly :data:`NONCE_BYTES` long so the nonce
    is unpredictable and fixed-width. ``audience`` (an admitting peer's compressed pubkey
    hex) binds the eventual signature to one verifier; leave it ``""`` for an open challenge.
    """
    if not isinstance(now_s, int) or isinstance(now_s, bool):
        raise OnboardError("now_s must be an integer (injected clock)")
    if now_s < 0:
        raise OnboardError("now_s must be non-negative")
    if not isinstance(ttl_s, int) or isinstance(ttl_s, bool) or ttl_s <= 0:
        raise OnboardError("ttl_s must be a positive integer")
    if ttl_s > MAX_TTL_S:
        raise OnboardError(f"ttl_s exceeds MAX_TTL_S={MAX_TTL_S}")
    if not isinstance(nonce_bytes, (bytes, bytearray)) or len(nonce_bytes) != NONCE_BYTES:
        raise OnboardError(f"nonce_bytes must be exactly {NONCE_BYTES} bytes")
    if audience != "" and not _is_compressed_pubkey(audience):
        raise OnboardError("audience must be a 33-byte compressed pubkey hex or empty")
    return OnboardChallenge(
        scope=scope,
        audience=audience,
        nonce=bytes(nonce_bytes).hex(),
        issued=now_s,
        expires=now_s + ttl_s,
        device=device,
    )


def sign_challenge(priv_hex: str, ch: OnboardChallenge) -> OnboardProof:
    """Sign a challenge with the onboarding node's wallet key, producing an :class:`OnboardProof`.

    Pure crypto (``knitweb.core.crypto.sign`` over :func:`onboard_preimage`) -- no clock, no
    randomness beyond ECDSA's internal nonce, which ``cryptography`` derives deterministically
    per RFC 6979 so the signed bytes are reproducible for golden-vector conformance.
    """
    pub = crypto.public_from_private(priv_hex)
    sig = crypto.sign(priv_hex, onboard_preimage(ch))
    return OnboardProof(pubkey=pub, sig=sig, challenge=ch)


# ---------------------------------------------------------------------------
# QR / deep-link URI (compact, byte-stable) -- matches onboard.js build/parse
# ---------------------------------------------------------------------------

_QR_SCHEME = "knitweb"
_QR_PATH = "onboard"
# Ordered field list for the QR query string. Order is FIXED so the URI is byte-stable and
# the JS builder/parser agree; parsing is order-independent (we read keys by name).
_QR_FIELDS = ("scope", "audience", "nonce", "issued", "expires", "device", "scheme")


def build_qr_uri(ch: OnboardChallenge, *, multiaddr: str = "") -> str:
    """Encode a challenge as a compact ``knitweb://onboard?...`` deep link for a QR/link.

    ``multiaddr`` is the issuer's reflexive/relay address a scanner dials AFTER verifying
    the signature (it is transport routing only, never part of the signed pre-image). The
    field order is fixed so the same challenge always renders the same URI bytes.
    """
    from urllib.parse import quote

    rec = ch.to_record()
    pairs = [f"{k}={quote(str(rec[k]), safe='')}" for k in _QR_FIELDS]
    if multiaddr:
        pairs.append(f"multiaddr={quote(multiaddr, safe='')}")
    return f"{_QR_SCHEME}://{_QR_PATH}?" + "&".join(pairs)


def parse_qr_uri(uri: str) -> tuple[OnboardChallenge, str]:
    """Parse a ``knitweb://onboard?...`` deep link back into ``(challenge, multiaddr)``.

    Rejects a wrong scheme/path or any malformed challenge field (delegating to
    :meth:`OnboardChallenge.from_record`). ``multiaddr`` is returned separately and is
    untrusted routing metadata -- it is never folded into the signed pre-image.
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(uri)
    if parsed.scheme != _QR_SCHEME or parsed.netloc != _QR_PATH:
        raise OnboardError("not a knitweb://onboard QR/deep-link")
    q = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)

    def one(key: str, *, required: bool = True) -> str:
        vals = q.get(key)
        if not vals:
            if required:
                raise OnboardError(f"QR missing field: {key}")
            return ""
        if len(vals) != 1:
            raise OnboardError(f"QR has duplicate field: {key}")
        return vals[0]

    rec = {
        "scope": one("scope"),
        "audience": one("audience", required=False),
        "nonce": one("nonce"),
        "issued": _to_int(one("issued")),
        "expires": _to_int(one("expires")),
        "device": one("device"),
        "scheme": one("scheme"),
    }
    ch = OnboardChallenge.from_record(rec)
    return ch, one("multiaddr", required=False)


# ---------------------------------------------------------------------------
# THE GATE: verify a node's signed onboarding before admitting it
# ---------------------------------------------------------------------------

def verify_onboarding(
    proof: OnboardProof | dict,
    *,
    now_s: int,
    expected_scope: str,
    seen: SeenNonces,
    local_pubkey: str | None = None,
) -> str:
    """Authenticate a node's onboarding and return its admitted compressed-pubkey hex.

    This is the ONLY admission path. It rejects anything **unsigned, malformed, scope-
    mismatched, audience-mismatched, expired, future-dated, or replayed**, and only on a
    valid wallet signature does it burn the nonce and return the admitted pubkey. The caller
    opens the DataChannel / admits the peer **iff this returns** (it raises otherwise), and
    stamps the returned pubkey as the verified ``ENVELOPE_PEER_KEY`` for the reputation gate.

    Parameters
    ----------
    proof:
        An :class:`OnboardProof` or its record form (``{pubkey, sig, challenge}``).
    now_s:
        Current time as an INJECTED integer (seconds). No wall-clock is read here.
    expected_scope:
        The scope this verifier admits into; a challenge for any other scope is rejected
        (defence-in-depth so a signature can't be replayed across classrooms).
    seen:
        The caller's one-time-nonce store. A nonce already present => replay => rejected.
        On success the nonce is added so the SAME challenge can never be admitted twice.
    local_pubkey:
        This verifier's own compressed-pubkey hex. If given and the challenge's ``audience``
        is non-empty, it MUST equal ``audience`` (the proof was issued for this peer); an
        open challenge (``audience == ""``) is accepted by any verifier.

    Returns
    -------
    str
        The admitted node's 33-byte compressed pubkey hex.

    Raises
    ------
    OnboardError
        On any failure. A raise means NO admission -- full stop.
    """
    if not isinstance(now_s, int) or isinstance(now_s, bool):
        raise OnboardError("now_s must be an integer (injected clock)")

    pr = proof if isinstance(proof, OnboardProof) else OnboardProof.from_record(proof)
    ch = pr.challenge

    # 1) scope binding -- only admit into the scope this verifier serves.
    if ch.scope != expected_scope:
        raise OnboardError("challenge scope does not match this peer's scope")

    # 2) audience binding -- if the challenge names a verifier, it must be us.
    if ch.audience != "":
        if local_pubkey is None:
            raise OnboardError("audience-bound challenge but no local pubkey to match")
        if ch.audience != local_pubkey:
            raise OnboardError("challenge audience is a different peer")

    # 3) freshness -- integer-second window, no wall-clock, no float.
    #    Reject future-dated (issued in the future => clock-forgery) and expired challenges.
    if now_s < ch.issued:
        raise OnboardError("challenge is not yet valid (issued in the future)")
    if now_s >= ch.expires:
        raise OnboardError("challenge has expired")

    # 4) anti-replay -- a burned nonce can never be admitted again.
    if ch.nonce in seen:
        raise OnboardError("challenge nonce already used (replay)")

    # 5) THE SIGNATURE GATE -- verify the wallet signature over the exact pre-image.
    #    crypto.verify returns False (never raises) on any bad/forged/wrong-key signature.
    if not crypto.verify(pr.pubkey, onboard_preimage(ch), pr.sig):
        raise OnboardError("onboarding signature does not verify for this pubkey")

    # Admission granted -- burn the nonce LAST (only a fully-valid proof consumes it, so a
    # replay attempt with a bad signature can't grief a future legitimate retry).
    seen.add(ch.nonce)
    return pr.pubkey


# ---------------------------------------------------------------------------
# Field validators (typed, strict -- reject before any crypto runs)
# ---------------------------------------------------------------------------

def _req_str(rec: dict, key: str) -> str:
    value = rec.get(key)
    if not isinstance(value, str):
        raise OnboardError(f"{key} must be a string")
    return value


def _req_int(rec: dict, key: str) -> int:
    value = rec.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise OnboardError(f"{key} must be an integer")
    return value


def _to_int(text: str) -> int:
    """Parse a base-10 integer field from a URI; reject anything non-integer (no float)."""
    s = text.strip()
    if not s or (s[0] == "-" and not s[1:].isdigit()) or (s[0] != "-" and not s.isdigit()):
        raise OnboardError(f"expected an integer, got {text!r}")
    return int(s, 10)


def _is_compressed_pubkey(pub_hex: str) -> bool:
    """True iff ``pub_hex`` is a 33-byte compressed secp256k1 point hex (0x02/0x03 prefix)."""
    if not crypto.is_valid_hex(pub_hex, 33):
        return False
    return pub_hex[:2].lower() in ("02", "03")
