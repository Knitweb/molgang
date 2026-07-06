# The 1M-concurrent measurement standard (#128)

A public "1,000,000 concurrent peers" claim is only meaningful if *concurrent*,
*peer*, and *the workload* are defined precisely and measured reproducibly. This
is that definition — the yardstick every load test (#122/#132/#133) and the
public dashboard (#131) must report against, so the number cannot be inflated by
counting idle sockets or one-shot pings.

## Definitions

- **Peer** — a process running the real Knitweb engine (the `molgang.webnode`
  Pyodide peer in a browser tab, or a native `FabricNode`) that holds a wallet,
  a `web_state_root`, and can serve a `fabric-sync` request. NOT: an open TCP
  socket, an HTTP poll, or a bot with no engine.
- **Concurrent** — a peer is concurrent in a measurement window `W` (default
  60 s) iff it (a) held a live session for the whole window AND (b) completed at
  least one **useful protocol round** in `W`: a woven Knit, a cast vote that
  settled, or a successful `sync_from` that changed or confirmed its state root.
  Idle-but-connected does not count.
- **The workload** — the GTA6 comparison workload (see below), not a synthetic
  echo. Concurrency is reported at the workload's steady state, not its peak
  connection count.

## What is reported (RED, per the /metrics contract, #121)

For each window: concurrent-peer count (by the definition above), request rate,
error rate, and the **p50/p95/p99 quorum-settle latency** and **sync-convergence
latency**. A run publishes the raw histogram, not just a headline — the
`molgang_http_request_duration_seconds` buckets and
`molgang_knit_woven_total` deltas are the primary evidence.

## The GTA6 comparison workload

A steady mix per concurrent peer per window: propose ~1 knit, cast ~3 votes on
peers' knits, run ~1 anti-entropy `sync_from`. This exercises the settle path
(economic + quorum), the gossip path, and the reconvergence path together — the
three costs that actually scale. The comparison to a launch-day AAA title is
*sustained concurrency under a real read+write mix*, explicitly NOT raw
connection count.

## Reproducibility rules

- Every reported number cites the git commit, the window `W`, the peer count,
  and the raw `/metrics` scrape.
- No silent truncation: if a run sampled, capped, or dropped peers, it says so.
- Deterministic where possible: simulated-network runs (no sockets) use injected
  clocks/RNG so a claim can be re-derived, exactly like the engine's tests.

## Go/no-go coupling

The public "N concurrent" figure is valid for launch only if measured under this
standard; the S10 runbook treats an unqualified or non-reproducible number as
**no-go**.
