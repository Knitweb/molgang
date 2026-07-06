# The 1M-concurrent measurement standard

*Closes #128. The single, auditable yardstick the whole road-to-1M sprint measures against, so
the "1M concurrent / beat GTA6" claim is defensible rather than marketing. Everyone —
`monitor.py`, the public dashboard, the load driver (#132/#133) — reports **exactly** these
definitions.*

## The unit: a concurrent peer

A **concurrent peer** is a **distinct signed identity**, not a socket, browser tab, or IP. It
counts as concurrent at time *t* only if **all** of the following hold:

1. **Identity** — it is a distinct onboarded identity in `node_registry`, keyed by its
   secp256k1 **pubkey** (onboarding via `php/src/Onboard.php`). One wallet = one peer, no matter
   how many tabs, devices, or regions it appears from.
2. **Liveness** — it pinged presence within the online window
   `Relay::ONLINE_WINDOW_S` (currently **120 s**; `php/src/Relay.php`, mirrored by
   `molgang.relay_sync`). A peer last seen > 120 s ago is **offline**, not concurrent.
3. **Activity floor** — presence alone does **not** count. Within the same window the identity
   must have at least one **real** unit of useful work: a `game.py` `propose` / `cast_vote` /
   `settle`, or a relay-woven `WovenItem`. Idle lurkers and pure presence beacons are excluded.

> Rationale: GTA6's reference figure is *concurrent players actually in the world*. Counting
> sockets or idle presence would let us inflate the number dishonestly; the activity floor makes
> our count **at least as honest** as the figure we compare against.

## Canonical counting recipe

Count over `node_registry` joined to the relay message log, deduped by pubkey, at a snapshot *t*:

```sql
-- concurrent peers at snapshot :t (window W = ONLINE_WINDOW_S = 120)
SELECT COUNT(DISTINCT r.pubkey) AS concurrent_peers
FROM   node_registry r
JOIN   relay_log      m ON m.pubkey = r.pubkey
WHERE  r.last_presence_ts >= :t - :W          -- liveness (rule 2)
  AND  m.kind IN ('propose','vote','settle','woven')   -- activity floor (rule 3)
  AND  m.ts   >= :t - :W;                       -- work within the same window
```

- **Dedup by pubkey** is mandatory (rule 1). A wallet appearing from multiple regions/relays is
  **one** peer — the `COUNT(DISTINCT r.pubkey)` enforces it.
- **Synthetic vs human are tallied separately, then summed.** agentplay swarm peers
  (`source:agentplay`) carry a synthetic marker in `node_registry`; report
  `concurrent_peers_human`, `concurrent_peers_synthetic`, and their sum
  `concurrent_peers_total`. A claim states which figure it means — never silently mixing.

## The GTA6 win condition (falsifiable)

The claim "we beat GTA6" is **true iff**, for a sustained window, both hold:

- **Concurrency floor** — `concurrent_peers_total ≥ N_target` held continuously for
  **≥ T_sustain minutes** (not a one-second spike). Initial target for the GTA6 comparison:
  `N_target = 1_000_000`, `T_sustain = 30` min.
- **Useful-work floor** — over that same window, non-zero and sustained useful-work throughput:
  a minimum rate of confirmed `settle`/`woven` events (not just proposes), proving the peers are
  *doing chemistry*, not idling. Report `useful_work_events_per_min`.

A run that hits the head-count but flatlines useful work **does not** win — that would be a
presence farm, exactly what the activity floor exists to reject.

## Anti-gaming rules

- **One wallet, one peer** — dedup by pubkey across all regions/relays (rule 1).
- **No socket/tab inflation** — the unit is the identity, not the connection.
- **No presence-only counting** — the activity floor (rule 3) is mandatory.
- **Human/synthetic never silently merged** — always report the split and label the headline.
- **Window is fixed and single-sourced** — `ONLINE_WINDOW_S` in `php/src/Relay.php` is the one
  definition; `molgang.relay_sync` and any dashboard must read/mirror it, not redefine it.

## Dashboard metric names (single source of truth)

`monitor.py` and the public dashboard MUST expose exactly these names, matching the definitions
above so a viewer can audit the claim:

| Metric | Meaning |
|---|---|
| `concurrent_peers_human` | rule 1–3, human identities |
| `concurrent_peers_synthetic` | rule 1–3, agentplay identities |
| `concurrent_peers_total` | sum of the two |
| `useful_work_events_per_min` | confirmed settle/woven rate in the window |
| `online_window_s` | the live value of `Relay::ONLINE_WINDOW_S` |

## Sign-off

Per #128's acceptance, this document is the sprint's source of truth once a maintainer signs off.
Downstream issues (dashboard, load driver #132/#133, budgets #125) reference these definitions
rather than inventing their own.
