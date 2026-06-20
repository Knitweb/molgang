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
import time
from dataclasses import dataclass, field
from typing import Callable

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
SEATS_PER_TABLE = 24
STALE_SESSION_SECONDS = 45.0


@dataclass
class Proposal:
    pid: str
    table_id: str
    by: str                      # session id of the proposer
    by_name: str
    term: str
    round: game.Round
    parsed: dict = field(default_factory=dict)  # parse_knit() result (term vs link)
    links: list = field(default_factory=list)  # one-to-many knit: the full list of link dicts
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
    last_seen: float = 0.0                     # heartbeat timestamp; bots are never reaped


@dataclass
class Table:
    id: str
    name: str
    base_name: str
    owner_sid: str | None = None
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
    shared_votes: dict = field(default_factory=dict)  # stable voter key -> verdict
    leader_key: str = ""
    shared: bool = False
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

    def __init__(self, world_path: str | None = None, registry=None, *,
                 stale_session_s: float = STALE_SESSION_SECONDS,
                 clock: Callable[[], float] | None = None) -> None:
        self.registry = registry               # optional device→wallet DB (knitweb Registry)
        self.stale_session_s = float(stale_session_s)
        self._clock = clock or time.time
        self._next_table_num = 1
        self.tables: dict[str, Table] = {}
        for tid, name in DEFAULT_TABLES:
            self._add_table(table_id=tid, name=name, seed_bots=False)
        self.sessions: dict[str, Session] = {}
        self.proposals: dict[str, Proposal] = {}
        self.spirals: dict[str, SpiralView] = {}         # auxiliary/capture spirals by id
        self.spiral_record: dict[str, int] = {}          # longest captured spiral per table
        self.woven: list[dict] = []                      # this instance's woven terms
        self._pid = itertools.count(1)
        self._scid = itertools.count(1)                  # spiral ids
        # the SHARED knitweb web every confirmed knit extends (file-shared across instances)
        self.world = World(world_path or default_world_path())
        self._seed_bots(seed_all=True)                      # NPC table-mates so a solo human can reach quorum

    _BOT_NAMES = ["Bea", "Cy", "Dex", "Vala", "Mo", "Pim"]

    def _now(self) -> float:
        return float(self._clock())

    def _seed_bots(self, seed_all: bool = False, table_id: str | None = None,
                   per_table: int = 3) -> None:
        if table_id is not None:
            target = [table_id]
        elif seed_all:
            target = list(self.tables)
        else:
            target = []
        for tid in target:
            for _ in range(per_table):
                sid = secrets.token_hex(8)
                nm = self._BOT_NAMES[len(self.sessions) % len(self._BOT_NAMES)]
                self.sessions[sid] = Session(
                    sid=sid, name=f"🤖 {nm}", player=Player.join(nm), table_id=tid, bot=True,
                    avatar=_AVATAR_IDS[len(self.sessions) % len(_AVATAR_IDS)],
                    last_seen=self._now())

    def _next_table_id(self) -> str:
        """Return a deterministic dynamic table id that is not in use yet."""
        while True:
            tid = f"table-{self._next_table_num}"
            self._next_table_num += 1
            if tid not in self.tables:
                return tid

    def _add_table(self, table_id: str | None = None, name: str | None = None,
                   seed_bots: bool = True) -> Table:
        """Create a new table and return it."""
        tid = table_id or self._next_table_id()
        base_name = name or f"Table {tid.split('-', 1)[-1]}"
        tbl = Table(id=tid, name=base_name, base_name=base_name)
        self.tables[tid] = tbl
        if seed_bots:
            self._seed_bots(table_id=tid)
        return tbl

    def _all_tables_full(self) -> bool:
        return all(self._seated_count(t.id) >= t.seats for t in self.tables.values())

    def _normalize_table_name(self, name: str) -> str:
        n = (name or "").strip()
        if not n:
            raise ValueError("table name cannot be empty")
        if len(n) > 64:
            raise ValueError("table name is too long")
        return n

    def _release_table_owner(self, sid: str, table_id: str) -> None:
        table = self.tables.get(table_id)
        if not table or table.owner_sid != sid:
            return
        table.owner_sid = None
        table.name = table.base_name

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
    def _player_key(self, sess: Session) -> str:
        return sess.device or sess.player.node.address

    def _spiral_record(self, sv: SpiralView) -> dict:
        return {
            "cid": sv.cid,
            "table_id": sv.table_id,
            "by_name": sv.by_name,
            "leader_key": sv.leader_key,
            "links": [{"subject": l["subject"], "object": l["object"],
                       "relation": l.get("relation", "links")} for l in sv.round.links],
            "votes": [{"voter": k, "verdict": v} for k, v in sorted(sv.shared_votes.items())],
        }

    def _fake_spiral_voter(self, key: str) -> Player:
        return Player.from_device(f"spiral-voter:{key}", f"peer:{key[:8]}")

    def _apply_shared_votes(self, sv: SpiralView, record: dict) -> None:
        for row in record.get("votes", []):
            key = str(row.get("voter", ""))
            verdict = str(row.get("verdict", "confirm"))
            if not key or key in sv.shared_votes:
                continue
            try:
                game.cast_spiral_vote(sv.round, self._fake_spiral_voter(key),
                                      quorum.Verdict(verdict))
            except RuntimeError:
                continue
            sv.shared_votes[key] = verdict

    def _spiral_from_record(self, record: dict) -> SpiralView:
        leader_key = str(record.get("leader_key") or record.get("by_name") or record["cid"])
        leader = Player.from_device(f"spiral-leader:{leader_key}",
                                    str(record.get("by_name") or "remote"),
                                    silk=100)
        rnd = game.SpiralRound(leader=leader, escrow=game.AccountNode(),
                               links=list(record.get("links", [])))
        sv = SpiralView(
            cid=str(record["cid"]),
            table_id=str(record["table_id"]),
            by=f"shared:{leader_key}",
            by_name=str(record.get("by_name") or "remote"),
            round=rnd,
            leader_key=leader_key,
            shared=True,
        )
        self._apply_shared_votes(sv, record)
        return sv

    def _sync_shared_spirals(self) -> None:
        records = {str(r["cid"]): r for r in self.world.list_open_spirals()}
        for cid, record in records.items():
            sv = self.spirals.get(cid)
            if sv is None:
                self.spirals[cid] = self._spiral_from_record(record)
            elif not sv.settled:
                self._apply_shared_votes(sv, record)
        for cid, sv in list(self.spirals.items()):
            if sv.leader_key and not sv.settled and cid not in records:
                self.spirals.pop(cid, None)

    def propose_spiral(self, sid: str, lines: list[str]) -> SpiralView:
        sess = self._require(sid)
        if not sess.table_id:
            raise RuntimeError("take a seat at a table first")
        self._sync_shared_spirals()
        open_here = [s for s in self.spirals.values()
                     if s.table_id == sess.table_id and not s.settled]
        if len(open_here) >= 2:
            raise RuntimeError("too many open spirals at this table (max 2)")
        links = spiral_links(lines)                       # raises if not all links
        rnd = game.propose_spiral(sess.player, links)     # spends escalating silk
        cid = f"s{secrets.token_hex(6)}"
        sv = SpiralView(cid=cid, table_id=sess.table_id, by=sid, by_name=sess.name, round=rnd,
                        leader_key=self._player_key(sess))
        self.spirals[cid] = sv
        self.world.publish_open_spiral(self._spiral_record(sv))
        self._bots_spiral_act()                           # NPCs back it immediately
        self._persist_balances()                          # leader spent silk (+ any settle)
        return sv

    def vote_spiral(self, sid: str, cid: str, verdict: str) -> SpiralView:
        sess = self._require(sid)
        self._sync_shared_spirals()
        sv = self.spirals.get(cid)
        if not sv or sv.settled:
            raise RuntimeError("no open spiral with that id")
        voter_key = self._player_key(sess)
        if sid == sv.by or (sv.leader_key and voter_key == sv.leader_key):
            raise RuntimeError("you cannot back your own spiral")
        if sid in sv.voters or voter_key in sv.shared_votes:
            raise RuntimeError("you already backed this spiral")
        game.cast_spiral_vote(sv.round, sess.player, quorum.Verdict(verdict))
        sv.voters.add(sid)
        sv.shared_votes[voter_key] = verdict
        self.world.publish_open_spiral(self._spiral_record(sv))
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
        self.world.remove_open_spiral(sv.cid)
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
        self.reap_stale()
        if device:
            for sess in self.sessions.values():
                if not sess.bot and sess.device == device:
                    sess.name = (name or sess.name or "guest")[:24]
                    if avatar in _AVATAR_IDS:
                        sess.avatar = avatar
                    self.touch(sess.sid)
                    if table_id:
                        self.sit(sess.sid, table_id)
                    return sess
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
        sess = Session(sid=sid, name=nm, avatar=avatar, player=player, device=device,
                       last_seen=self._now())
        self.sessions[sid] = sess
        if table_id:
            self.sit(sid, table_id)
        return sess

    def touch(self, sid: str) -> dict:
        sess = self.sessions.get(sid)
        if not sess:
            raise KeyError("unknown session — join the bar first")
        if not sess.bot:
            sess.last_seen = self._now()
        return {"sid": sess.sid, "last_seen": sess.last_seen, "table": sess.table_id}

    def reap_stale(self, max_age: float | None = None) -> list[str]:
        """Remove inactive human sessions and free their table seats."""
        max_age = self.stale_session_s if max_age is None else float(max_age)
        if max_age <= 0:
            return []
        cutoff = self._now() - max_age
        stale = [sid for sid, s in self.sessions.items()
                 if not s.bot and s.last_seen and s.last_seen < cutoff]
        for sid in stale:
            self.leave(sid)
        return stale

    def rename_table(self, sid: str, table_id: str, name: str) -> Table:
        sess = self._require(sid)
        if table_id not in self.tables:
            raise KeyError(f"no such table: {table_id}")
        table = self.tables[table_id]
        if sess.bot:
            raise RuntimeError("bots cannot rename tables")
        if sess.table_id != table_id:
            raise RuntimeError("take a seat at that table first")
        if table.owner_sid and table.owner_sid != sid:
            raise RuntimeError("only the current namer can rename this table")
        table.owner_sid = sid
        table.name = self._normalize_table_name(name)
        return table

    def sit(self, sid: str, table_id: str) -> None:
        sess = self._require(sid)
        if table_id not in self.tables:
            raise KeyError(f"no such table: {table_id}")
        table = self.tables[table_id]
        if self._seated_count(table_id) >= table.seats and sess.table_id != table_id:
            if not self._all_tables_full():
                raise RuntimeError("table is full")
            table = self._add_table()
        if sess.table_id and sess.table_id != table.id:
            self._release_table_owner(sess.sid, sess.table_id)
        sess.table_id = table.id

    def leave(self, sid: str) -> None:
        sess = self.sessions.pop(sid, None)
        if not sess:
            return
        if sess.table_id:
            self._release_table_owner(sess.sid, sess.table_id)

    def stand(self, sid: str) -> None:
        sess = self._require(sid)
        if sess.table_id:
            self._release_table_owner(sess.sid, sess.table_id)
        sess.table_id = None

    # -- the knit loop -----------------------------------------------------
    def propose(self, sid: str, term: str, topic: str | None = None) -> Proposal:
        sess = self._require(sid)
        if not sess.table_id:
            raise RuntimeError("take a seat at a table first")
        parsed = parse_knit(term)                         # term, link, or list of links
        # a one-to-many knit ("X has A, B and C") parses to a list of link dicts — treat it
        # as a mini-spiral: a synthesized headline label, the full link list woven on settle.
        links: list = []
        if isinstance(parsed, list):
            links = parsed
            subject, rel = links[0]["subject"], links[0]["relation"]
            objs = ", ".join(l["object"] for l in links)
            label = f"{subject} {rel} {{{objs}}}"
            topic = subject.strip().lower()
            head = {"kind": "link", "label": label}        # for parsed.get() lookups downstream
        else:
            label = parsed["label"]
            topic = (parsed.get("subject") or parsed.get("term") or label).strip().lower()
            head = parsed
        rnd = game.propose_term(sess.player, label)        # spends 1 silk
        pid = f"p{next(self._pid)}"
        prop = Proposal(pid=pid, table_id=sess.table_id, by=sid, by_name=sess.name,
                        term=label, round=rnd, parsed=head, links=links, topic=topic)
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
                "anchor_ts": int(time.time()),   # weave time → enables seasonal boards (#112)
            })
            # extend the SHARED knitweb web — a term node, a single LINK edge, or (one-to-many
            # knit) every link of the enumeration woven as its own edge.
            if prop.links:
                self.world.weave_links(prop.links, prop.by_name, s.woven_fiber_cid, s.result.confirms)
            else:
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

    def certificate_data(self, sid: str) -> dict:
        """Everything a PoUW certificate needs for the player behind ``sid``.

        ``pulses_used`` is the proof-of-useful-work metric: the free faucet grant minus the
        pulses the player still holds (clamped >=0) — i.e. what they *spent* staking votes and
        weaving spirals. ``work_summary`` counts their useful work (terms proposed, knits woven,
        spirals captured, votes cast). ``provenance`` is the shared web's OriginTrail anchor.
        """
        sess = self._require(sid)
        player = sess.player
        pulses_used = max(0, game.FAUCET_PULSES - player.pulses)
        my_props = [p for p in self.proposals.values() if p.by == sid]
        my_spirals = [sv for sv in self.spirals.values() if sv.by == sid]
        votes_cast = (sum(1 for p in self.proposals.values() if sid in p.voters)
                      + sum(1 for sv in self.spirals.values() if sid in sv.voters))
        from . import achievements
        work_summary = {
            "terms_proposed": len(my_props),
            "knits_woven": sum(1 for p in my_props if p.woven),
            "spirals_captured": sum(1 for sv in my_spirals if sv.captured),
            "votes_cast": votes_cast,
            # woven-knowledge proof — reputation, not a bearer token (#111, no-NFT rule)
            "achievements_unlocked": achievements.achievement_count(self.woven, [], sess.name),
        }
        return {
            "holder": sess.name,
            "address": player.node.address,
            "public_key": player.node.pub,
            "private_key": player.node.priv,
            "pulses_used": pulses_used,
            "work_summary": work_summary,
            "provenance": self.web_view().get("anchor"),
        }

    def state(self, sid: str | None = None) -> dict:
        from . import progression

        self.reap_stale()
        if sid in self.sessions:
            self.touch(sid)
        self._sync_shared_spirals()
        tables = []
        me = self.sessions.get(sid) if sid else None
        for t in self.tables.values():
            can_rename = bool(me and not me.bot and me.table_id == t.id
                              and (t.owner_sid is None or t.owner_sid == sid))
            seated = []
            for s in self.sessions.values():
                if s.table_id != t.id:
                    continue
                w = self._woven_by(s.sid)
                lvl = progression.level_for(w * progression.XP_PER_WOVEN)
                seated.append({"name": s.name, "avatar": s.avatar, "you": s.sid == sid,
                               "woven": w, "level": lvl, "title": progression.title_for(lvl),
                               "live": True, "last_seen": s.last_seen if not s.bot else None})
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
                           "can_rename": can_rename,
                           "seated": seated, "open": opens, "spirals": spirals_open,
                           "spiral_record": self.spiral_record.get(t.id, 0),
                           "fabric": [w for w in self.woven if w["table"] == t.id]})
        you = None
        if me:
            w = self._woven_by(sid)
            lvl = progression.level_for(w * progression.XP_PER_WOVEN)
            you = {"sid": me.sid, "name": me.name, "avatar": me.avatar, "table": me.table_id,
                   "address": me.player.node.address, "device": bool(me.device),
                   "pulses": me.player.pulses, "silk": me.player.silk,
                   "knits_made": sum(1 for p in self.proposals.values() if p.by == sid),
                   "woven": w, "level": lvl, "title": progression.title_for(lvl),
                   "xp": w * progression.XP_PER_WOVEN, "last_seen": me.last_seen}
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
        self.reap_stale()
        if sid not in self.sessions:
            raise KeyError("unknown session — join the bar first")
        self.touch(sid)
        return self.sessions[sid]

    def _seated_count(self, table_id: str) -> int:
        return sum(1 for s in self.sessions.values() if s.table_id == table_id)


def suggested_terms() -> list[str]:
    """A few real molecules to seed brainstorming (chemistry knits that can be confirmed)."""
    return list(MOLECULES.keys())
