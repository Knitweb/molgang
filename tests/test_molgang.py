"""MOLGANG core tests — runs against the real knitweb package.

    PYTHONPATH=src:/path/to/pulse/src python3 -m pytest -q
"""

from __future__ import annotations

from knitweb.pouw import quorum

from molgang import Player, cast_vote, chemistry, propose, settle
from molgang.chemistry import Bond


def test_faucet_grants_free_pulses_and_silk():
    p = Player.join("A")
    assert p.pulses == 50 and p.silk == 10


def test_chemistry_ground_truth():
    assert chemistry.is_correct(Bond.propose("H2O", "Water"))
    assert chemistry.is_correct(Bond.propose("C6H12O6", "Glucose"))
    assert not chemistry.is_correct(Bond.propose("NaCl2", "bogus"))  # not a real molecule


def test_correct_bond_is_woven_and_pulses_conserved():
    alice = Player.join("Alice")
    peers = [Player.join(n) for n in ("Bob", "Carol", "Dave")]
    start = alice.pulses + sum(p.pulses for p in peers)

    rnd = propose(alice, "H2O", "Water")
    for p in peers:
        cast_vote(rnd, p)               # honest confirm; stakes a real Knit
    s = settle(rnd)

    assert s.woven and s.outcome is quorum.Outcome.CONFIRMED
    assert s.woven_fiber_cid                      # a real Fiber was woven
    assert s.reward == len(peers)                 # earned the staked pot
    assert alice.pulses + sum(p.pulses for p in peers) == start   # conserved


def test_wrong_bond_is_rejected_and_refunded():
    alice = Player.join("Alice")
    peers = [Player.join(n) for n in ("Bob", "Carol", "Dave")]
    rnd = propose(alice, "NaCl2", "Bogus salt")
    for p in peers:
        cast_vote(rnd, p)               # honest mismatch
    s = settle(rnd)
    assert not s.woven
    assert all(p.pulses == 50 for p in peers)     # refunded


def test_proposer_cannot_vote_on_own_bond():
    alice = Player.join("Alice")
    rnd = propose(alice, "H2O", "Water")
    try:
        cast_vote(rnd, alice)
        assert False, "expected refusal"
    except RuntimeError:
        pass


def test_roblox_wallet_id_maps_to_stable_account():
    a = Player.from_roblox("roblox:42")
    b = Player.from_roblox("roblox:42")
    assert a.address == b.address                 # same Roblox id → same knitweb identity
    assert Player.from_roblox("roblox:43").address != a.address
