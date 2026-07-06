# SLO budgets — latency, settle, errors, relay lag

*Closes #125. Load numbers are meaningless without a target: this fixes the budgets that turn
"1M concurrent" into per-ramp **pass/fail gates**. The load harness (`tests/load/ramp.py`)
enforces them without Prometheus; the [Prometheus alert rules](../monitoring/alerts.yml) + the
[setup runbook](../monitoring/README.md) enforce them live. Change a number here and in
`monitoring/alerts.yml` together — they must never drift.*

## The budgets

| SLO | Ceiling | Why |
|---|---|---|
| **`/api/state` p99** | **≤ 150 ms** | The poll every client makes; above this the bar feels laggy. |
| **`/api/vote` p99** | **≤ 400 ms** | A vote stakes a real Knit; a little slower than a read is acceptable, but not sluggish. |
| **quorum-settle p99** (propose→woven) | **≤ 2 s** | From `bar._settle` (the `game.settle` + `knitweb.pouw.quorum` path), timed by `molgang_quorum_settle_seconds` (#125). A knit should weave within a couple of seconds or the loop feels dead. |
| **5xx error rate** | **≤ 0.5 %** | Sustained server errors above this = unhealthy fabric. |
| **relay pull-lag** (`molgang_relay_queue_depth`) | **≤ 500** | The relay must not fall persistently behind or NAT'd peers desync. |

These are **production targets** for a healthy fleet, not a claim that any single instance meets
them at all loads — see the baseline below.

## Measured baseline (single instance, modest ramp)

`python3 tests/load/ramp.py --steps 5,10,15,20 --hold 4` against one `molgang serve`
(Apple-silicon laptop, rate limits off, threaded stdlib server):

| concurrency | `/api/state` p99 | verdict |
|---:|---:|:--|
| 5 | 12 ms | ✅ within budget |
| 10 | 103 ms | ✅ within budget |
| 15 | 164 ms | ❌ over the 150 ms budget |

- **quorum-settle**: a real propose→woven settled in **85 ms** (`molgang_quorum_settle_seconds`),
  well within the 2 s budget — the settle path is fast; latency pressure is at the HTTP read.
- **Interpretation**: one Python instance holds the `/api/state` budget to **~10–15 concurrent**,
  then queues. That is expected — the road to 1M is **not** one bigger box but the fleet + the
  **peer-relay crossover** in [`COST_MODEL.md`](COST_MODEL.md) (#145). This baseline is the line
  future ramps must beat; a regression that pushes the breach point below ~10 shows up here.

## How the budgets are enforced

- **CI / local gate** — `tests/load/ramp.py` asserts every budget per ramp step and **exits
  non-zero at the first breach**, naming the SLO and the measured value vs the ceiling (verified:
  it fails at the step where `/api/state` p99 crosses 150 ms). Wire it into a load job to gate a
  ramp.
- **Live alerting** — `monitoring/alerts.yml` fires a Prometheus alert per breached budget (with a
  `for:` debounce) and clears on recovery. Standing it up + the forced firing→resolved test are in
  [`monitoring/README.md`](../monitoring/README.md).

## Metric names (single source of truth)

| Budget | Metric / query |
|---|---|
| `/api/state`, `/api/vote` p99 | `histogram_quantile(0.99, …molgang_http_request_duration_seconds_bucket{path=…})` |
| quorum-settle p99 | `histogram_quantile(0.99, …molgang_quorum_settle_seconds_bucket)` |
| error rate | `sum(rate(molgang_http_requests_total{code=~"5.."}[5m])) / sum(rate(molgang_http_requests_total[5m]))` |
| relay lag | `molgang_relay_queue_depth` |
