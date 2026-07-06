"""#125 — SLO budget enforcement: p99 from the RED histogram + breach naming."""
import io
import json

import pytest

from molgang import slo
from molgang.bar import Bar
from molgang.metrics import BUCKETS
from molgang.webserver import make_handler


def _drive(Handler, raw):
    rfile, wfile = io.BytesIO(raw), io.BytesIO()

    class _H(Handler):
        def __init__(self):
            self.rfile, self.wfile = rfile, wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = ""; self.request_version = "HTTP/1.1"; self.command = ""
            self.handle_one_request()

        def setup(self): pass
        def finish(self): pass
        def log_message(self, *a): pass
    _H()
    return wfile.getvalue()


def _post(H, path, obj):
    b = json.dumps(obj).encode()
    return _drive(H, (f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
                      f"Content-Length: {len(b)}\r\n\r\n").encode() + b)


def _metrics_after_a_game(tmp):
    bar = Bar(str(tmp / "w.json"))
    H = make_handler(bar)
    sid = json.loads(_post(H, "/api/join", {"name": "P", "device": "d"}).split(b"\r\n\r\n", 1)[1])["sid"]
    _post(H, "/api/sit", {"sid": sid, "table": "periodic"})
    _post(H, "/api/propose", {"sid": sid, "term": "H2O"})
    return _drive(H, b"GET /metrics HTTP/1.1\r\n\r\n").split(b"\r\n\r\n", 1)[1].decode()


def test_in_process_flow_is_within_budget(tmp_path):
    # /metrics reads the process-global registry, so isolate this flow's counters
    from molgang import metrics
    metrics.REGISTRY._counters.clear()
    metrics.REGISTRY._hist.clear()
    text = _metrics_after_a_game(tmp_path)
    assert slo.check_budgets(text) == []          # the fast in-process path is healthy
    assert slo.p99_seconds(text, "/api/propose") is not None


def test_p99_is_computed_from_the_histogram():
    # a synthetic exposition where all propose requests took ~1s -> p99 in the 1.0 bucket
    lines = ["# TYPE molgang_http_request_duration_seconds histogram"]
    for le in BUCKETS:
        c = 0 if le < 1.0 else 5
        lines.append(f'molgang_http_request_duration_seconds_bucket{{path="/api/propose",le="{le}"}} {c}')
    lines.append('molgang_http_request_duration_seconds_bucket{path="/api/propose",le="+Inf"} 5')
    lines.append('molgang_http_request_duration_seconds_count{path="/api/propose"} 5')
    text = "\n".join(lines)
    assert slo.p99_seconds(text, "/api/propose") == 1.0


def test_forced_breach_is_named_with_ceiling_and_measured():
    lines = ["# TYPE molgang_http_request_duration_seconds histogram"]
    for le in BUCKETS:                            # everything overflows -> p99 == +Inf
        lines.append(f'molgang_http_request_duration_seconds_bucket{{path="/api/propose",le="{le}"}} 0')
    lines.append('molgang_http_request_duration_seconds_bucket{path="/api/propose",le="+Inf"} 3')
    lines.append('molgang_http_request_duration_seconds_count{path="/api/propose"} 3')
    breaches = slo.check_budgets("\n".join(lines))
    assert len(breaches) == 1
    b = breaches[0]
    assert b.slo == "quorum_settle_p99_s" and b.ceiling == slo.BUDGETS["quorum_settle_p99_s"]
    assert b.measured > b.ceiling


def test_error_rate_budget():
    text = ('molgang_http_requests_total{path="/api/state",method="GET",code="200"} 99\n'
            'molgang_http_requests_total{path="/api/state",method="GET",code="500"} 5\n')
    assert slo.error_rate(text) > slo.BUDGETS["error_rate_max"]
    assert any(x.slo == "error_rate_max" for x in slo.check_budgets(text))


def test_budgets_doc_and_alerts_exist():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs" / "BUDGETS.md").read_text(encoding="utf-8")
    for k in ("150", "300", "500", "baseline", "error rate"):
        assert k.lower() in doc.lower(), k
    alerts = (root / "monitoring" / "molgang-alerts.yml").read_text(encoding="utf-8")
    assert "MolgangQuorumSettleP99High" in alerts and "histogram_quantile(0.99" in alerts
