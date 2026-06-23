"""The in-browser MOLGANG peer — a full Knitweb node running in one tab.

This is the engine side of the server-free architecture (Variant A: "the real engine
in every tab"). It is composed ENTIRELY from the unchanged ``molgang`` + ``knitweb``
Python: the deterministic identity, the ledger ``AccountNode``, the game ``Bar`` loop,
the integer-only faucet, the real ``pouw.quorum`` BFT verdict, the canonical-CBOR wire
framing, and a single new browser carrier (:class:`WebRtcTransport`). There is NO
server, NO subprocess, NO HTTP polling. The Pyodide module-Worker imports this and
calls :class:`WebPeer` methods in response to ``postMessage`` RPCs framed by
:mod:`molgang.webnode.contract`.

Why this composition is correct-by-construction
-----------------------------------------------
Every load-bearing rule is the SAME ``.py`` byte in every peer, so sacred invariants
hold for free:

  * (a) INTEGER-ONLY — faucet (``game.faucet_micropulses`` / ``current_faucet_pulses``),
    quorum (``quorum.default_threshold(n) = (2*n)//3 + 1``), and merge/tension all run as
    the original integer Python. This module adds no ``float``/``/``/``round`` anywhere.
  * (b) NO wall-clock / NO randomness on decision paths — the Bar's session clock, the
    identity-proof freshness clock, the liveness token-bucket clock, and all nonce bytes
    are INJECTED here from the shell's browser seams: an integer monotonic clock, an
    integer seconds clock, and ``crypto.getRandomValues`` CSPRNG bytes (never
    ``Math.random``, never ``time.time()``). They never order or hash anything.
  * (c) BYTE-IDENTITY — frames are built/parsed by the shared
    ``knitweb.p2p.wire.write_frame_bytes`` / ``read_frame_bytes`` and signed by the
    shared ``knitweb.core.crypto``; this module never re-encodes a hashed/signed field.

The single new file the architecture needed is the :class:`WebRtcTransport` below: it
satisfies the 5-method ``Transport`` Protocol (``tag``, ``dial``, ``listen``, ``close``,
``local_address``) and slots into the HOLE-PUNCH SEAM in ``knitweb.p2p.transport`` with
ZERO edits to ``node.py`` / ``base_node.py``. The browser owns the ``RTCDataChannel``;
this transport only moves opaque length-prefixed canonical-CBOR frames across it.

VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. Never "loom".
"""

from __future__ import annotations

import asyncio
import base64
import itertools

# --- unchanged engine + substrate (the same bytes in every peer) -------------------
from knitweb.core import crypto
from knitweb.ledger.node import AccountNode
from knitweb.p2p import discovery
from knitweb.p2p.relay import ENVELOPE_PEER_KEY, RELAY_ENVELOPE_PREFIX
from knitweb.p2p.transport import PeerAddress
from knitweb.p2p.wire import (
    MAX_FRAME_BYTES,
    WireError,
    read_frame_bytes,
    write_frame_bytes,
)

from molgang import game
from molgang.bar import Bar
from molgang import relay_sync

from . import contract

__all__ = [
    "SEED_DOMAIN",
    "QR_PREIMAGE_TAG",
    "WebRtcTransport",
    "WebPeer",
    "derive_account",
    "qr_offer_preimage",
]

# ---------------------------------------------------------------------------
# Identity — deterministic, subprocess-free (retires pulse_host.py)
# ---------------------------------------------------------------------------
#
# ``pulse_host.py`` shelled out to the Pulse CLI (``subprocess.run``) to mint an
# identity. In the tab there is no subprocess and no filesystem: identity is the pure,
# deterministic ``AccountNode.from_seed(seed)`` — ``priv = sha256("knitweb:account:seed:"+seed)``
# — where ``seed`` is the device seed the shell loaded from IndexedDB (or re-derived from
# a scanned QR). Same seed -> same key, address, and Fiber CID on every device and reload.

#: Domain tag for the wallet-signed onboarding QR challenge pre-image. The QR is a
#: challenge -> sign -> verify-BEFORE-connect handshake (signature-gated authentication,
#: never an unauthenticated backdoor): the scanning peer runs ``crypto.verify`` over this
#: tagged pre-image before any DataChannel opens. Domain-separated from the relay tag so a
#: relay signature can never be replayed as a QR admission and vice-versa.
QR_PREIMAGE_TAG = "molgang-webnode-qr:v1"

