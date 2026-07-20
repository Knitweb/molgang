"""Relay-sync for the shared :class:`~molgang.world.World` — converge two installs across
machines over the live **5mart.ml HTTP relay** (knitweb/molgang#44).

Raw inbound p2p is firewalled on shared hosting (molgang PR #77 / ``php/PORTCHECK.md``), so the
internet-traversing transport is the always-on **HTTP relay**: a node POSTs a *signed* message,
the relay stores it in MySQL, and any subscriber GETs it later. (The knitweb ``FabricNode`` stays
the LAN / reachable-peer transport; this relay is purely the WAN hop.) Every woven knit/spiral
this install confirms is **pushed** to the relay; a **pull** drains new messages, verifies each
signature end-to-end, and weaves the items into the local World — so a fresh install pointed at
the same ``--relay`` URL converges on the same web (same node-set ⇒ same ``state_root`` / UAL).

Protocol (mirrors the live relay, ``php/src/Relay.php`` + ``php/src/Onboard.php`` on PR #77):

* **identity / signing** = ``knitweb.core.crypto`` — secp256k1 ECDSA over SHA-256, 33-byte
  compressed pubkey hex, DER signature hex. A stable node (``AccountNode.from_seed`` / the pulse
  host wallet) signs, and the relay re-verifies; readers re-verify independently.
* **onboard** (registered-only relay): ``GET  …/onboard/challenge`` → sign the exact challenge
  string → ``POST …/onboard/register {pubkey, sig, device_fp, challenge}``.
* **send**: ``POST …/relay/send {from, to?, topic, body, sig}`` where the signed pre-image is
  exactly ``"knitweb-relay:v1\n{to}\n{topic}\n{body}"`` (``to=""`` for a broadcast).
* **fetch**: ``GET  …/relay/fetch?topic=&since=<cursor>&limit=`` →
  ``{messages:[{id,from,to,topic,body,sig,created}], cursor, count}``.

The body of a knitweb.web message is the woven item as JSON (``WovenItem`` fields). On pull we
**dedup by the same casefold/edge keys the World already uses** (so a re-applied item never
double-counts) while still **bumping confirmations/tension** for a fiber several installs each
wove — exactly how :mod:`molgang.merge` unions co-woven fibers.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict

from knitweb.core import crypto
from knitweb.ledger.node import AccountNode

from .engine_compat import EngineCompatibilityError, assert_peer_engine_compatible, engine_metadata
from .world import WovenItem, World

# The canonical relay topic molgang's shared web rides on.
WEB_TOPIC = "knitweb.web"
# Pre-image tag — must byte-match the live relay's Relay::signedPreimage (PR #77).
_PREIMAGE_TAG = "knitweb-relay:v1"
_HTTP_TIMEOUT = 20
# A relayed item's `confirmations` (edge weight/tension) and `validators` are SELF-REPORTED by the
# untrusted sender — anyone with a keypair can sign a message claiming confirmations=9999 and have
# the local World weave/bump that edge at a dominating weight. Clamp both on ingest so a forged
# weight can't take over the shared web; an honest fiber is at most this many co-weaves anyway.
RELAY_MAX_CONFIRMATIONS = 64


def _tls_context() -> ssl.SSLContext:
    """A verifying TLS context, preferring certifi's CA bundle when installed.

    Verification stays ON (this never disables cert checks); certifi just supplies a complete CA
    bundle on machines whose default OpenSSL store can't reach the issuer.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        # certifi is optional; fall back to the platform trust store.
        return ssl.create_default_context()


# -- the signed-message envelope ---------------------------------------------
def signed_preimage(to: str, topic: str, body: str) -> bytes:
    """The exact bytes a sender signs for a relay message (recompute identically on read).

    Mirrors ``Relay::signedPreimage($to, $topic, $body)`` on the live node: ``from`` is *not*
    in the pre-image (it is the verifying key itself), ``to`` is a pls1 address or ``""`` for a
    broadcast. Signing/verifying the same three fields is what makes a stored message
    unforgeable and un-replayable under another node's identity.
    """
    return f"{_PREIMAGE_TAG}\n{to}\n{topic}\n{body}".encode("utf-8")


