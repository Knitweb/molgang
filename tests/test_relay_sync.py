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
    # terms are case-preserved (chemistry is case-significant: Co ≠ CO), so "NaCl"
    # is stored verbatim rather than case-folded to "nacl".
    assert "NaCl" in g["terms"] and any(l["subject"] == "Na" for l in g["links"])

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

    class FakeRelayHandle:
        def __init__(self, bases):
            self.bases = list(bases)     # _start_relay now receives the whole pool (#95)
            self.base = self.bases[0]
            self.signer = FakeSigner()

    def fake_start_relay(bar, bases, wallet, interval):
        captured["relay_bases"] = bases
        captured["relay_wallet"] = wallet
        captured["relay_interval"] = interval
        return FakeRelayHandle(bases)

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
        # repeatable + comma-list --relay flags flatten into ONE ordered pool (#95)
        "--relay", "https://5mart.ml/molgang/api/relay",
        "--relay", "https://relay-b.example/api,https://relay-c.example/api",
        "--relay-wallet", str(tmp_path / "server-node.cbor"),
        "--relay-interval", "7",
        "--monitor",
        "--monitor-nodes", "alice=59000",
    ])

    assert code == 0
    assert captured["addr"] == ("127.0.0.1", 0)
    assert captured["relay_bases"] == ["https://5mart.ml/molgang/api/relay",
                                       "https://relay-b.example/api",
                                       "https://relay-c.example/api"]
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


# -- concept sharding (#97): bound per-node memory + per-topic fetch volume ----
from molgang import chemistry
from molgang.shard import shard_of, item_shard, shard_topic, shard_topics


def test_shard_of_is_deterministic_and_casefold_stable():
    # same casefold key ⇒ same shard, regardless of case or repeated calls (no PYTHONHASHSEED)
    assert shard_of("NaCl", 8) == shard_of("nacl", 8) == shard_of("NACL", 8)
    assert shard_of("H2O", 8) == shard_of("H2O", 8)
    assert 0 <= shard_of("H2O", 8) < 8
    assert shard_of("anything", 1) == 0            # n<=1 collapses to one shard
    # a realistic vocab spreads across shards (not all in one bucket)
    buckets = {shard_of(f, 8) for f in chemistry.MOLECULES}
    assert len(buckets) >= 3
    # shard_topics: unsharded is the bare base; sharded is suffixed + subscribable
    assert shard_topics(WEB_TOPIC, 1) == [WEB_TOPIC]
    assert shard_topics(WEB_TOPIC, 4, subscribe=[0, 2]) == [
        shard_topic(WEB_TOPIC, 0), shard_topic(WEB_TOPIC, 2)]


def test_item_lands_only_on_its_shard_topic(tmp_path):
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener, shards=4)
    a.on_weave = ra.push
    a.weave_knit({"kind": "term", "term": "H2O"}, "alice", "f1", 3)
    expected = shard_topic(WEB_TOPIC, shard_of("H2O", 4))
    assert {m["topic"] for m in relay.messages} == {expected}   # only its shard topic
    assert relay._fetch("u?topic=" + WEB_TOPIC)["count"] == 0    # NOT on the base topic


def test_subscriber_only_receives_its_shards(tmp_path):
    relay = FakeRelay()
    a = _bar_world(tmp_path, "A")
    ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener, shards=4)
    a.on_weave = ra.push
    terms = list(chemistry.MOLECULES)[:16]
    for i, t in enumerate(terms):
        a.weave_knit({"kind": "term", "term": t}, "alice", f"f{i}", 2)
    # B holds only shard 0
    b = _bar_world(tmp_path, "B")
    rb = RelaySync("http://stub", b, host_signer("B"), opener=relay.opener, shards=4, subscribe=[0])
    rb.pull()
    got = set(b.graph()["terms"])
    shard0 = {t for t in terms if shard_of(t, 4) == 0}
    assert shard0, "expected at least one term to hash to shard 0"
    assert got == shard0                                   # exactly its shard, nothing else
    assert all(shard_of(t, 4) == 0 for t in got)           # never a foreign-shard item


