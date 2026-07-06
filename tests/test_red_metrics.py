"""#121 — RED metrics on the /api contract (stdlib-only Prometheus exposition)."""
import io
import json

from molgang import metrics
from molgang.bar import Bar
from molgang.webserver import make_handler


def _drive(Handler, raw: bytes) -> bytes:
    rfile, wfile = io.BytesIO(raw), io.BytesIO()

    class _H(Handler):
        def __init__(self):
            self.rfile = rfile
            self.wfile = wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = ""
            self.request_version = "HTTP/1.1"
            self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

        def finish(self):
            pass

        def log_message(self, *a):
            pass

    _H()
    return wfile.getvalue()


def _post(Handler, path, obj):
    body = json.dumps(obj).encode()
    return _drive(Handler, (f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
                            f"Content-Length: {len(body)}\r\n\r\n").encode() + body)


def test_driving_the_flow_populates_red_and_domain_metrics(tmp_path):
    bar = Bar(str(tmp_path / "world.json"))
    Handler = make_handler(bar)
    out = _post(Handler, "/api/join", {"name": "Metric", "avatar": "laser-maxi", "device": "dev-m1"})
    sid = json.loads(out.split(b"\r\n\r\n", 1)[1])["sid"]
    _post(Handler, "/api/sit", {"sid": sid, "table": "periodic"})
    _post(Handler, "/api/propose", {"sid": sid, "term": "H2O"})

    exp = _drive(Handler, b"GET /metrics HTTP/1.1\r\n\r\n").decode()
    head, body = exp.split("\r\n\r\n", 1)
    assert "text/plain; version=0.0.4" in head
    # RED: request counters + duration histogram for the driven endpoints
    assert 'molgang_http_requests_total{path="/api/propose",method="POST",code="200"}' in body
    assert 'molgang_http_request_duration_seconds_bucket{path="/api/propose",le="+Inf"}' in body
    assert "molgang_http_inflight" in body
    # domain: the proposed knit was woven by honest bots and voted on
    assert "molgang_knit_proposed_total" in body
    assert "molgang_knit_woven_total" in body
    assert 'molgang_vote_total{verdict="confirm"}' in body
    assert "molgang_seats_occupied" in body


def test_label_cardinality_is_bounded_no_user_data():
    metrics.record_request("/api/monitor/nodes/deep/path", "GET", 200, 0.01)
    metrics.record_request("/api/definitely-not-a-route-xyz", "GET", 404, 0.01)
    metrics.record_request("/api/state?sid=SECRET123", "GET", 200, 0.01)
    out = metrics.REGISTRY.render()
    assert 'path="/api/monitor/*"' in out          # subpaths collapse
    assert 'path="other"' in out                   # unknown api paths collapse
    assert "SECRET123" not in out and "sid=" not in out
    assert "definitely-not-a-route" not in out


def test_exposition_format_is_prometheus_004():
    out = metrics.REGISTRY.render()
    # TYPE appears exactly once per metric name
    for name in ("molgang_http_requests_total", "molgang_http_request_duration_seconds"):
        assert out.count(f"# TYPE {name} ") == 1
    # histogram invariants: +Inf bucket == count
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        if '_bucket{path="/api/propose",le="+Inf"}' in ln:
            inf = int(ln.rsplit(" ", 1)[1])
            cnt = next(int(l.rsplit(" ", 1)[1]) for l in lines
                       if l.startswith('molgang_http_request_duration_seconds_count{path="/api/propose"}'))
            assert inf == cnt


def test_no_third_party_dependency():
    import molgang.metrics as m
    src = open(m.__file__).read()
    assert "prometheus_client" not in src and "import requests" not in src
