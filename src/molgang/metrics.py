"""Stdlib-only Prometheus metrics (#121) — RED signals for the bar API.

Zero third-party dependencies: a tiny in-process registry rendering Prometheus
text exposition format 0.0.4. The webserver wraps request dispatch to record

    molgang_http_requests_total{path,method,code}     counter
    molgang_http_request_duration_seconds{path}       histogram (1ms..2.5s buckets)
    molgang_quorum_settle_seconds                      histogram — propose→woven latency (#125)
    molgang_http_inflight                              gauge

and the bar records domain counters at the settle sites

    molgang_knit_proposed_total / molgang_knit_woven_total
    molgang_vote_total{verdict}

Label cardinality is bounded by construction: paths are normalised through
:func:`norm_path` (monitor subpaths collapse to one value, unknown paths to
"other") and NOTHING user-controlled (sid, term, name) ever becomes a label.
"""
from __future__ import annotations

import threading
from collections import defaultdict

BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

# the known public routes — anything else collapses to "other" so an attacker
# probing random paths cannot explode the label space
_KNOWN = {
    "/api/state", "/api/version", "/api/certificates", "/api/pulse", "/api/suggested",
    "/api/web", "/api/quests", "/api/achievements", "/api/graph", "/api/relay",
    "/api/lens/chemistry", "/api/export/jsonld", "/api/web/jsonld", "/api/join",
    "/api/heartbeat", "/api/leave", "/api/stand", "/api/sit", "/api/rename",
    "/api/propose", "/api/vote", "/api/spiral/propose", "/api/spiral/vote",
    "/api/relay/pull", "/api/certificate", "/metrics",
}


def norm_path(path: str) -> str:
    """Bounded path label: known routes verbatim, monitor collapsed, rest 'other'."""
    p = path.split("?")[0]
    if p.startswith("/api/monitor"):
        return "/api/monitor/*"
    if p in _KNOWN:
        return p
    return "other" if p.startswith("/api/") else "static"


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple, int] = defaultdict(int)
        self._hist: dict[str, dict] = {}
        self.inflight = 0

    # -- primitives ---------------------------------------------------------
    def inc(self, name: str, labels: tuple[tuple[str, str], ...] = (), by: int = 1) -> None:
        with self._lock:
            self._counters[(name, labels)] += by

    def observe(self, name: str, seconds: float, labels: tuple[tuple[str, str], ...] = ()) -> None:
        with self._lock:
            h = self._hist.setdefault((name, labels), {"buckets": [0] * len(BUCKETS), "sum": 0.0, "count": 0})
            for i, le in enumerate(BUCKETS):
                if seconds <= le:
                    h["buckets"][i] += 1
            h["sum"] += seconds
            h["count"] += 1

    def track(self, delta: int) -> None:
        with self._lock:
            self.inflight += delta

    # -- exposition ---------------------------------------------------------
    @staticmethod
    def _lbl(labels: tuple[tuple[str, str], ...], extra: str = "") -> str:
        parts = [f'{k}="{v}"' for k, v in labels]
        if extra:
            parts.append(extra)
        return "{" + ",".join(parts) + "}" if parts else ""

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            names = sorted({n for n, _ in self._counters})
            for name in names:
                lines.append(f"# TYPE {name} counter")
                for (n, labels), v in sorted(self._counters.items()):
                    if n == name:
                        lines.append(f"{name}{self._lbl(labels)} {v}")
            hist_names = sorted({n for n, _ in self._hist})
            for hname in hist_names:
                lines.append(f"# TYPE {hname} histogram")
                for (name, labels), h in sorted(self._hist.items()):
                    if name != hname:
                        continue
                    for i, le in enumerate(BUCKETS):
                        lines.append(f"{name}_bucket{self._lbl(labels, f'le=\"{le}\"')} {h['buckets'][i]}")
                    lines.append(f"{name}_bucket{self._lbl(labels, 'le=\"+Inf\"')} {h['count']}")
                    lines.append(f"{name}_sum{self._lbl(labels)} {h['sum']:.6f}")
                    lines.append(f"{name}_count{self._lbl(labels)} {h['count']}")
            lines.append("# TYPE molgang_http_inflight gauge")
            lines.append(f"molgang_http_inflight {self.inflight}")
        return "\n".join(lines) + "\n"


REGISTRY = Metrics()


# -- convenience wrappers used by webserver.py / bar.py ----------------------
def record_request(path: str, method: str, code: int, seconds: float) -> None:
    p = norm_path(path)
    REGISTRY.inc("molgang_http_requests_total",
                 (("path", p), ("method", method), ("code", str(code))))
    REGISTRY.observe("molgang_http_request_duration_seconds", seconds, (("path", p),))


def knit_proposed() -> None:
    REGISTRY.inc("molgang_knit_proposed_total")


def knit_woven() -> None:
    REGISTRY.inc("molgang_knit_woven_total")


def vote_cast(verdict: str) -> None:
    REGISTRY.inc("molgang_vote_total", (("verdict", str(verdict)),))


def settle_observed(seconds: float) -> None:
    """Record propose→woven quorum-settle latency (the #125 SLO histogram)."""
    REGISTRY.observe("molgang_quorum_settle_seconds", float(seconds))
