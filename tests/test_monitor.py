"""📡 Monitor tab — node/p2p status + the local woven knitweb (issues #59 + #60).

Covers ``molgang.monitor.Monitor`` (the aggregator) and the ``/api/monitor/*`` HTTP routes
added to ``webserver.make_handler``: node liveness + shared-web/provenance, plus the local
woven knitweb's stats/languages/tension/hubs/subgraph reused from the :8990 explorer + graphx.
"""

from __future__ import annotations

import io
import json

from molgang.bar import Bar
from molgang.monitor import Monitor
from molgang.webserver import make_handler


def _store(tmp_path):
    """A tiny 4-language gateway.App store on disk — the 'local woven knitweb' for the tab."""
    def lab(key, en, ru, zh, ar):
        return [{"t": "link", "subject": key, "object": en, "relation": "label:en", "weight": 1},
                {"t": "link", "subject": key, "object": ru, "relation": "label:ru", "weight": 1},
                {"t": "link", "subject": key, "object": zh, "relation": "label:zh", "weight": 1},
                {"t": "link", "subject": key, "object": ar, "relation": "label:ar", "weight": 1}]

    store = {"name": "t", "balances": {}, "records": [
        {"t": "record", "data": {"kind": "concept", "key": "H2O", "formula": "H2O",
                                 "definition": "water", "by": "alice"}},
        {"t": "record", "data": {"kind": "concept", "key": "oxygen", "by": "alice"}},
        *lab("H2O", "water", "вода", "水", "ماء"),
        *lab("oxygen", "oxygen", "кислород", "氧", "أكسجين"),
        {"t": "link", "subject": "H2O", "object": "oxygen", "relation": "contains", "weight": 2},
    ]}
    p = tmp_path / "chem.json"
    p.write_text(json.dumps(store), encoding="utf-8")
    return str(p)


def _monitor(tmp_path):
    bar = Bar(str(tmp_path / "world.json"))
    # use ports nothing should be bound to, so liveness deterministically reads 'down'
    return Monitor(bar, web=_store(tmp_path),
                   pulse_host={"account": {"address": "0xhost", "balance_pls": 7},
                               "listen": "0.0.0.0:8771"},
                   nodes="alice=59001,bob=59002")


# -- the Monitor aggregator ------------------------------------------------
def test_node_status_reports_liveness_web_and_provenance(tmp_path):
    st = _monitor(tmp_path).node_status()
    labels = [n["label"] for n in st["nodes"]]
    assert labels == ["alice", "bob"]
    # nothing is listening on those ports in the test → both 'down', live_count 0
    assert all(n["live"] is False for n in st["nodes"])
    assert st["live_count"] == 0
    assert "nodes" in st["web"] and "edges" in st["web"]      # shared-web stats present
    assert "ual" in st["anchor"] and "verified" in st["anchor"]
    assert st["pulse_host"]["address"] == "0xhost"           # OriginTrail/Pulse host surfaced


def test_kg_stats_has_languages_concepts_and_tension(tmp_path):
    m = _monitor(tmp_path)
    s = m.kg_stats()
    assert s["concepts"] == 2
    # the four languages are present in the local woven knitweb (#60)
    assert s["languages"] == {"en": 2, "ru": 2, "zh": 2, "ar": 2}
    assert "chem.json" in s["source"]
    bands = m.kg_tension()["bands"]
    assert set(bands) == {"taut", "neutral", "slack", "contested"}
    assert sum(bands.values()) == s["edges"]                 # every edge banded


def test_kg_hubs_and_subgraph_centre_with_tension(tmp_path):
    m = _monitor(tmp_path)
    hubs = m.kg_hubs(8)["hubs"]
    assert any(h["term"] == "H2O" for h in hubs)
    sg = m.kg_subgraph("h2o", depth=1)                       # case-insensitive resolve
    assert sg["center"] == "H2O"
    # every edge in the focused subgraph carries a tension band (taut/slack colouring)
    assert all("tension_band" in e for e in sg["edges"])
    assert m.kg_subgraph("does-not-exist") is None


def test_overview_bundles_status_and_kg(tmp_path):
    ov = _monitor(tmp_path).overview()
    assert "status" in ov and "kg" in ov
    assert ov["kg"]["languages"]["zh"] == 2
    assert "tension" in ov["kg"] and "hubs" in ov["kg"]


# -- the /api/monitor HTTP routes -----------------------------------------
def _get(tmp_path, path):
    """Drive make_handler's do_GET in-process and return the parsed JSON body + status line."""
    Handler = make_handler(_monitor(tmp_path).bar, monitor=_monitor(tmp_path))
    raw = ("GET %s HTTP/1.1\r\n\r\n" % path).encode()

    class _H(Handler):
        def __init__(self, rfile, wfile):
            self.rfile, self.wfile = rfile, wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = self.request_version = self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

    wfile = io.BytesIO()
    _H(io.BytesIO(raw), wfile)
    out = wfile.getvalue()
    head, _, body = out.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0]
    return status, json.loads(body) if body.strip() else {}


def test_api_monitor_overview_route(tmp_path):
    status, data = _get(tmp_path, "/api/monitor")
    assert b"200" in status
    assert data["status"]["pulse_host"]["address"] == "0xhost"
    assert data["kg"]["languages"]["ar"] == 2


def test_api_monitor_status_and_kg_routes(tmp_path):
    s1, st = _get(tmp_path, "/api/monitor/status")
    assert b"200" in s1
    assert [n["label"] for n in st["nodes"]] == ["alice", "bob"]
    assert "live" in st["nodes"][0]

    s2, stats = _get(tmp_path, "/api/monitor/kg/stats")
    assert b"200" in s2 and stats["languages"]["ru"] == 2

    s3, tension = _get(tmp_path, "/api/monitor/kg/tension")
    assert b"200" in s3 and set(tension["bands"]) == {"taut", "neutral", "slack", "contested"}

    s4, hubs = _get(tmp_path, "/api/monitor/kg/hubs?n=3")
    assert b"200" in s4 and len(hubs["hubs"]) <= 3


def test_api_monitor_subgraph_route_and_miss(tmp_path):
    s1, sg = _get(tmp_path, "/api/monitor/kg/subgraph?term=h2o&depth=1")
    assert b"200" in s1 and sg["center"] == "H2O"
    assert all("tension_band" in e for e in sg["edges"])
    s2, _ = _get(tmp_path, "/api/monitor/kg/subgraph?term=nope")
    assert b"404" in s2
