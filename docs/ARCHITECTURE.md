# MOLGANG — architecture

MOLGANG teaches chemistry (scheikunde) by having learners *operate the Knitweb*. Nothing is
mocked: bonds are real Knits, molecules are real Fibers, validation is the real PoUW quorum.

## Components

```
molgang/
├── src/molgang/
│   ├── chemistry.py   ground truth: elements, molecules, formula parser, is_correct()
│   ├── game.py        engine: Player (knitweb account + silk), propose / cast_vote / settle
│   └── __init__.py
├── examples/
│   ├── play_demo.py   in-process round (faucet → propose → pulse-vote → quorum → Fiber)
│   └── p2p_demo.py    the SAME, but over real sockets (knitweb.p2p.AsyncioP2PNode)
├── roblox/            Lua mirror (Chemistry/Game/VoteExport) + hourly export → bridge
├── bridge/            ingest.py: weave the hourly Roblox export into the knitweb
└── tests/
```

## The mapping (chemistry ↔ knitweb)

| Game | Knitweb | Module |
|---|---|---|
| form a **bond** | a **Knit** (two-party transfer) | `knitweb.ledger` (`AccountNode.transfer_to`) |
| grow a molecule | a **Fiber** (account-state commitment) | `knitweb.ledger` (`node.braid.head`) |
| **vote** with a pulse | a staked **PLS** Knit + a `quorum.Verdict` | `game.cast_vote` |
| accept a bond | **confirm quorum** (BFT k = ⌊2n/3⌋+1) | `knitweb.pouw.quorum.tally` |
| free start | **silk + pulses** faucet | `Player.join` / `Player.from_roblox` |
| the classroom | a **P2P web** of nodes | `knitweb.p2p.AsyncioP2PNode` |

## Round lifecycle

1. **Faucet** — a new learner gets free pulses (`AccountNode(genesis_balances={"PLS": 50})`)
   and free silk. (No premine on the real token; this is dev/faucet seeding.)
2. **Propose** — the proposer spins silk into a bond (a formula claim, e.g. `H2O`).
3. **Vote** — each peer stakes 1 PLS as a *real Knit* into a round escrow and records a
   verdict (honest peers `CONFIRM` correct chemistry, `MISMATCH` wrong).
4. **Settle** — `quorum.tally` decides: `CONFIRMED` → the bond is woven (escrow pays the
   proposer; their Braid advances → a new **Fiber**); otherwise voters are refunded.

Pulses are conserved throughout — a confirmed bond just routes the staked pot to correct
chemistry (proof-of-knowledge), nothing is minted.

## Real peer-to-peer

`p2p_demo.py` runs each player as a real `AsyncioP2PNode` on a real TCP port; votes cross the
wire via the proposal→accept→finalize handshake. A live web of player-nodes is an actual
class — not a single-process simulation.

## Roblox counterpart + hourly bridge

`roblox/` is a 1:1 Lua mirror that plays locally in Roblox (wallet id = `Player.UserId`).
**Once an hour** `VoteExport.lua` POSTs the accumulated votes (the exact shape of
`bridge/sample_roblox_votes.json`) to an endpoint running `bridge/ingest.py`, which:

1. maps each unique **Roblox wallet id** → a *stable* knitweb account (`Player.from_roblox`,
   key derived deterministically from the id, so identity persists across hours);
2. replays every vote as a real Knit;
3. tallies with the real quorum and **breit/weaves** confirmed bonds into Fibers.

This keeps the fun, low-latency Roblox classroom and the authoritative Knitweb in sync at an
hourly cadence.

## Vocabulary

Web · Knitweb · Knit · Pulse · Fiber; spiders; pay-token **PLS**. We never use "loom".
