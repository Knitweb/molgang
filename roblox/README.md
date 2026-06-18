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
| `VoteExport.lua` | (bridge feed) | buffers settled rounds, exports hourly to the bridge |

## Deploy in Roblox Studio

1. Put `Chemistry.lua` and `Game.lua` as **ModuleScripts** under
   `ReplicatedStorage/MOLGANG`.
2. Put `VoteExport.lua` under `ServerScriptService` and enable **HTTP Requests**
   (Game Settings → Security → Allow HTTP Requests).
3. The **Roblox wallet id** for each player is their `Player.UserId` — pass it to
   `Game.newPlayer(player.UserId, player.Name)`. This is the unique id the bridge keys on.
4. After each `Game.settle(round)`, call `VoteExport.record(round)`.
5. Once, on server start: `VoteExport.startHourlyExport("https://<your-bridge>/ingest")`.

## The hourly weave into the Knitweb

Roblox plays autonomously; **only once an hour** do we copy all the votes out and weave them
into the real Knitweb. `VoteExport` POSTs a JSON payload (see
[`../bridge/sample_roblox_votes.json`](../bridge/sample_roblox_votes.json) for the exact
shape) to a small ingestion endpoint that runs [`../bridge/ingest.py`](../bridge/ingest.py).
The bridge then:

- maps every unique **Roblox wallet id** → a *stable* knitweb account (`Player.from_roblox`),
- replays each vote as a **real Knit** (a staked pulse),
- tallies with the real `knitweb.pouw.quorum`, and **weaves** confirmed bonds into Fibers.

So the Roblox classroom and the Knitweb stay in sync at an hourly cadence, and every Roblox
player ends up with a real, consistent knitweb identity and woven chemistry.

> Vocabulary: Web · Knitweb · Knit · Pulse · Fiber — never "loom". PLS = pulses.
