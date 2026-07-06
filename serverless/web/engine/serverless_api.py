# MOLGANG serverless in-tab API bridge.
#
# This file is fetched by the engine worker (see peer.js) and executed inside
# Pyodide AFTER the engine wheel (molgang + knitweb, the UNCHANGED .py bytes)
# has been installed. It replaces the HTTP layer of molgang/webserver.py with a
# pure in-process dispatch over one Bar, so the classic render layer (app.js)
# keeps calling the SAME /api/* routes with the SAME request/response shapes —
# only the transport changed (postMessage RPC instead of HTTP).
#
# Sacred-invariant discipline: nothing here computes CBOR/CID/signature/faucet
# values itself — every route delegates to the unchanged molgang/knitweb code.
# The only crypto this file touches is the wallet-signed QR onboarding payload,
# and that goes through knitweb.core.crypto.sign/verify verbatim.

import json
from urllib.parse import parse_qs, urlparse

from knitweb.core import crypto
from knitweb.ledger.node import AccountNode
from molgang.bar import Bar, suggested_terms

# Domain-tagged pre-image for the wallet-signed onboarding QR. The signature is
# over this exact byte string; a scanner MUST re-verify before opening a channel.
ONBOARD_DOMAIN = b"molgang:serverless:onboard:v1:"


def _onboard_preimage(payload: dict) -> bytes:
    core = {k: payload[k] for k in ("v", "pubkey", "address", "multiaddr")}
    return ONBOARD_DOMAIN + json.dumps(
        core, sort_keys=True, separators=(",", ":")).encode()


def signed_onboarding(node: AccountNode, multiaddr: str = "webrtc:self") -> dict:
    payload = {"v": 1, "pubkey": node.pub, "address": node.address,
               "multiaddr": multiaddr}
    payload["sig"] = crypto.sign(node.priv, _onboard_preimage(payload))
    payload["fingerprint"] = crypto.sha256_hex(node.pub.encode())[:16]
    return payload


def verify_onboarding(payload: dict) -> dict:
    try:
        pub = str(payload["pubkey"])
        sig = str(payload["sig"])
        ok = crypto.verify(pub, _onboard_preimage(payload), sig)
    except (KeyError, TypeError, ValueError):
        return {"ok": False}
    if not ok:
        return {"ok": False}
    return {"ok": True, "pubkey": pub,
            "multiaddr": payload.get("multiaddr", ""),
            "fingerprint": crypto.sha256_hex(pub.encode())[:16]}


