"""Tests for molgang.webnode.onboard_verify — signature-gated QR onboarding."""

import secrets

import pytest

from knitweb.core import crypto
from molgang.webnode.onboard_verify import (
    DEFAULT_TTL_S,
    NONCE_BYTES,
    InMemorySeenNonces,
    OnboardError,
    issue_challenge,
    sign_challenge,
    verify_onboarding,
)

# Stable test keypair (generated once, reused — no randomness in tests).
_PRIV, _PUB = crypto.generate_keypair()
_NOW = 1_000_000  # arbitrary injected integer clock (never wall-clock)


def _nonce() -> bytes:
    return secrets.token_bytes(NONCE_BYTES)


def _challenge(scope="classroom-1", device="dev-001", audience="", now=_NOW):
    return issue_challenge(
        scope=scope, device=device, now_s=now, nonce_bytes=_nonce(), audience=audience
    )


def test_verify_accepts_valid_proof():
    ch = _challenge()
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    admitted = verify_onboarding(
        proof, now_s=_NOW, expected_scope="classroom-1", seen=seen
    )
    assert admitted == _PUB


def test_nonce_is_burned_after_verify():
    ch = _challenge()
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    verify_onboarding(proof, now_s=_NOW, expected_scope="classroom-1", seen=seen)
    # Second verify with the same proof must raise (replay).
    with pytest.raises(OnboardError):
        verify_onboarding(proof, now_s=_NOW, expected_scope="classroom-1", seen=seen)


def test_expired_challenge_raises():
    ch = _challenge(now=_NOW)
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    # Verify at a time well past expiry.
    with pytest.raises(OnboardError):
        verify_onboarding(
            proof, now_s=_NOW + DEFAULT_TTL_S + 1, expected_scope="classroom-1", seen=seen
        )


def test_wrong_scope_raises():
    ch = _challenge(scope="classroom-1")
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    with pytest.raises(OnboardError):
        verify_onboarding(
            proof, now_s=_NOW, expected_scope="classroom-99", seen=seen
        )


def test_bad_signature_raises():
    ch = _challenge()
    proof = sign_challenge(_PRIV, ch)
    # Corrupt the signature.
    bad_proof = proof.__class__(pubkey=proof.pubkey, sig="00" * 71, challenge=ch)
    seen = InMemorySeenNonces()
    with pytest.raises(OnboardError):
        verify_onboarding(bad_proof, now_s=_NOW, expected_scope="classroom-1", seen=seen)


def test_audience_binding_rejects_wrong_local_key():
    _, other_pub = crypto.generate_keypair()
    ch = _challenge(audience=_PUB)  # bound to _PUB
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    # Verifying as a different peer should fail.
    with pytest.raises(OnboardError):
        verify_onboarding(
            proof, now_s=_NOW, expected_scope="classroom-1",
            seen=seen, local_pubkey=other_pub
        )


def test_audience_binding_accepts_correct_local_key():
    ch = _challenge(audience=_PUB)
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    admitted = verify_onboarding(
        proof, now_s=_NOW, expected_scope="classroom-1",
        seen=seen, local_pubkey=_PUB
    )
    assert admitted == _PUB


def test_issue_challenge_rejects_float_clock():
    with pytest.raises(OnboardError):
        issue_challenge(
            scope="x", device="d", now_s=1.5, nonce_bytes=_nonce()  # type: ignore[arg-type]
        )


def test_verify_from_record_form():
    """``verify_onboarding`` accepts the dict record form of a proof."""
    ch = _challenge()
    proof = sign_challenge(_PRIV, ch)
    seen = InMemorySeenNonces()
    admitted = verify_onboarding(
        proof.to_record(), now_s=_NOW, expected_scope="classroom-1", seen=seen
    )
    assert admitted == _PUB