def test_full_subscribe_converges_identically_to_unsharded(tmp_path):
    def run(shards):
        relay = FakeRelay()
        a = _bar_world(tmp_path, f"A{shards}")
        ra = RelaySync("http://stub", a, host_signer("A"), opener=relay.opener, shards=shards)
        a.on_weave = ra.push
        a.weave_knit({"kind": "term", "term": "H2O"}, "x", "f1", 3)
        a.weave_knit({"kind": "term", "term": "CO2"}, "x", "f2", 3)
        a.weave_links([{"subject": "Na", "object": "Cl", "relation": "bonds"}], "x", "f3", 4)
        b = _bar_world(tmp_path, f"B{shards}")
        rb = RelaySync("http://stub", b, host_signer("B"), opener=relay.opener, shards=shards)
        res = rb.pull()
        return a.state_root(), b.state_root(), res

    (a1, b1, _), (a4, b4, res4) = run(1), run(4)
    assert a1 == b1                     # unsharded converges (baseline)
    assert a4 == b4                     # full-subscribe sharded converges
    assert a1 == a4                     # sharded weaving yields the identical web
    assert res4["applied"] == 3 and res4["rejected"] == 0


# -- the relay POOL: fan-out push, union pull, failover (#95) -----------------
def test_pool_write_fans_out_and_b_only_reader_converges(tmp_path):
    """A pool write lands on EVERY relay, so a peer reading only relay B still converges."""
    from molgang.relay_sync import RelayPool

    relay_a, relay_b = FakeRelay(), FakeRelay()

    def pool_opener(url, data=None):
        return (relay_a if "://a/" in url else relay_b).opener(url, data)

    w = _bar_world(tmp_path, "W")
    pool = RelayPool(["http://a/relay", "http://b/relay"], w, host_signer("W"),
                     opener=pool_opener)
    w.on_weave = pool.push
    w.weave_knit({"kind": "link", "subject": "Na", "object": "Cl", "relation": "bonds"},
                 "alice", "f1", 4)

    # fan-out: the SAME signed message is stored on both relays
    assert relay_a._fetch("u?topic=" + WEB_TOPIC)["count"] == 1
    assert relay_b._fetch("u?topic=" + WEB_TOPIC)["count"] == 1

    # a single-relay peer bound ONLY to B converges on W's web
    b = _bar_world(tmp_path, "Bonly")
    rb = RelaySync("http://b/relay", b, host_signer("Bonly"), opener=relay_b.opener)
    res = rb.pull()
    assert res["applied"] == 1
    assert b.state_root() == w.state_root()


def test_pool_unions_without_double_count(tmp_path):
    """The same replicated message on two relays weaves ONCE — no double apply, no re-bump."""
    from molgang.relay_sync import RelayPool

    relay_a, relay_b = FakeRelay(), FakeRelay()
    msg = pack(WovenItem(kind="link", by="carol", fiber_cid="fc", confirmations=2,
                         subject="Na", object="Cl", relation="bonds"),
               host_signer("C"))
    relay_a._send(msg)
    relay_b._send(dict(msg))            # replicated verbatim (identical sig) onto relay B

    def pool_opener(url, data=None):
        return (relay_a if "://a/" in url else relay_b).opener(url, data)

    b = _bar_world(tmp_path, "reader")
    pool = RelayPool(["http://a/relay", "http://b/relay"], b, host_signer("R"),
                     opener=pool_opener)
    res = pool.pull()
    assert res["applied"] == 1 and res["bumped"] == 0    # once, not twice
    assert res["skipped"] == 1                           # B's identical copy sig-skipped
    assert len(b.items) == 1
    w = pool.syncs[0]._edge_weight(b._term_node("Na"), b._term_node("Cl"), "bonds")
    assert w == 2                                        # weight applied exactly once

    # a DIFFERENT co-weaving signer still bumps (that is a genuine second confirmation)
    other = pack(WovenItem(kind="link", by="dave", fiber_cid="fd", confirmations=1,
                           subject="Na", object="Cl", relation="bonds"),
                 host_signer("D"))
    relay_b._send(other)
    res2 = pool.pull()
    assert res2["bumped"] == 1 and res2["applied"] == 0


