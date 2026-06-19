"""Explore the woven knitweb graph with **NetworkX**.

Builds a `networkx.DiGraph` from the World's woven terms (nodes) and links (edges), and offers
graph analytics so players can *explore the web they made*: hub terms (degree + PageRank
centrality — the most-knitted ideas), a term's neighbours, the shortest path between two terms,
and connected-component clusters. Pure analysis over the fabric — the authoritative graph is the
knitweb `Web`; this is the explorer lens on top of it.
"""

from __future__ import annotations

import json
import os

import networkx as nx

# the four languages the chemistry web was woven in (label:<lang> edges)
LANGS = ("en", "ru", "zh", "ar")


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


def _rels(g, u, v) -> list[str]:
    """Every relation label on the edge(s) u→v (works for DiGraph and MultiDiGraph)."""
    data = g.get_edge_data(u, v) or {}
    if g.is_multigraph():
        return [ed.get("relation", "links") for ed in data.values()]
    return [data.get("relation", "links")]


# -- case-insensitive term resolution + suggestions -------------------------
_RESOLVE_ATTR = "_molgang_resolve_index"


def _is_formula_like(folded: str) -> bool:
    """True for a chemistry-formula-ish token: no whitespace, alnum-only, ≥1 digit.

    The guard for the 0↔o fallback — so the swap only ever touches things like ``v205``
    and never normal words (which carry no digit) or multi-word phrases.
    """
    return (bool(folded) and not any(c.isspace() for c in folded)
            and folded.isalnum() and any(c.isdigit() for c in folded))


def _zero_o_variants(folded: str) -> list[str]:
    """0↔o swap variants of a (casefolded) formula-like token, excluding the original.

    Treats digit ``0`` and letter ``o`` as interchangeable, so ``v205`` yields ``v2o5``
    (and ``v2o5`` yields ``v205``). Returns the two single-direction swaps — folding all
    zeros to ``o`` and all ``o`` to ``0`` — which covers the realistic typo both ways.
    """
    out = []
    for variant in (folded.replace("0", "o"), folded.replace("o", "0")):
        if variant != folded and variant not in out:
            out.append(variant)
    return out


def _resolve_index(g) -> dict[str, str]:
    """A ``casefold(name) → actual node`` index, built once and cached on the graph.

    ``casefold`` (not ``lower``) so it folds the full Unicode case map; it is a no-op for
    zh/ar node labels (correct — they are caseless) but resolves en/ru regardless of case.
    The cache is invalidated when the node count changes (graphs here are built once and
    read-only, but this keeps the index correct if a node is ever added).
    """
    idx = g.graph.get(_RESOLVE_ATTR)
    if idx is not None and idx.get("__n__") == g.number_of_nodes():
        return idx
    idx = {"__n__": g.number_of_nodes()}
    for node in g.nodes():
        if isinstance(node, str):
            idx.setdefault(node.casefold(), node)
    g.graph[_RESOLVE_ATTR] = idx
    return idx


def resolve(g, term: str | None) -> str | None:
    """Resolve a user-supplied ``term`` to the real node, case-insensitively.

    Trims surrounding whitespace and casefolds, so ``v2o5`` / ``" V2O5 "`` / ``V2o5`` all
    resolve to the node ``V2O5``. An exact (already-correct) term is returned as-is. When the
    case-insensitive lookup misses *and* the term looks like a chemistry formula (alnum, no
    whitespace, ≥1 digit), a 0↔o typo fallback is tried — so ``v205`` (digit zero) resolves
    to ``V2O5`` (letter O). Returns ``None`` when nothing matches.
    """
    if not term:
        return None
    term = term.strip()
    if not term:
        return None
    if term in g:                       # exact hit — cheapest path
        return term
    idx = _resolve_index(g)
    folded = term.casefold()
    hit = idx.get(folded)
    if hit is not None:                  # case-insensitive hit
        return hit
    if _is_formula_like(folded):         # fallback: 0↔o typo on a formula-like token only
        for variant in _zero_o_variants(folded):
            hit = idx.get(variant)
            if hit is not None:
                return hit
    return None


