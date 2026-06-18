"""Two-way bridge tests — alternating upload/download, persistence, continuity.

    PYTHONPATH=.:src:/path/to/pulse/src python3 -m pytest -q
"""

from __future__ import annotations

import json

from bridge.ingest import ingest
from bridge.sync import step

EXPORT = "bridge/sample_roblox_votes.json"


def test_upload_ingests_votes_and_weaves():
    export = json.load(open(EXPORT, encoding="utf-8"))
    summ = ingest(export)
    assert summ["roblox_wallets_ingested"] == 4
    woven = {b["formula"] for b in summ["bonds_woven"]}
    assert "H2O" in woven and "NaCl2" not in woven   # correct woven, bogus rejected


def test_two_way_sync_alternates_persists_and_continues(tmp_path):
    state = str(tmp_path / "state.json")
    snap = str(tmp_path / "snap.json")

    i0 = step(state, EXPORT, snap, now="t0")          # even → upload
    assert i0["direction"] == "upload" and i0["woven_now"] >= 1

    i1 = step(state, EXPORT, snap, now="t1")          # odd → download
    assert i1["direction"] == "download"
    d = json.load(open(snap, encoding="utf-8"))
    assert "H2O" in d["confirmed_formulas"]
    # 50 faucet + H2O woven: vote-pot (3 confirms ×1) + base 2 + usefulness_bonus(3)=2**3-1=7 → +12.
    assert d["players"]["roblox:1001"]["pulses"] == 62   # useful work reward persisted

    i2 = step(state, EXPORT, snap, now="t2")          # even → upload again
    assert i2["direction"] == "upload"

    s = json.load(open(state, encoding="utf-8"))
    assert s["cursor"] == 3 and "H2O" in s["web"]     # cursor advanced, web accumulated
