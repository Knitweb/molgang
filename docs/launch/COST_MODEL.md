# Launch cost model + peer-relay incentive crossover (#145)

Bounds launch-wave spend and states the point where paying peers to relay is
cheaper than scaling a central relay fleet — so the economy is understood before
the faucet opens, not after.

## What actually costs money

The pure-P2P dapp has **no backend**, so the only central cost surface is the
**relay** (NAT store-and-forward / hole-punch coordination, #89) and static
hosting. Everything else — the engine, quorum, weaving — runs on the peers.

| Cost | Driver | Bound / lever |
|---|---|---|
| Static hosting / CDN (#144) | app-shell + engine-wheel bytes × cold loads | cache-immutable; the service worker serves repeat loads from cache — a returning peer costs ~0 |
| Relay bandwidth (#129) | NAT'd peers × coordination + fallback traffic | hole-punch (#89) moves traffic *direct* after a brief handshake; only symmetric-NAT peers stay on the relay mailbox |
| Relay compute | requests/s at the flash crowd | per-source rate caps (#130); multi-relay fan-out (#95) spreads it |

## The µPLS emission bound (from TOKENOMICS.md)

Fresh PLS minted per confirmed knit is bounded by
`PROPOSER_BASE_REWARD + MAX_USEFULNESS_BONUS + confirms·VOTER_CONFIRM_REWARD`
≤ **89 PLS** at a 24-seat table. PLS is an accounting unit, not a fiat cost — but
the faucet **grant** (phase-1 up to 10M PLS/device-day) is the sybil-exposure
lever, capped per source in the registry. A launch kill-switch throttles the
faucet grant, not the play rewards.

## Peer-relay incentive crossover

Let `C_relay` be the €/GB-month of central relay bandwidth and `R_peer` the PLS
paid to a peer that relays a GB for others (#138 PoUW reward for relay
operators). Paying peers to relay is net-cheaper once:

```
demand_GB × C_relay  >  peers_relaying × R_peer_GB × (€/PLS)
```

Because relayed traffic scales with the NAT'd fraction while direct hole-punched
traffic does not, the central relay cost grows sub-linearly with total peers,
and the crossover is reached early in the launch wave — the design goal: **fabric
capacity scales with the player count, not with one PHP box** (#89 rationale).

## Launch-wave spend bound

Projected central spend for a wave of `P` peers over the wave window is
`hosting(P) + relay_bw(NAT_frac·P) + relay_compute(rate)`, each with the lever
above. The runbook requires this projection to be inside budget (with the
kill-switch as backstop) before go.
