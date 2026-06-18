"""MOLGANG end-to-end demo — a chemistry round that weaves real Knits & Fibers.

Run:  PYTHONPATH=src:../pulse/src python3 examples/play_demo.py   (exit 0 ⇒ it works)

Shows: faucet (free pulses + silk) → propose a bond → peers vote with their pulses
(real Knits into escrow) → real `pouw.quorum` tally → a correct bond is woven (Fiber
+ reward-bank PLS), an incorrect one is caught and everyone is refunded.
"""

from __future__ import annotations

from molgang import Player, cast_vote, propose, settle
from molgang.game import PROPOSER_BASE_REWARD, VOTE_COST, usefulness_bonus


def main() -> None:
    print("== MOLGANG — weave your first chemistry bonds ==\n")

    # 1. Faucet: four learners join with free pulses + free silk.
    alice = Player.join("Alice")
    peers = [Player.join(n) for n in ("Bob", "Carol", "Dave")]
    print(f"1. faucet   Alice={alice.pulses} PLS / {alice.silk} silk; "
          f"peers each {peers[0].pulses} PLS")
    start_total = alice.pulses + sum(p.pulses for p in peers)

    # 2. Alice proposes a CORRECT bond: water = H2O. Peers vote honestly with a pulse each.
    rnd = propose(alice, "H2O", "Water")
    for p in peers:
        v = cast_vote(rnd, p)            # honest verdict from real chemistry; stakes 1 PLS
        print(f"2. vote     {p.name} staked 1 PLS → {v.verdict.value}  (knit {v.knit_id[:14]}…)")
    s = settle(rnd)
    print(f"   settle   outcome={s.outcome.value}  woven={s.woven}  reward={s.reward} PLS")
    print(f"   Alice now {alice.pulses} PLS; her woven Fiber = {s.woven_fiber_cid[:18]}…\n")
    assert s.woven and s.outcome.value == "confirmed"
    expected_reward = len(peers) * VOTE_COST + PROPOSER_BASE_REWARD + usefulness_bonus(len(peers))
    assert s.reward == expected_reward and alice.pulses == 50 + s.reward
    assert s.woven_fiber_cid is not None                     # a real Fiber was woven

    # 3. Alice proposes a WRONG bond: 'NaCl2' is not a real molecule. Peers catch it.
    bad = propose(alice, "NaCl2", "Bogus salt")
    for p in peers:
        cast_vote(bad, p)                # honest peers vote MISMATCH
    s2 = settle(bad)
    print(f"3. wrong    proposed NaCl2 → outcome={s2.outcome.value}  woven={s2.woven} "
          f"(voters refunded)")
    assert not s2.woven

    # 4. Accounting: the staked pot moved to Alice; fresh rewards came from the protocol bank.
    end_total = alice.pulses + sum(p.pulses for p in peers)
    fresh_pls = (s.reward - len(peers) * VOTE_COST) + s.voter_rewards
    print(f"\n4. account  start_total={start_total} PLS  end_total={end_total} PLS  "
          f"fresh_rewards={fresh_pls} PLS")
    assert end_total == start_total + fresh_pls

    print("\n✅ MOLGANG core verified: faucet → propose → pulse-vote → quorum → woven Fiber")


if __name__ == "__main__":
    main()