#: Re-exported for clarity; the account seed itself is domain-separated inside
#: ``AccountNode.from_seed`` (``"knitweb:account:seed:"`` prefix).
SEED_DOMAIN = "knitweb:account:seed:"


def derive_account(seed: str) -> AccountNode:
    """The tab's long-lived identity — deterministic, no subprocess, no key storage.

    The seed IS the private key (see ``AccountNode.from_seed``'s security note), so it is
    held only inside this Worker and never handed to the JS shell. The shell receives the
    public key + address only.
    """
    return AccountNode.from_seed(seed)


def qr_offer_preimage(pubkey_hex: str, multiaddr: str, nonce_hex: str, exp: int) -> bytes:
    """The exact bytes the onboarding QR signs (recompute identically on the scanner).

    Pre-image = ``"molgang-webnode-qr:v1\\n{pubkey}\\n{multiaddr}\\n{nonce}\\n{exp}"``.
    ``nonce`` is a single-use CSPRNG value (from ``crypto.getRandomValues``, never
    ``Math.random``) and ``exp`` is an INJECTED integer-seconds expiry (the identity-proof
    freshness clock, never ``time.time()``), so a captured QR cannot be replayed past its
    window. Signing this with the device key proves possession of the private key; the
    scanner verifies it before admission. There is no admission path without a valid sig.
    """
    return (
        f"{QR_PREIMAGE_TAG}\n{pubkey_hex}\n{multiaddr}\n{nonce_hex}\n{exp}"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# WebRtcTransport — the ONE new carrier file (satisfies the Transport Protocol)
# ---------------------------------------------------------------------------

#: Reputation-key prefix for a WebRTC sender (a verified peer pubkey), distinct from
#: ``tcp:`` / ``relay:`` so the address spaces never collide in the reputation ledger.
WEBRTC_PEER_PREFIX = "webrtc:"


def webrtc_peer_id(pubkey_hex: str) -> str:
    """Stable reputation key for a WebRTC peer: its verified (signed-QR/handshake) pubkey.

    Unlike a raw TCP socket (keyed on a re-mintable ``tcp:<ip>``) a WebRTC peer is
    admitted only after wallet-signed verification, so keying on the proven pubkey makes
    misbehavior stick to the real identity with zero NAT collateral.
    """
    return f"{WEBRTC_PEER_PREFIX}{pubkey_hex}"


class WebRtcTransport:
    """Browser ``RTCDataChannel`` carrier for the Knitweb p2p stack.

    Satisfies the 5-method ``knitweb.p2p.transport.Transport`` Protocol so it registers
    via ``BaseNode.add_transport`` and the ``Dialer`` routes ``transport="webrtc"`` peers
    to it with NO edits to ``node.py`` / ``base_node.py`` (the documented HOLE-PUNCH SEAM).

    The JS shell owns the actual ``RTCPeerConnection`` / ``RTCDataChannel`` objects (a
    browser API). This transport is the Python half: it hands the shell opaque frame
    BYTES to ``channel.send`` and is fed inbound frame bytes from ``channel.onmessage``.
    It NEVER interprets a frame — framing is the shared ``wire`` module, so signed-record
    bytes stay byte-identical across the carrier.

    Request/response over a message-oriented channel is correlated EXACTLY like
    ``relay.py``: each request carries a fresh INTEGER ``_relay_rid`` plus a ``reply_to``
    routing tag; the responder echoes the same ``rid``. These ``_relay_*`` keys are
    transport-envelope only and are stripped by the same reservation before any
    signed/business logic, so they never enter canonical/hashed bytes. ``rid`` is an
    integer counter, never a wall-clock value.
    """

    tag = "webrtc"

    # Transport-envelope correlation keys (reuse the reserved ``_relay_*`` namespace so
    # the existing ``_strip_envelope`` drops them before any signed/business logic).
    _RID_KEY = RELAY_ENVELOPE_PREFIX + "rid"
    _REPLY_TO_KEY = RELAY_ENVELOPE_PREFIX + "reply_to"

    def __init__(self, *, self_pubkey: str, send_cb, local_label: str = "tab") -> None:
        """``send_cb(peer_label: str, frame_bytes: bytes)`` is the shell hook that pushes a
        frame over the matching ``RTCDataChannel``. ``self_pubkey`` is this tab's verified
        identity (stamped on inbound requests as the WebRTC reputation key).
        """
        self._self_pubkey = self_pubkey
        self._send = send_cb
        self._label = local_label
        self._handler = None            # set by listen(): the node's _dispatch seam
        self._on_frame_fault = None
        self._waiters: dict[int, asyncio.Future] = {}
        self._rid = itertools.count(1)  # integer correlation counter (never wall-clock)
        self._closed = False

    # -- Transport Protocol: dial / listen / close / local_address ----------
    async def dial(self, peer: PeerAddress, request: dict) -> dict:
        """Send one request frame to ``peer`` and await its correlated reply.

        Mirrors ``RelayTransport.dial``: stamp an integer ``rid`` + our reply label, frame
        the map with the shared ``write_frame_bytes`` (byte-identical to TCP for the nested
        signed records), hand the bytes to the shell to put on the DataChannel, and resolve
        when ``ingest_frame`` delivers the matching ``rid`` reply.
        """
        if self._closed:
            raise WireError("transport closed")
        target = peer.params.get("label") or peer.params.get("mailbox")
        if not target:
            raise WireError("webrtc peer address is missing a channel label")
        rid = next(self._rid)
        loop = asyncio.get_event_loop()
        waiter: asyncio.Future = loop.create_future()
        self._waiters[rid] = waiter
        envelope = dict(request)
        envelope[self._RID_KEY] = rid
        envelope[self._REPLY_TO_KEY] = self._label
        frame = write_frame_bytes(envelope)
        try:
            self._send(target, frame)
            return await waiter
        finally:
            self._waiters.pop(rid, None)

    async def listen(self, handler, on_frame_fault=None) -> None:
        """Register the node's dispatch seam. Inbound frames arrive via :meth:`ingest`."""
        self._handler = handler
        self._on_frame_fault = on_frame_fault

    async def close(self) -> None:
        self._closed = True
        for w in self._waiters.values():
            if not w.done():
                w.cancel()
        self._waiters.clear()

    def local_address(self) -> PeerAddress:
        return PeerAddress(transport="webrtc",
                           params={"label": self._label, "pubkey": self._self_pubkey})

    # -- the inbound edge: called by the Worker on every channel.onmessage --
    async def ingest(self, frame: bytes, *, peer_pubkey: str | None) -> None:
        """Decode one opaque DataChannel frame and route it (reply or request).

        ``peer_pubkey`` is the VERIFIED identity of the channel's far end (bound at
        signed-QR/handshake admission), so a reply is trusted and a request is stamped with
        the WebRTC reputation key for the same ban/reputation gate the TCP carrier applies.
        A malformed/oversized frame from an identified peer charges the graded penalty via
        ``on_frame_fault`` (exactly like ``TcpTransport``), then nothing else happens.
        """
        try:
            decoded = read_frame_bytes(frame)
        except WireError as exc:
            if self._on_frame_fault is not None and peer_pubkey is not None:
                reply = self._on_frame_fault(webrtc_peer_id(peer_pubkey), exc)
                self._send_reply_safe(peer_pubkey, reply, rid=None)
            return
        rid = decoded.get(self._RID_KEY)
        reply_to = decoded.get(self._REPLY_TO_KEY)
        # A reply to one of our own dials carries an rid but no reply_to.
        if self._REPLY_TO_KEY not in decoded and isinstance(rid, int):
            waiter = self._waiters.get(rid)
            if waiter is not None and not waiter.done():
                waiter.set_result(_strip_relay(decoded))
            return
        if self._handler is None:
            return
        request = _strip_relay(decoded)
        if peer_pubkey is not None:
            request[ENVELOPE_PEER_KEY] = webrtc_peer_id(peer_pubkey)
        try:
            response = await self._handler(request)
        except Exception:  # noqa: BLE001 — one bad frame must not kill the loop
            return
        if isinstance(rid, int) and isinstance(reply_to, str):
            self._send_reply_safe(reply_to, response, rid=rid)

    def _send_reply_safe(self, target: str, response: dict, *, rid: int | None) -> None:
        out = dict(response)
        if rid is not None:
            out[self._RID_KEY] = rid
        try:
            self._send(target, write_frame_bytes(out))
        except WireError:
            # an over-budget reply is dropped; never crash the dispatch loop
            pass


def _strip_relay(decoded: dict) -> dict:
    """Drop the reserved ``_relay_*`` transport-envelope keys, leaving the carried map.

    Identical reservation to ``knitweb.p2p.relay._strip_envelope`` so the handler sees
    byte-for-byte the map the TCP transport would have delivered — the correlation keys
    never enter canonical/hashed bytes.
    """
    return {k: v for k, v in decoded.items()
            if not k.startswith(RELAY_ENVELOPE_PREFIX)}


# ---------------------------------------------------------------------------
# WebPeer — the composed in-tab node the Worker drives over the RPC contract
# ---------------------------------------------------------------------------

class WebPeer:
    """One browser tab as a complete MOLGANG peer.

    Composes the unchanged pieces:

      * ``derive_account(seed)``           -> the deterministic identity (no subprocess).
      * ``Bar(world_path=None, clock=…)``  -> the in-tab game loop, fed an INJECTED integer
        clock so no ``time.time()`` reaches a session/ordering path.
      * ``game.faucet_micropulses`` /      -> the integer-only decaying device faucet.
        ``current_faucet_pulses``
      * ``pouw.quorum`` (inside the Bar)   -> the real BFT ``(2*n)//3 + 1`` vote verdict.
      * ``WebRtcTransport``                -> the serverless carrier for WAN peers.
      * ``relay_sync``                     -> the SAME signed relay pre-image, used only as
        an OPTIONAL opaque first-contact mailbox (never a required server).

    The Worker holds exactly one ``WebPeer`` and calls its methods from ``dispatch``.
    """

    def __init__(self, *, seed: str, seams: dict | None = None) -> None:
        seams = seams or {}
        self.seed = seed
        self.account = derive_account(seed)
        # Injected integer seams (sacred invariant b). All default to a deterministic
        # monotonic integer counter so nothing falls back to wall-clock/randomness.
        self._mono = int(seams.get("now", 0))
        self._id_proof_now = int(seams.get("id_proof_now", 0))
        self._nonce_hex = str(seams.get("nonce_hex", ""))  # CSPRNG bytes from the shell
        # The Bar runs with NO world file (IndexedDB-backed persistence is layered by the
        # Worker via export/import; in-memory here) and an injected INTEGER clock that
        # returns whole seconds, so session staleness never touches a hashed/ordering path.
        self.bar = Bar(world_path=None, clock=self._injected_clock)
        # Stream every locally-woven item to the shell so it can redraw + (optionally)
        # broadcast it over WebRTC. This is the same hook ``relay_sync`` subscribes to.
        self.bar.world.on_weave = self._on_weave
        self._events: list[dict] = []          # buffered events drained by the Worker
        self._outbox: list[dict] = []          # opaque frames the shell must put on a channel
        self.transport: WebRtcTransport | None = None
        self.node = None                       # the BaseNode/AsyncioP2PNode, started on demand

    # -- injected seams -----------------------------------------------------
    def _injected_clock(self) -> float:
        """Whole-integer seconds, monotonic, INJECTED — never ``time.time()``.

        Returned as a float only because the Bar's type hint is ``Callable[[], float]``;
        the value is always a whole integer the shell advances, so no fractional/wall-clock
        value ever reaches a decision path.
        """
        return float(self._mono)

    def advance_clock(self, *, now: int | None = None, id_proof_now: int | None = None,
                      nonce_hex: str | None = None) -> None:
        """The Worker pushes fresh INTEGER seam values each tick (from the browser)."""
        if now is not None:
            self._mono = int(now)
        if id_proof_now is not None:
            self._id_proof_now = int(id_proof_now)
        if nonce_hex is not None:
            self._nonce_hex = str(nonce_hex)

    # -- identity view ------------------------------------------------------
    def identity(self) -> dict:
        """The public identity the shell may hold (NEVER the private seed/key)."""
        return {
            "pubkey": self.account.pub,           # 33-byte compressed pubkey hex
            "address": self.account.address,      # pls1… address
            "fiber_cid": self.account.braid.head.cid,
            "network": self.account.network,
        }

    def version(self) -> dict:
        """Contract + engine versions (the in-worker analogue of GET /api/version)."""
        return {
            "contract": contract.CONTRACT_VERSION,
            "engine": "pyodide",
            "max_frame_bytes": MAX_FRAME_BYTES,
            "micropulses_per_pulse": game.MICROPULSES_PER_PULSE,
        }

    # -- event / outbox plumbing -------------------------------------------
    def _on_weave(self, item) -> None:
        # Mirror World.on_weave: surface the woven item to the shell for redraw.
        self._events.append(contract.make_event("woven", {
            "kind": item.kind, "label": item.label, "by": item.by,
            "fiber_cid": item.fiber_cid, "confirmations": item.confirmations,
        }))

    def drain_events(self) -> list[dict]:
        """Pop buffered unsolicited events (the Worker forwards them via postMessage)."""
        out, self._events = self._events, []
        return out

    def drain_outbox(self) -> list[dict]:
        """Pop opaque frames the shell must send over a ``RTCDataChannel``.

        Each entry is ``{"label": <peer channel>, "frame_b64": <base64 frame>}``. The shell
        does not interpret the frame; it only relays the exact bytes ``wire`` produced.
        """
        out, self._outbox = self._outbox, []
        return out

    def _queue_frame(self, label: str, frame: bytes) -> None:
        self._outbox.append({"label": label, "frame_b64": base64.b64encode(frame).decode("ascii")})
        self._events.append(contract.make_event("outbox", {"pending": len(self._outbox)}))

    # -- p2p lifecycle ------------------------------------------------------
    async def peer_start(self, *, seed_peer: str | None = None) -> dict:
        """Boot the in-tab node with the WebRTC carrier registered (no TCP, no server).

        The node is constructed with the ``WebRtcTransport`` as its listening transport, so
        ``BaseNode.start()`` wires ``transport.listen(self._dispatch, self._on_frame_fault)``
        with zero changes to the node layer. Its ``_id_proof_now`` is overridden with our
        INJECTED integer seconds clock (the only ``time.time()`` in the node, used purely for
        identity-proof freshness — never a CID/ordering input). A ``seed_peer`` multiaddr (a
        QR-paired or PEX-learned peer) bootstraps discovery; with none, the tab plays solo and
        converges later when a peer arrives.
        """
        self.transport = WebRtcTransport(
            self_pubkey=self.account.pub,
            send_cb=self._queue_frame,
            local_label=self.account.pub[:16],
        )
        node = _build_node(self.account, self.transport, self._injected_id_proof_now)
        await node.start()
        self.node = node
        if seed_peer:
            try:
                await node.bootstrap_peers([PeerAddress(
                    transport="webrtc",
                    params={"label": seed_peer})])
            except Exception:  # noqa: BLE001 — an unreachable seed must not sink boot
                pass
        return {"started": True, "address": self.transport.local_address().uri()}

    def _injected_id_proof_now(self) -> int:
        """Integer-seconds identity-proof freshness clock (overrides BaseNode._id_proof_now)."""
        return self._id_proof_now

    async def peer_stop(self) -> dict:
        if self.node is not None:
            await self.node.stop()
            self.node = None
        if self.transport is not None:
            await self.transport.close()
            self.transport = None
        return {"stopped": True}

    async def ingest_frame(self, *, frame_b64: str, peer_key: str | None = None) -> dict:
        """Feed one opaque inbound DataChannel frame into the transport.

        ``peer_key`` is the VERIFIED far-end pubkey bound at signed-QR/handshake admission;
        the shell supplies it from the channel it opened, so the engine trusts identity, not
        the carrier. An over-budget base64 blob is rejected before decode.
        """
        if self.transport is None:
            raise RuntimeError("peer not started")
        raw = base64.b64decode(frame_b64, validate=True)
        if len(raw) > MAX_FRAME_BYTES + 4:
            raise WireError("inbound frame exceeds maximum size")
        await self.transport.ingest(raw, peer_pubkey=peer_key)
        return {"ingested": True}

    # -- wallet-signed QR onboarding (signature-gated auth, verify-before-connect) --
    def qr_offer(self, *, ttl_s: int = 600) -> dict:
        """Mint a wallet-signed onboarding QR offer for THIS peer.

        The payload carries ``{pubkey, multiaddr, nonce, exp, sig}``. ``nonce`` is the
        single-use CSPRNG value the shell injected (``crypto.getRandomValues``); ``exp`` is
        our injected integer-seconds clock + ``ttl_s`` (no wall-clock). The signature is over
        ``qr_offer_preimage(...)`` with the device key. A scanner MUST ``crypto.verify`` it
        before opening any channel — this is the authentication gate, not a backdoor.
        """
        if not self._nonce_hex:
            raise RuntimeError("no CSPRNG nonce injected; refusing to mint an offer")
        multiaddr = self.transport.local_address().uri() if self.transport else \
            PeerAddress(transport="webrtc", params={"label": self.account.pub[:16]}).uri()
        exp = self._id_proof_now + int(ttl_s)
        preimage = qr_offer_preimage(self.account.pub, multiaddr, self._nonce_hex, exp)
        sig = crypto.sign(self.account.priv, preimage)
        return {
            "pubkey": self.account.pub,
            "multiaddr": multiaddr,
            "nonce": self._nonce_hex,
            "exp": exp,
            "sig": sig,
        }

    def qr_admit(self, *, offer: dict) -> dict:
        """Verify a SCANNED wallet-signed QR offer BEFORE any channel is opened.

        Returns ``{"ok": True, "peer": {pubkey, multiaddr, peer_key}}`` only when the
        signature verifies over the exact pre-image AND the offer is unexpired against our
        injected integer-seconds clock. Any malformed field, a bad signature, or an expired
        ``exp`` yields ``{"ok": False, ...}`` — and the shell MUST NOT open a DataChannel.
        There is no admission path that bypasses this signature check.
        """
        try:
            pub = str(offer["pubkey"])
            multiaddr = str(offer["multiaddr"])
            nonce = str(offer["nonce"])
            exp = int(offer["exp"])
            sig = str(offer["sig"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "reason": "malformed offer"}
        if not crypto.is_valid_hex(pub, 33):
            return {"ok": False, "reason": "bad pubkey"}
        # Freshness against the INJECTED integer clock (never time.time()).
        if exp <= self._id_proof_now:
            return {"ok": False, "reason": "expired"}
        preimage = qr_offer_preimage(pub, multiaddr, nonce, exp)
        if not crypto.verify(pub, preimage, sig):
            return {"ok": False, "reason": "bad signature"}
        return {"ok": True, "peer": {
            "pubkey": pub,
            "multiaddr": multiaddr,
            "peer_key": webrtc_peer_id(pub),
        }}

    # -- optional opaque mailbox (first-contact only; never required) -------
    def relay_pull(self, *, base: str) -> dict:
        """Drain an OPTIONAL anyone-can-run opaque store-and-forward mailbox (replaces 5mart.ml).

        Uses the SAME signed pre-image ``"knitweb-relay:v1\\n{to}\\n{topic}\\n{body}"``: every
        item is re-verified end-to-end via ``relay_sync.verify_message`` before it folds into
        the local World by the domain dedup keys (``item_keys``), so the carrier is
        untrusted-by-construction and cannot forge or replay under another identity. This is
        used only for first-contact / NAT-blocked mailboxing; direct WebRTC takes over after
        the handshake. The mailbox is PEX-advertised as a multi-bootstrap list (no SPOF).
        """
        signer = relay_sync.signer_from_wallet(None)
        rs = relay_sync.RelaySync(base, self.bar.world, signer)
        result = rs.pull()
        self._events.append(contract.make_event("synced", {
            "state_root": self.bar.world.state_root(),
            "applied": result.get("applied", 0),
            "bumped": result.get("bumped", 0),
        }))
        return result

    # -- the RPC dispatch table the Worker calls ----------------------------
    async def call(self, method: str, args: dict):
        """Route one validated RPC to the matching engine operation.

        Bar gameplay methods (state/join/sit/propose/vote/spiral/...) are direct in-worker
        ``Bar`` calls — the exact operations the retired ``/api/*`` HTTP routes wrapped, with
        no server, no polling. Async p2p methods are awaited; everything else is synchronous.
        """
        # --- identity / lifecycle ---
        if method == "version":
            return self.version()
        if method == "identity":
            return self.identity()
        # --- async p2p control ---
        if method == "peer_start":
            return await self.peer_start(seed_peer=args.get("seed_peer"))
        if method == "peer_stop":
            return await self.peer_stop()
        if method == "ingest_frame":
            return await self.ingest_frame(
                frame_b64=str(args["frame_b64"]), peer_key=args.get("peer_key"))
        if method == "drain_outbox":
            return {"frames": self.drain_outbox()}
        if method == "qr_offer":
            return self.qr_offer()
        if method == "qr_admit":
            return self.qr_admit(offer=dict(args.get("offer") or {}))
        if method == "relay_pull":
            return self.relay_pull(base=str(args["base"]))
        # --- bar gameplay (synchronous, one-to-one with the retired routes) ---
        if method == "state":
            return self.bar.state(args.get("sid"))
        if method == "join":
            sess = self.bar.join(
                args.get("name", "guest"), avatar=args.get("avatar"),
                table_id=args.get("table"), device=args.get("device") or self.seed)
            return {"sid": sess.sid, "name": sess.name, "table": sess.table_id,
                    "address": sess.player.address, "pulses": sess.player.pulses,
                    "silk": sess.player.silk}
        if method == "sit":
            self.bar.sit(args["sid"], args["table"])
            return {"ok": True}
        if method == "stand":
            self.bar.stand(args["sid"])
            return {"ok": True}
        if method == "leave":
            self.bar.leave(args["sid"])
            return {"ok": True}
        if method == "heartbeat":
            return self.bar.touch(args["sid"])
        if method == "rename_table":
            tbl = self.bar.rename_table(args["sid"], args["table"], args["name"])
            return {"table": tbl.id, "name": tbl.name}
        if method == "propose":
            prop = self.bar.propose(args["sid"], args["term"], topic=args.get("topic"))
            return self.bar._knit_row(prop)
        if method == "vote":
            prop = self.bar.vote(args["sid"], args["pid"], args["verdict"])
            return self.bar._knit_row(prop)
        if method == "spiral_propose":
            sv = self.bar.propose_spiral(args["sid"], list(args.get("lines") or []))
            return self.bar._spiral_record(sv)
        if method == "spiral_vote":
            sv = self.bar.vote_spiral(args["sid"], args["cid"], args["verdict"])
            return self.bar._spiral_record(sv)
        if method == "certificate":
            return self.bar.certificate_data(args["sid"])
        if method == "web":
            return self.bar.web_view()
        if method == "graph":
            return self.bar.world.graph(limit=int(args.get("limit", 50)))
        if method == "leaderboard":
            return {"rows": self.bar._spiral_leaderboard()}
        raise contract.ContractError(f"unhandled rpc method: {method!r}")


def _build_node(account: AccountNode, transport: WebRtcTransport, id_proof_now):
    """Construct the real in-tab node over the WebRTC carrier, overriding only the
    injected identity-proof clock seam.

    Prefers the molgang/knitweb async node if present (``AsyncioP2PNode``), else falls back
    to the substrate ``BaseNode``. Either way the carrier is registered as the listening
    transport and ``_id_proof_now`` is replaced with the injected integer-seconds clock — the
    sole ``time.time()`` in the node layer, used ONLY for proof freshness, never for a CID or
    ordering decision. No other node code changes.
    """
    NodeCls = None
    try:
        from knitweb.p2p.node import AsyncioP2PNode as NodeCls  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from knitweb.p2p.node import P2PNode as NodeCls  # type: ignore
        except Exception:  # noqa: BLE001
            NodeCls = None
    if NodeCls is None:
        from knitweb.p2p.base_node import BaseNode as NodeCls  # type: ignore

    try:
        node = NodeCls(transport=transport, account=account)  # node.py accepts an account
    except TypeError:
        node = NodeCls(transport=transport)
        # Best-effort attach: the substrate BaseNode keys identity off an attached account.
        try:
            node.account = account  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    # Override the ONLY wall-clock seam in the node layer with the injected integer clock.
    try:
        node._id_proof_now = id_proof_now  # type: ignore[assignment]
    except Exception:  # noqa: BLE001
        pass
    return node


# Re-export the PEX message builders so the Worker can drive peer-relayed signaling
# (rung (c) of the bootstrap ladder) without importing discovery directly.
build_peer_exchange = discovery.peer_exchange_message
handle_peer_exchange = discovery.handle_peer_exchange
