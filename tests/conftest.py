"""Test defaults that keep wallet derivation deterministic and local to pytest."""

import pytest


@pytest.fixture(autouse=True)
def _molgang_test_wallet_secret(monkeypatch):
    monkeypatch.setenv("MOLGANG_WALLET_SECRET", "molgang-test-domain-secret")
    monkeypatch.setenv("MOLGANG_WALLET_KDF_ITERATIONS", "8")