def test_pool_survives_a_dark_relay_with_cooldown_retry(tmp_path):
    """A dead base is health-marked and skipped, never fatal; after cooldown it is retried."""
    from molgang.relay_sync import RelayPool

    relay_a = FakeRelay()
    b_calls = []

    def pool_opener(url, data=None):
        if "://b/" in url:
            b_calls.append(url)
            raise OSError("relay B is dark")
        return relay_a.opener(url, data)

    now = [0.0]
    w = _bar_world(tmp_path, "W")
    pool = RelayPool(["http://a/relay", "http://b/relay"], w, host_signer("W"),
                     opener=pool_opener, cooldown=60.0, clock=lambda: now[0])
    w.on_weave = pool.push              # push through the pool MUST NOT raise into the weave

    w.weave_knit({"kind": "term", "term": "NaCl"}, "alice", "f1", 3)
    assert relay_a._fetch("u?topic=" + WEB_TOPIC)["count"] == 1     # A still got the knit
    assert pool.healthy("http://a/relay") and not pool.healthy("http://b/relay")

    # while B is in cooldown the pool does not touch it (no stall, no extra calls) …
    dark_calls = len(b_calls)
    stats = pool.pull()
    assert stats["errors"] == 0 and len(b_calls) == dark_calls

    # … and /api/relay-style status reports the pool truthfully
    st = {s["base"]: s for s in pool.status()}
    assert st["http://a/relay"]["healthy"] is True
    assert st["http://b/relay"]["healthy"] is False
    assert st["http://b/relay"]["failures"] >= 1

    # after the cooldown expires B is probed again (and marked down again on failure)
    now[0] = 61.0
    pool.pull()
    assert len(b_calls) > dark_calls
    assert not pool.healthy("http://b/relay")


# -- region-aware bootstrap discovery (#98) -----------------------------------
def test_discover_relays_ranks_and_falls_back(tmp_path):
    from molgang.relay_sync import RelayPool, discover_relays, expand_relay_bases

    roster = {"relays": [
        {"base": "https://relay-eu.example/api", "region": "eu-west", "load": 3, "age_s": 1.0},
        {"base": "https://relay-us.example/api", "region": "us-east", "load": 9, "age_s": 2.0},
        {"base": "https://relay-eu.example/api"},        # duplicate → dropped
        {"base": "ftp://bogus.example"},                  # non-http(s) → dropped
    ]}
    calls = []

    def boot_opener(url, data=None):
        calls.append(url)
        return roster

    # ranked roster comes back in registry order, deduped and scheme-filtered
    bases = discover_relays("https://seed.example/api/relay", opener=boot_opener)
    assert bases == ["https://relay-eu.example/api", "https://relay-us.example/api"]
    assert calls and calls[0].endswith("/bootstrap")

    # region preference is passed through to the registry
    discover_relays("https://seed.example/api/relay", opener=boot_opener, region="us-east")
    assert "region=us-east" in calls[-1]

    # unreachable registry → the configured rendezvous base itself (never zero relays)
    def dead_opener(url, data=None):
        raise OSError("registry down")
    assert discover_relays("https://seed.example/api/relay", opener=dead_opener) == \
        ["https://seed.example/api/relay"]

    # expand_relay_bases: plain entries pass through, bootstrap+ entries resolve, dedup'd
    expanded = expand_relay_bases(
        ["https://fixed.example/api", "bootstrap+https://seed.example/api/relay",
         "https://relay-eu.example/api"], opener=boot_opener)
    assert expanded == ["https://fixed.example/api", "https://relay-eu.example/api",
                        "https://relay-us.example/api"]

    # the discovered, ranked order seeds a RelayPool as-is (healthiest first)
    w = _bar_world(tmp_path, "boot")
    pool = RelayPool(bases, w, host_signer("boot"), opener=lambda u, d=None: {"messages": [],
                                                                              "cursor": 0})
    assert pool.bases == ["https://relay-eu.example/api", "https://relay-us.example/api"]


