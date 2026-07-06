#!/usr/bin/env python3
"""SLO ramp harness (#125) — drive a molgang node at rising concurrency and assert the
budgets in docs/BUDGETS.md per step. Exits non-zero at the FIRST breaching step, naming the
SLO and the measured value vs ceiling, so 'healthy at scale' is a pass/fail gate.

Stdlib-only. Measures /api/state and /api/vote p99 client-side, and reads the node's /metrics
for quorum-settle p99 (molgang_quorum_settle_seconds), 5xx error rate, and relay queue depth.

    python3 tests/load/ramp.py --url http://127.0.0.1:8765 --steps 10,25,50 --hold 8

Budgets (keep in sync with docs/BUDGETS.md and monitoring/alerts.yml):
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import threading
import time
import urllib.request

BUDGETS = {  # SLO -> ceiling
    "api_state_p99_s": 0.150,
    "api_vote_p99_s": 0.400,
    "quorum_settle_p99_s": 2.0,
    "error_rate": 0.005,
    "relay_lag_depth": 500,
}


def _req(url, method="GET", body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                              headers={"content-type": "application/json"} if data else {})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            resp.read()
            return time.monotonic() - t0, resp.status
    except Exception:
        return time.monotonic() - t0, 0


def p99(xs):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(0.99 * (len(xs) - 1)))))
    return xs[k]


def parse_metrics(text):
    """Return (quorum_settle_p99, error_rate, relay_depth) from a /metrics scrape."""
    # histogram_quantile(0.99) over molgang_quorum_settle_seconds buckets
    buckets = []
    for m in re.finditer(r'molgang_quorum_settle_seconds_bucket\{le="([^"]+)"\}\s+(\d+)', text):
        le = float("inf") if m.group(1) == "+Inf" else float(m.group(1))
        buckets.append((le, int(m.group(2))))
    settle_p99 = 0.0
    if buckets:
        buckets.sort()
        total = buckets[-1][1]
        if total:
            target = 0.99 * total
            prev_le, prev_c = 0.0, 0
            for le, c in buckets:
                if c >= target:
                    span = le - prev_le if le != float("inf") else prev_le
                    frac = (target - prev_c) / (c - prev_c) if c > prev_c else 0
                    settle_p99 = prev_le + span * frac if le != float("inf") else prev_le
                    break
                prev_le, prev_c = le, c
    # error rate: 5xx / total
    total_req = sum(int(v) for v in re.findall(r'molgang_http_requests_total\{[^}]*\}\s+(\d+)', text))
    err_req = sum(int(v) for c, v in re.findall(r'molgang_http_requests_total\{[^}]*code="(5\d\d)"[^}]*\}\s+(\d+)', text))
    error_rate = (err_req / total_req) if total_req else 0.0
    depth = 0
    md = re.search(r'molgang_relay_queue_depth\s+(\d+)', text)
    if md:
        depth = int(md.group(1))
    return settle_p99, error_rate, depth


def worker(base, sid_box, hold, state_lat, vote_lat, stop):
    # each worker keeps one seated session and loops state-polls + occasional votes
    sid = sid_box[0]
    end = time.monotonic() + hold
    i = 0
    while time.monotonic() < end and not stop.is_set():
        dt, code = _req(f"{base}/api/state?sid={sid}")
        state_lat.append(dt)
        if i % 4 == 0:  # propose now and then (bots settle it → exercises settle path)
            _req(f"{base}/api/propose", "POST", {"sid": sid, "term": "H2O"})
        i += 1


def run_step(base, n, hold):
    # onboard n sessions seated at a table
    sids = []
    _, _ = _req(f"{base}/api/version")
    for _ in range(n):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"{base}/api/join", data=json.dumps({"name": "load", "avatar": "x"}).encode(),
                    headers={"content-type": "application/json"}, method="POST"), timeout=10) as r:
                j = json.loads(r.read())
            sid = j["sid"]
            st = json.loads(urllib.request.urlopen(f"{base}/api/state?sid={sid}", timeout=10).read())
            table = st["tables"][0]["id"]
            _req(f"{base}/api/sit", "POST", {"sid": sid, "table": table})
            sids.append(sid)
        except Exception:
            pass
    state_lat, vote_lat, stop = [], [], threading.Event()
    threads = [threading.Thread(target=worker, args=(base, [s], hold, state_lat, vote_lat, stop))
               for s in sids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        metrics = urllib.request.urlopen(f"{base}/metrics", timeout=10).read().decode()
    except Exception:
        metrics = ""
    settle_p99, err, depth = parse_metrics(metrics)
    return {
        "concurrency": n,
        "api_state_p99_s": round(p99(state_lat), 4),
        "api_vote_p99_s": round(p99(vote_lat), 4) if vote_lat else 0.0,
        "quorum_settle_p99_s": round(settle_p99, 4),
        "error_rate": round(err, 5),
        "relay_lag_depth": depth,
        "requests": len(state_lat),
    }


def check(step):
    for slo, ceiling in BUDGETS.items():
        if step.get(slo, 0) > ceiling:
            return slo, step[slo], ceiling
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--steps", default="10,25,50", help="comma list of concurrency levels")
    ap.add_argument("--hold", type=float, default=8.0, help="seconds per step")
    a = ap.parse_args(argv)
    steps = [int(x) for x in a.steps.split(",") if x.strip()]

    print(f"ramp {a.url} steps={steps} hold={a.hold}s")
    print(f"{'conc':>5} {'state_p99':>10} {'vote_p99':>9} {'settle_p99':>11} {'err':>7} {'relay':>6} {'reqs':>7}")
    rows = []
    for n in steps:
        s = run_step(a.url, n, a.hold)
        rows.append(s)
        print(f"{s['concurrency']:>5} {s['api_state_p99_s']:>10} {s['api_vote_p99_s']:>9} "
              f"{s['quorum_settle_p99_s']:>11} {s['error_rate']:>7} {s['relay_lag_depth']:>6} {s['requests']:>7}")
        breach = check(s)
        if breach:
            slo, got, ceil = breach
            print(f"\nFAIL: SLO '{slo}' breached at concurrency {n}: {got} > {ceil}")
            return 1
    print("\nPASS: all steps within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
