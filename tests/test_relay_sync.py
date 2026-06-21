"""relay-sync: two installs converge on the SAME shared web over the relay (knitweb/molgang#44).

The convergence test uses a LOCAL in-memory relay stub (never the live 5mart.ml relay) that
mirrors the live node's contract: it re-verifies each message's signature on ``send`` (a forged
message is refused) and serves stored messages on ``fetch`` with a ``since`` cursor — exactly
``php/src/Relay.php`` (PR #77). One opt-in test does a single read-only round-trip against the
live relay (``MOLGANG_LIVE_RELAY=1``) — never a write, so it can't spam the live node.
"""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

from knitweb.core import crypto
from knitweb.ledger.node import AccountNode

from molgang.relay_sync import (
    RelaySync,
    WEB_TOPIC,
    host_signer,
    item_from_body,
    pack,
    signed_preimage,
    signer_from_wallet,
    verify_message,
)
from molgang.world import World, WovenItem


# -- a local in-memory relay stub mirroring the live node's send/fetch contract --
class FakeRelay:
    """An in-memory store-and-forward relay (the live server's contract, no network).

    ``send`` re-verifies the signature over ``signed_preimage(to, topic, body)`` and refuses a
    bad one (``ok:false``); ``fetch`` returns messages newer than ``since`` filtered by topic
    with a monotonic ``created`` cursor — identical shapes to the live ``…/relay/{send,fetch}``.
    """

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self._t = 0.0

    def opener(self, url: str, data: bytes | None = None) -> dict:
        if data is not None:                       # POST …/send
            return self._send(json.loads(data))
        return self._fetch(url)                    # GET  …/fetch?...

    def _send(self, msg: dict) -> dict:
        frm, to = str(msg.get("from", "")), msg.get("to") or ""
        topic, body, sig = str(msg.get("topic", "")), str(msg.get("body", "")), str(msg.get("sig", ""))
        if not crypto.verify(frm, signed_preimage(to, topic, body), sig):
            return {"ok": False, "error": "invalid signature"}      # the relay re-verifies
        self._t += 1.0
        self.messages.append({"id": f"m{len(self.messages)}", "from": frm,
                              "to": to or None, "topic": topic, "body": body,
                              "sig": sig, "created": self._t})
        return {"ok": True, "id": self.messages[-1]["id"]}

    def _fetch(self, url: str) -> dict:
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(url).query)
        topic = (q.get("topic") or [""])[0]
        since = float((q.get("since") or ["0"])[0])
        out = [m for m in self.messages
               if m["created"] > since and (not topic or m["topic"] == topic)]
        cursor = max([since, *[m["created"] for m in out]]) if out else since
        return {"messages": out, "cursor": cursor, "count": len(out)}


def _bar_world(tmp_path, name):
    return World(str(tmp_path / f"{name}.json"))


# -- envelope / signing ------------------------------------------------------
def test_pack_roundtrips_through_verify_and_body():
    signer = host_signer("test:node:a")
    item = WovenItem(kind="term", by="alice", fiber_cid="f1", confirmations=3, term="H2O")
    msg = pack(item, signer)
    assert msg["from"] == signer.pub and msg["topic"] == WEB_TOPIC
    assert verify_message(msg, topic=WEB_TOPIC)
    back = item_from_body(msg["body"])
    assert back == item                            # body is the exact WovenItem JSON


def test_tampered_message_is_rejected():
    signer = host_signer("test:node:a")
    item = WovenItem(kind="link", by="b", fiber_cid="f", confirmations=2,
                     subject="V205", object="V2O5", relation="is")
    msg = pack(item, signer)
    assert verify_message(msg)
    # flip the body after signing → signature no longer matches → rejected
    bad = dict(msg, body=msg["body"].replace("V2O5", "XXXX"))
    assert not verify_message(bad)
    # a wrong-topic replay is also rejected when a topic is pinned
    assert not verify_message(dict(msg, topic="other.topic"), topic=WEB_TOPIC)