def pack(item: WovenItem, signer: AccountNode, *, topic: str = WEB_TOPIC, to: str = "") -> dict:
    """Pack a woven item into a signed relay message ``{from, to, topic, body, sig}``.

    ``body`` is the item's JSON (canonical: sorted keys, compact) so the bytes a reader weaves
    are exactly the bytes the signer signed.
    """
    record = asdict(item)
    record["_engine"] = engine_metadata(engine="relay")
    body = json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    sig = crypto.sign(signer.priv, signed_preimage(to, topic, body))
    return {"from": signer.pub, "to": to, "topic": topic, "body": body, "sig": sig}


def verify_message(msg: dict, *, topic: str | None = None) -> bool:
    """Re-verify a fetched message end-to-end: signature over ``signed_preimage(to,topic,body)``.

    ``to`` is normalised to ``""`` when the relay stored it as ``null``. An optional ``topic``
    pins the expected channel (defence-in-depth so a message can't be replayed onto another
    topic). Returns ``False`` on any malformed field rather than raising.
    """
    try:
        frm = str(msg["from"])
        mtopic = str(msg.get("topic", ""))
        body = str(msg["body"])
        sig = str(msg["sig"])
        to = msg.get("to") or ""
    except (KeyError, TypeError):
        return False
    if topic is not None and mtopic != topic:
        return False
    return crypto.verify(frm, signed_preimage(str(to), mtopic, body), sig)


def clamp_relayed_weights(item: WovenItem) -> WovenItem:
    """Bound a relayed item's self-reported weight so a forged value can't dominate the web.

    ``confirmations``/``validators`` come from the untrusted sender; clamp ``validators`` to the
    ceiling and ``confirmations`` to ``min(ceiling, validators-if-claimed)``, floored at 1.
    Also validates the ``lang`` field — falls back to ``"en"`` if unknown. Mutates and returns.
    """
    from .world import VALID_LANGS
    v = item.validators if isinstance(item.validators, int) and item.validators > 0 else 0
    v = min(v, RELAY_MAX_CONFIRMATIONS)
    item.validators = v
    c = item.confirmations if isinstance(item.confirmations, int) else 1
    cap = min(RELAY_MAX_CONFIRMATIONS, v) if v > 0 else RELAY_MAX_CONFIRMATIONS
    item.confirmations = max(1, min(c, cap))
    if not isinstance(item.lang, str) or item.lang not in VALID_LANGS:
        item.lang = "en"
    return item


def item_from_body(body: str) -> WovenItem | None:
    """Parse a relay message body back into a :class:`WovenItem` (None if it isn't one)."""
    try:
        d = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict) or "kind" not in d:
        return None
    fields = {f for f in WovenItem.__dataclass_fields__}
    try:
        return WovenItem(**{k: v for k, v in d.items() if k in fields})
    except TypeError:
        return None


