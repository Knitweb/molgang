"""Two-way bridge tests — alternating upload/download, persistence, continuity.

    PYTHONPATH=.:src:/path/to/pulse/src python3 -m pytest -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bridge.ingest import ingest
from bridge.sync import step

EXPORT = "bridge/sample_roblox_votes.json"
ROOT = Path(__file__).resolve().parents[1]


def _script_env() -> dict[str, str]:
    paths = [str(ROOT / "src")]
    pulse_src = ROOT.parent / "pulse" / "src"
    if pulse_src.exists():
        paths.append(str(pulse_src))
    current = os.environ.get("PYTHONPATH")
    if current:
        paths.append(current)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


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


def test_bridge_entrypoints_run_directly(tmp_path):
    """The documented `python bridge/*.py` commands must work outside pytest imports."""
    env = _script_env()
    help_run = subprocess.run(
        [sys.executable, "bridge/server.py", "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "MOLGANG bridge HTTP server" in help_run.stdout

    state = tmp_path / "state.json"
    snap = tmp_path / "snap.json"
    sync_run = subprocess.run(
        [
            sys.executable,
            "bridge/sync.py",
            "--state",
            str(state),
            "--export",
            EXPORT,
            "--snapshot",
            str(snap),
            "--now",
            "t0",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert sync_run.returncode == 0, sync_run.stderr
    assert "MOLGANG sync [upload" in sync_run.stdout
