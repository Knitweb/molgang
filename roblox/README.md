# MOLGANG — Roblox counterpart

An easily-deployable Roblox version of MOLGANG with the **same gameplay** as the Python
client: open the faucet (free pulses + silk), propose a chemistry **bond**, classmates **vote
with their pulses**, and a bond is accepted on a **BFT k-of-n quorum**. These Lua modules
mirror `src/molgang/*.py` 1:1.

## Files

| Module | Mirrors | Role |
|---|---|---|
| `Chemistry.lua` | `chemistry.py` | element + molecule table, formula parser, `isCorrect` |
| `Game.lua` | `game.py` | faucet, `propose`, `castVote`, `settle` (same quorum rule) |
| `VoteExport.lua` | (bridge feed) | buffers settled rounds + serializes the export JSON |
| `Sync.lua` | `bridge/sync.py` | **two-way** bridge client, alternating every 30 min |

## Deploy in Roblox Studio

1. Put `Chemistry.lua` and `Game.lua` as **ModuleScripts** under
   `ReplicatedStorage/MOLGANG`.
2. Put `VoteExport.lua` under `ServerScriptService` and enable **HTTP Requests**
   (Game Settings → Security → Allow HTTP Requests).
3. The **Roblox wallet id** for each player is their `Player.UserId` — pass it to
   `Game.newPlayer(player.UserId, player.Name)`. This is the unique id the bridge keys on.
4. After each `Game.settle(round)`, call `VoteExport.record(round)`.
5. Once, on server start, start the **two-way** loop:
   `Sync.start("https://<bridge>/upload", "https://<bridge>/snapshot.json")`.
6. Use `Sync.isConfirmed(formula)` / `Sync.players` in the UI to show what the wider Knitweb
   has confirmed and each player's continued balance.

## The two-way weave (alternating every 30 minutes)

Roblox plays autonomously; the bridge keeps it and the Knitweb in sync **both ways**,
alternating direction every 30 min (so each direction is hourly, never both at once):

- ⬆️ **Upload tick** — `Sync.lua` POSTs the buffered votes (shape of
  [`../bridge/sample_roblox_votes.json`](../bridge/sample_roblox_votes.json)) to an endpoint
  running [`../bridge/sync.py`](../bridge/sync.py). The bridge maps every unique **Roblox
  wallet id** → a *stable* knitweb account (balance **continued** across cycles), replays each
  vote as a **real Knit**, tallies with the real `knitweb.pouw.quorum`, and **weaves**
  confirmed bonds into Fibers.
- ⬇️ **Download tick** — `Sync.lua` GETs the canonical knitweb snapshot
  ([`../bridge/snapshot.py`](../bridge/snapshot.py) output) and applies it: which bonds are
  confirmed network-wide (**including bonds woven by the Python P2P game / other peers**) and
  each player's continued balance.

So every Roblox player keeps a real, consistent knitweb identity, and updates flow **both**
directions on a 30-minute alternating cadence.

> Vocabulary: Web · Knitweb · Knit · Pulse · Fiber — never "loom". PLS = pulses.
