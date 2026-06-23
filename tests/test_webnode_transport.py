"""Tests for molgang.webnode.transport — WebRtcTransport with FakeWorkerBridge."""

import asyncio
from typing import Awaitable, Callable

import pytest

from knitweb.p2p.relay import ENVELOPE_PEER_KEY
from knitweb.p2p.transport import PeerAddress
from knitweb.p2p.wire import read_frame_bytes, write_frame_bytes
from molgang.webnode.transport import (
    WEBRTC_TAG,
    WebRtcError,
    WebRtcTransport,
    WorkerBridge,
    webrtc_peer_id,
)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fake in-process bridge pair
# ---------------------------------------------------------------------------


class FakeWorkerBridge(WorkerBridge):
    """In-process bridge: dial_frame on side-A delivers as inbound on side-B."""

    def __init__(self, self_key: str) -> None:
        self._self_key = self_key
        self._dial_waiters: dict = {}
        self._inbound: Callable[[str, int, bytes], Awaitable[None]] | None = None
        self._fault: Callable[[str, str], None] | None = None
        self._peer: "FakeWorkerBridge | None" = None

    async def dial_frame(self, peer_key: str, rid: int, frame: bytes) -> bytes:
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._dial_waiters[rid] = waiter
        if self._peer is not None and self._peer._inbound is not None:
            asyncio.ensure_future(self._peer._inbound(self._self_key, rid, frame))
        return await waiter

    def respond_frame(self, peer_key: str, rid: int, frame: bytes) -> None:
        if self._peer is not None:
            waiter = self._peer._dial_waiters.pop(rid, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(frame)

    def set_inbound(self, callback: Callable[[str, int, bytes], Awaitable[None]]) -> None:
        self._inbound = callback

    def set_frame_fault(self, callback: Callable[[str, str], None]) -> None:
        self._fault = callback

    async def close(self) -> None:
        for w in self._dial_waiters.values():
            if not w.done():
                w.set_exception(WebRtcError("transport closed"))
        self._dial_waiters.clear()

    def local_params(self) -> dict:
        return {"pubkey": self._self_key}


def make_pair(key_a="pub_a", key_b="pub_b"):
    ba = FakeWorkerBridge(key_a)
    bb = FakeWorkerBridge(key_b)
    ba._peer = bb
    bb._peer = ba
    ta = WebRtcTransport(bridge=ba, self_key=key_a)
    tb = WebRtcTransport(bridge=bb, self_key=key_b)
    addr_b = PeerAddress(transport=WEBRTC_TAG, params={"pubkey": key_b})
    return ta, tb, addr_b


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dial_listen_roundtrip():
    async def scenario():
        ta, tb, addr_b = make_pair()

        async def handler(req):
            return {"kind": "pong", "echo": req.get("value")}

        await tb.listen(handler)
        resp = await ta.dial(addr_b, {"kind": "ping", "value": 99})
        assert resp == {"kind": "pong", "echo": 99}

    run(scenario())


def test_envelope_peer_key_is_stamped_with_webrtc_prefix():
    async def scenario():
        ta, tb, addr_b = make_pair(key_a="abc123")
        seen = {}

        async def handler(req):
            seen["peer"] = req.get(ENVELOPE_PEER_KEY)
            return {}

        await tb.listen(handler)
        await ta.dial(addr_b, {"kind": "x"})
        assert seen["peer"] == webrtc_peer_id("abc123")
        assert seen["peer"].startswith("webrtc:")

    run(scenario())


def test_frame_bytes_are_byte_identical():
    async def scenario():
        ta, tb, addr_b = make_pair()

        async def handler(req):
            return {"z": 1, "a": 2}

        await tb.listen(handler)
        resp = await ta.dial(addr_b, {"kind": "x"})
        # Canonical re-encoding must be stable.
        assert write_frame_bytes(resp) == write_frame_bytes(read_frame_bytes(write_frame_bytes(resp)))

    run(scenario())


def test_webrtc_peer_id_prefix():
    assert webrtc_peer_id("abc") == "webrtc:abc"
    assert not webrtc_peer_id("abc").startswith("relay:")
    assert not webrtc_peer_id("abc").startswith("tcp:")


def test_close_raises_on_pending_dial():
    async def scenario():
        ba = FakeWorkerBridge("pub_a")
        bb = FakeWorkerBridge("pub_b")
        ba._peer = bb  # bb has no inbound registered — dial hangs
        ta = WebRtcTransport(bridge=ba, self_key="pub_a", dial_timeout_s=60)
        addr_b = PeerAddress(transport=WEBRTC_TAG, params={"pubkey": "pub_b"})

        task = asyncio.ensure_future(ta.dial(addr_b, {"kind": "ping"}))
        await asyncio.sleep(0)
        await ta.close()
        with pytest.raises(Exception):
            await task

    run(scenario())


def test_local_address_includes_self_key():
    ba, _ = FakeWorkerBridge("mypub"), FakeWorkerBridge("other")
    ta = WebRtcTransport(bridge=ba, self_key="mypub")
    addr = ta.local_address()
    assert addr.transport == WEBRTC_TAG
    assert addr.params["pubkey"] == "mypub"


def test_missing_pubkey_raises_immediately():
    async def scenario():
        ba = FakeWorkerBridge("pub_a")
        ta = WebRtcTransport(bridge=ba, self_key="pub_a")
        bad = PeerAddress(transport=WEBRTC_TAG, params={})
        with pytest.raises(WebRtcError, match="pubkey"):
            await ta.dial(bad, {})

    run(scenario())
