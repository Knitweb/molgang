"""Unit guards for the #122 ramp harness helpers (pure functions, no server)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "load"))

from ramp import CLIENT_TOLERANCE_FACTOR, CLIENT_TOLERANCE_SLACK_S, delta_p99, percentile  # noqa: E402
from molgang.metrics import BUCKETS  # noqa: E402


def test_percentile_nearest_rank():
    xs = [float(i) for i in range(1, 101)]      # 1..100
    assert percentile(xs, 0.50) == 50.0
    assert percentile(xs, 0.95) == 95.0
    assert percentile(xs, 0.99) == 99.0
    assert percentile([7.0], 0.99) == 7.0
    assert percentile([], 0.99) is None


def _expo(path: str, bucket_counts: dict, total: int) -> str:
    lines = []
    cum = 0
    for le in BUCKETS:
        cum += bucket_counts.get(le, 0)
        lines.append(
            f'molgang_http_request_duration_seconds_bucket{{path="{path}",le="{le}"}} {cum}')
    lines.append(f'molgang_http_request_duration_seconds_count{{path="{path}"}} {total}')
    return "\n".join(lines)


def test_delta_p99_uses_only_the_step_window():
    # before: 100 fast requests; step adds 100 requests of which 2 land in 0.5s
    before = _expo("/api/vote", {0.001: 100}, 100)
    after = _expo("/api/vote", {0.001: 198, 0.5: 2}, 200)
    assert delta_p99(before, after, "/api/vote") == 0.5     # the step's own tail
    # while against an empty BEFORE (i.e. the cumulative view) the 100 old fast
    # requests drown the step's tail — exactly why the harness diffs scrapes
    assert delta_p99(_expo("/api/vote", {}, 0), after, "/api/vote") == 0.001


def test_delta_p99_empty_window_is_none_and_overflow_is_inf():
    e = _expo("/api/vote", {0.001: 10}, 10)
    assert delta_p99(e, e, "/api/vote") is None             # nothing happened
    slow = _expo("/api/vote", {}, 10)                       # 10 requests, no bucket ≤2.5s
    fast = _expo("/api/vote", {}, 0)
    assert delta_p99(fast, slow, "/api/vote") == float("inf")


def test_tolerance_contract_is_documented_sane():
    # the documented cross-check: client may sit above the server bucket (transport +
    # queueing) but not an order of magnitude — keep the knobs in a sane band
    assert 1.0 <= CLIENT_TOLERANCE_FACTOR <= 5.0
    assert 0.0 <= CLIENT_TOLERANCE_SLACK_S <= 0.5