# -- the relay MESH: relay-to-relay reconcile, convergence + failover (#100) --
# The php side reconciles relays with GET /api/relay/reconcile (anti-entropy, #96). These
# tests prove the MESH property that reconcile buys: peers writing through DIFFERENT relays
# still converge, and losing a relay mid-run does not lose items. The reconcile helper below
# mirrors php/src/Relay.php::reconcile(): fetch the peer's log after a stored per-peer
# cursor, re-verify EVERY signature through the same gate as send(), skip known sigs.
def _reconcile(dst: FakeRelay, src: FakeRelay, cursors: dict) -> int:
    """One incremental anti-entropy pass dst←src; returns newly ingested messages."""
    key = (id(dst), id(src))
    got = src._fetch(f"u?topic={WEB_TOPIC}&since={cursors.get(key, 0.0)}")
    known = {m["sig"] for m in dst.messages}
    new = 0
    for m in got["messages"]:
        if m["sig"] in known:
            continue
        if not crypto.verify(m["from"], signed_preimage(m["to"] or "", m["topic"], m["body"]),
                             m["sig"]):
            continue                       # a forged message never propagates through the mesh
        dst._t += 1.0
        dst.messages.append({**m, "id": f"r{len(dst.messages)}", "created": dst._t})
        known.add(m["sig"])
        new += 1
    cursors[key] = got["cursor"]
    return new


def _reconcile_mesh(relays: list, cursors: dict, max_rounds: int = 5) -> tuple[int, int]:
    """Gossip every pair until a full round moves nothing. Returns (ingested, rounds)."""
    total = 0
    for rounds in range(1, max_rounds + 1):
        moved = sum(_reconcile(dst, src, cursors)
                    for dst in relays for src in relays if dst is not src)
        total += moved
        if moved == 0:
            return total, rounds
    return total, max_rounds


def _mesh_opener(relays: dict, dead: set):
    """Route http://<name>/relay to the named FakeRelay; a dead relay raises like a socket."""
    def opener(url, data=None):
        for name, r in relays.items():
            if f"://{name}/" in url:
                if name in dead:
                    raise OSError(f"relay {name} is dark")
                return r.opener(url, data)
        raise AssertionError(f"unroutable url {url}")
    return opener


