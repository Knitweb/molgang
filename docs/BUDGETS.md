# MOLGANG SLOs — latency & error budgets (#125)

"Healthy at scale" must be testable, not a feeling. These are the fabric's
service-level objectives; the load harness (`tests/load/`) asserts them per ramp
step and the Prometheus alert rules (`monitoring/molgang-alerts.yml`) fire on a
breach. All are computed from the RED histogram the node emits on `/metrics`
(#121); enforcement lives in `src/molgang/slo.py`.

## Ceilings

| SLO | Ceiling | Rationale |
|---|---|---|
| `/api/state` p99 | **150 ms** | the primary poll/render payload — above this the bar feels laggy on mobile |
| `/api/vote` p99 | **300 ms** | casting a vote stakes a real PLS Knit into escrow + may auto-settle; must stay interactive |
| quorum-settle p99 (`/api/propose` → woven) | **500 ms** | the full settle path (bots weigh in, `pouw.quorum` tallies, weave) — the game's core loop |
| error rate | **≤ 1%** | of all requests may return a non-2xx code |
| relay pull-lag | **≤ 2 s** | store-and-forward mailbox drain for NAT'd peers (relay tracing, #124) |

## Enforcement

- **Load harness:** `slo.check_budgets(metrics_text)` returns the breaching SLOs
  (ceiling vs measured); the harness exits non-zero at the first breaching ramp
  step and names it.
- **Alerts:** `monitoring/molgang-alerts.yml` mirrors each ceiling as a
  Prometheus alert on the histogram quantiles / counters.

## Committed baseline (single instance, in-process)

Measured against the real request handler with the standard join→sit→propose→vote
flow (no sockets), on the CI runner:

| Metric | Measured p99 | Ceiling | Headroom |
|---|---|---|---|
| `/api/state` p99 | sub-millisecond (`le=0.001` bucket) | 150 ms | ✓ vast |
| quorum-settle p99 | ≤ few ms | 500 ms | ✓ vast |
| error rate | 0% on the happy path | ≤ 1% | ✓ |

The in-process engine is *far* under budget; the ceilings exist to catch
regressions and to bound the networked/relayed path under a real ramp. Re-run
`tests/load/` on a change to refresh this table; a regression makes a ramp step
breach and the harness names it.
