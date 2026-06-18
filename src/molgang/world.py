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
from dataclasses import asdict, dataclass

from knitweb.anchor import Notary
from knitweb.anchor.origintrail import OriginTrailAnchorBackend
from knitweb.core.pulse import Pulse
from knitweb.fabric.items import checkpoint, web_state_root
from knitweb.fabric.web import Web

_NOTARY_PRIV = "0" * 63 + "1"  # fixed dev notary so the UAL is reproducible per web state


@dataclass
class WovenItem:
    kind: str            # "term" | "link"
    by: str
    fiber_cid: str
    confirmations: int
    term: str = ""
    subject: str = ""
    object: str = ""
    relation: str = ""

    @property
    def label(self) -> str:
        return self.term if self.kind == "term" else f"{self.subject} {self.relation} {self.object}"


class World:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._mtime = 0.0
        self.web = Web()
        self.items: list[WovenItem] = []
        self._term_cid: dict[str, str] = {}
        self._beat = 0
        self._sync()

    # -- term de-dup + applying an item to the fabric -----------------------
    def _term_node(self, term: str) -> str:
        key = term.casefold()
        cid = self._term_cid.get(key)
        if cid is None:
            cid = self.web.weave({"kind": "molgang-term", "term": term})
            self._term_cid[key] = cid
        return cid

    def _apply(self, it: WovenItem) -> None:
        if it.kind == "link":
            s, o = self._term_node(it.subject), self._term_node(it.object)
            self.web.link(s, o, rel=it.relation or "links", weight=max(1, it.confirmations))
        else:
            self._term_node(it.term)
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
        for d in data.get("items", []):
            self._apply(WovenItem(**d))
        self._mtime = mt

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"items": [asdict(i) for i in self.items]}, fh, indent=2, ensure_ascii=False)
        self._mtime = os.path.getmtime(self.path)

    # -- the operation the game calls on a confirmed knit -------------------
    def weave_knit(self, parsed: dict, by: str, fiber_cid: str, confirmations: int) -> None:
        self._sync()
        self._apply(WovenItem(
            kind=parsed.get("kind", "term"), by=by, fiber_cid=fiber_cid, confirmations=confirmations,
            term=parsed.get("term", ""), subject=parsed.get("subject", ""),
            object=parsed.get("object", ""), relation=parsed.get("relation", ""),
        ))
        if self.path:
            self._save()

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
        recent = [{"kind": i.kind, "label": i.label, "by": i.by,
                   "confirmations": i.confirmations, "fiber": i.fiber_cid}
                  for i in self.items[-limit:][::-1]]
        links = [{"subject": i.subject, "relation": i.relation, "object": i.object, "by": i.by}
                 for i in self.items if i.kind == "link"]
        terms = sorted(self._term_cid)  # the woven vocabulary (case-folded keys)
        return {"nodes": nodes, "edges": edges, "state_root": web_state_root(self.web),
                "recent": recent, "links": links[-limit:][::-1], "terms": terms}


def default_world_path() -> str:
    return os.environ.get("MOLGANG_WORLD", os.path.expanduser("~/.molgang/world.json"))