def test_mesh_of_three_reconciling_relays_converges_all_readers(tmp_path):
    """M writers each pushing to a DIFFERENT relay converge every reader after reconcile."""
    relays = {"a": FakeRelay(), "b": FakeRelay(), "c": FakeRelay()}
    names = list(relays)
    writers, items = 6, 4
    for i in range(writers):                       # writer i is pinned to ONE relay only
        w = _bar_world(tmp_path, f"w{i}")
        sync = RelaySync(f"http://{names[i % 3]}/relay", w, host_signer(f"w{i}"),
                         opener=_mesh_opener(relays, set()))
        w.on_weave = sync.push
        for k in range(items):
            w.weave_knit({"kind": "term", "term": f"W{i}K{k}"}, f"peer{i}", f"f{i}.{k}", 2)

    # before reconcile each relay only holds its own writers' items
    assert all(len(r.messages) == writers // 3 * items for r in relays.values())
    ingested, rounds = _reconcile_mesh(list(relays.values()), {})
    assert ingested == 2 * writers * items         # every item reached the 2 OTHER relays
    assert all(len(r.messages) == writers * items for r in relays.values())

    # a reader bound to ANY single relay now sees the identical web
    roots = set()
    for n in names:
        rd = _bar_world(tmp_path, f"rd{n}")
        res = RelaySync(f"http://{n}/relay", rd, host_signer(f"rd{n}"),
                        opener=_mesh_opener(relays, set())).pull(limit=10_000)
        assert res["applied"] == writers * items and res["rejected"] == 0
        roots.add(rd.state_root())
    assert len(roots) == 1                         # deterministic convergence, one state root


def test_mesh_forged_message_never_propagates(tmp_path):
    """A relay polluted with a forged message reconciles it to NOBODY (the send gate holds)."""
    relays = {"a": FakeRelay(), "b": FakeRelay()}
    w = _bar_world(tmp_path, "w")
    sync = RelaySync("http://a/relay", w, host_signer("w"), opener=_mesh_opener(relays, set()))
    w.on_weave = sync.push
    w.weave_knit({"kind": "term", "term": "H2O"}, "peer", "f1", 2)
    good = dict(relays["a"].messages[0])
    relays["a"].messages.append({**good, "id": "forged", "body": good["body"] + "X",
                                 "created": relays["a"]._t + 1})
    relays["a"]._t += 1
    ingested, _ = _reconcile_mesh(list(relays.values()), {})
    assert ingested == 1                           # only the genuine message crossed
    assert [m["body"] for m in relays["b"].messages] == [good["body"]]


def test_mesh_failover_one_relay_dies_midrun_and_nothing_is_lost(tmp_path):
    """Writers on a 3-relay POOL keep converging when one relay dies halfway through."""
    from molgang.relay_sync import RelayPool

    relays = {"a": FakeRelay(), "b": FakeRelay(), "c": FakeRelay()}
    dead: set = set()
    now = [0.0]
    writers = []
    for i in range(4):
        w = _bar_world(tmp_path, f"w{i}")
        pool = RelayPool([f"http://{n}/relay" for n in relays], w, host_signer(f"w{i}"),
                         opener=_mesh_opener(relays, dead), cooldown=300.0,
                         clock=lambda: now[0])
        w.on_weave = pool.push
        writers.append((w, pool))
    for i, (w, _) in enumerate(writers):           # first half of the run: all relays up
        w.weave_knit({"kind": "term", "term": f"PRE{i}"}, f"p{i}", f"pre{i}", 2)

    dead.add("c")                                  # ☠ relay C dies mid-run
    for i, (w, _) in enumerate(writers):           # second half: writes keep flowing
        w.weave_knit({"kind": "term", "term": f"POST{i}"}, f"p{i}", f"post{i}", 2)
    assert all(not p.healthy("http://c/relay") for _, p in writers)
    assert len(relays["a"].messages) == len(relays["b"].messages) == 8

    # anti-entropy among the SURVIVORS: fan-out re-signs per relay (distinct ECDSA sigs for
    # the same item), so reconcile carries the copies across — and the READER's item-key
    # dedup is what keeps the web single-counted, exactly the deployed pipeline.
    ingested, _ = _reconcile_mesh([relays["a"], relays["b"]], {})
    assert ingested == 2 * 8                       # each survivor ingests the other's copies
    roots = set()
    for n in ("a", "b"):
        rd = _bar_world(tmp_path, f"rd{n}")
        res = RelaySync(f"http://{n}/relay", rd, host_signer(f"rd{n}"),
                        opener=_mesh_opener(relays, dead)).pull(limit=10_000)
        assert res["applied"] == 8                 # all 4 PRE + all 4 POST items, once each
        assert len(rd.items) == 8                  # never double-applied via the copies
        roots.add(rd.state_root())
    assert len(roots) == 1


def test_mesh_bounded_scale_reports_convergence_time_and_counts(tmp_path):
    """Bounded scale proof for CI: N single-relay writers × K items over a 3-relay
    reconciling mesh converge every reader; prints the measured numbers so the CI log
    carries a trend line (road-to-1M measurement, docs/MEASUREMENT.md)."""
    import time as _time

    relays = {"a": FakeRelay(), "b": FakeRelay(), "c": FakeRelay()}
    names = list(relays)
    n_writers, k_items = 24, 25                    # 600 signed writes — bounded for CI
    t0 = _time.perf_counter()
    for i in range(n_writers):
        w = _bar_world(tmp_path, f"s{i}")
        sync = RelaySync(f"http://{names[i % 3]}/relay", w, host_signer(f"s{i}"),
                         opener=_mesh_opener(relays, set()))
        w.on_weave = sync.push
        for k in range(k_items):
            w.weave_knit({"kind": "term", "term": f"S{i}K{k}"}, f"s{i}", f"sf{i}.{k}", 2)
    t_write = _time.perf_counter() - t0

    t0 = _time.perf_counter()
    ingested, rounds = _reconcile_mesh(list(relays.values()), {})
    t_rec = _time.perf_counter() - t0
    total = n_writers * k_items
    assert ingested == 2 * total and rounds <= 2   # one full gossip round suffices

    t0 = _time.perf_counter()
    reader = _bar_world(tmp_path, "scale-reader")
    res = RelaySync("http://a/relay", reader, host_signer("scale-reader"),
                    opener=_mesh_opener(relays, set())).pull(limit=10_000)
    t_read = _time.perf_counter() - t0
    assert res["applied"] == total and res["rejected"] == 0
    assert len(reader.graph()["terms"]) >= total   # every item is IN the woven web
    print(f"\nMESH SCALE: {n_writers} writers x {k_items} items = {total} messages | "
          f"write {t_write:.2f}s, reconcile {t_rec:.2f}s ({ingested} ingested, "
          f"{rounds} rounds), reader-converge {t_read:.2f}s")
    assert t_write + t_rec + t_read < 120          # regression guard, generous CI bound
