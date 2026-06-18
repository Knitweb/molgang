"""The MOLGANG bar — a live, multiplayer social space.

Players walk into the bar, **take a seat at a table** (with an avatar), and **knit together**:
someone **brainstorms a term and knits it** (spends silk), and the others at the table
**vote with a pulse**. When the table reaches a BFT quorum the term is **woven** into the
table's fabric. Everything sits on real knitweb accounts (free faucet) — votes are real Knits,
woven terms advance real Fibers. No NFTs: silk + pulses + reputation only.

This is the server-side game state for the browser UI and the machine API (`webserver.py`).
"""

from __future__ import annotations

import itertools
import secrets
from dataclasses import dataclass, field

from knitweb.pouw import quorum

from . import game
from .chemistry import MOLECULES
from .game import Player
from .knit_parse import parse_knit, spiral_links
from .world import World, default_world_path

# Caricature avatars — crypto/tech *archetypes* (original personas, never real people's names).
AVATARS = [
    {"id": "laser-maxi", "name": "Laser-Eyes Maxi"},
    {"id": "hoodie-hacker", "name": "Hoodie Hacker"},
    {"id": "gas-goblin", "name": "Gas-Fee Goblin"},
    {"id": "dao-delegate", "name": "DAO Delegate"},
    {"id": "diamond-hands", "name": "Diamond Hands"},
    {"id": "validator-owl", "name": "Validator Owl"},
    {"id": "faucet-fairy", "name": "Faucet Fairy"},
    {"id": "degen-ape", "name": "Degen Ape"},
]
_AVATAR_IDS = [a["id"] for a in AVATARS]
DEFAULT_TABLES = [
    ("periodic", "Periodic Bar"),
    ("organic", "Organic Lounge"),
    ("noble", "Noble Corner"),
]
SEATS_PER_TABLE = 6


@dataclass
class Proposal:
    pid: str
    table_id: str
    by: str                      # session id of the proposer
    by_name: str
    term: str
    round: game.Round
    parsed: dict = field(default_factory=dict)  # parse_knit() result (term vs link)
    topic: str = ""                            # competing knits share a topic (default: the term)
    settled: bool = False
    outcome: str | None = None
    woven: bool = False
    fiber_cid: str | None = None              # the Fiber this knit wove (when confirmed)
    voters: set = field(default_factory=set)   # session ids that have voted

    @property
    def net(self) -> int:
        b = self.vote_breakdown()
        return b["confirm"] - b["mismatch"]

    def vote_breakdown(self) -> dict:
        c = m = a = 0
        for v in self.round.votes:
            val = v.verdict.value
            c += val == "confirm"
            m += val == "mismatch"
            a += val == "abstain"
        return {"confirm": c, "mismatch": m, "abstain": a, "total": len(self.round.votes)}


@dataclass
class Session:
    sid: str
    name: str
    avatar: str
    player: Player
    table_id: str | None = None
    bot: bool = False                          # an NPC table-mate (so solo humans get votes)
    device: str | None = None                  # the device id this session's wallet is bound to


@dataclass
class Table:
    id: str
    name: str
    seats: int = SEATS_PER_TABLE


@dataclass
class SpiralView:
    """A spiral woven at a table — auxiliary (gathering pulses) until captured (sticky)."""

    cid: str
    table_id: str
    by: str
    by_name: str
    round: "game.SpiralRound"
    voters: set = field(default_factory=set)
    settled: bool = False
    captured: bool = False

    @property
    def length(self) -> int:
        return self.round.length

    def breakdown(self) -> dict:
        c = sum(1 for v in self.round.votes if v.verdict == quorum.Verdict.CONFIRM)
        m = sum(1 for v in self.round.votes if v.verdict == quorum.Verdict.MISMATCH)
        return {"confirm": c, "mismatch": m, "total": len(self.round.votes)}


