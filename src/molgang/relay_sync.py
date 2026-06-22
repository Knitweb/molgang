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

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict

from knitweb.core import crypto
from knitweb.ledger.node import AccountNode

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
    except Exception:  # noqa: BLE001 — certifi optional; fall back to the system store
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
    body = json.dumps(asdict(item), separators=(",", ":"), sort_keys=True, ensure_ascii=False)
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
    ceiling and ``confirmations`` to ``min(ceiling, validators-if-claimed)``, floored at 1. Mutates
    and returns the item.
    """
    v = item.validators if isinstance(item.validators, int) and item.validators > 0 else 0
    v = min(v, RELAY_MAX_CONFIRMATIONS)
    item.validators = v
    c = item.confirmations if isinstance(item.confirmations, int) else 1
    cap = min(RELAY_MAX_CONFIRMATIONS, v) if v > 0 else RELAY_MAX_CONFIRMATIONS
    item.confirmations = max(1, min(c, cap))
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
                 topic: str = WEB_TOPIC, opener=None) -> None:
        self.base = base.rstrip("/")
        self.world = world
        self.signer = signer
        self.topic = topic
        self.cursor = 0.0
        # the de-dup index of every fiber key already present in the local World
        self._seen: set[tuple] = set()
        self._reindex()
        # injectable transport (the test stub swaps this; default = urllib over HTTPS)
        self._open = opener or self._urlopen

    # -- transport ---------------------------------------------------------
    def _urlopen(self, url: str, data: bytes | None = None) -> dict:
        req = urllib.request.Request(
            url, data=data, method="POST" if data is not None else "GET",
            headers={"Content-Type": "application/json"} if data is not None else {})
        ctx = _tls_context() if url.lower().startswith("https") else None
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as r:  # noqa: S310
            return json.loads(r.read() or b"{}")

    # -- local de-dup index ------------------------------------------------
    def _reindex(self) -> None:
        self.world._sync()
        self._seen = set()
        for it in self.world.items:
            self._seen.update(item_keys(it))

    # -- PUSH --------------------------------------------------------------
    def push(self, item: WovenItem, *, to: str = "") -> dict:
        """Pack ``item`` into a signed message and POST it to ``…/relay/send``.

        Returns the relay's ``{ok, id|error}``. Its keys are recorded locally so a later pull of
        our own echoed message is a no-op (we already wove it).
        """
        msg = pack(item, self.signer, topic=self.topic, to=to)
        out = self._open(f"{self.base}/send", json.dumps(msg).encode("utf-8"))
        self._seen.update(item_keys(item))
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
        since = self.cursor if since is None else since
        q = urllib.parse.urlencode({"topic": self.topic, "since": since, "limit": limit})
        resp = self._open(f"{self.base}/fetch?{q}", None)
        msgs = resp.get("messages", []) if isinstance(resp, dict) else []
        applied = bumped = rejected = skipped = 0
        for msg in msgs:
            if msg.get("from") == self.signer.pub:
                # our own echoed push — already woven + counted locally; never re-bump it
                skipped += 1
                continue
            if not verify_message(msg, topic=self.topic):
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
        self.cursor = float(resp.get("cursor", since)) if isinstance(resp, dict) else since
        return {"applied": applied, "bumped": bumped, "rejected": rejected,
                "skipped": skipped, "scanned": len(msgs), "cursor": self.cursor}

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
        except Exception as exc:  # noqa: BLE001 - distinguish legacy JSON from broken node files.
            try:
                with open(wallet_path, encoding="utf-8") as fh:
                    record = json.load(fh)
            except Exception as read_exc:  # noqa: BLE001 - unreadable wallet should stop startup.
                raise RuntimeError(f"relay wallet is unreadable: {wallet_path}") from read_exc
            if isinstance(record, dict) and record.get("kind") == "node-snapshot":
                raise RuntimeError(f"relay wallet node snapshot is invalid: {wallet_path}") from exc
    seed = f"molgang:relay:host:{wallet_path or 'default'}"
    return AccountNode.from_seed(seed)
