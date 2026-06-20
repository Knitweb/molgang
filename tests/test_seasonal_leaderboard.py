"""Sprint 7 #112 — seasonal (time-windowed) leaderboards.

Pure tests: load `progression.py` by path (its only knitweb use is a lazy import inside
`reputation_threshold`, which we don't call), and drive the seasonal helpers with synthetic woven
items carrying `anchor_ts`. Covers window boundaries, empty seasons, tie-breaking, deterministic
season ids, and that the all-time board is unaffected.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("molgang_progression", ROOT / "src/molgang/progression.py")
prog = importlib.util.module_from_spec(spec)
sys.modules["molgang_progression"] = prog
spec.loader.exec_module(prog)

SECS = prog._SEASON_SECONDS


def _item(formula, by, ts):
    return {"formula": formula, "by": by, "confirmations": 3, "anchor_ts": ts}


def test_season_id_is_deterministic_and_window_round_trips():
    assert prog.season_id(0) == "S0"
    assert prog.season_id(SECS) == "S1"
    assert prog.season_id(SECS - 1) == "S0"
    sid = prog.season_id(5 * SECS + 123)
    assert sid == "S5"
    since, until = prog.season_window(sid)
    assert since == 5 * SECS and until == 6 * SECS
    assert since <= (5 * SECS + 123) < until


def test_window_boundaries_are_half_open():
    woven = [
        _item("H2O", "A", 100),               # in [100, 200)
        _item("CO2", "A", 199),               # in
        _item("O2", "B", 200),                # excluded: until is exclusive
        _item("NaCl", "B", 99),               # excluded: since is inclusive lower bound
    ]
    rows = prog.seasonal_leaderboard(woven, since=100, until=200)
    by_player = {r["player"]: r for r in rows}
    assert by_player["A"]["molecules"] == 2     # both A items in window
    assert "B" not in by_player                  # both B items outside window


def test_empty_season_is_empty():
    woven = [_item("H2O", "A", 5_000)]
    assert prog.seasonal_leaderboard(woven, since=0, until=1_000) == []


def test_items_without_timestamp_are_not_in_any_season():
    woven = [{"formula": "H2O", "by": "A", "confirmations": 3}]  # no anchor_ts
    assert prog.seasonal_leaderboard(woven, since=0, until=10**12) == []


def test_tie_break_matches_all_time_board():
    # equal XP (one molecule each) → tie-break by player id ascending, same as leaderboard()
    woven = [_item("H2O", "B", 10), _item("CO2", "A", 20)]
    rows = prog.seasonal_leaderboard(woven, since=0, until=100)
    assert [r["player"] for r in rows] == ["A", "B"]
    assert [r["rank"] for r in rows] == [1, 2]


def test_all_time_leaderboard_unchanged_by_timestamps():
    # leaderboard() ignores anchor_ts entirely — ranking is identical with or without it
    woven = [_item("H2O", "A", 1), _item("CO2", "A", 10**12), _item("O2", "B", 5)]
    lb = prog.leaderboard(woven)
    assert lb[0]["player"] == "A" and lb[0]["molecules"] == 2
    assert lb[1]["player"] == "B" and lb[1]["molecules"] == 1


def test_current_season_helper_packages_window_and_rows():
    now = 7 * SECS + 42
    woven = [_item("H2O", "A", 7 * SECS + 1), _item("CO2", "A", 6 * SECS)]  # 2nd is last season
    out = prog.current_season_leaderboard(woven, now)
    assert out["season"] == "S7"
    assert out["since"] == 7 * SECS and out["until"] == 8 * SECS
    assert len(out["rows"]) == 1 and out["rows"][0]["player"] == "A"
    assert out["rows"][0]["molecules"] == 1   # only the in-season weave counts
