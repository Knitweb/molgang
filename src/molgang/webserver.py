"""MOLGANG browser bar — a stdlib HTTP server.

Serves the bar UI (the `web/` folder) AND a small JSON API over one live `Bar`. The SAME
endpoints are used by humans (the browser) and machines (bots/agents) — dual play:

    GET  /api/version                 {api_version, engine, molgang, knitweb} — contract drift check (#58)
    GET  /api/state?sid=…              full bar snapshot (tables, seats, avatars, open knits)
    POST /api/join     {name,avatar,table?}   walk in (free silk + pulses), optionally sit
    POST /api/sit      {sid,table}            take a seat at a table
    POST /api/table/rename {sid,table,name}    rename a table you currently sit at
    POST /api/propose  {sid,term}             brainstorm + knit a term (spends silk)
    POST /api/vote     {sid,pid,verdict}      vote with a pulse ('confirm'|'mismatch'|'abstain')
    POST /api/certificate {sid}                download a public PoUW Certificate PDF
                                              (always redacted; bearer export is CLI/local only)

    molgang serve --port 8765
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from typing import Callable

from .bar import Bar, DEFAULT_FAUCET_SOURCE_CAP, suggested_terms
from .monitor import _simulate_p2p
from .pulse_host import bootstrap_host, default_wallet_path

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web")
_CTYPE = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
          ".json": "application/json", ".svg": "image/svg+xml"}

# Frozen /api contract version (Sprint 3 #58, see docs/API.md). Bump only on a breaking change.
API_VERSION = "1"
_COSTLY_POST_ROUTES = {
    "/api/propose",
    "/api/vote",
    "/api/spiral/propose",
    "/api/spiral/vote",
    "/api/relay/pull",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_s: float


@dataclass(frozen=True)
class RateLimitConfig:
    read: RateLimitRule
    write: RateLimitRule
    costly: RateLimitRule
    certificate: RateLimitRule

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        return cls(
            read=RateLimitRule(
                _env_int("MOLGANG_RATE_READ", 240),
                _env_float("MOLGANG_RATE_READ_WINDOW", 60.0),
            ),
            write=RateLimitRule(
                _env_int("MOLGANG_RATE_WRITE", 60),
                _env_float("MOLGANG_RATE_WRITE_WINDOW", 60.0),
            ),
            costly=RateLimitRule(
                _env_int("MOLGANG_RATE_COSTLY", 20),
                _env_float("MOLGANG_RATE_COSTLY_WINDOW", 60.0),
            ),
            certificate=RateLimitRule(
                _env_int("MOLGANG_RATE_CERTIFICATE", 10),
                _env_float("MOLGANG_RATE_CERTIFICATE_WINDOW", 300.0),
            ),
        )

    def rule_for(self, method: str, path: str) -> RateLimitRule:
        if method == "GET":
            return self.read
        if path == "/api/certificate":
            return self.certificate
        if path in _COSTLY_POST_ROUTES:
            return self.costly
        return self.write


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter:
    """Small token-bucket limiter shared by all handler instances."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        import time

        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float, int, float]] = {}
        self._ops = 0

    def check(self, rule: RateLimitRule, keys: list[str]) -> RateLimitDecision:
        limit = int(rule.limit)
        window_s = float(rule.window_s)
        if limit <= 0 or window_s <= 0:
            return RateLimitDecision(True)
        uniq = list(dict.fromkeys(k for k in keys if k))
        if not uniq:
            return RateLimitDecision(True)
        now = self._clock()
        refill_per_s = limit / window_s
        with self._lock:
            refilled = []
            retry_after = 0.0
            for key in uniq:
                tokens, updated, old_limit, old_window = self._buckets.get(
                    key, (float(limit), now, limit, window_s))
                if old_limit != limit or old_window != window_s:
                    tokens = min(tokens, float(limit))
                    updated = now
                else:
                    tokens = min(float(limit), tokens + max(0.0, now - updated) * refill_per_s)
                refilled.append((key, tokens))
                if tokens < 1.0:
                    retry_after = max(retry_after, (1.0 - tokens) / refill_per_s)
            if retry_after > 0:
                for key, tokens in refilled:
                    self._buckets[key] = (tokens, now, limit, window_s)
                return RateLimitDecision(False, max(1, math.ceil(retry_after)))
            for key, tokens in refilled:
                self._buckets[key] = (tokens - 1.0, now, limit, window_s)
            self._ops += 1
            if self._ops % 256 == 0 and len(self._buckets) > 4096:
                self._sweep(now)
            return RateLimitDecision(True)

    def _sweep(self, now: float) -> None:
        stale = [
            key for key, (tokens, updated, limit, window_s) in self._buckets.items()
            if tokens >= limit and now - updated > window_s
        ]
        for key in stale:
            self._buckets.pop(key, None)


