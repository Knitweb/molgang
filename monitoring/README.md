# MOLGANG monitoring stack (#123)

A committed, reproducible Prometheus + Grafana pair over the stdlib `/metrics`
exposition (#121), with the SLO alert rules from #125 loaded into Prometheus.

## Bring it up

```bash
# 1. something to watch — a local peer with metrics on (default port 8765)
PYTHONPATH=src:../pulse/src python -m molgang.cli serve

# 2. the stack
docker compose -f monitoring/docker-compose.yml up
```

* Grafana: <http://localhost:3000> — anonymous viewer; the **MOLGANG — RED + weave**
  board is provisioned from `grafana/dashboards/molgang-red.json`, no clicks needed.
* Prometheus: <http://localhost:9090> — scrape config in `prometheus.yml`,
  alert rules from `molgang-alerts.yml` (budgets mirror `docs/BUDGETS.md`).

## The board

RED panels (request rate by path, error fraction vs the 1% budget, p50/p95/p99
latency), quorum-settle p99 for `/api/propose`–`/api/vote`–`/api/state` against
their #125 budgets, weave throughput (proposed vs woven knits/s), votes by
verdict, and inflight requests — the tail-latency + settle picture to watch
while ramping the swarm (road-to-1M, `docs/MEASUREMENT.md`).

## Watching a deployed peer

The Fly/Render/VPS deploys from `DEPLOY.md` serve the same `/metrics` path —
add the instance under the `molgang-peers` job in `prometheus.yml`:

```yaml
  - job_name: molgang-peers
    metrics_path: /metrics
    static_configs:
      - targets: ["molgang.fly.dev:443"]
        labels: { role: peer }
```

(For HTTPS targets add `scheme: https` to the job.)

## Linking the board from the game

`molgang serve` surfaces the board read-only in the Monitor tab when the
operator sets:

```bash
MOLGANG_GRAFANA_URL=http://localhost:3000/d/molgang-red python -m molgang.cli serve
```
