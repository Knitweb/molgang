"""Heartbeat presence + stale-session reaping for the shared world (Sprint 3 #17).

The bar tracks seats but not liveness: a player who closes their tab without calling `leave` lingers
forever as a ghost in a seat. This module is the pure, time-injected core that fixes that — it records
a `last_seen` per session, classifies each as online / away / gone, and reaps the gone ones so the
caller (the bar) can free their seats. No knitweb, no wall-clock reads (time is passed in), so it is
fully unit-testable and deterministic.

Wiring (thin, in the server): call `beat(sid)` on every authenticated `/api/*` hit; periodically call
`reap()` and `bar.leave(sid)` for each returned sid; call `drop(sid)` on explicit leave.
"""
from __future__ import annotations

ONLINE = "online"
AWAY = "away"
GONE = "gone"


class Presence:
    """Liveness tracker keyed by session id. `away_after` < `gone_after`, in seconds."""

    def __init__(self, away_after: float = 30.0, gone_after: float = 90.0) -> None:
        if not (0 < away_after < gone_after):
            raise ValueError("require 0 < away_after < gone_after")
        self.away_after = away_after
        self.gone_after = gone_after
        self._seen: dict[str, float] = {}

    def beat(self, sid: str, now: float) -> None:
        """Record a heartbeat for `sid` at time `now`."""
        self._seen[sid] = now

    def drop(self, sid: str) -> None:
        """Stop tracking `sid` (explicit leave). Idempotent."""
        self._seen.pop(sid, None)

    def status(self, sid: str, now: float) -> str:
        """online | away | gone. An unknown sid is `gone`."""
        last = self._seen.get(sid)
        if last is None:
            return GONE
        age = now - last
        if age <= self.away_after:
            return ONLINE
        if age <= self.gone_after:
            return AWAY
        return GONE

    def online(self, now: float) -> list[str]:
        """Sessions currently online or away (i.e. still present)."""
        return [sid for sid in self._seen if self.status(sid, now) != GONE]

    def reap(self, now: float) -> list[str]:
        """Return the sids that have gone stale AND stop tracking them (so each is reaped once).

        The caller frees their seats, e.g. `for sid in presence.reap(now): bar.leave(sid)`.
        """
        gone = [sid for sid, last in self._seen.items() if (now - last) > self.gone_after]
        for sid in gone:
            del self._seen[sid]
        return gone

    def snapshot(self, now: float) -> dict[str, str]:
        """{sid: status} for everyone still tracked — handy for the Monitor tab / state payload."""
        return {sid: self.status(sid, now) for sid in self._seen}
