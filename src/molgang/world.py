"""The shared Knitweb **World** — the living web the game extends.

Every confirmed knit **extends a shared, persistent knitweb fabric `Web`**: the term becomes a
content-addressed node, linked under its topic with a weighted edge (weight = peer
confirmations). The web grows as people play, its state_root changes, and it's anchored to
OriginTrail (a verifiable UAL).

The World is **file-shared across processes**: two `molgang serve` instances (e.g. :8765 and
:9876) pointed at the same `--world` file extend and see the *same* growing web — each op syncs
from disk first (so player A's knit on :8765 appears for player B on :9876). The fabric is the
real `knitweb.fabric.web.Web`; the knitweb P2P layer feeds peer records into the same interface.
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
class WovenEdge:
    topic: str
    term: str
    by: str
    fiber_cid: str
    confirmations: int


class World:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._mtime = 0.0
        self.web = Web()
        self.edges: list[WovenEdge] = []
        self._topic_cid: dict[str, str] = {}
        self._beat = 0
        self._sync()

    # -- multi-process sharing: pull the shared file if it changed -----------
    def _sync(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        mt = os.path.getmtime(self.path)
        if mt <= self._mtime:
            return
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.web, self.edges, self._topic_cid = Web(), [], {}
        for w in data.get("edges", []):
            self._weave(WovenEdge(**w))
        self._mtime = mt

    def _weave(self, w: WovenEdge) -> str:
        tcid = self._topic_cid.get(w.topic)
        if tcid is None:
            tcid = self.web.weave({"kind": "molgang-topic", "topic": w.topic})
            self._topic_cid[w.topic] = tcid
        ncid = self.web.weave({"kind": "molgang-term", "term": w.term, "by": w.by, "fiber": w.fiber_cid})
        self.web.link(tcid, ncid, rel="has-term", weight=max(1, w.confirmations))
        self.edges.append(w)
        return ncid

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"edges": [asdict(w) for w in self.edges]}, fh, indent=2, ensure_ascii=False)
        self._mtime = os.path.getmtime(self.path)

    # -- the one operation the game calls on a confirmed knit ---------------
    def extend(self, term: str, by: str, fiber_cid: str, confirmations: int,
               topic: str | None = None) -> str:
        self._sync()  # pull other players' extends first
        ncid = self._weave(WovenEdge((topic or term).strip().lower(), term, by, fiber_cid, confirmations))
        if self.path:
            self._save()
        return ncid

    # -- views (sync first so they reflect every player) --------------------
    def size(self) -> tuple[int, int]:
        self._sync(); return self.web.size

    def state_root(self) -> str:
        self._sync(); return web_state_root(self.web)

    def anchor(self) -> dict:
        self._sync()
        if not self.edges:
            return {"ual": None, "verified": False, "nodes": 0, "edges": 0}
        self._beat += 1
        beat = Pulse(interval_s=60, genesis_ts=0).beat(timestamp=self._beat, state_root=web_state_root(self.web))
        cp = checkpoint(self.web, beat)
        receipt = Notary(_NOTARY_PRIV).anchor(cp, OriginTrailAnchorBackend(), self._beat)
        n, e = self.web.size
        return {"ual": receipt.external_ref, "state_root": cp.state_root,
                "receipt_cid": receipt.cid, "verified": bool(receipt.sig), "nodes": n, "edges": e}

    def graph(self, limit: int = 40) -> dict:
        self._sync()
        nodes, edges = self.web.size
        recent = [{"topic": w.topic, "term": w.term, "by": w.by,
                   "confirmations": w.confirmations, "fiber": w.fiber_cid} for w in self.edges[-limit:][::-1]]
        topics: dict[str, list[str]] = {}
        for w in self.edges:
            topics.setdefault(w.topic, [])
            if w.term not in topics[w.topic]:
                topics[w.topic].append(w.term)
        return {"nodes": nodes, "edges": edges, "state_root": web_state_root(self.web),
                "recent": recent, "topics": topics}


def default_world_path() -> str:
    return os.environ.get("MOLGANG_WORLD", os.path.expanduser("~/.molgang/world.json"))
