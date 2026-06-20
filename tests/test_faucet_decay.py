"""Load-bearing tests for the decaying faucet schedule.

Pin the exact integer µPLS curve so any drift in the schedule breaks the build, and
prove it is float-free, monotone non-increasing, and never reaches 0 (always exists).
The production onboarding grant (a fresh device wallet) must follow the curve.
"""
from datetime import date

from molgang import game
from molgang.bar import Bar, FAUCET_GENESIS_DATE, _faucet_day

MPP = game.MICROPULSES_PER_PULSE  # 1 PLS = 1_000_000 µPLS


def test_genesis_grant_is_ten_million_pls():
    assert game.current_faucet_pulses(0) == 10_000_000
    assert game.faucet_micropulses(0) == 10_000_000 * MPP


def test_phase1_is_exact_linear_ramp_to_ten_thousand():
    # 10,000,000 PLS → 10,000 PLS over exactly 100 days, integer-exact at every point
    assert game.current_faucet_pulses(100) == 10_000
    assert game.faucet_micropulses(100) == 10_000 * MPP
    assert game.faucet_micropulses(50) == 5_005_000 * MPP          # midpoint, exact
    assert game.faucet_micropulses(1) == 10_000_000 * MPP - 99_900 * MPP


def test_phase2_decays_one_percent_per_day():
    # day 101 = 10,000 PLS × 99/100 = 9,900 PLS, exact in integer µPLS
    assert game.faucet_micropulses(101) == 9_900 * MPP
    assert game.current_faucet_pulses(101) == 9_900
    # k days in = floor(10,000 PLS × (99/100)**k), integer-rational
    for k in (2, 5, 30):
        expected = (10_000 * MPP * 99**k) // (100**k)
        assert game.faucet_micropulses(100 + k) == expected


def test_monotone_non_increasing():
    prev = game.faucet_micropulses(0)
    for d in range(1, 1200):
        cur = game.faucet_micropulses(d)
        assert cur <= prev
        prev = cur


def test_always_exists_never_zero():
    # decades out the faucet is still >= 1 µPLS — it never empties
    for d in (1000, 2000, 5000, 20000):
        assert game.faucet_micropulses(d) >= game.FAUCET_MIN_MICROPULSES >= 1


def test_float_free_integer_only():
    for d in (0, 1, 50, 100, 101, 500, 3000):
        assert type(game.faucet_micropulses(d)) is int
        assert type(game.current_faucet_pulses(d)) is int


def test_faucet_day_genesis_and_clamp():
    assert _faucet_day(FAUCET_GENESIS_DATE) == 0
    assert _faucet_day(date(2026, 6, 19)) == 0           # before genesis clamps to 0
    assert _faucet_day(date(2026, 9, 28)) == 100         # exactly 100 days later


def test_new_device_onboarding_opens_faucet_at_todays_grant(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))                   # no registry → faucet branch
    fresh = bar.join("amasser", device="dev-genesis", today=FAUCET_GENESIS_DATE)
    assert fresh.player.pulses == 10_000_000              # day 0 grant
    later = bar.join("late", device="dev-late", today=date(2026, 9, 28))
    assert later.player.pulses == 10_000                  # day 100 grant
