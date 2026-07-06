# Cost model & the peer-relay crossover

*Closes the gap in #145 (G7). Bounds the $ cost of the relay fleet on the road to 1M
concurrent peers, and models the crossover where peer-run relays replace paid ones — so the
"players are the infra, not a server farm" claim is quantified, not asserted. Figures are
engineering estimates with stated assumptions, not guarantees.*

## The three infra layers

MOLGANG's serverless claim does **not** mean "no paid boxes ever"; it means paid boxes are a
thin, bounded bootstrap layer whose share of the load falls as peers arrive.

| Layer | What it does | Who pays | Scales with N? |
|---|---|---|---|
| **A · Bootstrap/backend** | `molgang serve` API + a stable entry point (`DEPLOY.md`: Fly.io / Render / VPS / Pi) | project | **No** — fixed small fleet |
| **B · HTTPS relay/presence** | `5mart.ml` PHP `/api/relay/*` + `/api/onboard/*`, presence, mailbox for NAT'd peers | project | Sub-linear — only NAT-blocked peers + gossip fan-in |
| **C · Peer-run relays** | Players port-open (`molgang serve`) and carry relay/presence for others; DePIN-rewarded | **peers** (earn PLS) | **Yes** — grows *with* N |

The cost question is: how much of layer B must the project pay for at N peers, and when does
layer C carry enough that project $ stops growing?

## Parametric cost model

Let **N** = concurrent peers. Define (assumptions, tune from measurement — see #128/#133):

- `f_nat` — fraction of peers that cannot accept inbound and must lean on a relay mailbox.
  Assume **0.6** (mobile + CGNAT heavy).
- `r_peer` — relay capacity of one peer-run node (layer C), in relayed-peers served.
  Conservative **50**.
- `p_open` — fraction of peers that port-open and run as a layer-C relay. Starts near **0**,
  rises with the DePIN reward (ECONOMY.md) and the "run a node" funnel.
- `C_A` — fixed monthly $ for layer A. One always-on small instance ≈ **$5–25/mo**
  (Fly.io/Render/VPS per `DEPLOY.md`); a 3-box HA fleet ≈ **$15–75/mo**.
- `c_relay` — marginal $/month of paid relay capacity per 1,000 NAT'd peers it must carry
  (bandwidth + presence). Estimate **$3–10 per 1k** on commodity hosting.

**Relayed peers not covered by layer C:**

```
uncovered(N) = max(0, f_nat·N − p_open·N·r_peer)
```

**Monthly project cost:**

```
$(N) = C_A + c_relay · uncovered(N) / 1000
```

## The crossover

Paid relay cost stays flat once peer-run relays cover the NAT'd population, i.e. when

```
p_open · r_peer ≥ f_nat      ⟹      p_open* = f_nat / r_peer
```

With the assumptions above: **p_open\* = 0.6 / 50 = 1.2 %**. Once ~1 in 80 peers runs an
open node, layer C covers the relayed population and `uncovered(N) → 0`, so `$(N) → C_A` — a
**flat ~$15–75/mo** regardless of whether N is 10³ or 10⁶.

| Scenario | p_open | N = 100k | N = 1M |
|---|---|---|---|
| **Cold launch** (no peer relays) | 0 % | ~$180–600/mo | ~$1.8k–6k/mo |
| **Early** (0.5 % open) | 0.5 % | ~$105–350/mo | ~$1.05k–3.5k/mo |
| **At crossover** (≥1.2 % open) | ≥1.2 % | **~$15–75/mo** | **~$15–75/mo** |

*(`c_relay` mid-estimate; layer A HA fleet.)* The launch $ is therefore **bounded**: even the
cold-launch worst case at 1M is low thousands/month, and any realistic open-node rate collapses
it to the fixed layer-A floor.

## Why peers actually run relays (incentive crossover)

Layer C only materialises if running an open node pays. It does, through the same economy that
rewards useful chemistry work:

- **DePIN reward** — a port-open node carrying relay/presence is useful work and earns PLS,
  the same integer-only reward path as validation (ECONOMY.md, `ROUND_REWARD_BANK_PLS`).
- **No new issuance surface** — relay rewards must come from the existing capped reward bank,
  not a new mint (ECONOMY.md invariant: issuance surfaces are reviewed constants in `game.py`).
- **Reputation** — uptime as a relay is non-transferable standing, like woven-work reputation.

So the crossover is self-reinforcing: more peers → more relay demand → more DePIN reward per
open node → more open nodes → paid relays needed for a *smaller* share → project $ flat.

## What this bounds, and the open follow-ups

- **Bounds**: project monthly $ is `C_A + c_relay·uncovered(N)/1000`, flat at `C_A` past a
  ~1 % open-node rate — the "decentralized" claim is now a measurable target, not a slogan.
- **Must measure to firm up** (`f_nat`, `r_peer`, `c_relay`): the 1M measurement standard
  (#128) and the load driver / swarm (#132, #133) provide the real numbers; the DePIN relay
  reward itself is the peer-run-relay work (G8) that makes layer C pay.
