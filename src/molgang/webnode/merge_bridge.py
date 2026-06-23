"""merge_bridge — the in-tab, server-free deterministic merge for the MOLGANG peer.

Canonical server-free architecture (Variant A): every browser tab runs the UNCHANGED
``molgang`` + ``knitweb`` Python bytes via Pyodide. This module is the thin, NEW bridge the
Pyodide engine worker calls to fold a peer's woven item into the local
:class:`molgang.world.World` and to read the canonical ``web_state_root``/UAL — with NO server
in the path. Two peers who exchange the same signed items therefore converge on the SAME
``web_state_root`` (and the same OriginTrail UAL) regardless of arrival order.

It is *wrap, not re-implement*. Every byte-identity-critical operation is delegated to the
already-audited modules so this bridge can never introduce a fork:

  * dedup keys           -> :func:`molgang.relay_sync.item_keys`  (the SAME casefold/edge keys
                            ``World.weave_links`` and ``molgang.merge`` fold on)
  * signature verify     -> :func:`molgang.relay_sync.verify_message` (exact relay pre-image
                            ``"knitweb-relay:v1\n{to}\n{topic}\n{body}"``)
  * body <-> item        -> :func:`molgang.relay_sync.item_from_body` / :func:`pack`
  * weaving / bumping    -> the World's own ``weave_*`` entry points + the relay-sync
                            confirmations/tension SUM rule (co-woven fibers get tauter)
  * CID / canonical CBOR -> ``knitweb.core.canonical`` (via World + WovenItem) — never here
  * state_root           -> :func:`knitweb.fabric.items.web_state_root` (via ``World.state_root``)

SACRED INVARIANTS preserved:
  (a) INTEGER-ONLY: every weight/confirmation is an ``int``; this module uses only ``+`` and
      ``max`` on integers and ``//`` is never needed. No ``float``/``round``/``/`` touches a
      decision, scoring, or ordering path.
  (b) NO wall-clock / NO randomness on a decision path: the bridge takes ordering ONLY from the
      caller-supplied signed item set and the World's own deterministic fold. It NEVER calls
      ``time.time()`` or ``random``. (``WovenItem.anchor_ts`` is display/seasonal metadata that
      the World already excludes from the CID / state-root hash — the bridge never reads it for
      a decision.)
  (c) BYTE-IDENTITY: all CID / canonical-CBOR / signature / state-root bytes are produced by the
      unchanged ``knitweb`` / ``molgang`` modules. This bridge moves items, it does not encode.

VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. (Never "loom".)
"""

from __future__ import annotations

import json
from dataclasses import asdict

from molgang import relay_sync
from molgang.relay_sync import (
    WEB_TOPIC,
    item_from_body,
    item_keys,
    pack,
    signed_preimage,
    verify_message,
)
from molgang.world import World, WovenItem

from knitweb.ledger.node import AccountNode

__all__ = [
    "MergeBridge",
    "WEB_TOPIC",
    "signed_preimage",
    "verify_message",
    "item_keys",
]


def account_from_seed(seed: str) -> AccountNode:
    """Derive this peer's stable identity from the device seed held in IndexedDB.

    Deterministic and pure — ``priv = sha256("knitweb:account:seed:" + seed)`` (node.py). This is
    the server-free replacement for ``pulse_host.py``'s subprocess shell-out: identity is derived
    in-process, with NO ``subprocess`` and NO key file to manage. The SAME seed signs the
    wallet-signed QR onboarding challenge, so the wallet IS the identity.
    """
    return AccountNode.from_seed(seed)


