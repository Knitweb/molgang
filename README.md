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

**One command (macOS / Linux)** — sets up a venv, fetches the knitweb engine, and gives you a
`molgang` command:

```bash
git clone https://github.com/knitweb/molgang.git && cd molgang
./install.sh
source .venv/bin/activate

molgang serve     # 🍸 the browser bar       →  http://localhost:8765
molgang seed --world chem_web.json   # 🌱 weave the full chemistry curriculum into a fabric
molgang explore --web chem_web.json  # 🕸 knowledge-graph explorer →  http://localhost:8990
molgang           # a narrated session in the terminal
molgang play      # interactive terminal
molgang doctor    # check your setup
molgang certificate --wallet wallet.json   # 🏅 public PoUW Certificate PDF
# bearer export, local-only and explicit:
# molgang certificate --wallet wallet.json --private --confirm-private-key-export
```

Public nodes should keep the built-in API limiter enabled. The defaults allow `240` reads/min,
`60` ordinary writes/min, `20` costly writes/min, and `10` certificate renders/5 min per source
and actor. Tune with `MOLGANG_RATE_*` env vars or `molgang serve --rate-read ... --rate-write ...`;
set a limit to `0` only for a trusted local run.

**Prefer no install?** Clone the knitweb engine next to this repo — the bootstrap auto-finds
it, so there's no `PYTHONPATH` to juggle:

```bash
git clone https://github.com/knitweb/pulse.git ../pulse   # if you don't have it
PYTHONPATH=src python3 -m molgang.cli serve                # then open http://localhost:8765
```

(See [`examples/`](examples/) for the headless `play_demo.py` / `p2p_demo.py`, and run the
tests with `PYTHONPATH=.:src:../pulse/src python3 -m pytest -q`.)

E2E browser smoke test (headless Playwright):

```bash
PYTHONPATH=src:../pulse/src python tests/e2e/molgang_e2e.py
```

The script starts a clean one-shot Molgang server in temporary files, runs:
walk-in → sit → knit → woven, saves screenshots in `.artifacts/e2e/`, and exits
non-zero when the flow does not complete.

## The browser bar

`molgang serve` opens a **dapp-style** bar: take a seat at a table with an avatar, **brainstorm a
term and knit it** (1 silk), and the table **votes with pulses** — a quorum weaves it into a
Fiber. Your **PLS balance, silk, and knits** are always in the header; **📒 My knits** lists each
knit with its votes and woven Fiber; **🔭 Explorer** shows competing knits for a topic in
side-by-side columns (best first). Same `/api/*` endpoints drive bots, so it's machine-playable
too. No NFTs — value is pulses, reputation, and woven knowledge. See
[`ECONOMY.md`](ECONOMY.md) for PLS/silk sources, sinks, and invariants.

**🏅 PoUW Certificate.** The header's **🏅 Request PoUW Certificate** button (and
`POST /api/certificate {sid}`) downloads an official PDF that documents your wallet and your
**Proof of Useful Work**: how many **pulses** you used, the **knits/spirals woven and votes cast**,
and the shared web's OriginTrail UAL. The browser/API path is always **public mode**: private
wallet material is redacted. Bearer/private-key certificates are local operator exports only via
`molgang certificate --private --confirm-private-key-export`.

### Django front-end (`molgang_web/`)

The same bar also runs over **Django**, as a thin wrapper around the (Django-free) engine —
one `Bar` process singleton shared across requests, the same `/api/*` endpoints (DRF JSON),
and the same `web/` dapp UI served at the root, so the existing client runs unchanged:

```bash
python3 -m pip install -r molgang_web/requirements.txt
PYTHONPATH=src python3 molgang_web/manage.py runserver 8799   # → http://localhost:8799
```

This is increment 1 (Bar singleton + API + UI). Live tables via Channels/websockets and the
HTMX/dapp polish land in follow-up PRs. The engine stays Django-free — Django imports it,
never the reverse.

## The knowledge-graph explorer

`molgang explore` opens an interactive **NetworkX** lens on the *state* of the woven p2p web at
**http://localhost:8990** — built for the 523-concept, 4-language (EN / RU / ZH / AR) chemistry
graph. It loads a knitweb `gateway.App` store dump into a `networkx.MultiDiGraph` (reusing
[`src/molgang/graphx.py`](src/molgang/graphx.py)) and serves a single-page UI plus a JSON API:

```bash
# point it at a woven web (a gateway.App store dump); falls back to a tiny sample if absent
PYTHONPATH=src:../pulse/src python3 -m molgang.explorer --web /tmp/chem_web.json --port 8990
# or, as an alternate source, the shared molgang world:
python3 -m molgang.explorer --world ~/.molgang/world.json
```

| endpoint | returns |
| --- | --- |
| `GET /` | interactive UI (search, language filter EN/RU/ZH/AR, path finder, hubs, stats) |
| `GET /api/kg/stats` | nodes/edges/clusters/density + **per-language** `label:<lang>` counts |
| `GET /api/kg/hubs` | top terms by degree + centrality |
| `GET /api/kg/neighbors?term=` | in/out neighbours with relations |
| `GET /api/kg/path?from=&to=` | shortest path |
| `GET /api/kg/concept?key=H2O` | the concept's 4 language labels (water / вода / 水 / ماء) + relations |
| `GET /api/kg/subgraph?term=&depth=2` | a focused subgraph (nodes+edges) for the viz |

The viz never renders all ~2600 nodes at once: it centres on a searched term or the top hub and
expands focused subgraphs on click, so it stays interactive. Arabic labels render RTL.

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

## For teachers

MOLGANG is a graded elementary-to-high-school chemistry curriculum played as peer review — and the
value is **reputation/woven-knowledge only, never tokens or NFTs**. See
[`docs/CURRICULUM.md`](docs/CURRICULUM.md) for the tier↔learning-objective mapping and a quick-start
for running a class session (`molgang serve` or the 5mart.ml node), including where students find
quests, achievements, and the seasonal leaderboard.

## Community

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), [`SECURITY.md`](SECURITY.md). License:
[Apache-2.0](LICENSE).
