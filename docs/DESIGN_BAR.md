# MOLGANG Browser Bar — Design Brief

## 1. Verdict

MOLGANG's browser front end is a **web3-native knowledge bar**: a lobby of tables (rooms) you walk into with an avatar, take a seat, and **knit together** with the other seated peers. The core loop is Jackbox-Drawful's submit-then-vote round mapped onto the protocol you already shipped — a seated player **brainstorms a term and knits it (spends silk)**, the rest of the table **votes with a PLS pulse**, and the real `pouw.quorum` BFT tally either **weaves** it (advancing the proposer's Fiber, anchorable to OriginTrail as a UAL) or refunds the stake. The exact same authoritative state and the same logical actions (`join / sit / propose / vote`) are driven by **humans clicking in a DOM card-room UI** and by **bots polling a single action-manifest endpoint** — one server, one event-sourced state, two thin clients. Value is never an NFT: it is utility (pulses you spend to vote), reputation (XP/level/woven-count rendered at your seat), and the woven-knowledge graph itself. The browser tier ships first as plain DOM/CSS (PokerNow style); the Gather-style walk-around canvas is optional later polish.

## 2. No-NFT economy

Keep the two resources you already have — **silk** (proposal fuel) and **PLS pulses** (vote stake) — and make woven molecules pure reputation. Four borrowed MMO mechanics turn that into stakes + progression without any tradeable layer:

**(a) Closed circular loop — borrowed from Sky Strife's "orb."** Sky Strife runs on a fixed-supply token where creating a match is a flat sink and winners earn back along a rank curve; tokens recirculate and never inflate. MOLGANG already does the redistribution half: `game.settle()` pays the *staked vote-pot* back to the proposer on a confirmed weave and refunds voters on rejection — **nothing is minted on confirmation** (the code comment "Pulses are conserved" is exactly right). The missing half is closing the loop: today silk only ever leaves circulation (`SILK_PER_BOND` is burned in `propose_term`) and pulses only redistribute. Convert silk into a Sky-Strife loop — the burned silk should flow into a **shared table pot** that is redistributed to confirming voters on a successful weave, so silk recirculates between proposer and table instead of being destroyed forever.

**(b) Value = world state, not assets — borrowed from MUD/Dark Forest.** Dark Forest had *no* fungible token and its trophy NFTs went to zero trades; the durable value was persistent state and relative position. This validates your hard constraint directly: the woven molecule (the **Fiber CID** in `Bar.woven`) plus the **OriginTrail UAL** from `anchor_chemistry()` *is* the prize. Lean in: expose each player's woven-knowledge graph as a publicly queryable "portfolio," and never render a transfer/sell affordance on it.

**(c) Reputation via soulbound, one-person-one-vote — borrowed from Buterin's soulbound-token / coin-voting critique.** Coin-voting drifts to "whoever buys influence." So **pulse-vote weight must be a function of earned reputation (XP / level / confirmed-knowledge count from `progression.py`), not silk balance** — and it must be non-transferable. The Fiber and the XP ledger are already non-transferable account-state; this just means the quorum tally should weight a confirmed voter's verdict above a newcomer's.

**(d) Sinks must outpace issuance — borrowed from EVE Online.** Your faucet (`FAUCET_SILK=10`, `FAUCET_PULSES=50` in `game.py`) is a permanent inflation source. EVE's hard lesson: faucets that outpace sinks inflate the currency to worthlessness. Add permanent counter-sinks: (i) **slashing** — silk/pulses staked on a term that *fails* quorum are partly burned, not fully refunded; (ii) **decay** — stale unconfirmed proposals expire and forfeit their silk; (iii) **taboo cost escalation** (see §3). Ship a cheap **"MOLGANG economic report"** (silk minted-vs-burned, pulses staked-vs-redistributed) from day one to force discipline.

**Anti-speculation guarantees:** silk and pulses are the *only* resources; woven molecules are non-transferable reputation anchored to a verifiable UAL; no minting on confirmation (conserved redistribution); faucet matched by slashing + decay sinks. **Sybil resistance is a launch blocker, not a later feature** (Gitcoin's quadratic funding was repeatedly Sybil-attacked): gate the faucet and vote-*counting* behind a reputation threshold — **a newcomer can knit and vote, but their pulse does not count toward quorum until they have earned N confirmations** — plus ESP-style anti-collusion (§3). Optionally add **quadratic pulse cost** (casting k pulses on one term costs k²) so no single seat dominates confirmation.

## 3. The bar

**Lobby / table / seat / avatar model** (already scaffolded in `bar.py`, refine toward the Colyseus room abstraction):
- **Bar = lobby / room-list.** `Bar` holds `tables: dict[str, Table]` with three defaults (`Periodic Bar`, `Organic Lounge`, `Noble Corner`). Each `Table` is one authoritative room instance with a fixed seat cap (`SEATS_PER_TABLE = 6`) — the Colyseus `maxClients` / PokerNow seat-cap pattern. `Bar._seated_count()` already enforces "table is full."
- **Take a seat = server-side reservation keyed to sessionId.** `Bar.sit(sid, table_id)` reserves; add a **seat-reservation timeout** (Colyseus default ~15s to claim) and an **allowReconnection grace window** so a dropped player keeps their chair briefly. Today `Bar.leave()` drops the seat instantly — add the grace window.
- **Avatar in the join packet.** `Bar.join(name, avatar, table)` already carries a cosmetic avatar from the fixed `AVATARS` set (Skribbl login-packet / Jackbox nickname+character pattern). Avatars are assigned/chosen, never owned — zero-friction no-NFT.
- **Seat badge = reputation.** Render avatar + name + XP/level/title (`progression.title_for`) + woven-count at each seat (the Jackbox score-not-ownership model). `Bar.state()` already returns seated lists; extend it with the per-player XP/level/woven badge.

**Per-table knit loop** (`propose → vote → settle` already exists in `bar.py`):
`brainstorm term` → `Bar.propose(sid, term)` spends 1 silk via `game.propose_term` and opens a `Proposal` → seated peers call `Bar.vote(sid, pid, verdict)` which stakes a real PLS Knit into escrow via `game.cast_vote` → once enough peers weigh in (`len(votes) >= max(1, others)`) `Bar._settle()` runs the real `game.settle()` → `pouw.quorum.tally` decides → on `woven` the term is appended to `Bar.woven` with its `fiber_cid` and confirmation count.

**Harden the loop with three GWAP rules** (ESP Game / ConceptNet / Codenames):
- **Output agreement, not assertion.** A knit is woven only when *independent* peers converge — which the BFT quorum already enforces. Good as-is.
- **Taboo terms.** Once a term has been woven enough times at a table, mark it **taboo** so players must brainstorm fresher, harder associations — stops farming trivial links for XP. New state on `Table`.
- **Anti-collusion.** Don't let the same identity-pair repeatedly co-confirm each other; check distinct identities at the faucet choke point. `Proposal.voters` already dedups per-round; add cross-round pair tracking.
- **(Optional) typed, weighted, auto-scored knits.** Evolve a knit from a bare `term` toward a ConceptNet edge `(termA, relation, termB)` with relation from a small fixed set (`IsA, PartOf, UsedFor, ReactsWith, RelatedTo`), weight = independent confirmations, and an **NPMI-over-corpus** plausibility score that sets silk cost/reward (spam scores low, non-obvious links score high). This is a phase-2 enrichment of the existing `Bond`/`term` split.

**Rounds / turns.** Drive each table with Skribbl's **explicit numbered state machine broadcast with a time-remaining field**, so every browser renders the same countdown from the server, not a local timer: `WAITING → BRAINSTORM (seated player types + knits, spends silk) → VOTE (peers cast pulses) → WOVEN/REJECTED (settled by pouw.quorum) → RESULTS/XP → WAITING`. Today `bar.py` is event-driven (settles when enough votes arrive) with no phase clock — add a server-owned phase + deadline per table so turns are fair and an idle proposer can't stall a table. The server is the **only** authority on whether a term is woven.

## 4. Dual play

**Same state, two thin clients — the CB2 "headless core + thin clients" pattern.** All knit/fiber/pulse/quorum logic already lives server-side in `Bar` + `game` + `quorum`; the browser and any bot are dumb callers. They already share the same logical actions in `webserver.py`: `GET /api/state`, `POST /api/{join,sit,propose,vote}`. Keep that invariant — the UI and the bot speak one small typed protocol.

**Add a Crab-Games action-manifest endpoint for bots.** Give agents one endpoint to poll: `GET /api/heartbeat?sid=…` returning a JSON of *everything currently legal* — `{tables_to_join, can_propose, open_knits_to_pulse, my_pulses, my_silk, notifications}`. Bots become stateless ("just act on whatever's in `actions`"); humans hit the same underlying `Bar` methods via the UI. Advance any time-based phase with an **idempotent, status-based server tick** so concurrent polls never double-settle a round.

**Make the event log the source of truth (CB2 event sourcing).** Persist every action (`join/sit/propose/vote/settle`) as a linear, replayable event list. This single log keeps UI and API in sync, gives free replay/audit, feeds the OriginTrail anchor (`anchor_chemistry` already consumes the `Bar.woven` records), and yields a training corpus for bots. Today `Bar` is in-memory only — adding the append-only log is the key durability upgrade.

**State sync: polling now, WebSocket next, given the stdlib server.** `webserver.py` is `http.server.ThreadingHTTPServer` — no native WS. Pragmatic path:
- **Phase 1 (ship first): short-interval polling.** Both humans and bots poll `GET /api/state` (humans) and `GET /api/heartbeat` (bots) every ~1–2s. This works today with zero new infra, matches the Crab-Games agent model, and both client types read the same DB/event-log state on each tick.
- **Phase 2: a WebSocket gateway** (the proven Gather/PokerNow/Skribbl pattern — one WS per joined table, server validates then **broadcasts deltas, not full state**). Since the stdlib `http.server` has no WS, implement a minimal RFC-6455 frame handler in the **knitweb gateway layer** (reusable transport) or accept a single small dependency there. Keep an **HTTP long-poll fallback** for proxy-hostile networks the way Skribbl falls back when the WS handshake fails. Allow the browser to **optimistically** show a pending knit/pulse, then reconcile to the authoritative quorum result and roll back if rejected.

## 5. Build plan

Modularity rule: **reusable transport/sync/Sybil primitives go down into `knitweb` (the gateway); everything bar/UI/game-specific stays in `molgang`.**

**P0 — close the loop the engine is missing (pure `molgang`, no new infra):**
1. **Reputation-weighted quorum** — feed XP/level/confirmed-count into the verdict weighting in `game.settle` / the `quorum.tally` call so a confirmed voter outweighs a newcomer (§2c). Wire `progression.collections()` into `Bar`.
2. **Newcomer-pulse gating** — in `Bar.vote`, a session below N confirmations may cast but its pulse doesn't count toward quorum (Sybil launch-blocker).
3. **Sinks** — add slashing of failed-quorum stakes and stale-proposal decay in `Bar._settle` / a sweep; convert burned silk into the redistributed table pot (Sky-Strife loop).
4. **Per-table phase clock** — add `WAITING/BRAINSTORM/VOTE/RESULTS` + deadline to `Table`, surfaced in `Bar.state()` with `time_remaining`.

**P1 — the dual-play API surface (endpoints in `webserver.py`):**
5. `GET /api/heartbeat?sid=` — Crab-Games action manifest for bots.
6. Extend `GET /api/state` seat objects with the XP/level/title/woven badge (already have `progression.leaderboard`).
7. `GET /api/leaderboard` and `GET /api/portfolio?player=` — expose `progression.leaderboard()` and the per-player woven graph (the no-NFT "portfolio").
8. **Event log** — append-only persistence of all `Bar` mutations (CB2 event sourcing); replace in-memory-only `Bar`.

**P2 — the browser UI (tier-1 DOM/CSS card-room in `web/`, extending `web/index.html`):**
9. Lobby view (table list + seat counts) → click to `sit`.
10. Table view: table `div`, seats absolutely positioned around it, avatars as `<img>`/emoji, the term under construction, a live pulse tally, the phase countdown, a personal `<input>` to propose and pulse buttons to vote (Jackbox shared-view + personal-controller split).
11. Poll `GET /api/state` every ~1.5s; render the broadcast countdown, not a local timer; optimistic pending-knit then reconcile.

**P3 — sync upgrade + provenance + telemetry:**
12. **WebSocket gateway in `knitweb`** (reusable RFC-6455 handler, delta broadcast, ping/pong heartbeat, reconnection grace) + Skribbl-style long-poll fallback. `molgang` consumes it; the transport stays generic.
13. **OriginTrail anchor button/endpoint** — `anchor_chemistry(Bar.woven)` already returns a verifiable UAL; surface it on each woven molecule.
14. **Economic report endpoint** — silk minted-vs-burned, pulses staked-vs-redistributed (EVE-style discipline).

**P4 — optional polish & platform:**
15. Gather-style `<canvas>` walk-around bar (32×32 tiles, one-tile-per-keypress, y-order depth sort) over the DOM tier.
16. Typed/weighted ConceptNet-style knits + NPMI plausibility scoring (§3).
17. Permissionless extension (Pixelaw App2App / Dark Forest open-world model): let agents register "expert tables" and curators against the same API — the existing 2-way Roblox bridge already proves the appetite.

**Key files mapped:** loop & economy → `src/molgang/game.py`, `bar.py`; quorum → `knitweb.pouw.quorum`; reputation → `src/molgang/progression.py`; provenance → `src/molgang/anchor.py` (`anchor_chemistry`); HTTP/API → `src/molgang/webserver.py`; UI → `web/index.html`; reusable WS gateway → **new in `knitweb`**.