def suggest(g, term: str | None, limit: int = 8) -> list[str]:
    """Up to ``limit`` node-name suggestions for a term that didn't resolve.

    Case-insensitive: substring matches first (the needle appears anywhere in the node
    name), then prefix matches, then any remaining names containing the needle — so a bare
    ``v`` surfaces ``V2O5``, ``valence electron``, ``vanadium…`` etc. Sorted shortest-first
    so the closest/tightest names float to the top. An empty/blank ``term`` returns ``[]``.
    """
    if not term:
        return []
    needle = term.strip().casefold()
    if not needle:
        return []
    # also match the 0↔o variant of a formula-like query, so 'v205' surfaces 'V2O5'
    needles = [needle]
    if _is_formula_like(needle):
        needles.extend(_zero_o_variants(needle))
    prefix: list[str] = []
    contains: list[str] = []
    for node in g.nodes():
        if not isinstance(node, str):
            continue
        folded = node.casefold()
        if folded == needle:            # exclude only the typed term itself (variants may hit)
            continue
        if any(folded.startswith(n) for n in needles):
            prefix.append(node)
        elif any(n in folded for n in needles):
            contains.append(node)
    prefix.sort(key=lambda s: (len(s), s.casefold()))
    contains.sort(key=lambda s: (len(s), s.casefold()))
    return (prefix + contains)[:limit]


def node_names(g, limit: int | None = None) -> list[str]:
    """Sorted node names — for the UI's type-ahead ``<datalist>``."""
    names = sorted((n for n in g.nodes() if isinstance(n, str)), key=lambda s: s.casefold())
    return names[:limit] if limit else names


def neighbors(g: nx.DiGraph, term: str) -> dict | None:
    term = resolve(g, term)
    if term is None:
        return None
    out, inn = [], []
    for v in g.successors(term):
        for rel in _rels(g, term, v):
            out.append({"to": v, "relation": rel})
    for u in g.predecessors(term):
        for rel in _rels(g, u, term):
            inn.append({"from": u, "relation": rel})
    return {"term": term, "out": out, "in": inn}


def path(g: nx.DiGraph, frm: str, to: str) -> dict | None:
    frm, to = resolve(g, frm), resolve(g, to)
    if frm is None or to is None:
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
        nb = neighbors(g, term)
        out["neighbors"] = nb
        if nb is None:                  # case-insensitive miss → offer suggestions
            out["missing"] = [term]
            out["suggestions"] = suggest(g, term)
    if frm and to:
        res = path(g, frm, to)
        out["path"] = res
        if res is None:
            missing = [t for t in (frm, to) if resolve(g, t) is None]
            out["missing"] = missing
            out["suggestions"] = sorted({s for t in missing for s in suggest(g, t)})
    return out


# -- building from a gateway.App store (the woven p2p web on disk) ----------
def build_from_web(store: dict) -> nx.MultiDiGraph:
    """A `networkx.MultiDiGraph` from a knitweb gateway.App store dump.

    The store format (see ``knitweb.gateway.App._load``) is
    ``{name, balances, records:[ {t:"record", data:{...}} | {t:"link", subject, object,
    relation, weight} ]}``. Each ``record`` (a woven concept/attestation) becomes a node
    carrying its data as attributes; each ``link`` becomes a typed, weighted edge
    (subject→object) — including the multilingual ``label:en|ru|zh|ar`` edges and the
    concept relations (``is-a``, ``part-of``, ``produces`` …). Nodes referenced only by a
    link are auto-created so the whole woven web is represented.

    A *multi*-graph is used deliberately: the woven web has parallel knits between the same
    two terms (e.g. several peers each weaving the same ``label:en`` edge, or a pair joined
    by both a label and a relation). A plain DiGraph would collapse those into one edge and
    under-count the multilingual coverage; the MultiDiGraph keeps every woven link, so all
    523 ``label:<lang>`` edges per language survive.
    """
    g = nx.MultiDiGraph()
    for r in store.get("records", []):
        if r.get("t") == "record":
            data = r.get("data", {})
            key = data.get("key") or data.get("term")
            if not key:
                continue
            attrs = {k: v for k, v in data.items() if k != "key"}
            attrs.setdefault("kind", data.get("kind", "concept"))
            attrs["concept"] = True
            g.add_node(key, **attrs)
        elif r.get("t") == "link":
            s, o = r.get("subject"), r.get("object")
            if s is None or o is None:
                continue
            rel = r.get("relation", "links")
            g.add_edge(s, o, relation=rel, weight=max(1, r.get("weight", 1) or 1))
    return g


