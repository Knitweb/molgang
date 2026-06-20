# MOLGANG `/api` Contract (v1)

> **Sprint 3 · issue #58 — freeze a versioned `/api` contract as the single seam across the engines.**
> This document is the **source of truth** for the wire protocol. The Python bar
> (`src/molgang/webserver.py`, served by `molgang serve` on `:8765`) is the **canonical engine**;
> the Django dapp (`molgang_web/`) and the PHP node (`php/`) are thin clients/projections that MUST
> conform to the shapes below. The knowledge-graph explorer (`molgang explore`, `:8990`,
> `src/molgang/explorer.py`) serves the read-only `/api/kg/*` family.

## Versioning policy

- Every engine SHOULD expose `GET /api/version` returning `{"api_version": "1", "engine": "<python|django|php>", "molgang": "<pkg version>", "knitweb": "<engine version>"}`. A client detects drift by comparing `api_version`. _(Implemented in all three engines: the canonical Python bar (`webserver.api_version_info()`), the PHP node (`php/public/index.php` `case 'version'`), and the Django dapp (`bar/views.version`, which reuses `api_version_info()`). A CI conformance test (`tests/test_api_version_contract.py`) asserts these literals stay in lockstep. `1` is the current contract.)_
- **Backwards-compatible** changes (new optional response fields, new endpoints) keep `api_version`. **Breaking** changes (renamed/removed fields, changed types) bump it.
- Clients MUST ignore unknown response fields and MUST NOT depend on field ordering.
- Balances shown to a player (`PLS`, silk, knits) are the **knitweb account braid** truth, not an independent counter — PHP/Django projections reconcile to the braid.

## Conventions

- All bodies are JSON (`Content-Type: application/json`); `POST` takes a JSON object.
- A session is identified by an opaque `sid` (from `POST /api/join`); pass it on every authenticated call.
- Errors return a non-2xx status with `{"error": "<message>"}`.

## Bar API — `:8765` (canonical, `webserver.py`)

### Read (GET)

| Endpoint | Query | Returns |
|---|---|---|
| `/api/state` | `sid` | Full session/world state for the seated player + `pulse_host`. The primary poll/push payload (Sprint 3 moves this to a Channels push). |
| `/api/pulse` | — | The host Pulse identity (`{}` if none). |
| `/api/suggested` | — | `{"terms": [string]}` — brainstorm suggestions. |
| `/api/web` | — | `bar.web_view()` — the woven web (knits → Fibers) for the current world. |
| `/api/quests` | `player*` | `{player, active, all, quest_xp}` — tier-graded quest goals derived from woven molecules (#110). Read-only/pure; omit `player` for the whole bar. |
| `/api/device` | `id` | `{"registered": bool, "wallet": object|null}` — wallet-signed device lookup. |
| `/api/graph` | `term` \| `from` \| `to` | Knowledge-graph slice (`world.explore`): a term's neighborhood or a path. |
| `/api/relay` | — | `{"enabled": bool, "base", "topic", "node", "address", "cursor"}` — relay status. |
| `/api/monitor` | — | Compact monitor overview (node/p2p + KG) for the Monitor tab. |
| `/api/monitor/status` | — | Node/p2p liveness + provenance. |
| `/api/monitor/kg/stats` | — | `{nodes, edges, concepts, languages}`. |
| `/api/monitor/kg/hubs` | `n` | Top-`n` hub concepts. |
| `/api/monitor/kg/tension` | — | Taut / slack / snapped fiber bands. |
| `/api/monitor/kg/subgraph` | `term, depth, lang*` | Focused subgraph for the viz (`404` if term absent). |
| `/api/monitor/kg/concept` | `key` | One concept's detail (`404` if absent). |

### Write (POST)

| Endpoint | Body | Returns |
|---|---|---|
| `/api/join` | `{name, avatar?, table?, device?}` | `{sid, avatar, address}` — faucet a player (free silk + pulses), seat them. |
| `/api/sit` | `{sid, table}` | Updated `state`. |
| `/api/table/rename` | `{sid, table, name}` | Updated `state` (name resets when the namer leaves). |
| `/api/propose` | `{sid, term}` | `{pid}` — spin silk into a **Knit** (a term/bond claim). |
| `/api/vote` | `{sid, pid, verdict}` | `{pid, settled, outcome, woven}` — stake a **PLS pulse**; quorum may weave a **Fiber**. |
| `/api/spiral/propose` | `{sid, links[] \| text}` | `{cid, length, state}` — propose a multi-knit spiral. |
| `/api/spiral/vote` | `{sid, cid, verdict}` | `{cid, settled, captured, votes}` — co-weave/validate a spiral. |
| `/api/relay/pull` | — | On-demand drain of the shared web from the relay (`400` if relay disabled). |
| `/api/certificate` | `{sid, mode?}` | A **PoUW Certificate PDF** (binary). `mode` in `{private,bearer,…}` exposes the wallet private key — default is redacted (see Sprint 6 security gate). |

`verdict` ∈ `{"confirm", "mismatch"}` (default `confirm`). Honest peers `confirm` correct chemistry.

## Explorer API — `:8990` (read-only, `explorer.py`)

`GET /api/kg/{stats,tension,hubs,neighbors,path,concept,subgraph,names}` — the knowledge-graph
explorer over the woven p2p web (NetworkX-backed). Read-only; same concept/tension semantics as the
`/api/monitor/kg/*` family above.

## Conformance (Sprint 3)

- `GET /api/version` is implemented on all three engines (Python, PHP, Django). DONE. A textual CI conformance test (`tests/test_api_version_contract.py`) keeps the `api_version` literals in lockstep across `webserver.py`, `php/public/index.php`, and this doc. _(A fuller runtime diff — boot each engine, compare live JSON shapes — is a future enhancement.)_
- Django live tables (issue #29) push the `/api/state` payload over Channels — the websocket message body is identical to this REST shape.
- PHP node (`php/`) projects the same `tables`/`account` top-level keys.

_Status: v1 contract frozen; `/api/version` live on all three engines with a CI conformance test.
Remaining Sprint 3 follow-up: reconcile Django/PHP balance source-of-truth to the
braid._
