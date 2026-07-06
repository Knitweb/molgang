"""#106 — docs/TOKENOMICS.md stays lockstep with the real economy in game.py.

The doc states every economic constant inline; this test re-derives each from
`molgang.game` and fails if the document drifts. Same pattern as
tests/test_curriculum_doc.py (the doc can never silently lie).
"""
import re
from pathlib import Path

from molgang import game

DOC = (Path(__file__).resolve().parents[1] / "docs" / "TOKENOMICS.md").read_text(encoding="utf-8")

CONSTANTS = [
    "FAUCET_PULSES", "FAUCET_SILK", "VOTE_COST", "SILK_PER_BOND",
    "PROPOSER_BASE_REWARD", "VOTER_CONFIRM_REWARD", "USEFULNESS_EXP_BASE",
    "MAX_USEFULNESS_BONUS", "ROUND_REWARD_BANK_PLS", "MICROPULSES_PER_PULSE",
    "FAUCET_PHASE1_DAYS", "FAUCET_MIN_MICROPULSES",
    "CONTAGION_SILK", "MIN_SPIRAL_VOTERS", "MAX_SPIRAL_LEN", "LEVEL_SILK_GRANT",
]


def test_every_stated_constant_matches_game_py():
    for name in CONSTANTS:
        value = getattr(game, name)
        m = re.search(rf"`{name}[^`]*=\s*([0-9,_]+)", DOC)
        assert m, f"TOKENOMICS.md does not state {name}"
        stated = int(m.group(1).replace(",", "").replace("_", ""))
        assert stated == value, f"{name}: doc says {stated}, game.py says {value}"


def test_decay_ratio_and_bonus_formula_match():
    assert f"{game.FAUCET_PHASE2_DECAY_NUM}/{game.FAUCET_PHASE2_DECAY_DEN}" in DOC
    # the worked bonus formula: base ** confirms - 1, capped
    assert game.usefulness_bonus(3) == min(game.MAX_USEFULNESS_BONUS,
                                           game.USEFULNESS_EXP_BASE ** 3 - 1)
    assert "USEFULNESS_EXP_BASE ** confirms − 1" in DOC


def test_worst_case_emission_bound_is_correct():
    """The doc's 24-seat bound (2 + 64 + 23×1 = 89) must equal the real math."""
    confirms = 23
    bound = (game.PROPOSER_BASE_REWARD + game.MAX_USEFULNESS_BONUS
             + confirms * game.VOTER_CONFIRM_REWARD)
    assert f"≤ **{bound} PLS" in DOC
    knits_per_bank = game.ROUND_REWARD_BANK_PLS // bound
    assert f"{knits_per_bank:,}".replace(",", ",") in DOC.replace(" ", " ") or str(knits_per_bank) in DOC.replace(",", "")


def test_spiral_cost_examples_match():
    assert game.spiral_silk_cost(2) == 2 and game.spiral_silk_cost(7) == 12
    assert "2 links → 2 silk, 7 links → 12" in DOC


def test_no_nft_stance_and_invariants_are_stated():
    for phrase in ("no-NFT", "Failed work mints nothing", "net-positive", "Integer-exact"):
        assert phrase in DOC, phrase
