"""D2: per-device/pubkey rate limiting; D5: durable relay snapshot/restore."""

from __future__ import annotations

import json
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# D2: per-device rate limiting
# ---------------------------------------------------------------------------


def _make_handler(limit: int = 5, window_s: int = 60):
    """Return a (limiter, rule, keys_fn) tuple for testing."""
    import math
    import threading
    from molgang.webserver import RateLimiter, RateLimitRule, RateLimitDecision

    limiter = RateLimiter(clock=lambda: 0.0)
    rule = RateLimitRule(limit=limit, window_s=window_s)
    return limiter, rule


def test_device_key_limits_independently():
    """Device bucket is independent of IP so a device over-limit is blocked even on fresh IP."""
    from molgang.webserver import RateLimiter, RateLimitRule

    limiter = RateLimiter(clock=lambda: 0.0)
    rule = RateLimitRule(limit=2, window_s=60)

    device_key = "device:abc123"
    ip_key_1 = "POST:/api/vote:source:1.2.3.4"
    ip_key_2 = "POST:/api/vote:source:5.6.7.8"

    # Exhaust device bucket from IP 1
    assert limiter.check(rule, [ip_key_1, device_key]).allowed
    assert limiter.check(rule, [ip_key_1, device_key]).allowed
    # Third attempt from IP 1 blocked
    assert not limiter.check(rule, [ip_key_1, device_key]).allowed
    # Same device from a DIFFERENT IP is also blocked
    assert not limiter.check(rule, [ip_key_2, device_key]).allowed


def test_combining_keys_takes_strictest():
    """When one key in the list is over-limit, the whole request is denied."""
    from molgang.webserver import RateLimiter, RateLimitRule

    limiter = RateLimiter(clock=lambda: 0.0)
    rule = RateLimitRule(limit=1, window_s=60)

    ip_key = "POST:/api/vote:source:9.9.9.9"
    device_key = "device:abc"

    # Exhaust device bucket (limit=1 → one allowed then blocked)
    assert limiter.check(rule, [device_key]).allowed
    # ip_key still fresh, but device_key is exhausted → combined call blocked
    assert not limiter.check(rule, [ip_key, device_key]).allowed


# ---------------------------------------------------------------------------
# D5: relay snapshot / restore
# ---------------------------------------------------------------------------

PYTHONPATH_PULSE = "/tmp/pulse-work/src"


@pytest.fixture()
def relay_sync(tmp_path):
    """Real RelaySync bound to a stub World with a few items."""
    import sys
    if PYTHONPATH_PULSE not in sys.path:
        sys.path.insert(0, PYTHONPATH_PULSE)
    from molgang.world import World, WovenItem
    from molgang.relay_sync import RelaySync, host_signer

    w = World()
    w.items.append(WovenItem(kind="term", by="test", fiber_cid="cid1", confirmations=1, term="hydrogen"))
    w.items.append(WovenItem(kind="term", by="test", fiber_cid="cid2", confirmations=1, term="oxygen"))
    signer = host_signer("test-seed")
    rs = RelaySync("https://example.com/relay", w, signer)
    rs.cursor = 42
    return rs


def test_snapshot_round_trips(relay_sync, tmp_path):
    path = str(tmp_path / "snap.json")
    relay_sync.snapshot(path)

    # Load raw JSON to verify structure
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    assert isinstance(data["cursor"], int)
    assert data["cursor"] == 42
    assert isinstance(data["world_hash"], str)
    assert len(data["world_hash"]) == 64  # sha256 hex
    assert isinstance(data["items"], list)
    assert len(data["items"]) >= 2


def test_tampered_snapshot_fails_restore(relay_sync, tmp_path):
    path = str(tmp_path / "snap.json")
    relay_sync.snapshot(path)

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["items"].append({"kind": "term", "by": "attacker", "fiber_cid": "evil",
                          "confirmations": 0, "term": "INJECTED", "subject": "",
                          "object": "", "relation": "", "links": [], "validators": 0,
                          "pls_staked": 0, "anchor_rel": 0, "anchor_ts": 0, "lang": "en"})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

    with pytest.raises(ValueError, match="world_hash"):
        relay_sync.restore(path)


def test_restore_sets_integer_cursor(relay_sync, tmp_path):
    path = str(tmp_path / "snap.json")
    relay_sync.cursor = 99
    relay_sync.snapshot(path)

    # Change cursor to something else, then restore
    relay_sync.cursor = 0
    relay_sync.restore(path)
    assert relay_sync.cursor == 99
    assert isinstance(relay_sync.cursor, int)
    assert not isinstance(relay_sync.cursor, bool)


def test_verify_snapshot_valid(relay_sync, tmp_path):
    path = str(tmp_path / "snap.json")
    relay_sync.snapshot(path)
    assert relay_sync.verify_snapshot(path)


def test_verify_snapshot_corrupt(tmp_path):
    from molgang.world import World
    from molgang.relay_sync import RelaySync, host_signer

    w = World()
    signer = host_signer("seed")
    rs = RelaySync("https://x.com", w, signer)
    path = str(tmp_path / "bad.json")
    with open(path, "w") as fh:
        fh.write("NOT JSON")
    assert not rs.verify_snapshot(path)
