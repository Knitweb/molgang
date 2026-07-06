# Monitoring the SLO budgets with Prometheus

The molgang node already exports Prometheus metrics at **`/metrics`** (RED histograms +
domain gauges, #121, plus `molgang_quorum_settle_seconds` from #125). This directory adds the
**SLO alert rules** (`alerts.yml`) that fire when a budget in [`../docs/BUDGETS.md`](../docs/BUDGETS.md)
is breached. The load harness (`../tests/load/ramp.py`) enforces the same budgets in CI without
Prometheus; Prometheus is for **live** alerting.

## 1. Point Prometheus at a node

```bash
molgang serve                       # exposes /metrics on :8765
prometheus --config.file=monitoring/prometheus.example.yml
```

`prometheus.example.yml` scrapes `127.0.0.1:8765/metrics` every 15 s and loads `alerts.yml`.
Adjust `targets:` for your host/port; add more targets for a multi-instance fleet.
(Grafana Agent / Grafana Cloud work the same way — scrape `/metrics`, import `alerts.yml`.)

## 2. Confirm the rules load

Open `http://localhost:9090/rules` — the five `molgang-slo` rules should be listed as *ok*.
`http://localhost:9090/alerts` lists them as *inactive* on a healthy, idle node.

## 3. Force a breach (the acceptance test)

Prove an alert goes **firing** and then **resolved**:

- **Quorum-settle / API-latency**: drive load past the budget with the harness in *soak* mode
  against a throttled node, or add artificial latency:
  ```bash
  # hammer /api/vote to push its p99 over 400 ms on a small box
  python3 tests/load/ramp.py --url http://127.0.0.1:8765 --steps 200,500,1000 --hold 60
  ```
- **Error rate**: point a target at a stopped node (5xx/scrape failure) briefly.
- **Relay lag**: let the relay queue back up (pause the puller) so `molgang_relay_queue_depth`
  climbs over 500.

Within the rule's `for:` window the alert appears on `/alerts` as **FIRING**; once the node
recovers it returns to **inactive** (resolved). That firing→resolved transition is the #125
acceptance for "alerts fire in a forced test and clear when healthy."

## Budgets (single source of truth: `../docs/BUDGETS.md`)

| SLO | Budget | Alert |
|---|---|---|
| `/api/state` p99 | ≤ 150 ms | `ApiStateP99Breach` |
| `/api/vote` p99 | ≤ 400 ms | `ApiVoteP99Breach` |
| quorum-settle p99 (propose→woven) | ≤ 2 s | `QuorumSettleP99Breach` |
| 5xx error rate | ≤ 0.5 % | `HttpErrorRateBreach` |
| relay pull-lag (queue depth) | ≤ 500 | `RelayLagBreach` |

Change a threshold in **both** `alerts.yml` and `docs/BUDGETS.md` so they never drift.
