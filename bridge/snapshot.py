"""MOLGANG bridge — DOWNLOAD: project the canonical Knitweb state for molgang/Roblox.

The download half of the two-way sync. It turns the persisted knitweb projection
(`bridge/state.py`) into a snapshot the Roblox/Python clients fetch and apply: the set of
**confirmed (woven) bonds** — including ones woven by other peers or the Python P2P game —
plus each player's continued **pulse/silk balance**. So an update on the p2p Knitweb flows
back down to molgang.
"""

from __future__ import annotations


def snapshot(state: dict, *, ts: str | None = None) -> dict:
    """Build the molgang-facing snapshot from the persisted knitweb state."""
    web = state.get("web", {})
    return {
        "source": "molgang-knitweb",
        "snapshot_at": ts or state.get("updated_at"),
        "confirmed_formulas": sorted(web.keys()),
        "web": [dict(formula=f, **w) for f, w in sorted(web.items())],
        "players": state.get("players", {}),
    }