class MergeBridge:
    """Bind one local :class:`World` and one signing :class:`AccountNode` for in-tab merge.

    The Pyodide worker constructs ONE of these per tab. ``world`` is a :class:`molgang.world.World`
    whose ``path`` is ``None`` (the tab persists via IndexedDB, not the filesystem) — the bridge
    keeps an in-memory dedup index instead of re-reading a file. ``signer`` is the peer's stable
    account. The same item woven on two peers maps to ONE :func:`item_keys` key, so a re-applied
    fiber BUMPS its confirmations/tension (integer SUM) rather than double-counting, and both
    peers reach the SAME ``web_state_root``.
    """

    def __init__(self, world: World, signer: AccountNode, *, topic: str = WEB_TOPIC) -> None:
        self.world = world
        self.signer = signer
        self.topic = topic
        # the de-dup index of every fiber key already present in the local World
        self._seen: set[tuple] = set()
        self._reindex()

    # -- identity / construction ------------------------------------------

    @classmethod
    def from_seed(cls, seed: str, world: World | None = None, *, topic: str = WEB_TOPIC) -> "MergeBridge":
        """Build a bridge from a device seed (the in-tab path: no file, no subprocess)."""
        return cls(world if world is not None else World(None), account_from_seed(seed), topic=topic)

    # -- local de-dup index (in-memory; the tab has no file to re-read) -----

    def _reindex(self) -> None:
        """Rebuild the seen-key index from the World's current items.

        Unlike :meth:`molgang.relay_sync.RelaySync._reindex` (which calls ``World._sync()`` to
        re-read a shared file), the in-tab World has no path, so we index the live items directly.
        """
        self._seen = set()
        for it in self.world.items:
            self._seen.update(item_keys(it))

    # -- the engine's outbound path: pack a locally-woven item for a peer ---

    def pack_local(self, item: WovenItem, *, to: str = "") -> dict:
        """Sign a locally-woven item into a relay message ``{from,to,topic,body,sig}``.

        Delegates to :func:`molgang.relay_sync.pack`, so ``body`` is the canonical (sorted-key,
        compact) JSON the signer signed and a peer re-verifies byte-for-byte. The worker hands the
        result to the JS shell, which frames it with ``write_frame_bytes`` and enqueues the EXACT
        bytes in the IndexedDB outbox (``store_idb.enqueueOutbound``) for delivery over a
        DataChannel — never altered, so the bytes that leave the peer are the bytes it signed.
        """
        msg = pack(item, self.signer, topic=self.topic, to=to)
        # record our own fiber keys so a later echo of our own push is a no-op (we already wove it)
        self._seen.update(item_keys(item))
        return msg

    # -- the engine's inbound path: verify + fold a peer's signed message ---

    def apply_remote_message(self, msg: dict) -> dict:
        """Verify a peer's signed relay message end-to-end, then fold its item into the World.

        Returns ``{"status": <str>, ...}`` where status is one of:
          * ``"applied"``  — a genuinely new fiber was woven (new node/edge set)
          * ``"bumped"``   — an already-woven fiber's confirmations/tension was SUMMED (co-woven)
          * ``"own"``      — our own echoed push; already woven + counted, skipped
          * ``"rejected"`` — signature did not verify against the exact relay pre-image
          * ``"skipped"``  — not a WovenItem body, or a term-only re-apply (no edge to bump)

        Verification uses :func:`verify_message` (the exact
        ``"knitweb-relay:v1\n{to}\n{topic}\n{body}"`` pre-image over secp256k1/SHA-256), so a relay
        or DataChannel carrier can neither forge nor replay under another identity.
        """
        # Drop our own echoed push: it is already woven and counted locally; re-bumping it would
        # double-count our own confirmation (matches RelaySync.pull's self-skip).
        if msg.get("from") == self.signer.pub:
            return {"status": "own"}
        if not verify_message(msg, topic=self.topic):
            return {"status": "rejected"}
        item = item_from_body(str(msg.get("body", "")))
        if item is None:
            return {"status": "skipped"}
        return self.apply_remote_item(item)

    def apply_remote_item(self, item: WovenItem) -> dict:
        """Fold one verified :class:`WovenItem` into the World by the union-of-co-woven rule.

        This is the heart of the server-free convergence: dedup by :func:`item_keys` (the SAME
        keys the World + ``molgang.merge`` fold on). A fiber already present is RE-APPLIED so its
        confirmations/tension bump (integer SUM — co-woven fibers get tauter); a genuinely new
        fiber is woven in full. Term-node set is stable across a bump, so ``web_state_root`` only
        changes when the node/edge SET changes — letting two peers converge to the same root
        regardless of arrival order.
        """
        keys = item_keys(item)
        if keys and all(k in self._seen for k in keys):
            return {"status": "bumped"} if self._bump(item) else {"status": "skipped"}
        self._weave(item)
        self._seen.update(keys)
        return {"status": "applied"}

    # -- weave / bump (the World's own entry points + the SUM tension rule) -

    def _weave(self, item: WovenItem) -> None:
        """Weave a NEW item via the World's own ``weave_*`` entry points (canonical CIDs/edges)."""
        if item.kind == "link":
            self.world.weave_links(
                [{"subject": item.subject, "object": item.object,
                  "relation": item.relation or "links"}],
                item.by, item.fiber_cid, item.confirmations)
        elif item.kind == "spiral":
            self.world.weave_spiral(
                item.links, item.by, item.fiber_cid, item.confirmations,
                validators=item.validators, pls_staked=item.pls_staked)
        else:
            self.world.weave_knit(
                {"kind": "term", "term": item.term}, item.by, item.fiber_cid, item.confirmations)

    def _bump(self, item: WovenItem) -> bool:
        """Re-apply an already-present item's edge(s) at heavier weight (SUM the tension).

        Mirrors :meth:`molgang.relay_sync.RelaySync._bump` exactly, but without the file ``_save``
        (the tab has no path; durability is the caller's ``export_world`` -> IndexedDB). The
        term-node SET is unchanged, so ``state_root`` is stable; each edge is re-tensioned at
        ``+confirmations`` so a fiber several peers wove ends up tauter. Returns ``True`` iff any
        edge was (re-)tensioned. Term-only items carry no edge -> a no-op bump (``False``).
        """
        links: list[tuple[str, str, str]] = []
        if item.kind == "link":
            links = [(item.subject, item.object, item.relation or "links")]
        elif item.kind == "spiral":
            links = [(pl["subject"], pl["object"], pl.get("relation", "links")) for pl in item.links]
        if not links:
            return False
        by = max(1, int(item.confirmations))  # integer-only weight (invariant a)
        for subj, obj, rel in links:
            src = self.world._term_node(subj)
            dst = self.world._term_node(obj)
            self._tension(src, dst, rel, by=by)
        # make the bump DURABLE: raise the matching stored item's confirmations so a fresh
        # World load (from the IndexedDB snapshot) re-applies the fiber at the summed weight.
        self._bump_stored(item, by)
        return True

    def _bump_stored(self, item: WovenItem, by: int) -> None:
        """Add integer ``by`` to the confirmations of the stored item that wove the same edge(s)."""
        want = set(item_keys(item))
        for it in self.world.items:
            if it.kind in ("link", "spiral") and set(item_keys(it)) & want:
                it.confirmations += by
                return

    def _tension(self, src: str, dst: str, rel: str, *, by: int) -> None:
        """Raise edge (src,dst,rel) weight by integer ``by`` IN PLACE (rebuild the Edge).

        ``Web.link`` is idempotent on ``(src,dst,rel,weight)``, so re-linking at a higher weight
        would leave a PARALLEL edge rather than a tauter one. We rebuild the existing
        :class:`knitweb.fabric.web.Edge` to the summed weight in both adjacency maps (or weave a
        fresh edge if absent) — identical to ``RelaySync._tension`` so the resulting web (and thus
        ``web_state_root``) is byte-for-byte what relay-sync would have produced server-side.
        """
        from knitweb.fabric.web import Edge

        out = self.world.web._out.setdefault(src, [])
        inc = self.world.web._in.setdefault(dst, [])
        for i, e in enumerate(out):
            if e.dst == dst and e.rel == rel:
                new = Edge(src=src, dst=dst, rel=rel, weight=e.weight + by)
                out[i] = new
                self.world.web._in[dst] = [new if x is e else x for x in inc]
                return
        self.world.web.link(src, dst, rel=rel, weight=by)  # not present yet -> weave it

    # -- batch fold (drain the IndexedDB inbox in one tick) -----------------

    def apply_remote_batch(self, messages: list[dict]) -> dict:
        """Fold a batch of verified inbound messages (the JS ``store_idb.takeInbound`` drain).

        Returns the same tally shape ``RelaySync.pull`` reports, so existing UI/telemetry reads
        unchanged: ``{applied, bumped, rejected, skipped, own, scanned}``.
        """
        applied = bumped = rejected = skipped = own = 0
        for msg in messages:
            out = self.apply_remote_message(msg)
            status = out.get("status")
            if status == "applied":
                applied += 1
            elif status == "bumped":
                bumped += 1
            elif status == "rejected":
                rejected += 1
            elif status == "own":
                own += 1
            else:
                skipped += 1
        return {"applied": applied, "bumped": bumped, "rejected": rejected,
                "skipped": skipped, "own": own, "scanned": len(messages)}

    # -- convergence views (the SAME canonical encoders every peer runs) ----

    def state_root(self) -> str:
        """The canonical ``web_state_root`` (64 hex chars) — identical on every converged peer.

        Delegates to ``World.state_root`` -> ``knitweb.fabric.items.web_state_root``: it commits
        to the sorted node CIDs AND the edges in total ``(src,rel,dst,weight)`` order, so two
        peers with the same node/edge set produce the same root regardless of insertion order.
        """
        return self.world.state_root()

    def ual(self) -> dict:
        """Anchor the converged web to OriginTrail and return its UAL/state_root receipt.

        Delegates to ``World.anchor`` (fixed dev notary -> reproducible UAL per web state). Two
        peers at the same ``web_state_root`` therefore anchor to the same UAL with no server.
        """
        return self.world.anchor()

    def size(self) -> tuple[int, int]:
        """``(node_count, edge_count)`` of the woven web (deterministic across peers)."""
        return self.world.size()

    # -- persistence handoff (the IndexedDB snapshot the JS shell stores) ---

    def export_world(self) -> dict:
        """The World document (``{items, open_spirals}``) for ``store_idb.putWorld``.

        Plain JSON-able dicts (``asdict`` of each :class:`WovenItem`) so the JS shell can persist
        it in IndexedDB verbatim. On a fresh tab the worker re-loads this via ``import_world`` and
        the deterministic fold reproduces the SAME web (and ``state_root``) — no re-faucet, no
        server.
        """
        return {
            "items": [asdict(i) for i in self.world.items],
            "open_spirals": list(self.world.open_spirals.values()),
        }

    def export_world_json(self) -> str:
        """The World document as a canonical (sorted-key, compact) JSON string for IndexedDB."""
        return json.dumps(self.export_world(), separators=(",", ":"),
                          sort_keys=True, ensure_ascii=False)

    def import_world(self, doc: dict) -> None:
        """Re-load a World document (from the IndexedDB snapshot) and rebuild the dedup index.

        Applies every stored item through the World's own ``_apply`` so the web — and thus
        ``web_state_root`` — is reconstructed byte-identically, then re-indexes the seen keys so
        subsequent peer folds dedup correctly.
        """
        self.world.web, self.world.items, self.world._term_cid = type(self.world.web)(), [], {}
        raw_spirals = doc.get("open_spirals", {})
        if isinstance(raw_spirals, list):
            self.world.open_spirals = {str(s.get("cid")): s for s in raw_spirals if s.get("cid")}
        elif isinstance(raw_spirals, dict):
            self.world.open_spirals = dict(raw_spirals)
        else:
            self.world.open_spirals = {}
        for d in doc.get("items", []):
            fields = {f for f in WovenItem.__dataclass_fields__}
            self.world._apply(WovenItem(**{k: v for k, v in d.items() if k in fields}))
        self._reindex()
