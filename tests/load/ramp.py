#!/usr/bin/env python3
"""Ramp load harness (#122): staircase concurrency with a per-step tail-latency report.

Drives N bot sessions per step against a live ``molgang serve`` (a fresh local one by
default, bootstrapped like ``tests/e2e/molgang_e2e.py``, or any ``--base`` URL), and per
step reports:

* client-observed p50/p95/p99 + error-rate for ``/api/propose`` and ``/api/vote``,
* time-to-woven (propose → the settle response reports ``woven``) p50/p99 + woven-rate,
* the server-side p99 for the same paths from ``/metrics``
  (``molgang_http_request_duration_seconds`` bucket DELTAS for the step),
* the ``molgang.slo.check_budgets`` verdict — the run names the FIRST breaching step.

Cross-check contract (documented tolerance): the client-observed p99 must stay within
``client_p99 <= server_p99_bucket * CLIENT_TOLERANCE_FACTOR + CLIENT_TOLERANCE_SLACK_S``
— client time includes transport + queueing, so it may sit above the server bucket, but
an order-of-magnitude gap means the client is measuring something the server is not
(connection starvation, event-loop stall) and the step is flagged ``client_server_agree:
false``.

Bots weave like players do: small groups sit at the least-occupied table (the known
crowded-table quorum behaviour — issues #53/#74 — means piling everyone onto one table
silently stops weaving), each proposes a REAL chemistry formula, and table-mates vote it
through; seated NPCs back honest knits too.

Usage:
    python tests/load/ramp.py --steps 100,500,1000 --base http://host:8765
    python tests/load/ramp.py --steps 25,50                # fresh local serve
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib import request

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[1] / "src"))
sys.path.insert(0, str(_HERE.parents[0] / "e2e"))

from molgang.slo import BUDGETS, check_budgets  # noqa: E402
from molgang.metrics import BUCKETS  # noqa: E402

# documented client-vs-server p99 tolerance (see module docstring)
CLIENT_TOLERANCE_FACTOR = 2.0
CLIENT_TOLERANCE_SLACK_S = 0.050

# real chemistry formulas the NPC backing recognises — cycled per bot, never fabricated
FORMULAS = [
    "H2O", "CO2", "NaCl", "CH4", "NH3", "O2", "N2", "H2SO4", "HCl", "NaOH",
    "CaCO3", "C2H5OH", "C6H12O6", "KCl", "MgO", "FeO", "Fe2O3", "SO2", "NO2", "H2O2",
    "CaO", "KOH", "HNO3", "H3PO4", "C2H4", "C2H2", "C3H8", "C4H10", "CuO", "ZnO",
    "AgCl", "BaSO4", "PbO", "SiO2", "Al2O3", "TiO2", "MnO2", "V2O5", "CrO3", "NiO",
]


# -- tiny timed HTTP client (stdlib; one call = one latency sample) ----------
def _call(base: str, path: str, body: dict | None = None, timeout: float = 15.0):
    """POST/GET returning (seconds, parsed-json | None, ok, status).

    status: HTTP code, or 0 on a transport-level failure. Never raises.
    """
    from urllib.error import HTTPError

    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(base + path, data=data,
                          headers={"Content-Type": "application/json"} if data else {})
    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode() or "{}")
            return time.perf_counter() - t0, payload, 200 <= r.status < 300, r.status
    except HTTPError as e:
        return time.perf_counter() - t0, None, False, e.code
    except Exception:
        return time.perf_counter() - t0, None, False, 0


def percentile(samples: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in [0,1]); None on empty input."""
    if not samples:
        return None
    import math
    xs = sorted(samples)
    idx = min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))
    return xs[idx]


def _hist_counts(text: str, path: str) -> tuple[list[int], int]:
    import re
    counts = []
    for le in BUCKETS:
        m = re.search(
            rf'molgang_http_request_duration_seconds_bucket\{{path="{re.escape(path)}",le="{le}"\}} (\d+)',
            text)
        counts.append(int(m.group(1)) if m else 0)
    tm = re.search(
        rf'molgang_http_request_duration_seconds_count\{{path="{re.escape(path)}"\}} (\d+)', text)
    return counts, (int(tm.group(1)) if tm else 0)


