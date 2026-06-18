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
   proposer, a capped exponential usefulness bonus is paid from the protocol reward bank,
   confirming voters get their stake plus a PLS reward, and the proposer's silk is restored);
   otherwise voters are refunded.

Confirmed useful work is intentionally net-positive in the game economy. Failed or unconfirmed
work does not mint rewards; voter stakes are refunded.

## Real peer-to-peer

`p2p_demo.py` runs each player as a real `AsyncioP2PNode` on a real TCP port; votes cross the
wire via the proposal→accept→finalize handshake. A live web of player-nodes is an actual
class — not a single-process simulation.

## Roblox counterpart + two-way bridge (alternating every 30 min)

`roblox/` is a 1:1 Lua mirror that plays locally in Roblox (wallet id = `Player.UserId`).
`roblox/Sync.lua` and `bridge/sync.py` keep Roblox and the Knitweb in sync **both ways**,
alternating direction by an internal cursor every **30 minutes** — so each direction syncs
**hourly**, *something* syncs every 30 min, and upload/download never collide in one tick.

```
bridge/
├── state.py      persisted projection (cursor · players{address,pulses,silk} · web{formula→…})
├── ingest.py     UPLOAD   : Roblox votes export → weave into the knitweb (real Knits/Fibers)
├── snapshot.py   DOWNLOAD : canonical knitweb state → molgang/Roblox
└── sync.py       the alternating runner (even tick ⇒ upload, odd ⇒ download)
```

**⬆️ Upload (Roblox → Knitweb).** `VoteExport.lua` buffers settled rounds; on an upload tick
`Sync.lua` POSTs them (shape of `bridge/sample_roblox_votes.json`) to an endpoint running
`sync.py`, which: (1) maps each unique **Roblox wallet id** → a *stable* knitweb account
(`Player.from_roblox`, deterministic key, **balance continued** from the persisted state),
(2) replays every vote as a real Knit, (3) tallies with the real quorum and **breit/weaves**
confirmed bonds into Fibers, updating `state.json`.

**⬇️ Download (Knitweb → molgang).** On a download tick `sync.py` writes a snapshot of the
canonical state (confirmed/woven bonds — *including those woven by other peers or the Python
P2P game* — plus continued balances). `Sync.lua` GETs it and applies it
(`Sync.isConfirmed(formula)`, `Sync.players`), so an update on the p2p Knitweb propagates back
down to the Roblox classroom.

Pulses/web continuity lives in `state.json`; for production the authoritative accounts/braids
persist via `knitweb.store` and this projection is the molgang-facing view both sides sync on.

## Vocabulary

Web · Knitweb · Knit · Pulse · Fiber; spiders; pay-token **PLS**. We never use "loom".