def load_web(path: str) -> nx.DiGraph:
    """Load a knitweb gateway.App store JSON from ``path`` into a DiGraph."""
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return build_from_web(json.load(fh))


def language_breakdown(g: nx.DiGraph) -> dict:
    """Count of ``label:<lang>`` edges per language — the multilingual coverage of the web."""
    out = {lng: 0 for lng in LANGS}
    other = 0
    for _, _, d in g.edges(data=True):
        rel = d.get("relation", "")
        if rel.startswith("label:"):
            lng = rel.split(":", 1)[1]
            if lng in out:
                out[lng] += 1
            else:
                other += 1
    if other:
        out["other"] = other
    return out


def web_stats(g: nx.DiGraph) -> dict:
    """stats() enriched with concept count + per-language label breakdown."""
    s = stats(g)
    s["concepts"] = sum(1 for _, d in g.nodes(data=True) if d.get("concept"))
    s["languages"] = language_breakdown(g)
    return s


def centrality_hubs(g: nx.DiGraph, n: int = 12) -> list[dict]:
    """Top terms by degree centrality (excludes pure label-target nodes when possible)."""
    if g.number_of_nodes() == 0:
        return []
    dc = nx.degree_centrality(g)
    rows = [{"term": t, "degree": d, "centrality": round(dc.get(t, 0.0), 4),
             "concept": bool(g.nodes[t].get("concept"))} for t, d in g.degree()]
    rows.sort(key=lambda r: (-r["degree"], -r["centrality"], r["term"]))
    return rows[:n]


def concept(g: nx.DiGraph, key: str) -> dict | None:
    """A concept's 4 language labels (en/ru/zh/ar) + its concept (non-label) relations."""
    key = resolve(g, key)
    if key is None:
        return None
    data = dict(g.nodes[key])
    labels: dict[str, str] = {}
    relations: list[dict] = []
    seen_out: set[tuple] = set()
    for v in g.successors(key):
        for rel in _rels(g, key, v):
            if rel.startswith("label:"):
                labels[rel.split(":", 1)[1]] = v
            elif (rel, v) not in seen_out:
                seen_out.add((rel, v))
                relations.append({"to": v, "relation": rel, "dir": "out"})
    incoming: list[dict] = []
    seen_in: set[tuple] = set()
    for u in g.predecessors(key):
        for rel in _rels(g, u, key):
            if not rel.startswith("label:") and (rel, u) not in seen_in:
                seen_in.add((rel, u))
                incoming.append({"from": u, "relation": rel, "dir": "in"})
    return {
        "key": key,
        "labels": {lng: labels.get(lng) for lng in LANGS},
        "definition": data.get("definition"),
        "formula": data.get("formula"),
        "by": data.get("by"),
        "is_concept": bool(data.get("concept")),
        "relations": relations,
        "incoming": incoming,
    }


