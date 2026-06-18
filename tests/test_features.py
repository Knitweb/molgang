"""Tests for the state-of-the-art layers: OriginTrail provenance, progression, CLI."""

from __future__ import annotations

import hashlib

from molgang import cli, progression
from molgang.anchor import anchor_chemistry

_WOVEN = [
    {"formula": "H2O", "name": "Water", "by": "A", "confirmations": 3},
    {"formula": "CO2", "name": "Carbon dioxide", "by": "A", "confirmations": 3},
    {"formula": "NaCl", "name": "Table salt", "by": "A", "confirmations": 3},
    {"formula": "O2", "name": "Oxygen gas", "by": "B", "confirmations": 3},
]


def test_origintrail_anchor_is_verified():
    a = anchor_chemistry(_WOVEN[:1])
    assert a.verified
    assert a.ual.startswith("did:dkg:knitweb/")
    assert a.bonds == 1


def test_anchor_is_deterministic_for_a_given_web():
    key = hashlib.sha256(b"molgang:notary").hexdigest()
    assert anchor_chemistry(_WOVEN, notary_priv=key).ual == anchor_chemistry(_WOVEN, notary_priv=key).ual


def test_progression_levels():
    assert progression.level_for(0) == 1
    assert progression.level_for(300) >= 3
    assert progression.title_for(1) == "Apprentice"


def test_leaderboard_ranks_by_xp():
    lb = progression.leaderboard(_WOVEN)
    assert lb[0]["player"] == "A" and lb[0]["molecules"] == 3 and lb[0]["rank"] == 1
    assert lb[1]["player"] == "B" and lb[1]["molecules"] == 1


def test_cli_demo_runs_clean(capsys):
    assert cli.main(["molgang", "demo"]) == 0
    out = capsys.readouterr().out
    assert "MOLGANG" in out and "OriginTrail" in out and "leaderboard" in out