class ServerlessBridge:
    """One in-tab peer: a real Bar + the device wallet, no HTTP anywhere."""

    def __init__(self, seed: str):
        self.seed = seed
        self.node = AccountNode.from_seed(seed)
        self.bar = Bar(world_path=None)
        self.peers: dict[str, str] = {}   # peerId -> verified pubkey

    # ---- wallet-signed QR onboarding (verify-before-connect) --------------
    def onboarding(self) -> str:
        return json.dumps(signed_onboarding(self.node))

    def verify(self, payload_json: str) -> str:
        try:
            payload = json.loads(payload_json)
        except ValueError:
            return json.dumps({"ok": False})
        return json.dumps(verify_onboarding(payload))

    # ---- WebRTC transport hooks (opaque frames only) -----------------------
    # The in-worker frame transport is not wired yet in this build; peers are
    # tracked so the mesh bookkeeping in peer.js never faults, and inbound
    # frames are acknowledged without being interpreted (never parsed in JS
    # either). Weaving stays local-first until the transport lands.
    def add_peer(self, peer_id: str, pubkey: str) -> None:
        self.peers[str(peer_id)] = str(pubkey)

    def drop_peer(self, peer_id: str) -> None:
        self.peers.pop(str(peer_id), None)

    def inbound_frame(self, peer_id: str, frame) -> None:
        return None

    # ---- the legacy /api/* surface, in-process -----------------------------
    def api(self, path: str, method: str = "GET", body_json: str | None = None) -> str:
        """Dispatch one legacy route. Returns json.dumps({status, body})."""
        try:
            status, out = self._dispatch(str(path), str(method or "GET").upper(),
                                         json.loads(body_json) if body_json else {})
        except (KeyError, RuntimeError, ValueError) as e:  # same contract as webserver.py
            status, out = 400, {"error": str(e)}
        return json.dumps({"status": status, "body": out})

    def _dispatch(self, path_q: str, method: str, b: dict):
        u = urlparse(path_q)
        path, q = u.path, parse_qs(u.query)
        bar = self.bar

        if method == "GET":
            if path == "/api/state":
                state = bar.state((q.get("sid") or [None])[0])
                state["pulse_host"] = {
                    "account": {"address": self.node.address,
                                "balance_pls": self.node.balance()},
                    "wallet": "in-tab device wallet (seed-derived)",
                }
                return 200, state
            if path == "/api/version":
                return 200, {"api_version": "1", "engine": "serverless-in-tab"}
            if path == "/api/certificates":
                return 200, {"certificates": []}
            if path == "/api/suggested":
                return 200, {"terms": suggested_terms()}
            if path == "/api/web":
                return 200, bar.web_view()
            if path == "/api/quests":
                from molgang import quests
                player = (q.get("player") or [None])[0]
                return 200, {
                    "player": player,
                    "active": quests.active_quests(bar.woven, player),
                    "all": quests.quest_progress(bar.woven, player),
                    "quest_xp": quests.quest_xp(bar.woven, player),
                }
            if path == "/api/achievements":
                from molgang import achievements
                player = (q.get("player") or [None])[0]
                return 200, {
                    "player": player,
                    "achievements": achievements.evaluate(bar.woven, [], player),
                    "unlocked": achievements.unlocked_achievements(bar.woven, [], player),
                    "count": achievements.achievement_count(bar.woven, [], player),
                }
            if path == "/api/leaderboard":
                import time
                from molgang import progression
                season = (q.get("season") or ["all"])[0]
                rows_src = [{"formula": w.get("term"), "by": w.get("by"),
                             "anchor_ts": w.get("anchor_ts")}
                            for w in bar.woven if w.get("is_chemistry")]
                if season in ("current", "season"):
                    return 200, progression.current_season_leaderboard(
                        rows_src, int(time.time()))
                return 200, {"season": "all", "rows": progression.leaderboard(rows_src)}
            if path == "/api/graph":
                try:
                    return 200, bar.world.explore(
                        term=(q.get("term") or [None])[0],
                        frm=(q.get("from") or [None])[0],
                        to=(q.get("to") or [None])[0])
                except ModuleNotFoundError:
                    # networkx not installed in this tab (offline first boot):
                    # empty-but-well-shaped so the Web tab renders gracefully.
                    return 200, {"stats": {}, "hubs": []}
            if path == "/api/monitor/simulate":
                try:
                    from molgang.monitor import _simulate_p2p
                except ModuleNotFoundError:
                    return 503, {"error": "simulation needs networkx (not installed in-tab)"}
                try:
                    n = int((q.get("n") or ["6"])[0])
                except ValueError:
                    n = 6
                return 200, _simulate_p2p(n)
            if path.startswith("/api/monitor"):
                return 503, {"error": "monitor unavailable"}
            return 404, {"error": "not found"}

        if method == "POST":
            if path == "/api/join":
                s = bar.join(b.get("name", "guest"), b.get("avatar"), b.get("table"),
                             device=b.get("device"))
                return 200, {"sid": s.sid, "avatar": s.avatar,
                             "address": s.player.node.address}
            if path == "/api/heartbeat":
                return 200, bar.touch(b["sid"])
            if path == "/api/leave":
                bar.leave(b["sid"])
                return 200, {"ok": True}
            if path == "/api/stand":
                bar.stand(b["sid"])
                return 200, bar.state(b["sid"])
            if path == "/api/sit":
                bar.sit(b["sid"], b["table"])
                return 200, bar.state(b["sid"])
            if path == "/api/table/rename":
                bar.rename_table(b["sid"], b["table"], b.get("name", ""))
                return 200, bar.state(b["sid"])
            if path == "/api/propose":
                p = bar.propose(b["sid"], b["term"])
                return 200, {"pid": p.pid}
            if path == "/api/vote":
                p = bar.vote(b["sid"], b["pid"], b.get("verdict", "confirm"))
                return 200, {"pid": p.pid, "settled": p.settled,
                             "outcome": p.outcome, "woven": p.woven}
            if path == "/api/spiral/propose":
                links = b.get("links") or [x for x in (b.get("text", "")).splitlines()
                                           if x.strip()]
                sv = bar.propose_spiral(b["sid"], links)
                return 200, {"cid": sv.cid, "length": sv.length,
                             "state": sv.round.state}
            if path == "/api/spiral/vote":
                sv = bar.vote_spiral(b["sid"], b["cid"], b.get("verdict", "confirm"))
                return 200, {"cid": sv.cid, "settled": sv.settled,
                             "captured": sv.captured, "votes": sv.breakdown()}
            if path == "/api/certificate":
                # PDF generation needs fpdf, which is not shipped in the in-tab
                # wheel; the caller shows this message as a toast.
                return 501, {"error": "PoUW certificate export is not available "
                                      "in the in-tab build yet — use `molgang "
                                      "serve` for PDF export."}
            if path in ("/peer/offer", "/peer/answer"):
                # No relay carrier in this build; the QR flow works device-to-
                # device. peer.js already treats this as best-effort.
                return 200, {"ok": False, "relayed": False}
            return 404, {"error": "not found"}

        return 405, {"error": "method not allowed"}


def make_bridge(seed: str) -> ServerlessBridge:
    return ServerlessBridge(str(seed))