def subgraph(g: nx.DiGraph, term: str, depth: int = 2, *, langs=None,
             max_nodes: int = 120) -> dict | None:
    """A focused ego-subgraph around ``term`` (nodes+edges JSON) for the visualisation.

    BFS outward to ``depth`` hops over the undirected view, capped at ``max_nodes`` so the
    client stays interactive. If ``langs`` is given (a set of language codes), only
    ``label:<lang>`` edges for those languages are kept (concept relations always kept).
    """
    term = resolve(g, term)
    if term is None:
        return None
    und = g.to_undirected(as_view=True)
    seen = {term}
    frontier = [term]
    for _ in range(max(1, depth)):
        nxt = []
        for node in frontier:
            for nb in und.neighbors(node):
                if nb not in seen:
                    seen.add(nb)
                    nxt.append(nb)
                    if len(seen) >= max_nodes:
                        break
            if len(seen) >= max_nodes:
                break
        frontier = nxt
        if len(seen) >= max_nodes or not frontier:
            break

    sub = g.subgraph(seen)
    nodes = []
    for nbr in sub.nodes():
        d = g.nodes[nbr]
        nodes.append({
            "id": nbr,
            "concept": bool(d.get("concept")),
            "definition": d.get("definition"),
            "formula": d.get("formula"),
            "center": nbr == term,
        })
    edges = []
    seen_edges: set[tuple] = set()
    for u, v, d in sub.edges(data=True):
        rel = d.get("relation", "links")
        if (u, v, rel) in seen_edges:   # collapse parallel woven knits for the viz
            continue
        seen_edges.add((u, v, rel))
        if rel.startswith("label:"):
            lng = rel.split(":", 1)[1]
            if langs is not None and lng not in langs:
                continue
            kind = "label"
        else:
            kind = "rel"
        edges.append({"from": u, "to": v, "relation": rel,
                      "weight": d.get("weight", 1), "kind": kind})
    return {"center": term, "depth": depth, "nodes": nodes, "edges": edges,
            "truncated": len(seen) >= max_nodes}


def sample_web() -> dict:
    """A tiny built-in chemistry web (gateway.App store shape) so the server boots without data."""
    def lab(key, en, ru, zh, ar):
        return [{"t": "link", "subject": key, "object": en, "relation": "label:en", "weight": 1},
                {"t": "link", "subject": key, "object": ru, "relation": "label:ru", "weight": 1},
                {"t": "link", "subject": key, "object": zh, "relation": "label:zh", "weight": 1},
                {"t": "link", "subject": key, "object": ar, "relation": "label:ar", "weight": 1}]

    records = [
        {"t": "record", "data": {"kind": "concept", "key": "H2O", "formula": "H2O",
                                 "definition": "Water — a compound of hydrogen and oxygen.", "by": "sample"}},
        {"t": "record", "data": {"kind": "concept", "key": "oxygen", "formula": "O",
                                 "definition": "A chemical element, atomic number 8.", "by": "sample"}},
        {"t": "record", "data": {"kind": "concept", "key": "hydrogen", "formula": "H",
                                 "definition": "The lightest chemical element.", "by": "sample"}},
        {"t": "record", "data": {"kind": "concept", "key": "atom", "formula": "",
                                 "definition": "The smallest particle of an element.", "by": "sample"}},
        *lab("H2O", "water", "вода", "水", "ماء"),
        *lab("oxygen", "oxygen", "кислород", "氧", "أكسجين"),
        *lab("hydrogen", "hydrogen", "водород", "氢", "هيدروجين"),
        *lab("atom", "atom", "атом", "原子", "ذرة"),
        {"t": "link", "subject": "H2O", "object": "hydrogen", "relation": "contains", "weight": 1},
        {"t": "link", "subject": "H2O", "object": "oxygen", "relation": "contains", "weight": 1},
        {"t": "link", "subject": "hydrogen", "object": "atom", "relation": "is-a", "weight": 1},
        {"t": "link", "subject": "oxygen", "object": "atom", "relation": "is-a", "weight": 1},
    ]
    return {"name": "sample-chem", "balances": {}, "records": records}
