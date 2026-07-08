"""The shared Knitweb **World** — the living web the game extends.

A confirmed knit weaves into a persistent knitweb fabric `Web`: a **term** knit ensures a
term node; a **link** knit (`A = B`, `A → B`, `A is B`) weaves both term nodes and joins them
with a weighted **edge** — so related terms *combine* into a real knowledge graph instead of
piling up isolated strings. Terms are de-duplicated case-insensitively. The web is anchored to
OriginTrail (a verifiable UAL) and **file-shared across processes**, so two `molgang serve`
instances extend and see the same growing web.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field

from .knit_parse import clean
from . import tension as T
from knitweb.anchor import Notary
from knitweb.anchor.origintrail import OriginTrailAnchorBackend
from knitweb.core.pulse import Pulse
from knitweb.fabric.items import checkpoint, web_state_root
from knitweb.fabric.web import Web

_NOTARY_PRIV = "0" * 63 + "1"  # fixed dev notary so the UAL is reproducible per web state


def _seed_anchor_rel(confirmations: int) -> int:
    """Seed a non-zero anchor reliability from confirm count.

    Use a capped exponential ramp so fresh one-confirm links are already non-slack,
    while extra confirms quickly move fibers toward strong reliability.
    """
    confirms = max(1, int(confirmations))
    rel = 5 * T.DEFAULT_ANCHOR_REL  # confirmations=1 starts neutral (>=300 on SLAUT threshold)
    rel <<= min(confirms - 1, 3)    # grow fast, then saturate
    return min(T.R_MAX, rel)


@dataclass
class WovenItem:
    kind: str            # "term" | "link" | "spiral"
    by: str
    fiber_cid: str
    confirmations: int
    term: str = ""
    subject: str = ""
    object: str = ""
    relation: str = ""
    links: list = field(default_factory=list)   # kind="spiral": ordered link dicts
    validators: int = 0
    pls_staked: int = 0
    anchor_rel: int = 0
    anchor_ts: int = 0
    lang: str = "en"
    dir: str = "ltr"  # W3C base-direction: ltr | rtl (for Arabic, Hebrew, etc.)

    @property
    def label(self) -> str:
        if self.kind == "spiral":
            return (" → ".join([self.links[0]["subject"], *[l["object"] for l in self.links]])
                    if self.links else "spiral")
        if self.kind in ("term", "reaction"):
            return self.term
        return f"{self.subject} {self.relation} {self.object}"


class World:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._mtime = 0.0
        self.web = Web()
        self.items: list[WovenItem] = []
        self.tombstones: set[str] = set()      # #140 redacted fiber CIDs (append-only-safe)
        self.open_spirals: dict[str, dict] = {}
        self._term_cid: dict[tuple[str, str], str] = {}  # key: (canon, lang), value: CID
        self._beat = 0
        # optional hook fired with each NEWLY-woven item (not on file-sync re-apply) — the
        # relay-sync push (knitweb/molgang#44) subscribes here so every confirmed knit/spiral
        # this install weaves is broadcast to the shared web. None ⇒ today's local-only behavior.
        self.on_weave = None
        self._sync()

    def _emit(self, item: WovenItem) -> None:
        if self.on_weave is not None:
            try:
                self.on_weave(item)
            except Exception:
                # Relay callbacks are best effort; local weaving must continue.
                pass

    # -- term de-dup + applying an item to the fabric -----------------------
    def _term_node(self, term: str, lang: str = "en", dir: str = "ltr") -> str:
        # Canonicalise (fold CH₄→CH4, strip markup) so any entry path hashes to ONE node/CID.
        # Terms are deduplicated by (canonical_form, language), not casefold alone,
        # so "sulfur" (en) and "azufre" (es) are separate nodes. W3C langString-compatible.
        canon = clean(term) or term
        key = (canon, lang)  # dedup: (NFC canonical term, BCP-47 language tag)
        cid = self._term_cid.get(key)
        if cid is None:
            cid = self.web.weave({
                "kind": "molgang-term",
                "term": canon,
                "lang": lang,      # BCP-47 tag: en, ru, zh-Hans, ar, etc.
                "dir": dir         # base-direction: ltr (left-to-right) | rtl (right-to-left)
            })
            self._term_cid[key] = cid
        return cid

    def _apply(self, it: WovenItem) -> None:
        if it.kind == "link":
            s = self._term_node(it.subject, lang=it.lang, dir=it.dir)
            o = self._term_node(it.object, lang=it.lang, dir=it.dir)
            self.web.link(s, o, rel=it.relation or "links", weight=max(1, it.confirmations))
        elif it.kind in ("spiral", "reaction"):
            # a reaction weaves like a mini-spiral: every reactant→product pair is a
            # real edge (rel "reacts-to"), so confirmed reactions render in the explorer (#109)
            for pl in it.links:
                s = self._term_node(pl["subject"], lang=it.lang, dir=it.dir)
                o = self._term_node(pl["object"], lang=it.lang, dir=it.dir)
                self.web.link(s, o, rel=pl.get("relation", "links"), weight=max(1, it.confirmations))
        else:
            self._term_node(it.term, lang=it.lang, dir=it.dir)
        self.items.append(it)

    # -- multi-process sharing ---------------------------------------------
    def _sync(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        mt = os.path.getmtime(self.path)
        if mt <= self._mtime:
            return
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.web, self.items, self._term_cid = Web(), [], {}
        self.tombstones = set(data.get("tombstones", []))
        raw_spirals = data.get("open_spirals", {})
        if isinstance(raw_spirals, list):
            self.open_spirals = {str(s.get("cid")): s for s in raw_spirals if s.get("cid")}
        elif isinstance(raw_spirals, dict):
            self.open_spirals = dict(raw_spirals)
        else:
            self.open_spirals = {}
        for d in data.get("items", []):
            self._apply(WovenItem(**d))
        self._mtime = mt

    def _save(self) -> None:
        target = os.path.abspath(self.path)
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {"items": [asdict(i) for i in self.items],
                   "tombstones": sorted(self.tombstones),
                   "open_spirals": list(self.open_spirals.values())}
        fd, tmp = tempfile.mkstemp(
            prefix=f".{os.path.basename(target)}.",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        self._mtime = os.path.getmtime(target)

    # -- open spiral board (non-settlement, shared game coordination) -------
    def list_open_spirals(self, table_id: str | None = None) -> list[dict]:
        self._sync()
        rows = [dict(v) for v in self.open_spirals.values()]
        if table_id is not None:
            rows = [r for r in rows if r.get("table_id") == table_id]
        return sorted(rows, key=lambda r: str(r.get("cid", "")))

    def publish_open_spiral(self, record: dict) -> None:
        self._sync()
        cid = str(record["cid"])
        self.open_spirals[cid] = dict(record)
        if self.path:
            self._save()

    def remove_open_spiral(self, cid: str) -> None:
        self._sync()
        self.open_spirals.pop(str(cid), None)
        if self.path:
            self._save()

    # -- the operation the game calls on a confirmed knit -------------------
    def weave_knit(self, parsed: dict, by: str, fiber_cid: str, confirmations: int) -> None:
        self._sync()
        links = []
        if parsed.get("kind") == "reaction":
            # strip stoichiometric coefficients for the node names (2H2O -> H2O);
            # the full equation (with conditions) is preserved as the item's term.
            import re as _re
            strip = lambda s: _re.sub(r"^\d+\s*", "", s)
            links = [{"subject": strip(r), "object": strip(p), "relation": "reacts-to"}
                     for r in parsed.get("reactants", []) for p in parsed.get("products", [])]
        item = WovenItem(
            kind=parsed.get("kind", "term"), by=by, fiber_cid=fiber_cid, confirmations=confirmations,
            term=parsed.get("term", ""), subject=parsed.get("subject", ""),
            object=parsed.get("object", ""), relation=parsed.get("relation", ""),
            links=links,
            lang=parsed.get("lang", "en"),  # BCP-47 tag: en, ru, zh-Hans, ar, etc.
            dir=parsed.get("dir", "ltr"),   # W3C base-direction: ltr | rtl
            anchor_rel=_seed_anchor_rel(confirmations), anchor_ts=int(time.time()),
        )
        self._apply(item)
        if self.path:
            self._save()
        self._emit(item)

    def weave_links(self, links: list[dict], by: str, fiber_cid: str, confirmations: int,
                    lang: str = "en", dir: str = "ltr") -> None:
        """Weave every link of a one-to-many knit — each link → two term-nodes + one weighted
        edge (weight = max(1, confirmations), an INTEGER). Because clean() folds CH₄→CH4 the
        node CID is canonical, so duplicate spellings hash to the same node automatically.
        Terms are deduplicated per (canonical_form, lang), making multilingual graphs possible."""
        self._sync()
        seen: set[tuple[str, str, str, str]] = set()
        woven: list[WovenItem] = []
        for pl in links:
            # Dedup key now includes language: (subject, relation, object, lang)
            key = (pl["subject"], pl.get("relation", "links"), pl["object"], lang)
            if key in seen:                       # belt-and-suspenders dedup before weaving
                continue
            seen.add(key)
            item = WovenItem(
                kind="link", by=by, fiber_cid=fiber_cid, confirmations=confirmations,
                subject=pl["subject"], object=pl["object"], relation=pl.get("relation", "links"),
                lang=lang, dir=dir,
                anchor_rel=_seed_anchor_rel(confirmations), anchor_ts=int(time.time()),
            )
            self._apply(item)
            woven.append(item)
        if self.path:
            self._save()
        for item in woven:
            self._emit(item)

    def weave_spiral(self, links: list[dict], by: str, fiber_cid: str, confirmations: int,
                     *, validators: int = 0, pls_staked: int = 0, lang: str = "en", dir: str = "ltr") -> None:
        """A captured spiral: weave every link (each → two term-nodes + a weighted edge) and
        record one kind='spiral' item for provenance/replay. One call, many edges.
        Supports multilingual spirals via lang/dir parameters."""
        self._sync()
        item = WovenItem(
            kind="spiral", by=by, fiber_cid=fiber_cid, confirmations=confirmations,
            links=[{"subject": l["subject"], "object": l["object"],
                    "relation": l.get("relation", "links")} for l in links],
            validators=validators, pls_staked=pls_staked,
            lang=lang, dir=dir,
            anchor_rel=_seed_anchor_rel(confirmations), anchor_ts=int(time.time()),
        )
        self._apply(item)
        if self.path:
            self._save()
        self._emit(item)

    # -- views --------------------------------------------------------------
    def size(self) -> tuple[int, int]:
        self._sync(); return self.web.size

    def state_root(self) -> str:
        self._sync(); return web_state_root(self.web)

    def anchor(self) -> dict:
        self._sync()
        if not self.items:
            return {"ual": None, "verified": False, "nodes": 0, "edges": 0}
        self._beat += 1
        beat = Pulse(interval_s=60, genesis_ts=0).beat(timestamp=self._beat, state_root=web_state_root(self.web))
        cp = checkpoint(self.web, beat)
        receipt = Notary(_NOTARY_PRIV).anchor(cp, OriginTrailAnchorBackend(), self._beat)
        n, e = self.web.size
        return {"ual": receipt.external_ref, "state_root": cp.state_root,
                "receipt_cid": receipt.cid, "verified": bool(receipt.sig), "nodes": n, "edges": e}

    def graph(self, limit: int = 50) -> dict:
        self._sync()
        nodes, edges = self.web.size
        from .moderation import REDACTED_LABEL
        def _lbl(i):
            return REDACTED_LABEL if i.fiber_cid in self.tombstones else i.label
        recent = [{"kind": i.kind, "label": _lbl(i), "by": i.by,
                   "confirmations": i.confirmations, "fiber": i.fiber_cid,
                   "redacted": i.fiber_cid in self.tombstones}
                  for i in self.items[-limit:][::-1]]
        links = [{"subject": i.subject, "relation": i.relation, "object": i.object, "by": i.by}
                 for i in self.items if i.kind == "link" and i.fiber_cid not in self.tombstones]
        # The woven vocabulary as case-preserved term strings, deduped across the
        # (term, lang) keys. Case is significant for chemistry (Co ≠ CO), so terms
        # are NOT folded; language-tagged duplicates collapse to one display string.
        terms = sorted({term for (term, _lang) in self._term_cid})
        return {"nodes": nodes, "edges": edges, "state_root": web_state_root(self.web),
                "recent": recent, "links": links[-limit:][::-1], "terms": terms}

    def tombstone(self, fiber_cid: str) -> bool:
        """Redact a woven Fiber by CID (#140 takedown). The item stays in the
        append-only log so the state root is unchanged; graph/display redact it.
        Returns whether it newly tombstoned."""
        self._sync()
        if fiber_cid in self.tombstones:
            return False
        self.tombstones.add(fiber_cid)
        if self.path:
            self._save()
        return True

    def explore(self, *, term: str | None = None, frm: str | None = None,
                to: str | None = None) -> dict:
        """Explore the woven graph with NetworkX (hubs, neighbours, shortest path)."""
        from . import graphx
        self._sync()
        return graphx.explore(self.items, term=term, frm=frm, to=to)


    def to_jsonld(self) -> dict:
        """Export the woven fabric as JSON-LD (schema.org + knitweb vocab).

        The export is provenance-linked (#107): it embeds the OriginTrail anchor
        (UAL + state_root) from :meth:`anchor` so external DKG tooling can verify
        the fabric offline against the anchored state. Term nodes carry their
        language + W3C base direction so multilingual webs survive round-trips.
        """
        self._sync()
        graph = []
        for item in self.items:
            node: dict = {
                "@id": f"knitweb:fiber/{item.fiber_cid}",
                "@type": "knitweb:Fiber",
                "knitweb:kind": item.kind,
                "knitweb:by": item.by,
                "knitweb:confirmations": item.confirmations,
            }
            if item.kind == "term":
                node["knitweb:term"] = item.term
                node["knitweb:lang"] = item.lang
                node["knitweb:baseDirection"] = "rtl" if item.lang in _RTL_LANGS else "ltr"
            elif item.kind == "link":
                node["knitweb:subject"] = item.subject
                node["knitweb:relation"] = item.relation
                node["knitweb:object"] = item.object
            elif item.kind == "spiral":
                node["knitweb:links"] = item.links
            elif item.kind == "reaction":
                node["knitweb:equation"] = item.term
                node["knitweb:links"] = item.links
            graph.append(node)
        anchor = self.anchor()
        return {
            "@context": {
                "schema": "https://schema.org/",
                "knitweb": "https://knitweb.art/vocab#",
                "prov": "http://www.w3.org/ns/prov#",
            },
            "knitweb:provenance": {
                "@type": "prov:Entity",
                "knitweb:ual": anchor.get("ual"),
                "knitweb:stateRoot": anchor.get("state_root"),
                "knitweb:verified": bool(anchor.get("verified", False)),
            },
            "@graph": graph,
        }


VALID_LANGS: frozenset[str] = frozenset({"en", "nl", "ru", "zh", "ar"})
_RTL_LANGS: frozenset[str] = frozenset({"ar"})


def validate_lang(lang: str | None) -> str:
    """Return ``lang`` if valid, raise ``ValueError`` otherwise.

    ``None`` or empty string returns ``"en"`` as default.
    RTL languages (``ar``) are accepted; the caller must handle direction.
    """
    if not lang:
        return "en"
    if lang not in VALID_LANGS:
        raise ValueError(f"unsupported lang {lang!r}; valid: {sorted(VALID_LANGS)}")
    return lang


def default_world_path() -> str:
    return os.environ.get("MOLGANG_WORLD", os.path.expanduser("~/.molgang/world.json"))
