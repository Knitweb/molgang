"""Explore the woven knitweb graph with **NetworkX**.

Builds a `networkx.DiGraph` from the World's woven terms (nodes) and links (edges), and offers
graph analytics so players can *explore the web they made*: hub terms (degree + PageRank
centrality — the most-knitted ideas), a term's neighbours, the shortest path between two terms,
and connected-component clusters. Pure analysis over the fabric — the authoritative graph is the
knitweb `Web`; this is the explorer lens on top of it.
"""

from __future__ import annotations

import networkx as nx


def build(items) -> nx.DiGraph:
    """A directed graph from woven items: link → edge (subject→object), term → bare node."""
    g = nx.DiGraph()
    for it in items:
        if it.kind == "link":
            g.add_edge(it.subject, it.object,
                       relation=it.relation or "links", weight=max(1, it.confirmations))
        elif it.kind == "spiral":
            for pl in it.links:
                g.add_edge(pl["subject"], pl["object"],
                           relation=pl.get("relation", "links"), weight=max(1, it.confirmations))
        else:
            g.add_node(it.term)
    return g


def stats(g: nx.DiGraph) -> dict:
    n = g.number_of_nodes()
    return {
        "nodes": n,
        "edges": g.number_of_edges(),
        "clusters": nx.number_weakly_connected_components(g) if n else 0,
        "density": round(nx.density(g), 4) if n > 1 else 0.0,
    }


def hubs(g: nx.DiGraph, n: int = 8) -> list[dict]:
    """Most-connected terms by degree centrality (pure-Python — no scipy/numpy needed)."""
    if g.number_of_nodes() == 0:
        return []
    dc = nx.degree_centrality(g)
    rows = [{"term": t, "degree": d, "centrality": round(dc.get(t, 0.0), 3)} for t, d in g.degree()]
    rows.sort(key=lambda r: (-r["degree"], -r["centrality"], r["term"]))
    return rows[:n]


def neighbors(g: nx.DiGraph, term: str) -> dict | None:
    if term not in g:
        return None
    return {
        "term": term,
        "out": [{"to": v, "relation": g[term][v].get("relation")} for v in g.successors(term)],
        "in": [{"from": u, "relation": g[u][term].get("relation")} for u in g.predecessors(term)],
    }


def path(g: nx.DiGraph, frm: str, to: str) -> dict | None:
    if frm not in g or to not in g:
        return None
    try:
        p = nx.shortest_path(g.to_undirected(as_view=True), frm, to)
        return {"from": frm, "to": to, "path": p, "hops": len(p) - 1}
    except nx.NetworkXNoPath:
        return {"from": frm, "to": to, "path": None, "hops": None}


def explore(items, *, term: str | None = None, frm: str | None = None,
            to: str | None = None) -> dict:
    """One call for the explorer UI/API: stats + hubs + optional neighbours/path."""
    g = build(items)
    out: dict = {"stats": stats(g), "hubs": hubs(g)}
    if term:
        out["neighbors"] = neighbors(g, term)
    if frm and to:
        out["path"] = path(g, frm, to)
    return out