# -- the headline: two Worlds converge over the relay ------------------------
def test_two_worlds_converge_over_relay(tmp_path):
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    b = _bar_world(tmp_path, "B")
    sa = host_signer("install:A")
    sb = host_signer("install:B")
    ra = RelaySync("http://stub/relay", a, sa, opener=relay.opener)
    rb = RelaySync("http://stub/relay", b, sb, opener=relay.opener)
    # PUSH-on-weave: A's confirmed knits broadcast to the relay automatically
    a.on_weave = ra.push

    # weave on A → pushed to the relay
    a.weave_knit({"kind": "term", "term": "NaCl"}, "alice", "fa1", 3)
    a.weave_knit({"kind": "link", "subject": "Na", "object": "Cl", "relation": "bonds"},
                 "alice", "fa2", 4)
    assert relay._fetch("u?topic=" + WEB_TOPIC)["count"] == 2

    # B starts empty, pulls, and now contains A's web
    assert b.size() == (0, 0)
    res = rb.pull()
    assert res["applied"] == 2 and res["rejected"] == 0
    g = b.graph()
    assert "nacl" in g["terms"] and any(l["subject"] == "Na" for l in g["links"])

    # CONVERGENCE: same node-set ⇒ identical state_root (the same UAL contribution)
    assert b.size() == a.size()
    assert b.state_root() == a.state_root()


def test_pull_is_idempotent_and_bumps_confirmations(tmp_path):
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    b = _bar_world(tmp_path, "B")
    ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener)
    rb = RelaySync("http://stub", b, host_signer("B"), opener=relay.opener)
    a.on_weave = ra.push
    a.weave_knit({"kind": "link", "subject": "Na", "object": "Cl", "relation": "bonds"},
                 "alice", "fa", 4)

    first = rb.pull()
    assert first["applied"] == 1
    root_after_first = b.state_root()
    n_items = len(b.items)

    # a SECOND pull of the same message must not double-count the node set …
    second = rb.pull()
    assert second["applied"] == 0
    assert b.state_root() == root_after_first      # node-set (hence state_root) is stable
    assert len(b.items) == n_items                 # no duplicate WovenItem appended

    # … re-pushing the SAME fiber from another install bumps the edge tension (tauter)
    edge_w = rb._edge_weight(b._term_node("Na"), b._term_node("Cl"), "bonds")
    msg = pack(WovenItem(kind="link", by="carol", fiber_cid="fc", confirmations=2,
                         subject="Na", object="Cl", relation="bonds"),
               host_signer("C"))
    relay._send(msg)
    third = rb.pull()
    assert third["bumped"] == 1 and third["applied"] == 0
    bumped_w = rb._edge_weight(b._term_node("Na"), b._term_node("Cl"), "bonds")
    assert bumped_w > edge_w

    # the bump is DURABLE: a fresh World load re-applies the fiber at the heavier weight
    reloaded = World(b.path)
    e = next(x for x in reloaded.web._out[reloaded._term_node("Na")]
             if x.dst == reloaded._term_node("Cl") and x.rel == "bonds")
    assert e.weight == bumped_w


def test_own_echo_is_not_double_counted(tmp_path):
    """Pulling back our OWN pushed message is a no-op — never re-bumps our own edge."""
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener)
    a.on_weave = ra.push
    a.weave_knit({"kind": "link", "subject": "Na", "object": "Cl", "relation": "bonds"},
                 "alice", "fa", 4)
    w0 = ra._edge_weight(a._term_node("Na"), a._term_node("Cl"), "bonds")
    res = ra.pull()                                 # drains our own echo
    assert res["applied"] == 0 and res["bumped"] == 0 and res["skipped"] == 1
    assert ra._edge_weight(a._term_node("Na"), a._term_node("Cl"), "bonds") == w0


def test_relay_refuses_a_forged_message():
    relay = FakeRelay()
    signer = host_signer("real")
    item = WovenItem(kind="term", by="x", fiber_cid="f", confirmations=1, term="Fe")
    msg = pack(item, signer)
    forged = dict(msg, body=msg["body"].replace("Fe", "Au"))   # tamper after signing
    assert relay._send(forged)["ok"] is False                   # relay re-verifies and refuses
    assert relay._send(msg)["ok"] is True                       # the genuine one is accepted


def test_signer_from_wallet_reuses_pulse_node_snapshot(tmp_path):
    from knitweb.store import save_node

    path = str(tmp_path / "pulse-identity.json")
    node = AccountNode()
    save_node(node, path)

    signer = signer_from_wallet(path)
    assert signer.pub == node.pub
    assert signer.address == node.address

    item = WovenItem(kind="term", by="host", fiber_cid="f", confirmations=1, term="H2O")
    msg = pack(item, signer)
    assert msg["from"] == node.pub
    assert verify_message(msg, topic=WEB_TOPIC)


def test_signer_from_legacy_wallet_file_keeps_stable_fallback(tmp_path):
    path = tmp_path / "legacy-pulse-identity.json"
    path.write_text(json.dumps({"address": "0xabc", "publicKey": "legacy", "balance": 0}))

    first = signer_from_wallet(str(path))
    second = signer_from_wallet(str(path))

    assert first.pub == second.pub
    assert first.address == second.address
    assert first.pub != "legacy"


