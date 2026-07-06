"""The pure-P2P dapp actually plays — end-to-end through the JS<->Python boundary.

Drives WebNodeRuntime with the exact contract messages the browser shell sends
(hello -> rpc), with NO server, NO sockets, NO browser: proof that a single tab
boots, weaves peer-confirmed chemistry (bots seed a table so a solo player
reaches quorum), and that the recent engine work (reactions, level-silk, story
tracks) is inherited unchanged by the serverless path.
"""
import asyncio

import pytest

from molgang.webnode.contract import CONTRACT_VERSION, make_hello
from molgang.webnode.runtime import WebNodeRuntime


def _seams(i):
    return {"now": 1000 + i, "id_proof_now": 500 + i, "nonce_hex": f"{i:032x}"}


class _Driver:
    """Collects posted messages and issues contract-framed RPCs like the shell."""

    def __init__(self):
        self.out = []
        self.rt = WebNodeRuntime(post=self.out.append)
        self._i = 0

    def hello(self, seed="device-seed"):
        self.rt.on_hello(make_hello(seed=seed, seams=_seams(0)))
        ready = [m for m in self.out if m.get("type") == "ready"]
        assert ready, [m for m in self.out if m.get("type") == "error"]
        return ready[-1]

    async def rpc(self, method, **args):
        self._i += 1
        rid = self._i
        await self.rt.handle({"type": "rpc", "id": rid, "method": method,
                              "args": args, "seams": _seams(rid)})
        res = [m for m in self.out if m.get("id") == rid]
        assert res, f"no result for {method}"
        m = res[-1]
        if m.get("type") == "error":
            raise AssertionError(f"{method} failed: {m.get('message')}")
        return m["payload"]


def _run(coro):
    return asyncio.run(coro)


def test_hello_derives_identity_without_a_server():
    d = _Driver()
    ready = d.hello()
    assert ready["contract"] == CONTRACT_VERSION
    assert ready["identity"]["address"].startswith("pls1")


def test_solo_tab_weaves_peer_confirmed_chemistry():
    async def scenario():
        d = _Driver()
        d.hello()
        state = await d.rpc("state")
        table = state["tables"][0]
        assert len(table["seated"]) >= 3          # bots seed the table -> quorum reachable
        me = await d.rpc("join", name="Edwin", avatar="laser-maxi", table=table["id"])
        sid = me["sid"]
        await d.rpc("sit", sid=sid, table=table["id"])
        knit = await d.rpc("propose", sid=sid, term="H2O")
        assert knit["woven"] and knit["outcome"] == "confirmed"   # woven with NO server
        you = (await d.rpc("state", sid=sid))["you"]
        assert you["level"] >= 2                  # weaving advanced the level (level-silk path)

    _run(scenario())


def test_serverless_path_inherits_reactions_and_tracks():
    async def scenario():
        d = _Driver()
        d.hello()
        table = (await d.rpc("state"))["tables"][0]
        sid = (await d.rpc("join", name="Roaster", table=table["id"]))["sid"]
        await d.rpc("sit", sid=sid, table=table["id"])
        # a balanced reaction knit (my #109 work) weaves through the boundary
        rxn = await d.rpc("propose", sid=sid, term="V2O3 + O2 -> V2O5 @ 850C roast")
        assert rxn["woven"]
        # an unbalanced one is rejected by the honest bots
        bad = await d.rpc("propose", sid=sid, term="H2 + O2 -> H2O @ spark")
        assert not bad["woven"]

    _run(scenario())


def test_certificate_and_web_view_over_the_boundary():
    async def scenario():
        d = _Driver()
        d.hello()
        table = (await d.rpc("state"))["tables"][0]
        sid = (await d.rpc("join", name="Cert", table=table["id"]))["sid"]
        await d.rpc("sit", sid=sid, table=table["id"])
        await d.rpc("propose", sid=sid, term="H2O")
        cert = await d.rpc("certificate", sid=sid)
        assert cert["address"].startswith("pls1")
        assert "pls_balance" in cert              # my #224 balance field, serverless too
        web = await d.rpc("web")
        assert web["nodes"] >= 1                  # the woven fabric is queryable in-tab

    _run(scenario())


def test_contract_mismatch_fails_closed():
    d = _Driver()
    d.rt.on_hello({"type": "hello", "contract": "wrong-version", "seed": "x"})
    errs = [m for m in d.out if m.get("code") == "contract_mismatch"]
    assert errs and not [m for m in d.out if m.get("type") == "ready"]
