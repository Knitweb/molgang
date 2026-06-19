"""Merge many locally-woven knitworks into **ONE** knitweb.

Each builder / agent / play-session weaves its own little web on disk in one of a handful
of shapes — a knitweb :class:`knitweb.gateway.App` store (``{records:[…]}``), a molgang
:class:`molgang.world.World` (``{items:[WovenItem…]}``), the explorer graph-export
(``{nodes,edges,links,terms,…}``), or a bare ``{edges:[…]}`` topic dump. This module
**normalises every shape into one common node/edge set, dedups, and unions** so the
co-woven fibers combine into a single, higher-tension knitweb instead of N scattered ones.

Normalisation rules (mirrors how :class:`molgang.world.World` already weaves):

* **Nodes** are de-duplicated by ``casefold(term)`` (``CH₄`` ↔ ``CH4`` is folded upstream by
  :func:`molgang.knit_parse.clean`, so the same concept hashes to one node).
* **Edges** are unioned by ``(casefold(subject), relation, casefold(object))``; on a
  duplicate edge the **confirmations / weights SUM** — so a fiber several sources each wove
  ends up *tauter* (higher confirm count → higher tautness in :mod:`molgang.tension`).
* Multilingual ``label:<lang>`` edges, concept relations (``is-a``/``part-of``/…) and
  ``spiral`` reaction-chain links are all preserved (they are just edges with a relation).
* Concept *records* (definition / formula / 4-language data) are merged into per-term
  attributes so the explorer's ``/api/kg/concept`` still resolves the rich data.

The result is emitted as a molgang ``World`` document (``{items:[…]}``) — losslessly
re-loadable by :class:`molgang.world.World` and the explorer (which converts a world to a
store on the fly), and the format the task asked the combined web to live in.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import asdict

from .knit_parse import clean
from .world import WovenItem

# the language tags carried on label:<lang> edges (kept multilingual through the merge)
LANGS = ("en", "ru", "zh", "ar")


# -- canonical keys ----------------------------------------------------------
def _canon(term: str) -> str:
    """Canonical *display* form of a term (markup-stripped, CH₄→CH4) — keeps the prettiest
    spelling for the merged node while :func:`_key` folds case for de-duplication."""
    return clean(term) or term


def _key(term: str) -> str:
    """The de-dup key for a term: ``casefold`` of its canonical form (CH₄ ↔ ch4 ↔ CH4)."""
    return _canon(term).casefold()


# -- the accumulator ---------------------------------------------------------
class _Merged:
    """Accumulates normalised nodes (with merged attrs) and unioned edges across sources."""

    def __init__(self) -> None:
        # casefold-key -> display term (first/prettiest spelling wins, kept stable)
        self.terms: dict[str, str] = {}
        # casefold-key -> merged concept attributes (definition/formula/labels/by/kind)
        self.attrs: dict[str, dict] = {}
        # (subj-key, relation, obj-key) -> {"subject","object","relation","weight","by"}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.sources: list[str] = []

    def add_term(self, term: str, attrs: dict | None = None) -> str:
        term = (term or "").strip()
        if not term:
            return ""
        k = _key(term)
        self.terms.setdefault(k, _canon(term))
        if attrs:
            cur = self.attrs.setdefault(k, {})
            for key, val in attrs.items():
                if val in (None, "", {}):
                    continue
                cur.setdefault(key, val)        # first non-empty value for an attribute wins
        return self.terms[k]

    def add_edge(self, subject: str, obj: str, relation: str, weight: int, by: str = "") -> None:
        subject, obj = (subject or "").strip(), (obj or "").strip()
        if not subject or not obj:
            return
        self.add_term(subject)
        self.add_term(obj)
        relation = relation or "links"
        k = (_key(subject), relation, _key(obj))
        w = max(1, int(weight or 1))
        e = self.edges.get(k)
        if e is None:                           # first time this fiber is seen
            self.edges[k] = {"subject": self.terms[_key(subject)],
                             "object": self.terms[_key(obj)],
                             "relation": relation, "weight": w, "by": by or ""}
        else:                                   # co-woven fiber — SUM the tension
            e["weight"] += w
            if by and not e["by"]:
                e["by"] = by

    # -- emit ---------------------------------------------------------------
    def world_items(self) -> list[dict]:
        """The merged web as molgang ``WovenItem`` dicts (term nodes first, then link edges).

        Bare term nodes are emitted only when no edge already touches them, so the document
        stays small but every node is representable (matching ``World``'s own weave order).
        """
        items: list[WovenItem] = []
        edged: set[str] = set()
        for e in self.edges.values():
            edged.add(_key(e["subject"]))
            edged.add(_key(e["object"]))
            items.append(WovenItem(
                kind="link", by=e["by"] or "merge", fiber_cid="",
                confirmations=e["weight"], subject=e["subject"],
                object=e["object"], relation=e["relation"]))
        for k, term in sorted(self.terms.items()):
            if k in edged:
                continue
            a = self.attrs.get(k, {})
            items.append(WovenItem(kind="term", by=a.get("by", "merge"), fiber_cid="",
                                   confirmations=1, term=term))
        return [asdict(i) for i in items]

    def app_records(self) -> list[dict]:
        """The merged web as gateway.App store records (concept records + typed link edges).

        Preserves each term's merged concept attributes (definition/formula/labels) so the
        explorer's concept panel stays rich; every unioned edge becomes one weighted link.
        """
        records: list[dict] = []
        for k, term in sorted(self.terms.items()):
            data = {"kind": "concept", "key": term, **{kk: vv for kk, vv in
                    self.attrs.get(k, {}).items() if kk != "kind"}}
            records.append({"t": "record", "data": data})
        for e in self.edges.values():
            records.append({"t": "link", "subject": e["subject"], "object": e["object"],
                            "relation": e["relation"], "weight": e["weight"]})
        return records


# -- source-shape detectors + normalisers ------------------------------------
def _ingest_app_store(m: _Merged, d: dict) -> None:
    """gateway.App store: ``{records:[{t:record,data}|{t:link,subject,object,relation,weight}]}``."""
    for r in d.get("records", []):
        if r.get("t") == "record":
            data = r.get("data", {})
            key = data.get("key") or data.get("term")
            if not key:
                continue
            attrs = {kk: vv for kk, vv in data.items() if kk not in ("key", "term")}
            m.add_term(key, attrs)
        elif r.get("t") == "link":
            m.add_edge(r.get("subject", ""), r.get("object", ""),
                       r.get("relation", "links"), r.get("weight", 1))


def _ingest_world(m: _Merged, d: dict) -> None:
    """molgang World: ``{items:[WovenItem…]}`` (kind term / link / spiral)."""
    for it in d.get("items", []):
        kind = it.get("kind", "term")
        conf = max(1, int(it.get("confirmations", 1) or 1))
        by = it.get("by", "")
        if kind == "link":
            m.add_edge(it.get("subject", ""), it.get("object", ""),
                       it.get("relation") or "links", conf, by)
        elif kind == "spiral":
            for pl in it.get("links", []):
                m.add_edge(pl.get("subject", ""), pl.get("object", ""),
                           pl.get("relation") or "links", conf, by)
        else:
            m.add_term(it.get("term", ""), {"by": by} if by else None)


def _ingest_graph_export(m: _Merged, d: dict) -> None:
    """Explorer graph-export: ``{nodes,edges,links:[{subject,relation,object,by}],terms,…}``."""
    for t in d.get("terms", []):
        m.add_term(t)
    for ln in d.get("links", []):
        m.add_edge(ln.get("subject", ""), ln.get("object", ""),
                   ln.get("relation") or "links", 1, ln.get("by", ""))


def _ingest_edges_dump(m: _Merged, d: dict) -> None:
    """Bare topic dump: ``{edges:[{topic,term,by,confirmations,…}]}`` — each is a term node.

    These carry a ``topic`` and a ``term`` but no subject/object, so they are woven as term
    nodes (and, when a distinct topic is present, a ``topic → term`` ``in-topic`` edge)."""
    for e in d.get("edges", []):
        term = e.get("term", "")
        topic = e.get("topic", "")
        conf = max(1, int(e.get("confirmations", 1) or 1))
        by = e.get("by", "")
        m.add_term(term, {"by": by} if by else None)
        if topic and _key(topic) != _key(term):
            m.add_edge(topic, term, "in-topic", conf, by)


def ingest(m: _Merged, d: dict) -> str:
    """Detect a source document's shape and ingest it. Returns the detected shape label."""
    if "records" in d:
        _ingest_app_store(m, d); return "app-store"
    if "items" in d:
        _ingest_world(m, d); return "world"
    if "links" in d or "terms" in d:
        _ingest_graph_export(m, d); return "graph-export"
    if "edges" in d:
        _ingest_edges_dump(m, d); return "edges-dump"
    return "unknown"


# -- the public API ----------------------------------------------------------
def merge_files(paths: list[str]) -> _Merged:
    """Merge every existing source path into one :class:`_Merged` accumulator (skip missing)."""
    m = _Merged()
    for p in paths:
        p = os.path.expanduser(p)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        shape = ingest(m, d)
        if shape != "unknown":
            m.sources.append(f"{p} ({shape})")
    return m


def discover_sources(extra: list[str] | None = None) -> list[str]:
    """The default source set: the named webs/worlds plus a glob of ``*_web.json`` /
    ``*world*.json`` under ``/tmp`` and ``~/.molgang`` (deduped, order-stable)."""
    named = [
        "/tmp/chem_web.json",
        os.path.expanduser("~/.molgang/world.json"),
        "/tmp/mg_machine.json",
    ]
    globbed: list[str] = []
    for pat in ("/tmp/*_web.json", "/tmp/*world*.json",
                os.path.expanduser("~/.molgang/*world*.json"),
                os.path.expanduser("~/.molgang/*_web.json")):
        globbed.extend(sorted(glob.glob(pat)))
    out: list[str] = []
    for p in [*(extra or []), *named, *globbed]:
        rp = os.path.realpath(os.path.expanduser(p))
        if rp not in {os.path.realpath(x) for x in out}:
            out.append(p)
    return out


def write_world(m: _Merged, path: str) -> dict:
    """Write the merged web as a molgang World document and return its node/edge size."""
    items = m.world_items()
    os.makedirs(os.path.dirname(os.path.expanduser(path)) or ".", exist_ok=True)
    with open(os.path.expanduser(path), "w", encoding="utf-8") as fh:
        json.dump({"items": items}, fh, indent=2, ensure_ascii=False)
    return {"items": len(items), "nodes": len(m.terms), "edges": len(m.edges)}


def stats(m: _Merged) -> dict:
    """Combined stats over the merged web: nodes / edges / concepts / languages / tension.

    Builds the merged web as a gateway.App store and runs the same :mod:`molgang.graphx`
    lenses the explorer uses (so the numbers match ``/api/kg/stats`` + ``/api/kg/tension``).
    """
    from . import graphx

    store = {"name": "combined-knitweb", "balances": {}, "records": m.app_records()}
    g = graphx.build_from_web(store)
    s = graphx.web_stats(g)
    s["distinct_concepts"] = s.get("concepts", 0)
    s["hubs"] = graphx.centrality_hubs(g, 12)
    s["tension"] = graphx.tension_stats(g)
    s["sources"] = m.sources
    return s


def anchor(m: _Merged) -> dict:
    """Anchor the merged web to OriginTrail via :class:`molgang.world.World` → a UAL."""
    import tempfile

    from .world import World

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump({"items": m.world_items()}, tf, ensure_ascii=False)
        tmp = tf.name
    try:
        return World(tmp).anchor()
    finally:
        os.unlink(tmp)


def main(argv: list[str]) -> int:
    """``molgang merge`` — merge sources into one knitweb, write it, and report.

        molgang merge [--out /tmp/combined_knitweb.json] [--source PATH …] [--app-store]
    """
    import argparse

    ap = argparse.ArgumentParser(prog="molgang merge",
                                 description="Merge locally-woven knitworks into ONE knitweb")
    ap.add_argument("--out", default="/tmp/combined_knitweb.json",
                    help="output path for the combined knitweb (default /tmp/combined_knitweb.json)")
    ap.add_argument("--source", action="append", default=[],
                    help="an extra source web/world JSON (repeatable); added to the default set")
    ap.add_argument("--app-store", action="store_true",
                    help="emit a gateway.App store instead of a molgang World document")
    ap.add_argument("--no-anchor", action="store_true", help="skip the OriginTrail anchor")
    a = ap.parse_args([x for x in argv if x != "merge"])

    sources = discover_sources(a.source)
    m = merge_files(sources)

    out = os.path.expanduser(a.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if a.app_store:
        doc = {"name": "combined-knitweb", "balances": {}, "records": m.app_records()}
    else:
        doc = {"items": m.world_items()}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    s = stats(m)
    print(f"  🕸 merged {len(m.sources)} source(s) → {out}")
    for src in m.sources:
        print(f"     · {src}")
    print(f"  nodes {s['nodes']} · edges {s['edges']} · concepts {s['distinct_concepts']} "
          f"· clusters {s['clusters']}")
    print(f"  languages {s['languages']}")
    t = s["tension"]["bands"]
    print(f"  tension taut {t.get('taut', 0)} · neutral {t.get('neutral', 0)} "
          f"· slack {t.get('slack', 0)} · contested {t.get('contested', 0)}")
    print("  top hubs: " + ", ".join(f"{h['term']}({h['degree']})" for h in s["hubs"][:8]))
    if not a.no_anchor:
        anc = anchor(m)
        print(f"  ⛓ OriginTrail UAL {anc.get('ual')}  (verified={anc.get('verified')})")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