class Bar:
    """In-memory, single-process bar. Real knitweb accounts under the hood."""

    def __init__(self, world_path: str | None = None, registry=None) -> None:
        self.registry = registry               # optional device→wallet DB (knitweb Registry)
        self.tables: dict[str, Table] = {tid: Table(tid, name) for tid, name in DEFAULT_TABLES}
        self.sessions: dict[str, Session] = {}
        self.proposals: dict[str, Proposal] = {}
        self.spirals: dict[str, SpiralView] = {}         # auxiliary/capture spirals by id
        self.spiral_record: dict[str, int] = {}          # longest captured spiral per table
        self.woven: list[dict] = []                      # this instance's woven terms
        self._pid = itertools.count(1)
        self._scid = itertools.count(1)                  # spiral ids
        # the SHARED knitweb web every confirmed knit extends (file-shared across instances)
        self.world = World(world_path or default_world_path())
        self._seed_bots()                      # NPC table-mates so a solo human can reach quorum

    _BOT_NAMES = ["Bea", "Cy", "Dex", "Vala", "Mo", "Pim"]

    def _seed_bots(self, per_table: int = 3) -> None:
        for tid in self.tables:
            for _ in range(per_table):
                sid = secrets.token_hex(8)
                nm = self._BOT_NAMES[len(self.sessions) % len(self._BOT_NAMES)]
                self.sessions[sid] = Session(
                    sid=sid, name=f"🤖 {nm}", player=Player.join(nm), table_id=tid, bot=True,
                    avatar=_AVATAR_IDS[len(self.sessions) % len(_AVATAR_IDS)])

    def _bots_act(self) -> None:
        """Seated NPCs vote 'confirm' on open knits they haven't weighed in on yet."""
        for prop in list(self.proposals.values()):
            if prop.settled:
                continue
            for s in list(self.sessions.values()):
                if (s.bot and s.table_id == prop.table_id and s.sid != prop.by
                        and s.sid not in prop.voters and s.player.pulses >= game.VOTE_COST):
                    try:
                        self.vote(s.sid, prop.pid, "confirm")
                    except (RuntimeError, KeyError):
                        pass

    def _bots_spiral_act(self) -> None:
        """Seated NPCs back open spirals with an honest verdict (a sound spiral → confirm)."""
        for sv in list(self.spirals.values()):
            if sv.settled:
                continue
            hv = game.honest_spiral_verdict(sv.round.links).value
            for s in list(self.sessions.values()):
                if (s.bot and s.table_id == sv.table_id and s.sid != sv.by
                        and s.sid not in sv.voters and s.player.pulses >= sv.round.stake_per_vote):
                    try:
                        self.vote_spiral(s.sid, sv.cid, hv)
                    except (RuntimeError, KeyError):
                        pass

    # -- the spiral loop ---------------------------------------------------
    def propose_spiral(self, sid: str, lines: list[str]) -> SpiralView:
        sess = self._require(sid)
        if not sess.table_id:
            raise RuntimeError("take a seat at a table first")
        open_here = [s for s in self.spirals.values()
                     if s.table_id == sess.table_id and not s.settled]
        if len(open_here) >= 2:
            raise RuntimeError("too many open spirals at this table (max 2)")
        links = spiral_links(lines)                       # raises if not all links
        rnd = game.propose_spiral(sess.player, links)     # spends escalating silk
        cid = f"s{next(self._scid)}"
        sv = SpiralView(cid=cid, table_id=sess.table_id, by=sid, by_name=sess.name, round=rnd)
        self.spirals[cid] = sv
        self._bots_spiral_act()                           # NPCs back it immediately
        self._persist_balances()                          # leader spent silk (+ any settle)
        return sv

    def vote_spiral(self, sid: str, cid: str, verdict: str) -> SpiralView:
        sess = self._require(sid)
        sv = self.spirals.get(cid)
        if not sv or sv.settled:
            raise RuntimeError("no open spiral with that id")
        if sid == sv.by:
            raise RuntimeError("you cannot back your own spiral")
        if sid in sv.voters:
            raise RuntimeError("you already backed this spiral")
        game.cast_spiral_vote(sv.round, sess.player, quorum.Verdict(verdict))
        sv.voters.add(sid)
        others = self._seated_count(sv.table_id) - 1
        if len(sv.round.votes) >= max(game.MIN_SPIRAL_VOTERS, others):
            self._settle_spiral(sv)
        self._persist_balances()                          # backer staked (+ any settle payout)
        return sv

    def _settle_spiral(self, sv: SpiralView) -> None:
        from . import progression
        levels = [progression.level_for(self._woven_by(s.sid) * progression.XP_PER_WOVEN)
                  for s in self.sessions.values()
                  if s.table_id == sv.table_id and not s.bot]
        k = progression.reputation_threshold(levels, len(sv.round.votes))
        s = game.settle_spiral(sv.round, threshold=k)
        sv.settled, sv.captured = True, s.captured
        if s.captured:
            self.world.weave_spiral(sv.round.links, sv.by_name, s.leader_fiber_cid,
                                    s.result.confirms, validators=len(sv.round.votes),
                                    pls_staked=s.pls_staked)
            path = " → ".join([sv.round.links[0]["subject"], *[l["object"] for l in sv.round.links]])
            self.woven.append({"term": f"🕸 {path}", "by": sv.by_name, "table": sv.table_id,
                               "fiber_cid": s.leader_fiber_cid, "confirmations": s.result.confirms,
                               "is_chemistry": False, "spiral": True})
            self.spiral_record[sv.table_id] = max(self.spiral_record.get(sv.table_id, 0), sv.length)

    # -- presence ----------------------------------------------------------
    def join(self, name: str, avatar: str | None = None, table_id: str | None = None,
             device: str | None = None) -> Session:
        sid = secrets.token_hex(8)
        avatar = avatar if avatar in _AVATAR_IDS else _AVATAR_IDS[len(self.sessions) % len(_AVATAR_IDS)]
        nm = (name or "guest")[:24]
        # a device id (e.g. a phone) → a STABLE PLS wallet, registered in the DB
        if device:
            # restore a persisted balance so pulses + silk survive a server restart;
            # otherwise open the faucet (default) and snapshot that starting balance.
            saved = self.registry.get_balance(device) if self.registry else None
            if saved is not None:
                player = Player.from_device(device, nm, pulses=saved["pulses"], silk=saved["silk"])
            else:
                player = Player.from_device(device, nm)
            if self.registry:
                self.registry.register(device, player.node.address, nm)
                if saved is None:
                    self.registry.save_balance(device, player.pulses, player.silk)
        else:
            player = Player.join(nm)
        sess = Session(sid=sid, name=nm, avatar=avatar, player=player, device=device)
        self.sessions[sid] = sess
        if table_id:
            self.sit(sid, table_id)
        return sess

    def sit(self, sid: str, table_id: str) -> None:
        sess = self._require(sid)
        if table_id not in self.tables:
            raise KeyError(f"no such table: {table_id}")
        if self._seated_count(table_id) >= self.tables[table_id].seats and sess.table_id != table_id:
            raise RuntimeError("table is full")
        sess.table_id = table_id

    def leave(self, sid: str) -> None:
        self.sessions.pop(sid, None)

    # -- the knit loop -----------------------------------------------------
    def propose(self, sid: str, term: str, topic: str | None = None) -> Proposal:
        sess = self._require(sid)
        if not sess.table_id:
            raise RuntimeError("take a seat at a table first")
        parsed = parse_knit(term)                         # term vs link; strips LaTeX/markup
        rnd = game.propose_term(sess.player, parsed["label"])  # spends 1 silk
        pid = f"p{next(self._pid)}"
        prop = Proposal(pid=pid, table_id=sess.table_id, by=sid, by_name=sess.name,
                        term=parsed["label"], round=rnd, parsed=parsed,
                        topic=(parsed.get("subject") or parsed.get("term") or parsed["label"]).strip().lower())
        self.proposals[pid] = prop
        self._bots_act()                                  # NPC table-mates weigh in immediately
        self._persist_balances()                          # proposer spent silk (+ any settle)
        return prop

    def vote(self, sid: str, pid: str, verdict: str) -> Proposal:
        sess = self._require(sid)
        prop = self.proposals.get(pid)
        if not prop or prop.settled:
            raise RuntimeError("no open proposal with that id")
        if sid == prop.by:
            raise RuntimeError("you cannot vote on your own knit")
        if sid in prop.voters:
            raise RuntimeError("you already voted")
        v = quorum.Verdict(verdict)                      # 'confirm' | 'mismatch' | 'abstain'
        game.cast_vote(prop.round, sess.player, v)       # stakes a real PLS Knit into escrow
        prop.voters.add(sid)
        # auto-settle once every other seated player has weighed in (min 1 vote)
        others = self._seated_count(prop.table_id) - 1
        if len(prop.round.votes) >= max(1, others):
            self._settle(prop)
        self._persist_balances()                          # voter staked (+ any settle payout)
        return prop

    def _settle(self, prop: Proposal) -> None:
        s = game.settle(prop.round)
        prop.settled = True
        prop.outcome = s.outcome.value
        prop.woven = s.woven
        prop.fiber_cid = s.woven_fiber_cid
        if s.woven:
            self.woven.append({
                "term": prop.term, "by": prop.by_name, "table": prop.table_id,
                "fiber_cid": s.woven_fiber_cid, "confirmations": s.result.confirms,
                "is_chemistry": prop.parsed.get("term", "") in MOLECULES,
            })
            # extend the SHARED knitweb web — a term node, or a LINK edge between two terms
            self.world.weave_knit(prop.parsed, prop.by_name, s.woven_fiber_cid, s.result.confirms)

    def web_view(self) -> dict:
        """The shared web's current state + its OriginTrail provenance anchor."""
        g = self.world.graph()
        g["anchor"] = self.world.anchor()
        return g

    # -- ledger & explorer -------------------------------------------------
    def _knit_row(self, p: Proposal) -> dict:
        return {"pid": p.pid, "term": p.term, "by": p.by_name, "topic": p.topic,
                "settled": p.settled, "outcome": p.outcome, "woven": p.woven,
                "fiber_cid": p.fiber_cid, "votes": p.vote_breakdown(), "net": p.net}

    def my_knits(self, sid: str) -> dict:
        mine = [self._knit_row(p) for p in self.proposals.values() if p.by == sid]
        total_votes = sum(r["votes"]["total"] for r in mine)
        return {"knits": mine, "knits_made": len(mine),
                "woven": sum(1 for r in mine if r["woven"]), "total_votes": total_votes}

    def explorer(self) -> list[dict]:
        """Knits grouped by topic; competing knits ranked into columns (best first)."""
        groups: dict[str, list[Proposal]] = {}
        for p in self.proposals.values():
            groups.setdefault(p.topic, []).append(p)
        rows = []
        for topic, props in groups.items():
            cols = sorted(props, key=lambda p: (-p.net, -p.vote_breakdown()["total"], p.pid))
            rows.append({"topic": topic, "competing": len(cols),
                         "columns": [self._knit_row(p) for p in cols]})
        # busiest / most-contested topics first
        rows.sort(key=lambda r: (-r["competing"], -sum(c["votes"]["total"] for c in r["columns"])))
        return rows

    # -- views -------------------------------------------------------------
    def _woven_by(self, sid: str) -> int:
        return sum(1 for p in self.proposals.values() if p.by == sid and p.woven)

    def _spiral_leaderboard(self) -> list[dict]:
        caps = sorted((sv for sv in self.spirals.values() if sv.captured), key=lambda x: -x.length)
        return [{"by": sv.by_name, "length": sv.length, "table": sv.table_id} for sv in caps[:10]]

    def state(self, sid: str | None = None) -> dict:
        from . import progression

        tables = []
        for t in self.tables.values():
            seated = []
            for s in self.sessions.values():
                if s.table_id != t.id:
                    continue
                w = self._woven_by(s.sid)
                lvl = progression.level_for(w * progression.XP_PER_WOVEN)
                seated.append({"name": s.name, "avatar": s.avatar, "you": s.sid == sid,
                               "woven": w, "level": lvl, "title": progression.title_for(lvl)})
            opens = [{"pid": p.pid, "term": p.term, "by": p.by_name, "topic": p.topic,
                      "votes": p.vote_breakdown(), "net": p.net,
                      "mine": p.by == sid, "voted": sid in p.voters}
                     for p in self.proposals.values()
                     if p.table_id == t.id and not p.settled]
            spirals_open = [{"cid": sv.cid, "by": sv.by_name, "length": sv.length,
                             "links": [f"{l['subject']} → {l['object']}" for l in sv.round.links],
                             "votes": sv.breakdown(), "state": sv.round.state,
                             "mine": sv.by == sid, "backed": sid in sv.voters,
                             "stake": sv.round.stake_per_vote}
                            for sv in self.spirals.values()
                            if sv.table_id == t.id and not sv.settled]
            tables.append({"id": t.id, "name": t.name, "seats": t.seats,
                           "seated": seated, "open": opens, "spirals": spirals_open,
                           "spiral_record": self.spiral_record.get(t.id, 0),
                           "fabric": [w for w in self.woven if w["table"] == t.id]})
        me = self.sessions.get(sid) if sid else None
        you = None
        if me:
            w = self._woven_by(sid)
            lvl = progression.level_for(w * progression.XP_PER_WOVEN)
            you = {"sid": me.sid, "name": me.name, "avatar": me.avatar, "table": me.table_id,
                   "address": me.player.node.address, "device": bool(me.device),
                   "pulses": me.player.pulses, "silk": me.player.silk,
                   "knits_made": sum(1 for p in self.proposals.values() if p.by == sid),
                   "woven": w, "level": lvl, "title": progression.title_for(lvl),
                   "xp": w * progression.XP_PER_WOVEN}
        return {
            "tables": tables,
            "avatars": AVATARS,
            "you": you,
            "my_knits": self.my_knits(sid) if sid else None,
            "explorer": self.explorer(),
            "bar_woven": len(self.woven),
            "spiral_leaderboard": self._spiral_leaderboard(),
        }

    # -- helpers -----------------------------------------------------------
    def _persist_balances(self) -> None:
        """Snapshot every device-backed (non-NPC) player's pulses + silk to the registry.

        Called after balance-changing events so a device's wallet survives a restart.
        No-op without a registry; NPC bots and guest (non-device) sessions are skipped.
        """
        if not self.registry:
            return
        for s in self.sessions.values():
            if s.device and not s.bot:
                self.registry.save_balance(s.device, s.player.pulses, s.player.silk)

    def _require(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError("unknown session — join the bar first")
        return self.sessions[sid]

    def _seated_count(self, table_id: str) -> int:
        return sum(1 for s in self.sessions.values() if s.table_id == table_id)


def suggested_terms() -> list[str]:
    """A few real molecules to seed brainstorming (chemistry knits that can be confirmed)."""
    return list(MOLECULES.keys())