def peer_engine_from_body(body: str) -> dict | None:
    """Return advertised engine metadata from a relay body, if present."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("_engine")
    return meta if isinstance(meta, dict) else None


# -- dedup keys (the SAME casefold/edge keys World + merge already use) -------
def _term_key(term: str) -> str:
    from .knit_parse import clean

    return (clean(term) or term).casefold()


def item_keys(it: WovenItem) -> list[tuple]:
    """The dedup key(s) an item contributes — one per fiber it weaves.

    * term : ``("term", casefold(term))``
    * link : ``("edge", subj-key, relation, obj-key)``
    * spiral: one ``("edge", …)`` per link in the chain.

    Identical to the keys :meth:`World.weave_links` and :mod:`molgang.merge` fold on, so a fiber
    woven on two installs maps to ONE key (re-applies bump confirmations instead of duplicating).
    """
    if it.kind == "link":
        return [("edge", _term_key(it.subject), it.relation or "links", _term_key(it.object))]
    if it.kind == "spiral":
        return [("edge", _term_key(pl["subject"]), pl.get("relation", "links"),
                 _term_key(pl["object"])) for pl in it.links]
    return [("term", _term_key(it.term))]


# -- the client --------------------------------------------------------------
class RelaySync:
    """A relay client bound to one local :class:`World` and a stable signing node.

    ``base`` is the relay API base, e.g. ``https://5mart.ml/molgang/api/relay``. The same
    ``signer`` (a deterministic ``AccountNode``) signs every push so the relay accepts it and
    peers can attribute it. ``cursor`` is the high-water mark of messages already pulled.
    """

    def __init__(self, base: str, world: World, signer: AccountNode, *,
                 topic: str = WEB_TOPIC, opener=None, shards: int = 1, subscribe=None,
                 seen_keys: set | None = None, seen_sigs: set | None = None) -> None:
        self.base = base.rstrip("/")
        self.world = world
        self.signer = signer
        self.topic = topic
        self.cursor = 0.0
        # Concept sharding (#97): shards==1 keeps the single un-suffixed topic (back-compat).
        # shards>1 routes each item to <topic>.sNN by its concept key; a node reads only the
        # shards it subscribes to (default: all). Per-shard high-water cursors live in _cursors.
        self.shards = max(1, int(shards))
        if subscribe is None:
            self.subscribe = list(range(self.shards))
        else:
            self.subscribe = sorted({int(i) for i in subscribe if 0 <= int(i) < self.shards})
        self._cursors: dict[str, float] = {}
        # the de-dup index of every fiber key already present in the local World. A RelayPool
        # (#95) passes ONE shared set to all its per-base clients so an item applied via relay A
        # is bump-not-reweave for relay B; standalone use keeps a private set (unchanged).
        self._seen: set[tuple] = seen_keys if seen_keys is not None else set()
        # signature-level dedup (#95): the SAME signed message replicated onto several relays has
        # an identical `sig`, and must be woven/bumped exactly once across the whole pool.
        self._seen_sigs: set[str] = seen_sigs if seen_sigs is not None else set()
        self._reindex()
        # injectable transport (the test stub swaps this; default = urllib over HTTPS)
        self._open = opener or self._urlopen

    # -- shard routing (#97) ----------------------------------------------
    def _topic_for_item(self, item: WovenItem) -> str:
        """The relay topic an item is published to: the base topic when unsharded, else
        ``<topic>.sNN`` for the item's home shard."""
        if self.shards == 1:
            return self.topic
        from .shard import item_shard, shard_topic
        return shard_topic(self.topic, item_shard(item, self.shards))

    def _read_topics(self) -> list[str]:
        """The topics this node pulls from (the base topic when unsharded, else the
        subscribed per-shard topics)."""
        if self.shards == 1:
            return [self.topic]
        from .shard import shard_topic
        return [shard_topic(self.topic, i) for i in self.subscribe]

    # -- transport ---------------------------------------------------------
    def _urlopen(self, url: str, data: bytes | None = None) -> dict:
        req = urllib.request.Request(
            url, data=data, method="POST" if data is not None else "GET",
            headers={"Content-Type": "application/json"} if data is not None else {})
        ctx = _tls_context() if url.lower().startswith("https") else None
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as r:
            return json.loads(r.read() or b"{}")

    # -- local de-dup index ------------------------------------------------
    def _reindex(self) -> None:
        self.world._sync()
        # mutate IN PLACE (never reassign): a RelayPool shares this set across its clients
        self._seen.clear()
        for it in self.world.items:
            self._seen.update(item_keys(it))

    # -- PUSH --------------------------------------------------------------
    def push(self, item: WovenItem, *, to: str = "") -> dict:
        """Pack ``item`` into a signed message and POST it to ``…/relay/send``.

        Returns the relay's ``{ok, id|error}``. Its keys are recorded locally so a later pull of
        our own echoed message is a no-op (we already wove it).
        """
        msg = pack(item, self.signer, topic=self._topic_for_item(item), to=to)
        out = self._open(f"{self.base}/send", json.dumps(msg).encode("utf-8"))
        self._seen.update(item_keys(item))
        self._seen_sigs.add(str(msg["sig"]))
        return out

    def push_world_item(self, item: WovenItem, **kw) -> dict:
        """Alias matching the task's ``push(world_item, signer)`` wording (signer is bound)."""
        return self.push(item, **kw)

    # -- PULL --------------------------------------------------------------
    def pull(self, since: float | None = None, *, limit: int = 200) -> dict:
        """GET new messages, verify each signature, and weave the items into the local World.

        Dedup is by :func:`item_keys`: a fiber already in the World is **re-applied** (so its
        confirmations/tension bump — co-woven fibers get tauter, matching :mod:`molgang.merge`)
        but never appended a second time as a fresh node-set; a genuinely new fiber is woven in
        full. The cursor advances to the relay's high-water mark so the next pull is incremental.

        Returns ``{applied, bumped, rejected, skipped, scanned, cursor}``.
        """
        if self.shards == 1:
            # Single un-suffixed topic — identical behaviour + cursor to the pre-shard path.
            stats, cur = self._pull_topic(self.topic, self.cursor if since is None else since,
                                          limit=limit)
            self.cursor = cur
            stats["cursor"] = cur
            return stats
        # Sharded: drain each subscribed shard topic with its own high-water cursor, merge stats.
        total = {"applied": 0, "bumped": 0, "rejected": 0, "skipped": 0, "scanned": 0}
        for topic in self._read_topics():
            start = self._cursors.get(topic, 0.0) if since is None else since
            stats, cur = self._pull_topic(topic, start, limit=limit)
            self._cursors[topic] = cur
            for k in total:
                total[k] += stats[k]
        total["cursor"] = max(self._cursors.values()) if self._cursors else 0.0
        # keep self.cursor meaningful (max across shards) for callers that read it
        self.cursor = total["cursor"]
        return total

    def _pull_topic(self, topic: str, since: float, *, limit: int = 200) -> tuple[dict, float]:
        """Drain one relay topic from ``since``: verify each signature (pinned to ``topic``),
        weave/bump new items, and return ``(stats, new_cursor)``. Shared by the unsharded and
        per-shard pull paths so both weave through identical verification + dedup."""
        q = urllib.parse.urlencode({"topic": topic, "since": since, "limit": limit})
        resp = self._open(f"{self.base}/fetch?{q}", None)
        msgs = resp.get("messages", []) if isinstance(resp, dict) else []
        applied = bumped = rejected = skipped = 0
        for msg in msgs:
            if msg.get("from") == self.signer.pub:
                # our own echoed push — already woven + counted locally; never re-bump it
                skipped += 1
                continue
            sig = str(msg.get("sig", ""))
            if sig and sig in self._seen_sigs:
                # the SAME signed message already processed via another relay in the pool (#95)
                skipped += 1
                continue
            if not verify_message(msg, topic=topic):
                rejected += 1
                continue
            if sig:
                self._seen_sigs.add(sig)
            try:
                assert_peer_engine_compatible(peer_engine_from_body(str(msg.get("body", ""))))
            except EngineCompatibilityError:
                rejected += 1
                continue
            item = item_from_body(str(msg.get("body", "")))
            if item is None:
                skipped += 1
                continue
            clamp_relayed_weights(item)  # don't trust the sender's self-reported edge weight
            keys = item_keys(item)
            if keys and all(k in self._seen for k in keys):
                # already woven here — bump confirmations/tension for the co-woven fiber(s)
                if self._bump(item):
                    bumped += 1
                else:
                    skipped += 1
                continue
            self._weave(item)
            self._seen.update(keys)
            applied += 1
        cur = float(resp.get("cursor", since)) if isinstance(resp, dict) else since
        return ({"applied": applied, "bumped": bumped, "rejected": rejected,
                 "skipped": skipped, "scanned": len(msgs)}, cur)

    # -- weave / bump ------------------------------------------------------
    def _weave(self, item: WovenItem) -> None:
        """Weave a NEW item into the local World via the World's own weave_* entry points."""
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
        """Re-apply an already-present item's edge(s) with a heavier weight (more confirmations).

        The term-node set is unchanged (so ``state_root`` is stable), but each edge is re-linked
        at ``+confirmations`` weight, so a fiber several installs wove ends up TAUTER — the same
        "sum the tension on a co-woven fiber" rule :mod:`molgang.merge` applies. Returns True if
        any edge was (re-)tensioned. Term-only items carry no edge, so they are a no-op bump.
        """
        self.world._sync()
        links: list[tuple[str, str, str]] = []
        if item.kind == "link":
            links = [(item.subject, item.object, item.relation or "links")]
        elif item.kind == "spiral":
            links = [(pl["subject"], pl["object"], pl.get("relation", "links")) for pl in item.links]
        if not links:
            return False
        by = max(1, item.confirmations)
        for subj, obj, rel in links:
            s = self.world._term_node(subj)
            o = self.world._term_node(obj)
            self._tension(s, o, rel, by=by)
        # make the bump DURABLE: raise the matching stored item's confirmations, so a fresh
        # World load re-applies the fiber at the heavier (summed) weight via _apply().
        self._bump_stored(item, by)
        if self.world.path:
            self.world._save()
        return True

    def _bump_stored(self, item: WovenItem, by: int) -> None:
        """Add ``by`` to the confirmations of the stored item that wove the same edge(s)."""
        want = set(item_keys(item))
        for it in self.world.items:
            if it.kind in ("link", "spiral") and set(item_keys(it)) & want:
                it.confirmations += by
                return

    def _tension(self, src: str, dst: str, rel: str, *, by: int) -> None:
        """Re-tension edge (src,dst,rel): raise its weight by ``by`` IN PLACE.

        ``Web.link`` is idempotent on ``(src,dst,rel,weight)`` — linking again at a higher weight
        would leave a *parallel* edge rather than a tauter one — so we rebuild the existing
        ``Edge`` to the new weight in both adjacency maps (or weave a fresh edge if absent).
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
        self.world.web.link(src, dst, rel=rel, weight=by)   # not present yet → weave it

    def _edge_weight(self, src: str, dst: str, rel: str) -> int:
        """Current woven weight of edge (src,dst,rel) in the local web (0 if absent)."""
        for e in self.world.web._out.get(src, []):
            if e.dst == dst and e.rel == rel:
                return e.weight
        return 0

    # -- snapshot / restore ---------------------------------------------------

    def _world_hash(self) -> str:
        """Deterministic SHA-256 of the serialised world items (integer cursor ignored)."""
        items_json = json.dumps(
            [asdict(it) for it in self.world.items],
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(items_json).hexdigest()

    def snapshot(self, path: str) -> None:
        """Write ``{cursor: int, world_hash: str, items: list}`` as JSON to ``path``.

        ``cursor`` is stored as an integer (floor) so snapshot files stay float-free
        on the identity path.  The ``world_hash`` is a SHA-256 over the serialised
        world items; :meth:`verify_snapshot` uses it to detect tampering.
        """
        data = {
            "cursor": int(self.cursor),
            "world_hash": self._world_hash(),
            "items": [asdict(it) for it in self.world.items],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, indent=2)
        os.replace(tmp, path)

    def restore(self, path: str) -> None:
        """Load a snapshot, verify ``world_hash``, and reset cursor + world items.

        Raises :class:`ValueError` if the hash does not match (tampered or corrupt).
        Cursor is restored as ``int`` (no float on the deterministic path).
        """
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        stored_hash = data.get("world_hash", "")
        raw_items = data.get("items", [])
        items_json = json.dumps(raw_items, sort_keys=True, separators=(",", ":")).encode("utf-8")
        computed = hashlib.sha256(items_json).hexdigest()
        if computed != stored_hash:
            raise ValueError(
                f"snapshot world_hash mismatch: stored={stored_hash!r}, computed={computed!r}"
            )

        loaded: list[WovenItem] = []
        for rec in raw_items:
            try:
                loaded.append(WovenItem(**rec))
            except TypeError:
                pass
        self.world.items[:] = loaded
        self.cursor = int(data.get("cursor", 0))
        self._reindex()

    def verify_snapshot(self, path: str) -> bool:
        """Return True iff the snapshot file's world_hash matches its items payload."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return False
        stored = data.get("world_hash", "")
        raw_items = data.get("items", [])
        items_json = json.dumps(raw_items, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(items_json).hexdigest() == stored


# -- the multi-relay pool (#95) ----------------------------------------------
class RelayPool:
    """Fan a shared :class:`World` across a POOL of relays — push to all, pull-union, failover.

    One relay is one bottleneck and one point of failure for every peer (knitweb/molgang#95);
    the pool holds one :class:`RelaySync` per base, all bound to the SAME ``World`` + signer and
    sharing ONE dedup index (``seen_keys``/``seen_sigs``), so:

    * :meth:`push` fans a confirmed knit out to every *healthy* base, best-effort — a down relay
      is recorded and skipped, never raised into the weaving caller (``world.on_weave``);
    * :meth:`pull` drains every healthy base and unions the messages — a fiber arriving on two
      relays is applied once (identical ``sig`` ⇒ signature-level skip; a co-woven fiber from a
      different signer still bumps once per distinct message), each base advancing its own cursor;
    * a base whose transport errors enters a ``cooldown``-second timeout before it is retried,
      so one dark relay cannot stall convergence through the others. When EVERY base is down the
      pool retries them all anyway (a total outage should keep probing, not go silent forever).
    """

    def __init__(self, bases, world: World, signer: AccountNode, *,
                 topic: str = WEB_TOPIC, opener=None, shards: int = 1, subscribe=None,
                 cooldown: float = 60.0, clock=time.monotonic) -> None:
        cleaned, seen_bases = [], set()
        for b in bases if isinstance(bases, (list, tuple)) else [bases]:
            b = str(b).strip().rstrip("/")
            if b and b not in seen_bases:
                seen_bases.add(b)
                cleaned.append(b)
        if not cleaned:
            raise ValueError("RelayPool needs at least one relay base URL")
        self.bases = cleaned
        self.world = world
        self.signer = signer
        self.topic = topic
        self.cooldown = float(cooldown)
        self._clock = clock
        # ONE shared dedup index across every per-base client (see RelaySync.__init__)
        shared_keys: set[tuple] = set()
        shared_sigs: set[str] = set()
        self.syncs: list[RelaySync] = [
            RelaySync(b, world, signer, topic=topic, opener=opener,
                      shards=shards, subscribe=subscribe,
                      seen_keys=shared_keys, seen_sigs=shared_sigs)
            for b in self.bases
        ]
        self._health: dict[str, dict] = {b: {"failures": 0, "down_until": 0.0}
                                         for b in self.bases}

    # -- back-compat surface (webserver reads these off a single RelaySync) ----
    @property
    def base(self) -> str:
        """Primary base (first configured) — kept so single-relay callers keep working."""
        return self.bases[0]

    @property
    def cursor(self) -> float:
        """Pool high-water mark = the furthest cursor any base reached."""
        return max((s.cursor for s in self.syncs), default=0.0)

    # -- health ------------------------------------------------------------
    def healthy(self, base: str) -> bool:
        return self._clock() >= self._health[base]["down_until"]

    def _mark_ok(self, base: str) -> None:
        self._health[base]["failures"] = 0
        self._health[base]["down_until"] = 0.0

    def _mark_fail(self, base: str) -> None:
        h = self._health[base]
        h["failures"] += 1
        h["down_until"] = self._clock() + self.cooldown

    def _active(self) -> list[RelaySync]:
        """The healthy clients — or ALL of them when every base is in cooldown."""
        up = [s for s in self.syncs if self.healthy(s.base)]
        return up or list(self.syncs)

    # -- PUSH: fan out to every healthy base -------------------------------
    def push(self, item: WovenItem, *, to: str = "") -> dict:
        """Best-effort fan-out of one confirmed item; per-base result, never raises transport.

        Returns ``{ok, results: {base: relay-response | {ok:false, error}}}`` where ``ok`` is
        True when at least one relay accepted — the caller (``world.on_weave``) must keep
        weaving locally even through a full relay outage.
        """
        results: dict[str, dict] = {}
        for s in self._active():
            try:
                results[s.base] = s.push(item, to=to)
                self._mark_ok(s.base)
            except Exception as e:  # a down relay is health-marked, not raised
                self._mark_fail(s.base)
                results[s.base] = {"ok": False, "error": str(e)}
        return {"ok": any(r.get("ok") for r in results.values()), "results": results}

    # -- PULL: drain every healthy base, union via the shared dedup ---------
    def pull(self, since: float | None = None, *, limit: int = 200) -> dict:
        """Union-pull across the pool; per-base cursors advance independently.

        Returns the summed per-base stats plus ``errors`` (bases that failed this round)
        and ``cursor`` (the pool high-water mark).
        """
        total = {"applied": 0, "bumped": 0, "rejected": 0, "skipped": 0,
                 "scanned": 0, "errors": 0}
        for s in self._active():
            try:
                stats = s.pull(since, limit=limit)
                self._mark_ok(s.base)
                for k in ("applied", "bumped", "rejected", "skipped", "scanned"):
                    total[k] += stats.get(k, 0)
            except Exception:
                self._mark_fail(s.base)
                total["errors"] += 1
        total["cursor"] = self.cursor
        return total

    # -- introspection (GET /api/relay) -------------------------------------
    def status(self) -> list[dict]:
        """Per-relay ``{base, cursor, healthy, failures}`` for the API/monitor surface."""
        return [{"base": s.base, "cursor": s.cursor, "healthy": self.healthy(s.base),
                 "failures": self._health[s.base]["failures"]} for s in self.syncs]


# -- identity helpers --------------------------------------------------------
def host_signer(seed: str = "molgang:relay:host") -> AccountNode:
    """A stable node identity to sign relay pushes (deterministic ``AccountNode.from_seed``)."""
    return AccountNode.from_seed(seed)


def signer_from_wallet(wallet_path: str | None) -> AccountNode:
    """Reuse the pulse-host wallet identity when present, else a stable seeded node.

    The pulse-host wallet (``~/.molgang/pulse-identity.json``) is the install's long-lived node;
    using its real private key keeps relay authorship tied to the same node identity advertised
    by ``molgang serve``. Older local fallback identity files did not store a private key, so
    those keep the historical path-seeded relay identity instead of failing startup.
    """
    if wallet_path and os.path.exists(wallet_path):
        try:
            from knitweb.store import load_node

            return load_node(wallet_path)
        except Exception as exc:
            # Distinguish legacy JSON wallets from broken node snapshots.
            try:
                with open(wallet_path, encoding="utf-8") as fh:
                    record = json.load(fh)
            except Exception as read_exc:
                raise RuntimeError(f"relay wallet is unreadable: {wallet_path}") from read_exc
            if isinstance(record, dict) and record.get("kind") == "node-snapshot":
                raise RuntimeError(f"relay wallet node snapshot is invalid: {wallet_path}") from exc
    seed = f"molgang:relay:host:{wallet_path or 'default'}"
    return AccountNode.from_seed(seed)