def delta_p99(before: str, after: str, path: str) -> float | None:
    """Server p99 bucket ceiling for the requests that happened BETWEEN two scrapes."""
    b_counts, b_total = _hist_counts(before, path)
    a_counts, a_total = _hist_counts(after, path)
    total = a_total - b_total
    if total <= 0:
        return None
    target = 0.99 * total
    for le, bc, ac in zip(BUCKETS, b_counts, a_counts):
        if (ac - bc) >= target:
            return le
    return float("inf")


# -- one bot session ---------------------------------------------------------
class _Recorder:
    """Thread-safe per-step sample sink."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.propose: list[float] = []
        self.vote: list[float] = []
        self.ttw: list[float] = []
        self.errors = 0
        self.rejected = 0
        self.calls = 0
        self.woven = 0

    def add(self, kind: str, seconds: float, ok: bool, status: int = 200) -> None:
        with self._lock:
            self.calls += 1
            if ok:
                if kind == "propose":
                    self.propose.append(seconds)
                elif kind == "vote":
                    self.vote.append(seconds)
            elif 400 <= status < 500:
                # a game-flow rejection (e.g. voting a knit that JUST settled in the
                # race window) — expected under concurrency, not a server failure
                self.rejected += 1
            else:
                self.errors += 1


def _bot(base: str, idx: int, mates: int, rec: _Recorder) -> None:
    device = f"ramp-{os.getpid()}-{idx}"
    j = ok = None
    for attempt in (1, 2):                     # one retry: a concurrent join can hit a
        _, j, ok, _st = _call(base, "/api/join",   # transient keep-alive disconnect
                              {"name": f"ramp{idx}", "device": device})
        if ok and j:
            break
    if not ok or not j:
        with rec._lock:
            rec.errors += 1
            rec.calls += 1
        return
    sid = j["sid"]

    # groups of `mates` sit together at the least-occupied table (auto-added tables
    # keep capacity coming); crowding one table raises the quorum past the group
    _, st, ok, _c = _call(base, f"/api/state?sid={sid}")
    if ok and st and st.get("tables"):
        tables = sorted(st["tables"], key=lambda t: len(t.get("seated", [])))
        _call(base, "/api/sit", {"sid": sid, "table": tables[(idx // mates) % len(tables)]["id"]})

    term = FORMULAS[idx % len(FORMULAS)]
    t_prop = time.perf_counter()
    sec, p, ok, code = _call(base, "/api/propose", {"sid": sid, "term": term})
    rec.add("propose", sec, ok, code)
    pid = (p or {}).get("pid")

    # vote table-mates' open knits through (honest confirms — real chemistry terms)
    woven_at: float | None = None
    deadline = time.time() + 30
    while time.time() < deadline:
        _, st, ok, _c = _call(base, f"/api/state?sid={sid}")
        if not ok or not st:
            time.sleep(0.5)
            continue
        you = st.get("you") or {}
        table = next((t for t in st.get("tables", []) if t["id"] == you.get("table")), None)
        if table is None:
            break
        for knit in table.get("open", []):
            if not knit.get("mine") and not knit.get("voted"):
                sec, v, ok, code = _call(base, "/api/vote",
                                         {"sid": sid, "pid": knit["pid"], "verdict": "confirm"})
                rec.add("vote", sec, ok, code)
        if woven_at is None and any(w.get("term") == term for w in table.get("fabric", [])):
            woven_at = time.perf_counter()
            with rec._lock:
                rec.woven += 1
                rec.ttw.append(woven_at - t_prop)
        if woven_at is not None and not table.get("open"):
            break
        time.sleep(0.4)
    _ = pid


# -- the ramp ----------------------------------------------------------------
def run_step(base: str, sessions: int, mates: int) -> dict:
    rec = _Recorder()
    before = _scrape(base)
    threads = [threading.Thread(target=_bot, args=(base, i, mates, rec), daemon=True)
               for i in range(sessions)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    wall = time.perf_counter() - t0
    after = _scrape(base)

    server_vote_p99 = delta_p99(before, after, "/api/vote") if before and after else None
    server_propose_p99 = delta_p99(before, after, "/api/propose") if before and after else None
    breaches = [{"slo": b.slo, "ceiling": b.ceiling, "measured": b.measured}
                for b in (check_budgets(after) if after else [])]

    client_vote_p99 = percentile(rec.vote, 0.99)
    agree = None
    if client_vote_p99 is not None and server_vote_p99 not in (None, float("inf")):
        agree = client_vote_p99 <= server_vote_p99 * CLIENT_TOLERANCE_FACTOR + CLIENT_TOLERANCE_SLACK_S

    return {
        "sessions": sessions,
        "wall_s": round(wall, 2),
        "calls": rec.calls,
        "rejected": rec.rejected,
        "error_rate": round(rec.errors / rec.calls, 4) if rec.calls else None,
        "propose": {"n": len(rec.propose),
                    "p50_s": percentile(rec.propose, 0.50),
                    "p95_s": percentile(rec.propose, 0.95),
                    "p99_s": percentile(rec.propose, 0.99)},
        "vote": {"n": len(rec.vote),
                 "p50_s": percentile(rec.vote, 0.50),
                 "p95_s": percentile(rec.vote, 0.95),
                 "p99_s": client_vote_p99},
        "woven": {"count": rec.woven,
                  "rate": round(rec.woven / sessions, 3),
                  "ttw_p50_s": percentile(rec.ttw, 0.50),
                  "ttw_p99_s": percentile(rec.ttw, 0.99)},
        "server": {"vote_p99_bucket_s": server_vote_p99,
                   "propose_p99_bucket_s": server_propose_p99},
        "client_server_agree": agree,
        "budget_breaches": breaches,
    }


def _scrape(base: str) -> str | None:
    try:
        with request.urlopen(base + "/metrics", timeout=5) as r:
            return r.read().decode()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="MOLGANG ramp load harness (#122)")
    ap.add_argument("--steps", default="25,50", help="comma list of session counts per step")
    ap.add_argument("--base", default="", help="target base URL (default: fresh local serve)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8821)
    ap.add_argument("--mates", type=int, default=3, help="bots seated together per group")
    ap.add_argument("--report", default=str(Path(".artifacts/load/ramp.json")),
                    help="machine-readable JSON report path")
    args = ap.parse_args()
    steps = [int(s) for s in args.steps.split(",") if s.strip()]

    proc = tmp = None
    base = args.base
    if not base:
        from molgang_e2e import _serve_process, _stop_process, _wait_for_api
        tmp = tempfile.TemporaryDirectory(prefix="molgang-ramp-")
        base = f"http://{args.host}:{args.port}"
        # the harness IS the flash crowd: everything comes from one source IP, so the
        # per-source rate limits + faucet cap must be off for the LOCAL target (a
        # remote target keeps whatever the operator configured)
        os.environ.setdefault("MOLGANG_RATE_READ", "0")
        os.environ.setdefault("MOLGANG_RATE_WRITE", "0")
        os.environ.setdefault("MOLGANG_RATE_COSTLY", "0")
        os.environ.setdefault("MOLGANG_FAUCET_SOURCE_CAP", "0")
        proc = _serve_process(Path(tmp.name), host=args.host, port=args.port)
        try:
            _wait_for_api(base, timeout_s=30)
        except Exception as e:
            _stop_process(proc)
            print(f"RAMP: server failed to start ({e})")
            return 1

    results, first_breach = [], None
    try:
        for n in steps:
            step = run_step(base, n, args.mates)
            results.append(step)
            if first_breach is None and step["budget_breaches"]:
                first_breach = n
            v, w = step["vote"], step["woven"]
            print(f"step {n:>5} | wall {step['wall_s']:6.1f}s | err {step['error_rate']} | "
                  f"vote p50/p95/p99 {v['p50_s']}/{v['p95_s']}/{v['p99_s']} | "
                  f"woven {w['count']}/{n} (ttw p99 {w['ttw_p99_s']}) | "
                  f"server vote p99≤{step['server']['vote_p99_bucket_s']} | "
                  f"agree={step['client_server_agree']} | breaches={len(step['budget_breaches'])}")
    finally:
        if proc is not None:
            from molgang_e2e import _stop_process
            _stop_process(proc)
        if tmp is not None:
            tmp.cleanup()

    report = {
        "steps": results,
        "budgets": BUDGETS,
        "tolerance": {"factor": CLIENT_TOLERANCE_FACTOR, "slack_s": CLIENT_TOLERANCE_SLACK_S},
        "first_breaching_step": first_breach,
        "target": base,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"report → {out}")
    if first_breach is not None:
        print(f"RAMP: first budget breach at step {first_breach} (docs/BUDGETS.md, #125)")
    else:
        print("RAMP: all steps within budget ✅")

    # the harness itself must have produced signal — no weave at all means the run
    # was hollow (crowded-table stall or a broken target), which is a failure
    hollow = all(s["woven"]["count"] == 0 for s in results)
    return 1 if hollow else 0


if __name__ == "__main__":
    raise SystemExit(main())
