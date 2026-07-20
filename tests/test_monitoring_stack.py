"""Monitoring stack (#123): the committed Prometheus + Grafana config is loadable,
self-consistent, and only queries metric names the /metrics exposition (#121)
actually emits — so the board can never silently rot away from the code."""

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")   # PyYAML is installed in CI; skip gracefully elsewhere

ROOT = Path(__file__).resolve().parents[1]
MON = ROOT / "monitoring"

# every series name the registry emits (metrics.py docstring is the contract)
EMITTED = {
    "molgang_http_requests_total",
    "molgang_http_request_duration_seconds",
    "molgang_http_inflight",
    "molgang_knit_proposed_total",
    "molgang_knit_woven_total",
    "molgang_vote_total",
}
_METRIC_RE = re.compile(r"\bmolgang_[a-z0-9_]+")


def _molgang_metrics(text: str) -> set:
    # strip histogram suffixes so bucket/sum/count queries map to the base series
    return {re.sub(r"_(bucket|sum|count)$", "", m) for m in _METRIC_RE.findall(text)}


def test_prometheus_config_parses_and_loads_the_alert_rules() -> None:
    cfg = yaml.safe_load((MON / "prometheus.yml").read_text())
    assert any(r.endswith("molgang-alerts.yml") for r in cfg["rule_files"])
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert jobs["molgang-serve"]["metrics_path"] == "/metrics"
    # the local target matches molgang serve's default --port
    assert any("8765" in t for sc in jobs["molgang-serve"]["static_configs"]
               for t in sc["targets"])


def test_alert_rules_query_only_emitted_series() -> None:
    rules = yaml.safe_load((MON / "molgang-alerts.yml").read_text())
    exprs = " ".join(r["expr"] for g in rules["groups"] for r in g["rules"])
    unknown = _molgang_metrics(exprs) - EMITTED
    assert not unknown, f"alert rules reference unemitted series: {unknown}"


def test_dashboard_json_is_valid_and_queries_only_emitted_series() -> None:
    dash = json.loads((MON / "grafana/dashboards/molgang-red.json").read_text())
    assert dash["uid"] == "molgang-red" and dash["panels"]
    exprs = " ".join(t["expr"] for p in dash["panels"] for t in p.get("targets", []))
    unknown = _molgang_metrics(exprs) - EMITTED
    assert not unknown, f"dashboard references unemitted series: {unknown}"
    # the sprint's board contents: RED + weave + quorum-settle p99 (#125 budgets)
    assert "molgang_http_requests_total" in exprs
    assert "histogram_quantile(0.99" in exprs
    assert "molgang_knit_woven_total" in exprs
    assert 'path=\\"/api/propose\\"' in json.dumps(exprs) or '/api/propose' in exprs
    # every panel pins the provisioned datasource uid
    assert all(p["datasource"]["uid"] == "molgang-prom" for p in dash["panels"])


def test_compose_mounts_exactly_the_committed_config() -> None:
    comp = yaml.safe_load((MON / "docker-compose.yml").read_text())
    vols = " ".join(v for s in comp["services"].values() for v in s.get("volumes", []))
    for mounted in ("prometheus.yml", "molgang-alerts.yml",
                    "grafana/provisioning", "grafana/dashboards"):
        assert mounted in vols, mounted
        src = mounted.split(":")[0].lstrip("./")
        assert (MON / src).exists(), f"compose mounts a missing path: {src}"
    # grafana provisioning actually points at the mounted dashboard dir
    prov = yaml.safe_load(
        (MON / "grafana/provisioning/dashboards/dashboards.yml").read_text())
    assert prov["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"
    ds = yaml.safe_load(
        (MON / "grafana/provisioning/datasources/prometheus.yml").read_text())
    assert ds["datasources"][0]["uid"] == "molgang-prom"


def test_monitor_overview_exposes_the_board_link_only_when_configured(monkeypatch,
                                                                      tmp_path) -> None:
    from molgang.monitor import Monitor
    from molgang.registry import Registry
    from molgang.bar import Bar

    bar = Bar(str(tmp_path / "w.json"), Registry(str(tmp_path / "r.json")))
    mon = Monitor(bar, web=False)
    monkeypatch.delenv("MOLGANG_GRAFANA_URL", raising=False)
    assert "dashboard" not in mon.overview()      # never guesses at a URL
    monkeypatch.setenv("MOLGANG_GRAFANA_URL", "http://localhost:3000/d/molgang-red")
    assert mon.overview()["dashboard"] == "http://localhost:3000/d/molgang-red"
