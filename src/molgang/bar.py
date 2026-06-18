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

AVATARS = ["🦊", "🐙", "🦉", "🐝", "🦋", "🐢", "🦜", "🐳", "🦄", "🐧"]
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


@dataclass
class Table:
    id: str
    name: str
    seats: int = SEATS_PER_TABLE


class Bar:
    """In-memory, single-process bar. Real knitweb accounts under the hood."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {tid: Table(tid, name) for tid, name in DEFAULT_TABLES}
        self.sessions: dict[str, Session] = {}
        self.proposals: dict[str, Proposal] = {}
        self.woven: list[dict] = []                      # the bar's whole fabric (woven terms)
        self._pid = itertools.count(1)

    # -- presence ----------------------------------------------------------
    def join(self, name: str, avatar: str | None = None, table_id: str | None = None) -> Session:
        sid = secrets.token_hex(8)
        avatar = avatar if avatar in AVATARS else AVATARS[len(self.sessions) % len(AVATARS)]
        sess = Session(sid=sid, name=(name or "guest")[:24], avatar=avatar,
                       player=Player.join(name or "guest"))
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
        rnd = game.propose_term(sess.player, term)       # spends 1 silk
        pid = f"p{next(self._pid)}"
        prop = Proposal(pid=pid, table_id=sess.table_id, by=sid, by_name=sess.name,
                        term=term.strip(), round=rnd,
                        topic=(topic or term).strip().lower())
        self.proposals[pid] = prop
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
                "is_chemistry": prop.term in MOLECULES,
            })

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
            tables.append({"id": t.id, "name": t.name, "seats": t.seats,
                           "seated": seated, "open": opens,
                           "fabric": [w for w in self.woven if w["table"] == t.id]})
        me = self.sessions.get(sid) if sid else None
        you = None
        if me:
            w = self._woven_by(sid)
            lvl = progression.level_for(w * progression.XP_PER_WOVEN)
            you = {"sid": me.sid, "name": me.name, "avatar": me.avatar, "table": me.table_id,
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
        }

    # -- helpers -----------------------------------------------------------
    def _require(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError("unknown session — join the bar first")
        return self.sessions[sid]

    def _seated_count(self, table_id: str) -> int:
        return sum(1 for s in self.sessions.values() if s.table_id == table_id)


def suggested_terms() -> list[str]:
    """A few real molecules to seed brainstorming (chemistry knits that can be confirmed)."""
    return list(MOLECULES.keys())