def test_invalid_node_snapshot_does_not_fallback_to_path_seed(tmp_path):
    path = tmp_path / "broken-pulse-identity.json"
    path.write_text(json.dumps({"kind": "node-snapshot", "priv": "not-hex", "pub": "bad"}))

    with pytest.raises(RuntimeError, match="node snapshot is invalid"):
        signer_from_wallet(str(path))


def test_spiral_converges_with_every_link(tmp_path):
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    b = _bar_world(tmp_path, "B")
    ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener)
    rb = RelaySync("http://stub", b, host_signer("B"), opener=relay.opener)
    a.on_weave = ra.push
    a.weave_spiral([{"subject": "H2", "object": "O2", "relation": "reacts"},
                    {"subject": "O2", "object": "H2O", "relation": "yields"}],
                   "alice", "fs", 3, validators=3, pls_staked=9)
    res = rb.pull()
    assert res["applied"] == 1                      # the whole spiral arrives as one item
    spirals = [it for it in b.items if it.kind == "spiral"]
    assert len(spirals) == 1
    blinks = {(l["subject"], l["object"]) for l in spirals[0].links}
    assert ("H2", "O2") in blinks and ("O2", "H2O") in blinks
    # every spiral link became a real woven edge → same node-set & edge-set as A
    assert b.size() == a.size()
    assert b.state_root() == a.state_root()


def test_webserver_main_accepts_operator_flags(monkeypatch, tmp_path):
    from molgang import webserver

    captured = {}

    monkeypatch.setattr(webserver, "bootstrap_host", lambda *a, **k: {
        "account": {"address": "pls1host", "balance_pls": 0},
        "listen": "127.0.0.1:0",
        "wallet": "host.cbor",
    })

    class FakeMonitor:
        def __init__(self, bar, *, web=None, world=None, pulse_host=None, nodes=None):
            captured["monitor_nodes"] = nodes
            self.nodes = [{"label": "alice"}]
            self.source = "fake"

    fake_monitor_mod = types.ModuleType("molgang.monitor")
    fake_monitor_mod.Monitor = FakeMonitor
    monkeypatch.setitem(sys.modules, "molgang.monitor", fake_monitor_mod)

    class FakeSigner:
        address = "pls1relay"

    class FakeRelay:
        def __init__(self, base):
            self.base = base
            self.signer = FakeSigner()

    def fake_start_relay(bar, base, wallet, interval):
        captured["relay_base"] = base
        captured["relay_wallet"] = wallet
        captured["relay_interval"] = interval
        return FakeRelay(base)

    class FakeServer:
        def __init__(self, addr, handler):
            captured["addr"] = addr
            captured["handler"] = handler

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(webserver, "_start_relay", fake_start_relay)
    monkeypatch.setattr(webserver, "ThreadingHTTPServer", FakeServer)

    code = webserver.main([
        "molgang", "serve",
        "--host", "127.0.0.1",
        "--port", "0",
        "--world", str(tmp_path / "world.json"),
        "--db", str(tmp_path / "registry.db"),
        "--relay", "https://5mart.ml/molgang/api/relay",
        "--relay-wallet", str(tmp_path / "server-node.cbor"),
        "--relay-interval", "7",
        "--monitor",
        "--monitor-nodes", "alice=59000",
    ])

    assert code == 0
    assert captured["addr"] == ("127.0.0.1", 0)
    assert captured["relay_base"] == "https://5mart.ml/molgang/api/relay"
    assert captured["relay_wallet"] == str(tmp_path / "server-node.cbor")
    assert captured["relay_interval"] == 7.0
    assert captured["monitor_nodes"] == "alice=59000"


# -- ONE opt-in, read-only live round-trip (no write → cannot spam) ----------
@pytest.mark.skipif(os.environ.get("MOLGANG_LIVE_RELAY") != "1",
                    reason="set MOLGANG_LIVE_RELAY=1 to hit the live 5mart.ml relay (read-only)")
def test_live_relay_fetch_roundtrip(tmp_path):
    """Read-only: GET the live relay and verify a real stored message end-to-end."""
    base = "https://5mart.ml/molgang/api/relay"
    w = _bar_world(tmp_path, "live")
    rs = RelaySync(base, w, AccountNode.from_seed("molgang:relay:live-smoke"), topic="chem")
    resp = rs._open(f"{base}/fetch?topic=chem", None)
    assert resp.get("messages"), "expected the seeded chem message on the live relay"
    assert all(verify_message(m) for m in resp["messages"])     # real sigs verify end-to-end
