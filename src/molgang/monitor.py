"""The 📡 **Monitor** — node / p2p status + the local woven knitweb, in one place.

Backs the in-game *Monitor* tab (issues #59 + #60). It does two jobs, both read-only:

1. **Node / p2p status** — daemon liveness of the watched knitweb nodes (alice/bob by
   default; a plain TCP-connect port check, same idea as ``knitweb/monitor``), the shared
   web's stats + its OriginTrail provenance anchor (reusing ``Bar.web_view()`` / the Pulse
   host), so the bar's p2p health is visible from inside the game.

2. **The local woven knitweb (:8990)** — the explorer's knowledge-graph lens over a
   gateway.App store (default ``/tmp/chem_web.json``, the 447-concept EN/RU/ZH/AR chemistry
   web), or the live molgang world. It reuses ``molgang.graphx`` / ``molgang.explorer`` so the
   same NetworkX analytics the :8990 explorer serves — ``stats`` (nodes/edges/concepts/
   languages), ``hubs``, ``tension`` (taut/slack/snapped bands from the merged fiber-tension),
   and focused ``subgraph`` / ``concept`` views — are available same-origin under ``/api/monitor``.

The graph is built once at first use and cached, so the Monitor tab stays cheap to poll.
"""

from __future__ import annotations

import hashlib
import os
import socket

from . import explorer, graphx

# Default knitweb nodes the bar watches (label → liveness port). Overridable via env
# MOLGANG_MONITOR_NODES="alice=8900,bob=8901" — purely a liveness (port-beat) check.
_DEFAULT_NODES = "alice=8900,bob=8901"


def _parse_nodes(spec: str | None = None) -> list[dict]:
    spec = spec if spec is not None else os.environ.get("MOLGANG_MONITOR_NODES", _DEFAULT_NODES)
    out: list[dict] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, _, port = chunk.partition("=")
        out.append({"label": label.strip() or chunk,
                    "port": int(port) if port.strip().isdigit() else None})
    return out


def port_live(port: int | None, host: str = "127.0.0.1") -> bool:
    """A node daemon is 'live' when its p2p port accepts a TCP connection (zero-dep beat)."""
    if not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=0.4):
            return True
    except OSError:
        return False


class Monitor:
    """Aggregates node/p2p status + the local woven knitweb for the Monitor tab.

    The KG (``graphx`` DiGraph) is loaded once — from ``web`` (a gateway.App store, default
    ``/tmp/chem_web.json``) or ``world`` (a molgang world.json), falling back to a built-in
    sample so it always boots — and cached, so polling the tab is cheap. ``bar`` is the live
    ``Bar`` (for the shared-web stats + OriginTrail anchor + the Pulse host).
    """

    def __init__(self, bar, *, web: str | None = None, world: str | None = None,
                 pulse_host: dict | None = None, nodes: str | None = None) -> None:
        self.bar = bar
        self.pulse_host = pulse_host
        self.nodes = _parse_nodes(nodes)
        # The "local woven knitweb" is the :8990 chem web — prefer an explicit --monitor-web,
        # else /tmp/chem_web.json if present, else the live shared world, else a sample. We
        # pass DEFAULT_WEB explicitly so it wins over the world even when both exist (#60).
        if web is None and os.path.exists(os.path.expanduser(explorer.DEFAULT_WEB)):
            web = explorer.DEFAULT_WEB
        self._g, self.source = explorer.load_graph(web, world)

    # -- node / p2p status -------------------------------------------------
    def node_status(self) -> dict:
        """alice/bob (or configured) daemon liveness + the shared-web/provenance + host."""
        nodes = [{"label": n["label"], "port": n["port"],
                  "live": port_live(n["port"])} for n in self.nodes]
        web = self.bar.web_view()
        anchor = web.get("anchor") or {}
        host = self.pulse_host or {}
        return {
            "nodes": nodes,
            "live_count": sum(1 for n in nodes if n["live"]),
            "web": {"nodes": web.get("nodes", 0), "edges": web.get("edges", 0),
                    "state_root": web.get("state_root"),
                    "recent": web.get("recent", [])[:8]},
            "anchor": {"ual": anchor.get("ual"), "verified": bool(anchor.get("verified")),
                       "nodes": anchor.get("nodes", 0), "edges": anchor.get("edges", 0),
                       "receipt_cid": anchor.get("receipt_cid")},
            "pulse_host": ({"address": (host.get("account") or {}).get("address"),
                            "balance_pls": (host.get("account") or {}).get("balance_pls"),
                            "listen": host.get("listen")} if host else None),
        }

    # -- the local woven knitweb (the :8990 explorer's KG over chem_web) ----
    def kg_stats(self) -> dict:
        s = graphx.web_stats(self._g)
        s["source"] = self.source
        return s

    def kg_hubs(self, n: int = 12) -> dict:
        return {"hubs": graphx.centrality_hubs(self._g, n)}

    def kg_tension(self) -> dict:
        return graphx.tension_stats(self._g)

    def kg_subgraph(self, term: str, depth: int = 2, langs=None) -> dict | None:
        return graphx.subgraph(self._g, term, depth, langs=langs)

    def kg_concept(self, key: str) -> dict | None:
        return graphx.concept(self._g, key)

    def overview(self) -> dict:
        """One compact poll for the Monitor tab: node status + the local-knitweb KG digest."""
        out = {
            "status": self.node_status(),
            "kg": {**self.kg_stats(), **self.kg_hubs(8), "tension": self.kg_tension()},
        }
        # Operator-configured Grafana board (monitoring/, #123) — read-only deep link;
        # absent unless the operator opted in, so the tab never guesses at a URL.
        dashboard = os.environ.get("MOLGANG_GRAFANA_URL", "").strip()
        if dashboard:
            out["dashboard"] = dashboard
        return out