def _trust_forwarded_for(client_host: str) -> bool:
    try:
        addr = ip_address(client_host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def api_version_info() -> dict:
    """Identity of this engine + the /api contract version, so clients can detect drift."""
    from . import __version__ as molgang_version
    try:
        import knitweb
        knitweb_version = getattr(knitweb, "__version__", "unknown")
    except Exception:
        knitweb_version = "unavailable"
    return {"api_version": API_VERSION, "engine": "python",
            "molgang": molgang_version, "knitweb": knitweb_version}


def make_handler(bar: Bar, pulse_host: dict | None = None, cors: str | None = "*",
                 monitor=None, relay=None, rate_limiter: RateLimiter | None = None,
                 rate_config: RateLimitConfig | None = None):
    limiter = rate_limiter or RateLimiter()
    limits = rate_config or RateLimitConfig.from_env()

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            # Let the static UI (e.g. https://5mart.ml/molgang/) hit this API cross-origin.
            if cors:
                self.send_header("Access-Control-Allow-Origin", cors)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Expose-Headers", "Retry-After")
                self.send_header("Access-Control-Max-Age", "86400")

        def _json(self, code: int, obj, headers: dict[str, str] | None = None) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _pdf(self, body: bytes, filename: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _join_source(self) -> str:
            client = str((self.client_address or ("unknown",))[0] or "unknown")
            forwarded = (self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
            if forwarded and _trust_forwarded_for(client):
                return forwarded
            return client

        def _rate_identity(self, body: dict | None = None) -> str | None:
            if body:
                actor = body.get("sid") or body.get("device")
                if actor:
                    return str(actor)
            if "?" in self.path:
                from urllib.parse import parse_qs, urlparse
                sid = (parse_qs(urlparse(self.path).query).get("sid") or [None])[0]
                if sid:
                    return str(sid)
            return None

        def _rate_limit(self, method: str, path: str, body: dict | None = None) -> bool:
            source = self._join_source()
            actor = self._rate_identity(body)
            keys = [f"{method}:{path}:source:{source}"]
            if actor:
                keys.append(f"{method}:{path}:actor:{source}:{actor}")
            decision = limiter.check(limits.rule_for(method, path), keys)
            if decision.allowed:
                return True
            self._json(
                429,
                {"error": f"too many actions; try again in {decision.retry_after_s}s",
                 "retry_after": decision.retry_after_s},
                headers={"Retry-After": str(decision.retry_after_s)},
            )
            return False

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(WEB_DIR) or not os.path.isfile(full):
                return self._json(404, {"error": "not found"})
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", _CTYPE.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path.startswith("/api/") and not self._rate_limit("GET", path):
                return
            if path == "/api/state":
                from urllib.parse import parse_qs, urlparse
                sid = parse_qs(urlparse(self.path).query).get("sid", [None])[0]
                state = bar.state(sid)
                state["pulse_host"] = pulse_host
                return self._json(200, state)
            if path == "/api/version":
                return self._json(200, api_version_info())
            if path == "/api/pulse":
                return self._json(200, pulse_host or {})
            if path == "/api/suggested":
                return self._json(200, {"terms": suggested_terms()})
            if path == "/api/web":
                return self._json(200, bar.web_view())
            if path == "/api/quests":
                # Tier-graded goals derived from a player's woven molecules (#110). Read-only;
                # ?player=<name> scopes to one peer (omit for the whole bar). Pure derived state.
                from urllib.parse import parse_qs, urlparse
                from . import quests
                player = (parse_qs(urlparse(self.path).query).get("player") or [None])[0]
                return self._json(200, {
                    "player": player,
                    "active": quests.active_quests(bar.woven, player),
                    "all": quests.quest_progress(bar.woven, player),
                    "quest_xp": quests.quest_xp(bar.woven, player),
                })
            if path == "/api/achievements":
                # Milestone badges derived from woven molecules (#111). Read-only/pure; reputation
                # only (no tokens). ?player=<name> scopes to one peer. Vote-based badges stay locked
                # until the bar records per-voter honesty (woven-based badges work today).
                from urllib.parse import parse_qs, urlparse
                from . import achievements
                player = (parse_qs(urlparse(self.path).query).get("player") or [None])[0]
                return self._json(200, {
                    "player": player,
                    "achievements": achievements.evaluate(bar.woven, [], player),
                    "unlocked": achievements.unlocked_achievements(bar.woven, [], player),
                    "count": achievements.achievement_count(bar.woven, [], player),
                })
            if path == "/api/leaderboard":
                # All-time or current-season ranking (#112). ?season=current for the time-windowed
                # board, else all-time. Pure derived state — seasons are a view over woven timestamps.
                import time
                from urllib.parse import parse_qs, urlparse
                from . import progression
                season = (parse_qs(urlparse(self.path).query).get("season") or ["all"])[0]
                rows_src = [{"formula": w.get("term"), "by": w.get("by"),
                             "anchor_ts": w.get("anchor_ts")}
                            for w in bar.woven if w.get("is_chemistry")]
                if season in ("current", "season"):
                    return self._json(200, progression.current_season_leaderboard(rows_src, int(time.time())))
                return self._json(200, {"season": "all", "rows": progression.leaderboard(rows_src)})
            if path == "/api/device":
                from urllib.parse import parse_qs, urlparse
                did = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
                reg = bar.registry.get(did) if (bar.registry and did) else None
                return self._json(200, {"registered": bool(reg), "wallet": reg})
            if path == "/api/graph":
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                return self._json(200, bar.world.explore(
                    term=(q.get("term") or [None])[0],
                    frm=(q.get("from") or [None])[0],
                    to=(q.get("to") or [None])[0]))
            if path.startswith("/api/monitor"):
                return self._monitor(path)
            if path == "/api/relay":
                if relay is None:
                    return self._json(200, {"enabled": False})
                return self._json(200, {"enabled": True, "base": relay.base,
                                        "topic": relay.topic, "node": relay.signer.pub,
                                        "address": relay.signer.address, "cursor": relay.cursor})
            return self._static(path)

        # -- 📡 Monitor: node/p2p status + the local woven knitweb (#59 #60) ----
        def _monitor(self, path: str) -> None:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            # Simulation endpoint works even when monitor is None.
            if path == "/api/monitor/simulate":
                n = int((q.get("n") or ["6"])[0])
                return self._json(200, _simulate_p2p(n))
            if monitor is None:
                return self._json(503, {"error": "monitor unavailable"})
            if path == "/api/monitor":                      # one compact poll for the tab
                return self._json(200, monitor.overview())
            if path == "/api/monitor/status":               # node/p2p liveness + provenance
                return self._json(200, monitor.node_status())
            if path == "/api/monitor/kg/stats":             # nodes/edges/concepts/languages
                return self._json(200, monitor.kg_stats())
            if path == "/api/monitor/kg/hubs":
                n = int((q.get("n") or ["12"])[0])
                return self._json(200, monitor.kg_hubs(n))
            if path == "/api/monitor/kg/tension":           # taut/slack/snapped bands
                return self._json(200, monitor.kg_tension())
            if path == "/api/monitor/kg/subgraph":          # focused graph for the viz
                term = (q.get("term") or [""])[0]
                depth = int((q.get("depth") or ["2"])[0])
                langs = q.get("lang")
                sg = monitor.kg_subgraph(term, depth, set(langs) if langs else None)
                if sg is None:
                    return self._json(404, {"error": f"term not in graph: {term!r}"})
                return self._json(200, sg)
            if path == "/api/monitor/kg/concept":
                key = (q.get("key") or [""])[0]
                c = monitor.kg_concept(key)
                if c is None:
                    return self._json(404, {"error": f"concept not in graph: {key!r}"})
                return self._json(200, c)
            return self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                b = self._body()
                path = self.path.split("?")[0]
                if not self._rate_limit("POST", path, b):
                    return
                if path == "/api/join":
                    s = bar.join(b.get("name", "guest"), b.get("avatar"), b.get("table"),
                                 device=b.get("device"), source=self._join_source())
                    return self._json(200, {"sid": s.sid, "avatar": s.avatar,
                                            "address": s.player.node.address})
                if path == "/api/heartbeat":
                    return self._json(200, bar.touch(b["sid"]))
                if path == "/api/leave":
                    bar.leave(b["sid"])
                    return self._json(200, {"ok": True})
                if path == "/api/stand":
                    bar.stand(b["sid"])
                    return self._json(200, bar.state(b["sid"]))
                if path == "/api/sit":
                    bar.sit(b["sid"], b["table"]); return self._json(200, bar.state(b["sid"]))
                if path == "/api/table/rename":
                    bar.rename_table(b["sid"], b["table"], b.get("name", ""))
                    return self._json(200, bar.state(b["sid"]))
                if path == "/api/propose":
                    p = bar.propose(b["sid"], b["term"]); return self._json(200, {"pid": p.pid})
                if path == "/api/vote":
                    p = bar.vote(b["sid"], b["pid"], b.get("verdict", "confirm"))
                    return self._json(200, {"pid": p.pid, "settled": p.settled,
                                            "outcome": p.outcome, "woven": p.woven})
                if path == "/api/spiral/propose":
                    links = b.get("links") or [x for x in (b.get("text", "")).splitlines() if x.strip()]
                    sv = bar.propose_spiral(b["sid"], links)
                    return self._json(200, {"cid": sv.cid, "length": sv.length,
                                            "state": sv.round.state})
                if path == "/api/spiral/vote":
                    sv = bar.vote_spiral(b["sid"], b["cid"], b.get("verdict", "confirm"))
                    return self._json(200, {"cid": sv.cid, "settled": sv.settled,
                                            "captured": sv.captured, "votes": sv.breakdown()})
                if path == "/api/relay/pull":
                    # on-demand drain of the shared web from the relay (knitweb/molgang#44)
                    if relay is None:
                        return self._json(400, {"error": "relay not enabled (start with --relay URL)"})
                    return self._json(200, relay.pull())
                if path == "/api/certificate":
                    import tempfile

                    from .certificate import make_pouw_certificate
                    d = bar.certificate_data(b["sid"])
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                        out = fh.name
                    make_pouw_certificate(
                        address=d["address"], public_key=d["public_key"],
                        private_key="", include_private_key=False,
                        pulses_used=d["pulses_used"],
                        work_summary=d["work_summary"], provenance=d["provenance"],
                        holder=d["holder"], out_path=out)
                    with open(out, "rb") as fh:
                        body = fh.read()
                    os.unlink(out)
                    short = (d["address"] or "wallet")[:12]
                    return self._pdf(body, f"pouw-certificate-{short}.pdf")
                return self._json(404, {"error": "not found"})
            except (KeyError, RuntimeError, ValueError) as e:
                return self._json(400, {"error": str(e)})

        def log_message(self, *args) -> None:
            pass

    return Handler


def _start_relay(bar: Bar, base: str, wallet: str | None, interval: float):
    """Wire relay-sync onto the bar's shared World (knitweb/molgang#44).

    * a stable node identity (derived from the pulse-host wallet) signs every push;
    * each newly-woven knit/spiral is PUSHED to the relay via ``world.on_weave``;
    * an initial pull converges this fresh install on the shared web, then a daemon
      timer keeps pulling so writes from other installs land here too.
    """
    import threading

    from .relay_sync import RelaySync, signer_from_wallet

    signer = signer_from_wallet(wallet)
    relay = RelaySync(base, bar.world, signer)
    bar.world.on_weave = relay.push          # PUSH every confirmed knit/spiral as it is woven
    try:
        relay.pull()                         # converge on the existing shared web at startup
    except Exception as e:
        # A relay outage must not block the local bar from opening.
        print(f"  ⚠ relay initial pull failed (continuing local): {e}")

    def _loop() -> None:
        import time
        while True:
            time.sleep(max(1.0, interval))
            try:
                relay.pull()
            except Exception:
                # Transient relay errors must not kill the background timer.
                pass

    threading.Thread(target=_loop, daemon=True, name="relay-pull").start()
    return relay


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG browser bar")
    default_limits = RateLimitConfig.from_env()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--world", default=None, help="shared world file (default ~/.molgang/world.json)")
    ap.add_argument("--db", default=None, help="device→wallet registry sqlite (default ~/.molgang/registry.db)")
    ap.add_argument("--wallet", default=default_wallet_path(),
                    help="Pulse host identity wallet (default ~/.molgang/pulse-identity.cbor)")
    ap.add_argument("--host-genesis", type=int, default=0,
                    help="dev/test only: seed the host Pulse wallet if it is first created")
    ap.add_argument("--cors", default="*",
                    help="Access-Control-Allow-Origin for the API (default '*'; "
                         "set e.g. https://5mart.ml to restrict, or '' to disable)")
    ap.add_argument("--monitor-web", default=None,
                    help="gateway.App store JSON for the 📡 Monitor tab's local-knitweb graph "
                         "(default /tmp/chem_web.json if present, else the shared world)")
    ap.add_argument("--monitor", dest="monitor", action="store_true", default=True,
                    help="enable /api/monitor endpoints (default on)")
    ap.add_argument("--no-monitor", dest="monitor", action="store_false",
                    help="disable /api/monitor endpoints")
    ap.add_argument("--monitor-nodes", default=None,
                    help="comma list label=port for monitor liveness, e.g. alice=8900,bob=8901")
    ap.add_argument("--relay", default=None,
                    help="relay API base to share the growing web across machines, e.g. "
                         "https://5mart.ml/molgang/api/relay (OFF by default = local-only)")
    ap.add_argument("--relay-wallet", default=None,
                    help="node wallet identity used to sign relay pushes (default --wallet)")
    ap.add_argument("--relay-interval", type=float, default=20.0,
                    help="seconds between background relay pulls when --relay is set (default 20)")
    ap.add_argument("--faucet-source-cap", type=int, default=DEFAULT_FAUCET_SOURCE_CAP,
                    help="fresh device faucet claims allowed per request source "
                         "(default env MOLGANG_FAUCET_SOURCE_CAP or 50; <=0 disables)")
    ap.add_argument("--rate-read", type=int, default=default_limits.read.limit,
                    help="GET /api requests allowed per source per window "
                         "(default env MOLGANG_RATE_READ or 240; <=0 disables)")
    ap.add_argument("--rate-read-window", type=float, default=default_limits.read.window_s,
                    help="seconds for --rate-read (default env MOLGANG_RATE_READ_WINDOW or 60)")
    ap.add_argument("--rate-write", type=int, default=default_limits.write.limit,
                    help="ordinary POST /api requests allowed per source/actor per window "
                         "(default env MOLGANG_RATE_WRITE or 60; <=0 disables)")
    ap.add_argument("--rate-write-window", type=float, default=default_limits.write.window_s,
                    help="seconds for --rate-write (default env MOLGANG_RATE_WRITE_WINDOW or 60)")
    ap.add_argument("--rate-costly", type=int, default=default_limits.costly.limit,
                    help="costly write requests allowed per source/actor per window "
                         "(default env MOLGANG_RATE_COSTLY or 20; <=0 disables)")
    ap.add_argument("--rate-costly-window", type=float, default=default_limits.costly.window_s,
                    help="seconds for --rate-costly (default env MOLGANG_RATE_COSTLY_WINDOW or 60)")
    ap.add_argument("--rate-certificate", type=int, default=default_limits.certificate.limit,
                    help="certificate renders allowed per source/actor per window "
                         "(default env MOLGANG_RATE_CERTIFICATE or 10; <=0 disables)")
    ap.add_argument("--rate-certificate-window", type=float,
                    default=default_limits.certificate.window_s,
                    help="seconds for --rate-certificate "
                         "(default env MOLGANG_RATE_CERTIFICATE_WINDOW or 300)")
    a = ap.parse_args([x for x in argv[1:] if x != "serve"])
    from .registry import Registry
    from .monitor import Monitor
    listen = f"{a.host}:{a.port}"
    pulse = bootstrap_host(a.wallet, listen=listen, genesis=a.host_genesis)
    bar = Bar(a.world, Registry(a.db), faucet_source_cap=a.faucet_source_cap)
    monitor = None
    if a.monitor:
        monitor = Monitor(bar, web=a.monitor_web, world=a.world, pulse_host=pulse,
                          nodes=a.monitor_nodes)
    relay_wallet = a.relay_wallet or a.wallet
    relay = _start_relay(bar, a.relay, relay_wallet, a.relay_interval) if a.relay else None
    rate_config = RateLimitConfig(
        read=RateLimitRule(a.rate_read, a.rate_read_window),
        write=RateLimitRule(a.rate_write, a.rate_write_window),
        costly=RateLimitRule(a.rate_costly, a.rate_costly_window),
        certificate=RateLimitRule(a.rate_certificate, a.rate_certificate_window),
    )
    srv = ThreadingHTTPServer((a.host, a.port),
                              make_handler(bar, pulse, cors=a.cors or None, monitor=monitor,
                                           relay=relay, rate_config=rate_config))
    print(f"  🍸 MOLGANG bar open at http://{a.host}:{a.port}  (shared web: "
          f"{a.world or '~/.molgang/world.json'}) (Ctrl-C to close)")
    if monitor:
        print(f"  📡 Monitor: nodes {[n['label'] for n in monitor.nodes]} · "
              f"local knitweb {monitor.source}")
    print(f"  pulse host {pulse['account']['address']} · wallet {pulse['wallet']}")
    if relay is not None:
        print(f"  🌐 relay sync ON · {relay.base} · node {relay.signer.address} "
              f"· pull every {a.relay_interval:g}s")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  bar closed.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
