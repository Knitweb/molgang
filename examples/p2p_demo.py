"""MOLGANG real-P2P demo — votes that cross real sockets between live nodes.

Run:  PYTHONPATH=src:../pulse/src python3 examples/p2p_demo.py   (exit 0 ⇒ it works)

This is NOT a simulation: each peer is a real `knitweb.p2p.AsyncioP2PNode` listening on
a real TCP port; every vote is a Knit sent over the wire via the proposal→accept→finalize
handshake. The proposer's balance grows only because real settled Knits arrived. The
verdicts are then tallied with the real `pouw.quorum` to weave (or reject) the bond.
"""

from __future__ import annotations

import asyncio

from knitweb.ledger.node import AccountNode
from knitweb.p2p.node import AsyncioP2PNode, PeerAddress
from knitweb.pouw import quorum

from molgang import chemistry
from molgang.chemistry import Bond


async def main() -> None:
    print("== MOLGANG — a real peer-to-peer validation round ==\n")

    proposer = AccountNode(genesis_balances={"PLS": 50})      # runs the table; collects votes
    voters = [AccountNode(genesis_balances={"PLS": 50}) for _ in range(3)]
    bond = Bond.propose("H2O", "Water")
    print(f"proposer {proposer.address[:16]}… opens a round on {bond.formula} ({bond.name})")

    server = AsyncioP2PNode(account=proposer, host="127.0.0.1", port=0)
    await server.start()
    print(f"table listening on a real socket {server.host}:{server.port}\n")

    verdicts: list[quorum.Verdict] = []
    try:
        for i, v in enumerate(voters, start=1):
            client = AsyncioP2PNode(account=v)
            knit = await client.send_knit(
                PeerAddress(server.host, server.port), proposer.pub, "PLS", 1, timestamp=i
            )
            verdicts.append(
                quorum.Verdict.CONFIRM if chemistry.is_correct(bond) else quorum.Verdict.MISMATCH
            )
            print(f"  {v.address[:16]}… staked 1 PLS over the wire → {verdicts[-1].value} "
                  f"(knit {knit.id[:14]}…)")
    finally:
        await server.stop()

    res = quorum.tally(verdicts)
    print(f"\nquorum: {res.outcome.value} ({res.confirms}/{res.n}, k={res.threshold})  "
          f"proposer now {proposer.balance('PLS')} PLS")
    assert res.releases and proposer.balance("PLS") == 53
    assert all(v.balance("PLS") == 49 for v in voters)        # each really spent 1 over the wire
    print("\n✅ real P2P verified: 3 vote-Knits settled over real sockets → confirm quorum")


if __name__ == "__main__":
    asyncio.run(main())
