# MOLGANG

**MOLGANG** is a peer-to-peer **chemistry (scheikunde)** learning game built on the
[Knitweb](https://github.com/knitweb/pulse). You learn elements, formulas and bonding by
*doing it on a real crypto web*: every bond you form is a real **Knit**, every molecule you
grow is a real **Fiber**, and your classmates validate your chemistry by **voting with their
pulses**. New players start with **free silk + pulses** from the faucet.

> Vocabulary: this is the Knitweb — **Web · Knitweb · Knit · Pulse · Fiber**, workers are
> **spiders**, the pay-token is **PLS** ("pulses"). (We never say "loom".)

## The idea — the game *is* the protocol

| Chemistry / game | Knitweb primitive | Where |
|---|---|---|
| Forming a **bond** | a **Knit** (two-party transfer over the ledger) | `knitweb.ledger` |
| A molecule's growing chain | a **Fiber** (immutable account-state commitment) | `knitweb.ledger` |
| Classmates **voting** on a bond | **PLS pulses** staked + a real `pouw.quorum` verdict | `knitweb.pouw` |
| A bond is accepted | a **confirm quorum** (BFT k-of-n) → woven into your Braid | `knitweb.pouw.quorum` |
| **Free silk + pulses** to start | the faucet (`Player.join` / `from_roblox`) | `src/molgang/game.py` |
| Real classroom over the wire | real **P2P** peers | `knitweb.p2p` |

Because votes are *real* Knits on *real* accounts, playing weaves your first Knits and Fibers
for real — and a bond is only "true" once peers who know their chemistry confirm it.

## What's in the box

- 🎮 **Playable client** (`molgang`) — faucet → propose → peers vote → woven Fiber → your
  collection, XP & level, leaderboard, and a provenance anchor, all in one session.
- 🌐 **Real peer-to-peer** — players are live `AsyncioP2PNode` peers; votes cross real sockets.
- 🗳️ **Pulse-voting + BFT quorum** — peers stake pulses; the real `pouw.quorum` settles.
- 🧬 **Collectible molecules** — every confirmed bond is a collectible backed by a real Fiber
  CID; XP, levels (Apprentice→Laureate) and a leaderboard (`molgang.progression`).
- 🔗 **OriginTrail provenance** — the confirmed-chemistry web is anchored to a DKG as a
  verifiable **UAL** + notary receipt (`molgang.anchor`) — web3 provenance, not a badge.
- 🔄 **Two-way bridge** — Roblox ⇄ Knitweb, alternating every 30 min, over a live HTTP server.

## Quickstart

```bash
# MOLGANG depends on the knitweb package (github.com/knitweb/pulse).
# For local dev, point PYTHONPATH at a knitweb checkout's src:
export PYTHONPATH=src:/path/to/pulse/src

python3 -m molgang.cli          # ▶ narrated session: play, collect, leaderboard, anchor
python3 examples/play_demo.py   # faucet → propose H2O → peers vote with pulses → woven Fiber
python3 examples/p2p_demo.py    # the same, but votes cross REAL sockets between live nodes
PYTHONPATH=.:$PYTHONPATH python3 -m pytest -q    # 13 tests, property-checked

# live bridge endpoint for the Roblox client (POST /upload · GET /snapshot.json):
PYTHONPATH=.:$PYTHONPATH python3 bridge/server.py --port 8787
```

(Installed via `pip`, the client is just `molgang`.)

## Real peer-to-peer

`examples/p2p_demo.py` is not a simulation: each player is a real
`knitweb.p2p.AsyncioP2PNode` on a real TCP port, and every vote is a Knit sent over the wire
through the proposal→accept→finalize handshake. A web of player-nodes forms an actual class.

## Roblox counterpart + two-way bridge

[`roblox/`](roblox/) holds Lua scripts for an easily-deployable **Roblox** version with the
same gameplay (propose a bond, classmates vote with pulses, k-of-n quorum). Roblox plays
locally; the [`bridge/`](bridge/) keeps it and the Knitweb in sync **both ways**, alternating
direction every **30 minutes** (so each direction syncs hourly, and never both in one tick):

- ⬆️ **Upload** (Roblox → Knitweb): each unique **Roblox wallet ID** maps to a *stable*
  knitweb account, every vote replays as a real Knit, and confirmed bonds are woven into Fibers.
- ⬇️ **Download** (Knitweb → molgang): the canonical woven-bonds web + continued balances —
  including bonds woven by other peers or the Python P2P game — flow back so Roblox stays current.

```bash
# cron every 30 min — alternates upload/download automatically (internal cursor):
#   */30 * * * *
PYTHONPATH=src:/path/to/pulse/src python3 bridge/sync.py \
    --state .molgang/state.json --export .molgang/inbox_votes.json \
    --snapshot .molgang/outbox_snapshot.json
```

(`bridge/ingest.py` is the upload half on its own; `bridge/snapshot.py` the download half.)
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Community

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), [`SECURITY.md`](SECURITY.md). License:
[Apache-2.0](LICENSE).
