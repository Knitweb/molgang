"""Progression & collection — the game layer over the woven Fibers.

Each peer-confirmed bond a player weaves is a **collectible molecule** backed by a real
Fiber CID (the web3-native "you own this because the web says so"). Players accrue XP and
levels, and a leaderboard ranks the class. This is pure, derived game state — the authority
is always the knitweb (Fibers + quorum); this is the motivating layer on top.
"""

from __future__ import annotations

XP_PER_WOVEN = 100                          # XP for weaving a peer-confirmed bond
LEVELS = [0, 100, 300, 600, 1000, 1500, 2500, 4000]  # XP thresholds → level 1..8
TITLES = [
    "Apprentice", "Student", "Lab Assistant", "Chemist", "Synthesist",
    "Catalyst", "Alchemist", "Laureate",
]


def level_for(xp: int) -> int:
    lvl = 1
    for i, threshold in enumerate(LEVELS):
        if xp >= threshold:
            lvl = i + 1
    return lvl


def title_for(level: int) -> str:
    return TITLES[min(level, len(TITLES)) - 1]


# -- Reputation ladder perks (#113) --------------------------------------------------------------
# Each level confers a concrete, NON-TOKEN perk — reputation/standing/skill only, nothing tradable.
# Most are recognition; the Catalyst+ entry maps to the real reputation-weighted quorum already
# enforced by reputation_threshold() below (so the ladder is a coherent mechanic, not cosmetics).
PERKS = [
    "Faucet access — free silk & pulses to weave and vote",            # 1 Apprentice
    "Brainstorm suggestions in your knit box",                          # 2 Student
    "Recognized contributor — your knits seed the shared web",          # 3 Lab Assistant
    "Chemist standing on the class leaderboard",                        # 4 Chemist
    "Mentor standing in peer review",                                   # 5 Synthesist
    "Reputation-weighted consensus — a Catalyst+ table demands a stricter quorum",  # 6 Catalyst
    "Veteran standing — among the longest-serving spiders",            # 7 Alchemist
    "Laureate — full reputation weight; curriculum steward",           # 8 Laureate
]


def perks_for(level: int) -> list[str]:
    """All perks a player has unlocked through ``level`` (cumulative, levels 1..8). Non-token."""
    n = max(0, min(level, len(PERKS)))
    return PERKS[:n]


def next_threshold(xp: int) -> dict:
    """Climb info for an XP total: next title and the XP still needed (``at_max`` when maxed out)."""
    level = level_for(xp)
    if level >= len(LEVELS):
        return {"level": level, "title": title_for(level), "next_title": None,
                "xp_to_next": 0, "at_max": True}
    next_at = LEVELS[level]                       # threshold for level+1 (LEVELS is 0-indexed by level-1)
    return {"level": level, "title": title_for(level), "next_title": title_for(level + 1),
            "xp_to_next": max(0, next_at - xp), "at_max": False}


def collections(woven: list[dict]) -> dict[str, dict]:
    """Group the woven bonds into per-player collections (keyed by Roblox/knitweb id)."""
    by_player: dict[str, dict] = {}
    for b in woven:
        owner = b.get("by", "?")
        p = by_player.setdefault(owner, {"molecules": [], "xp": 0})
        p["molecules"].append({
            "formula": b["formula"], "name": b.get("name", ""),
            "fiber_cid": b.get("fiber_cid"), "confirmations": b.get("confirmations", 0),
        })
        p["xp"] += XP_PER_WOVEN
    for p in by_player.values():
        p["level"] = level_for(p["xp"])
        p["title"] = title_for(p["level"])
    return by_player


def leaderboard(woven: list[dict]) -> list[dict]:
    """Rank players by XP (then id) — ready to render in any client."""
    cols = collections(woven)
    rows = [
        {"player": rid, "molecules": len(p["molecules"]), "xp": p["xp"],
         "level": p["level"], "title": p["title"]}
        for rid, p in cols.items()
    ]
    rows.sort(key=lambda r: (-r["xp"], r["player"]))
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
    return rows


# -- Seasonal (time-windowed) leaderboards (#112) ------------------------------------------------
# Seasons are a *view* over woven timestamps — no separate authority, the all-time leaderboard()
# above stays the lifetime board. A season is a fixed window of SEASON_DAYS indexed from the unix
# epoch, so a season id derives deterministically from any timestamp.
SEASON_DAYS = 30
_SEASON_SECONDS = SEASON_DAYS * 86_400


def season_id(ts: int) -> str:
    """Deterministic season id for a unix timestamp (e.g. ``"S642"``)."""
    return f"S{int(ts) // _SEASON_SECONDS}"


def season_window(sid: str) -> tuple[int, int]:
    """The ``[start, until)`` unix-second bounds for a season id."""
    idx = int(sid[1:]) if isinstance(sid, str) and sid.startswith("S") else int(sid)
    return idx * _SEASON_SECONDS, (idx + 1) * _SEASON_SECONDS


def _in_window(item: dict, since: int, until: int) -> bool:
    ts = item.get("anchor_ts")
    return ts is not None and since <= ts < until


def seasonal_leaderboard(woven: list[dict], *, since: int, until: int) -> list[dict]:
    """The all-time ranking restricted to woven items whose ``anchor_ts`` is in ``[since, until)``.

    Pure derived state with the same XP tally + tie-break (``-xp``, then player id) as
    :func:`leaderboard`. Items lacking an ``anchor_ts`` are not part of any bounded season.
    """
    return leaderboard([w for w in woven if _in_window(w, since, until)])


def current_season_leaderboard(woven: list[dict], now: int) -> dict:
    """The current season's id, ``[since, until)`` window, and ranked rows for timestamp ``now``."""
    sid = season_id(now)
    since, until = season_window(sid)
    return {"season": sid, "since": since, "until": until,
            "rows": seasonal_leaderboard(woven, since=since, until=until)}


def reputation_threshold(seated_levels: list[int], n_voters: int) -> int:
    """A reputation-scaled BFT threshold: a high-level (Catalyst+) table demands a stricter
    supermajority. It only ever *raises* k, and only when the quorum invariant (k ≤ n and
    2k > n) still holds — so `pouw.quorum` stays untouched and a newcomer table keeps the default.
    """
    from knitweb.pouw import quorum

    base = quorum.default_threshold(n_voters)
    if seated_levels and sum(seated_levels) / len(seated_levels) >= 6:   # avg level ≥ Catalyst
        bumped = base + 1
        if bumped <= n_voters and 2 * bumped > n_voters:
            return bumped
    return base