# ---------------------------------------------------------------------------
# Simulation helper — deterministic fake p2p network, no running nodes needed
# ---------------------------------------------------------------------------

_SIM_CITIES = [
    ("amsterdam", 8900), ("rotterdam", 8901), ("frankfurt", 8902),
    ("london", 8903), ("paris", 8904), ("berlin", 8905),
    ("dublin", 8906), ("stockholm", 8907), ("warsaw", 8908), ("madrid", 8909),
]
# Deterministic peer connections for n nodes (ring + diagonal)
_SIM_BALANCE = [50_000_000, 31_400_000, 22_700_000, 18_100_000,
                14_300_000, 11_800_000, 9_600_000, 7_700_000, 6_200_000, 5_000_000]


def _sim_address(label: str) -> str:
    """Deterministic fake PLS address derived from node label."""
    h = hashlib.sha256(f"knitweb-sim:{label}".encode()).hexdigest()
    return "0x" + h[:40]


def _simulate_p2p(n: int = 6) -> dict:
    """Return a deterministic fake p2p network with *n* nodes (max 10).

    Used by ``/api/monitor/simulate`` so the Monitor tab can show a realistic
    multi-node knitweb even when no real daemons are running.  All values are
    deterministic (no randomness) so the display is stable across reloads.
    """
    n = max(2, min(n, len(_SIM_CITIES)))
    nodes = []
    for i, (label, port) in enumerate(_SIM_CITIES[:n]):
        nodes.append({
            "id": i,
            "label": label,
            "address": _sim_address(label),
            "port": port,
            "live": True,
            "balance_pls": _SIM_BALANCE[i],
            "peers": min(n - 1, 4),
            "fibers": 12 + i * 3,
        })
    # Edges: ring topology + one skip-2 diagonal for realism
    edges = []
    for i in range(n):
        edges.append({"from": i, "to": (i + 1) % n, "label": "relay"})
    if n >= 4:
        for i in range(0, n, 3):
            edges.append({"from": i, "to": (i + 2) % n, "label": "webrtc"})
    return {
        "sim": True,
        "node_count": n,
        "nodes": nodes,
        "edges": edges,
        "total_balance_pls": sum(nd["balance_pls"] for nd in nodes),
        "total_fibers": sum(nd["fibers"] for nd in nodes),
    }
