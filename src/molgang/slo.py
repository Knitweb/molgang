"""Service-level objectives + budget enforcement (#125).

Load numbers are meaningless without a target. This defines the fabric's SLO
ceilings and computes p99 latency from the RED histogram (#121) so the load
harness can *assert* health per ramp step rather than eyeballing it. Pure and
deterministic — it reads the Prometheus exposition the node already emits.

``check_budgets`` returns a list of breaches (empty == healthy); each names the
SLO, the ceiling, and the measured value, so a failing ramp step reports exactly
what broke. See ``docs/BUDGETS.md`` for the rationale + committed baseline.
"""
from __future__ import annotations

import re

from .metrics import BUCKETS

__all__ = ["BUDGETS", "p99_seconds", "error_rate", "check_budgets", "Breach"]

# SLO ceilings (seconds / ratio). Integer/float-free where it matters — these are
# display/alert thresholds, never on a hashed or economic path.
BUDGETS = {
    "api_state_p99_s": 0.150,      # /api/state read stays snappy under load
    "api_vote_p99_s": 0.300,       # casting a vote (stakes a PLS Knit) settles fast
    "quorum_settle_p99_s": 0.500,  # propose -> woven (the settle path) p99
    "error_rate_max": 0.01,        # <= 1% of requests may error
}


class Breach:
    __slots__ = ("slo", "ceiling", "measured")

    def __init__(self, slo: str, ceiling: float, measured: float) -> None:
        self.slo, self.ceiling, self.measured = slo, ceiling, measured

    def __repr__(self) -> str:
        return f"Breach({self.slo}: {self.measured:.4f} > {self.ceiling:.4f})"


def _hist(text: str, path: str) -> "tuple[list[int], int]":
    """Return (cumulative bucket counts aligned to BUCKETS, total count) for a path."""
    counts = []
    for le in BUCKETS:
        m = re.search(
            rf'molgang_http_request_duration_seconds_bucket\{{path="{re.escape(path)}",le="{le}"\}} (\d+)',
            text)
        counts.append(int(m.group(1)) if m else 0)
    tm = re.search(
        rf'molgang_http_request_duration_seconds_count\{{path="{re.escape(path)}"\}} (\d+)', text)
    return counts, (int(tm.group(1)) if tm else 0)


def p99_seconds(text: str, path: str) -> "float | None":
    """The p99 latency bucket ceiling for ``path`` from the exposition, or None."""
    counts, total = _hist(text, path)
    if total <= 0:
        return None
    target = 0.99 * total
    for le, c in zip(BUCKETS, counts):
        if c >= target:
            return le
    return float("inf")            # p99 fell in the +Inf overflow bucket


def error_rate(text: str) -> float:
    """Fraction of requests with a non-2xx code across all paths."""
    total = err = 0
    for m in re.finditer(r'molgang_http_requests_total\{[^}]*code="(\d+)"\} (\d+)', text):
        code, n = int(m.group(1)), int(m.group(2))
        total += n
        if code >= 400:
            err += n
    return (err / total) if total else 0.0


def check_budgets(text: str) -> "list[Breach]":
    """Every breached SLO for a /metrics exposition (empty == healthy)."""
    out: list[Breach] = []
    checks = [
        ("api_state_p99_s", p99_seconds(text, "/api/state")),
        ("api_vote_p99_s", p99_seconds(text, "/api/vote")),
        ("quorum_settle_p99_s", p99_seconds(text, "/api/propose")),
    ]
    for slo, measured in checks:
        if measured is not None and measured > BUDGETS[slo]:
            out.append(Breach(slo, BUDGETS[slo], measured))
    er = error_rate(text)
    if er > BUDGETS["error_rate_max"]:
        out.append(Breach("error_rate_max", BUDGETS["error_rate_max"], er))
    return out
