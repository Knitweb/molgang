"""WebRtcTransport — the in-tab WebRTC carrier for the pulse wire protocol.

Canonical server-free architecture (Variant A): every browser tab IS a full
Knitweb peer running the *unchanged* ``molgang`` + ``knitweb`` Python bytes via
Pyodide in a module-type Web Worker. A browser cannot hand an ``RTCDataChannel``
to WASM, so the JS shell (:mod:`serverless/web/transport_webrtc.js`) owns the
browser-native peer connection and this module is its Python half: a single
:class:`WebRtcTransport` that satisfies the existing five-method
:class:`knitweb.p2p.transport.Transport` Protocol
(``tag`` / ``async dial`` / ``async listen`` / ``async close`` /
``local_address``).

This is exactly the carrier the **HOLE-PUNCH SEAM** docstring on
:meth:`Transport.listen` anticipates: "Nothing in this protocol — nor in the node
layer that consumes it — needs to change to add that transport." Registering it
via :meth:`BaseNode.add_transport` lets webrtc / relay / tcp peers coexist with
ZERO edits to ``node.py`` / ``base_node.py``; ``TcpTransport`` is simply not
instantiated in-tab (a tab cannot ``asyncio.start_server`` reachably anyway).

WIRE / CRYPTO CONTRACT (must stay byte-identical across peers):
  * frame = 4-byte big-endian length prefix + canonical-CBOR body;
    ``MAX_FRAME_BYTES = 8 MiB``. We reuse :func:`knitweb.p2p.wire.write_frame_bytes`
    and :func:`knitweb.p2p.wire.read_frame_bytes` VERBATIM — no new encoder ever
    sits on a hashed/signed path, so a Knit's CID and a DER signature are
    unchanged as a frame crosses this carrier.
  * request/response correlation mirrors :mod:`knitweb.p2p.relay` exactly: each
    request is tagged with a fresh INTEGER ``_relay_rid`` + ``_relay_reply_to``
    in the *transport envelope*; the reserved ``_relay_*`` namespace is stripped
    by :func:`knitweb.p2p.relay._strip_envelope` BEFORE any signed/business logic
    runs, so it never enters canonical/hashed bytes. The responder echoes the
    same ``rid``. (A ``DataChannel`` is message-oriented, so the same one-shot
    request->reply shape the relay uses fits without change.)
  * sender identity: a carrier that can positively identify the peer stamps it as
    :data:`knitweb.p2p.relay.ENVELOPE_PEER_KEY` on the decoded request, so the
    carrier-agnostic dispatch applies the SAME reputation/ban gate uniformly.
    Here the peer id is the wallet-signed-QR pubkey the JS shell verified
    (``crypto.verify``) BEFORE the DataChannel opened — signature-gated
    authentication, never an unauthenticated backdoor.

SACRED INVARIANTS honored:
  (a) INTEGER-ONLY: ``rid`` is an integer counter (``itertools.count``), never a
      clock; no float, ``//`` never ``/`` anywhere on a path that matters.
  (b) NO wall-clock / NO randomness on any decision/scoring/ordering path. The
      correlation id is a pure integer counter. The carrier reads no clock to
      decide anything; the only timeout is a transport-policy ceiling (never a
      CID/ordering input). Nonces for signaling come from the shell's WebCrypto
      CSPRNG, not ``Math.random``.
  (c) BYTE-IDENTITY: opaque carriage — the frame bytes are produced/consumed only
      by :mod:`knitweb.p2p.wire`; this adapter never re-encodes a body.

The bridge to the JS shell is a small injectable seam
(:class:`WorkerBridge`) so the engine stays testable off-browser (a fake bridge
loops frames in-process) and so the only Pyodide-specific code is one thin class.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Awaitable, Callable, Optional

from knitweb.p2p.relay import (
    ENVELOPE_PEER_KEY,
    RELAY_ENVELOPE_PREFIX,
    _strip_envelope,
)
from knitweb.p2p.transport import FrameFaultHandler, FrameHandler, PeerAddress
from knitweb.p2p.wire import (
    MAX_FRAME_BYTES,
    WireError,
    read_frame_bytes,
    write_frame_bytes,
)

__all__ = [
    "WebRtcTransport",
    "WorkerBridge",
    "WebRtcError",
    "webrtc_peer_id",
    "WEBRTC_TAG",
]

#: The ``PeerAddress.transport`` tag this carrier owns. The :class:`Dialer`
#: routes a peer with this tag here, so webrtc/relay/tcp peers coexist.
WEBRTC_TAG = "webrtc"

#: Reputation-key prefix for a WebRTC sender, distinguishing a ``webrtc://`` peer
#: from a ``tcp:<ip>`` / ``relay:<mailbox>`` one so the three address spaces never
#: collide in the reputation ledger (mirrors ``tcp:`` / ``relay:``).
_WEBRTC_PEER_PREFIX = "webrtc:"

#: Overall ceiling (integer seconds) a :meth:`WebRtcTransport.dial` waits for a
#: correlated reply before giving up. A pure transport-policy timeout — it never
#: enters a canonical/hashed/ordering byte (mirrors relay ``_DIAL_TIMEOUT_S``).
_DIAL_TIMEOUT_S = 30

# Transport-envelope correlation keys, in the reserved ``_relay_*`` namespace so
# :func:`_strip_envelope` removes them before any signed/business logic runs and
# they never enter canonical/hashed bytes. We reuse the SAME prefix as the relay
# carrier (rather than minting a parallel one) precisely so the existing
# envelope-strip handles them with zero new surface.
_RID_KEY = RELAY_ENVELOPE_PREFIX + "rid"            # "_relay_rid"
_REPLY_TO_KEY = RELAY_ENVELOPE_PREFIX + "reply_to"  # "_relay_reply_to"


class WebRtcError(RuntimeError):
    """Raised when the WebRTC carrier hop fails or returns a malformed frame."""


def webrtc_peer_id(pubkey: str) -> str:
    """Stable reputation key for a WebRTC sender, from its AUTHENTICATED pubkey.

    Unlike a relay mailbox (self-asserted, re-mintable per frame) or a TCP source
    IP (shared across honest NAT peers), the WebRTC peer id is the 33-byte
    compressed pubkey the wallet-signed-QR handshake already proved possession of
    — a per-identity-stable key. A forger is therefore banned individually with
    zero NAT collateral, the strongest identity any of the three carriers exposes.
    """
    return f"{_WEBRTC_PEER_PREFIX}{pubkey}"


class WorkerBridge:
    """Injectable seam between this Python transport and the JS shell.

    Under Pyodide the concrete bridge marshals frames over ``postMessage`` to/from
    :mod:`serverless/web/transport_webrtc.js`. Factored out as a Protocol-shaped
    seam so the engine is testable off-browser (a fake bridge loops frames in
    process) and so the only Pyodide-specific code is the thin default below.

    Contract (all ``frame`` args are OPAQUE length-prefixed canonical-CBOR bytes
    produced/consumed only by :mod:`knitweb.p2p.wire`):

      * ``async dial_frame(peer_key, rid, frame) -> bytes`` — send a request frame
        to the AUTHENTICATED ``peer_key`` over its DataChannel and return the
        correlated reply frame. Raises :class:`WebRtcError` on timeout/closure.
      * ``respond_frame(peer_key, rid, frame) -> None`` — mail a reply frame back
        to ``peer_key`` for the inbound request tagged ``rid``.
      * ``set_inbound(callback)`` — register an async callback the shell invokes
        for every inbound request: ``await callback(peer_key, rid, frame)``.
      * ``set_frame_fault(callback)`` — register a callback the shell invokes when
        an *identified* peer sends a malformed/oversized frame:
        ``callback(peer_key, error_str)``.
      * ``async close()`` — tear down all peer connections.
      * ``local_params() -> dict[str, str]`` — routing/identity params for
        :meth:`local_address` (e.g. ``{"pubkey": ..., "mailbox": ...}``).

    This base class is abstract; :func:`pyodide_bridge` builds the real one.
    """

    async def dial_frame(self, peer_key: str, rid: int, frame: bytes) -> bytes:
        raise NotImplementedError

    def respond_frame(self, peer_key: str, rid: int, frame: bytes) -> None:
        raise NotImplementedError

    def set_inbound(
        self, callback: Callable[[str, int, bytes], Awaitable[None]]
    ) -> None:
        raise NotImplementedError

    def set_frame_fault(self, callback: Callable[[str, str], None]) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def local_params(self) -> dict:
        raise NotImplementedError


class WebRtcTransport:
    """WebRTC ``RTCDataChannel`` transport satisfying the :class:`Transport` Protocol.

    Parameters
    ----------
    bridge:
        A :class:`WorkerBridge` to the JS shell that owns the actual
        ``RTCPeerConnection`` / ``RTCDataChannel`` objects. Injected so the engine
        is testable off-browser.
    self_key:
        This tab's 33-byte compressed pubkey hex (``AccountNode.pub``). It is the
        identity peers dial and the key this transport advertises in
        :meth:`local_address`.
    dial_timeout_s:
        Integer-seconds ceiling for a correlated reply. Transport policy only;
        never a canonical/hashed/ordering input.
    """

    tag = WEBRTC_TAG

    def __init__(
        self,
        *,
        bridge: WorkerBridge,
        self_key: str,
        dial_timeout_s: int = _DIAL_TIMEOUT_S,
    ) -> None:
        if dial_timeout_s < 1:
            raise ValueError("dial_timeout_s must be a positive integer")
        self.bridge = bridge
        self.self_key = self_key
        self.dial_timeout_s = dial_timeout_s
        self._handler: Optional[FrameHandler] = None
        self._on_frame_fault: Optional[FrameFaultHandler] = None
        # Fresh INTEGER request-correlation id per dial. A pure counter — never a
        # clock — so it touches no decision/ordering path, exactly like the relay
        # carrier's ``_relay_rid`` (relay.py:203). Starts at 1 so 0 is never a
        # valid rid (a falsy guard stays unambiguous).
        self._rid = itertools.count(1)
        self._closed = False

    # -- dial (request -> correlated reply) -------------------------------

    async def dial(self, peer: PeerAddress, request: dict) -> dict:
        """Send one ``request`` map to ``peer`` over its DataChannel; return the reply.

        The flow mirrors :meth:`RelayTransport.dial` (relay.py:235): stamp the
        transport envelope with a fresh integer ``rid`` + our reply mailbox
        (here, our own pubkey, since a DataChannel reply routes straight back to
        the originating peer), frame it with :func:`write_frame_bytes` so the
        bytes are identical to every other carrier, hand the OPAQUE frame to the
        bridge, and decode the correlated reply frame with
        :func:`read_frame_bytes`. The ``_relay_*`` envelope keys are stripped
        before the handler ever sees them, so they never enter hashed bytes.
        """
        peer_key = peer.params.get("pubkey")
        if not peer_key:
            raise WebRtcError("webrtc peer address is missing a pubkey")
        rid = next(self._rid)
        # Transport-envelope correlation only — these keys live in the reserved
        # ``_relay_*`` namespace and are stripped before any signed/business
        # logic, so the OPAQUE frame bytes we carry are framed exactly as the TCP
        # transport would frame ``request`` (sans envelope), preserving the
        # byte-identity of every nested signed record (a Knit's CID is unchanged).
        envelope = dict(request)
        envelope[_RID_KEY] = rid
        envelope[_REPLY_TO_KEY] = self.self_key
        frame = write_frame_bytes(envelope)
        try:
            reply_frame = await asyncio.wait_for(
                self.bridge.dial_frame(peer_key, rid, frame),
                timeout=self.dial_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise WebRtcError("webrtc dial timed out waiting for reply") from exc
        except WebRtcError:
            raise
        except Exception as exc:  # bridge/channel failure
            raise WebRtcError(f"webrtc dial failed: {exc}") from exc
        try:
            decoded = read_frame_bytes(reply_frame)
        except WireError as exc:
            raise WebRtcError(f"webrtc reply frame malformed: {exc}") from exc
        # Strip any transport-envelope keys the responder echoed, exactly as the
        # relay carrier does, so the caller sees the byte-identical carried map.
        return _strip_envelope(decoded)

    # -- listen (inbound request -> handler -> mail reply) ----------------

    async def listen(
        self,
        handler: FrameHandler,
        on_frame_fault: "FrameFaultHandler | None" = None,
    ) -> None:
        """Begin accepting inbound DataChannel requests, dispatching each to ``handler``.

        HOLE-PUNCH SEAM realized: the only thing that differs from the TCP
        listener is *how the channel becomes reachable* — the JS shell, after the
        wallet-signed-QR / STUN / PEX signaling ladder, hands us a connected,
        AUTHENTICATED channel. We register an inbound callback with the bridge;
        for every inbound request it invokes :meth:`_on_inbound`, which decodes
        the frame, stamps the verified sender pubkey as
        :data:`ENVELOPE_PEER_KEY` (so the carrier-agnostic dispatch applies the
        same reputation/ban gate), runs ``handler``, and mails the framed reply
        back over the same channel.
        """
        self._handler = handler
        self._on_frame_fault = on_frame_fault
        self.bridge.set_inbound(self._on_inbound)
        # The frame-fault path: the shell already validated the 4-byte prefix /
        # ceiling at the channel boundary, so a malformed/oversized frame from an
        # IDENTIFIED peer arrives here as a fault notification (never as a request
        # map). We charge the graded reputation penalty via ``on_frame_fault``,
        # exactly as the TCP carrier does (base_node._on_frame_fault).
        self.bridge.set_frame_fault(self._on_inbound_fault)

    async def _on_inbound(self, peer_key: str, rid: int, frame: bytes) -> None:
        """Decode one inbound request frame, dispatch, and mail the reply back.

        Mirrors :meth:`RelayTransport._dispatch` (relay.py:293): decode the
        OPAQUE frame, strip the reserved ``_relay_*`` envelope, stamp the
        AUTHENTICATED ``ENVELOPE_PEER_KEY``, call the handler, re-frame the
        response, and send it back tagged with the same integer ``rid``.
        """
        if self._handler is None:
            return
        try:
            decoded = read_frame_bytes(frame)
        except WireError as exc:
            # Defensive: the shell should have caught this, but if a frame slips
            # through, treat it as a fault against this identified peer.
            self._on_inbound_fault(peer_key, str(exc))
            return
        # Strip transport-envelope keys so the handler sees the byte-identical
        # carried map (the map the TCP transport would have delivered).
        request = _strip_envelope(decoded)
        # Stamp the carrier-agnostic peer identity. The pubkey was verified by the
        # signed-QR handshake BEFORE the channel opened, so this is a proven,
        # per-identity-stable key (``webrtc:<pubkey>``) — the dispatch ban gate
        # keys reputation on it with zero NAT collateral. It rides the reserved
        # envelope namespace and is popped before any signed/business logic, so
        # it never enters canonical/hashed bytes.
        request[ENVELOPE_PEER_KEY] = webrtc_peer_id(peer_key)
        try:
            response = await self._handler(request)
        except Exception:  # noqa: BLE001 — never let one bad frame kill the loop
            return
        try:
            out_frame = write_frame_bytes(response)
        except WireError:
            # An over-ceiling response cannot be framed; drop rather than send a
            # malformed reply (the dialer times out, same as the relay carrier).
            return
        self.bridge.respond_frame(peer_key, rid, out_frame)

    def _on_inbound_fault(self, peer_key: str, error: str) -> None:
        """Record the graded reputation penalty for a malformed/oversized frame.

        The node owns reputation, not the carrier: we hand the identified peer +
        the :class:`WireError` to ``on_frame_fault`` (the same hook the TCP
        carrier uses) so the matching penalty lands on ``webrtc:<pubkey>``. The
        returned error map is mailed back to the peer when we still have a live
        channel; with no hook the frame is simply dropped, as before.
        """
        if self._on_frame_fault is None:
            return
        peer_id = webrtc_peer_id(peer_key)
        # ``on_frame_fault`` expects a WireError; reconstruct one from the shell's
        # message so the node records the same penalty kind.
        self._on_frame_fault(peer_id, WireError(error))

    # -- lifecycle --------------------------------------------------------

    async def close(self) -> None:
        """Release all peer connections. Idempotent."""
        if self._closed:
            return
        self._closed = True
        await self.bridge.close()

    def local_address(self) -> PeerAddress:
        """The address peers should dial to reach this transport's listener.

        ``transport="webrtc"``; ``params`` carry the identity/routing the
        signaling ladder needs (the tab's pubkey + its inbound mailbox id). A
        peer that scans this tab's wallet-signed QR reconstructs exactly this
        :class:`PeerAddress` and the :class:`Dialer` routes a dial here by tag.
        """
        params = dict(self.bridge.local_params())
        params.setdefault("pubkey", self.self_key)
        return PeerAddress(transport=WEBRTC_TAG, params=params)


# ---------------------------------------------------------------------------
# Concrete Pyodide bridge: marshals frames over ``postMessage`` to the JS shell.
#
# Kept at module end and lazily importing ``js`` so the module imports cleanly
# under CPython (for the conformance/golden-vector suite and off-browser tests),
# where a fake in-process :class:`WorkerBridge` is injected instead.
# ---------------------------------------------------------------------------


def pyodide_bridge(post_to_shell, self_key: str, mailbox: str) -> WorkerBridge:
    """Build the real :class:`WorkerBridge` for the Pyodide Web Worker.

    ``post_to_shell`` is the worker's ``postMessage`` (a JS function proxied into
    Python by Pyodide). This bridge:

      * ``dial_frame`` posts ``{op:"webrtc_dial", peerKey, rid, frame}`` to the
        shell and awaits the matching ``webrtc_dial_result`` keyed by ``rid``.
      * ``respond_frame`` posts ``{op:"webrtc_respond", peerKey, rid, frame}``.
      * the shell delivers inbound requests / faults by calling the registered
        callbacks (the worker's onmessage routes ``webrtc_inbound`` /
        ``webrtc_frame_fault`` to them).

    All ``frame`` payloads are OPAQUE ``bytes`` — Pyodide copies them to/from a
    JS ``Uint8Array`` without this Python code ever decoding the body.
    """

    class _PyodideBridge(WorkerBridge):
        def __init__(self) -> None:
            self._post = post_to_shell
            self._self_key = self_key
            self._mailbox = mailbox
            self._inbound: Optional[
                Callable[[str, int, bytes], Awaitable[None]]
            ] = None
            self._fault: Optional[Callable[[str, str], None]] = None
            # Pending dial replies keyed by integer rid (transport correlation).
            self._dial_waiters: dict = {}

        # The worker's onmessage calls these when the shell posts results.
        def on_dial_result(self, rid: int, frame: bytes) -> None:
            waiter = self._dial_waiters.pop(rid, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(frame)

        def on_dial_error(self, rid: int, error: str) -> None:
            waiter = self._dial_waiters.pop(rid, None)
            if waiter is not None and not waiter.done():
                waiter.set_exception(WebRtcError(error))

        def on_inbound(self, peer_key: str, rid: int, frame: bytes) -> None:
            if self._inbound is not None:
                asyncio.ensure_future(self._inbound(peer_key, rid, frame))

        def on_frame_fault(self, peer_key: str, error: str) -> None:
            if self._fault is not None:
                self._fault(peer_key, error)

        # WorkerBridge contract.
        async def dial_frame(
            self, peer_key: str, rid: int, frame: bytes
        ) -> bytes:
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            self._dial_waiters[rid] = waiter
            try:
                self._post(
                    {
                        "op": "webrtc_dial",
                        "peerKey": peer_key,
                        "rid": rid,
                        "frame": frame,
                    }
                )
                return await waiter
            finally:
                self._dial_waiters.pop(rid, None)

        def respond_frame(self, peer_key: str, rid: int, frame: bytes) -> None:
            self._post(
                {
                    "op": "webrtc_respond",
                    "peerKey": peer_key,
                    "rid": rid,
                    "frame": frame,
                }
            )

        def set_inbound(
            self, callback: Callable[[str, int, bytes], Awaitable[None]]
        ) -> None:
            self._inbound = callback

        def set_frame_fault(
            self, callback: Callable[[str, str], None]
        ) -> None:
            self._fault = callback

        async def close(self) -> None:
            self._post({"op": "webrtc_close"})
            for waiter in self._dial_waiters.values():
                if not waiter.done():
                    waiter.set_exception(WebRtcError("transport closed"))
            self._dial_waiters.clear()

        def local_params(self) -> dict:
            return {"pubkey": self._self_key, "mailbox": self._mailbox}

    return _PyodideBridge()
