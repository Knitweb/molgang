"""Sprint 3 #17 — pure presence/reaping core (no knitweb, deterministic time).

Loaded by file path so it runs without the knitweb engine (the package __init__ bootstraps knitweb;
presence.py itself is pure stdlib). In CI `from molgang.presence import Presence` also works.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest

_spec = importlib.util.spec_from_file_location(
    "molgang_presence", Path(__file__).resolve().parent.parent / "src/molgang/presence.py")
m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(m)
Presence, ONLINE, AWAY, GONE = m.Presence, m.ONLINE, m.AWAY, m.GONE


def test_status_transitions():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", now=1000.0)
    assert p.status("a", 1010.0) == ONLINE
    assert p.status("a", 1040.0) == AWAY
    assert p.status("a", 1100.0) == GONE
    assert p.status("unknown", 1000.0) == GONE


def test_beat_refreshes():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", 1000.0); p.beat("a", 1080.0)
    assert p.status("a", 1090.0) == ONLINE


def test_reap_returns_and_removes_gone():
    p = Presence(away_after=30, gone_after=90)
    p.beat("ghost", 1000.0); p.beat("live", 1000.0); p.beat("live", 1200.0)
    assert p.reap(now=1200.0) == ["ghost"]
    assert p.reap(now=1200.0) == []
    assert p.status("live", 1200.0) == ONLINE


def test_online_and_snapshot():
    p = Presence(away_after=30, gone_after=90)
    p.beat("a", 1000.0); p.beat("b", 940.0)
    assert set(p.online(1000.0)) == {"a", "b"}
    snap = p.snapshot(1000.0)
    assert snap["a"] == ONLINE and snap["b"] == AWAY


def test_drop_and_validation():
    p = Presence()
    p.beat("a", 1.0); p.drop("a"); p.drop("a")
    assert p.status("a", 1.0) == GONE
    with pytest.raises(ValueError):
        Presence(away_after=90, gone_after=30)
