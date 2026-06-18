"""MOLGANG bridge — DOWNLOAD: project the canonical Knitweb state for molgang/Roblox.

The download half of the two-way sync. It turns the persisted knitweb projection
(`bridge/state.py`) into a snapshot the clients fetch and apply:

  * the **confirmed (woven) bonds** — including ones woven by other peers or the Python game;
  * each player's continued **pulse/silk balance**;
  * the **leaderboard** (XP / level / collection size) — the game layer;
  * a **provenance** block: the OriginTrail **UAL** the current chemistry web is anchored to,
    with a verified notary receipt — so an update on the p2p Knitweb (and its on-DKG proof)
    flows back down to molgang.
"""

from __future__ import annotations

import hashlib

from molgang import progression
from molgang.anchor import anchor_chemistry

# A stable notary key so the provenance UAL is reproducible for a given chemistry web.
_NOTARY_PRIV = hashlib.sha256(b"molgang:notary").hexdigest()


def snapshot(state: dict, *, ts: str | None = None, anchor: bool = True) -> dict:
    """Build the molgang-facing snapshot from the persisted knitweb state."""
    web = state.get("web", {})
    woven = [dict(formula=f, **w) for f, w in sorted(web.items())]

    snap = {
        "source": "molgang-knitweb",
        "snapshot_at": ts or state.get("updated_at"),
        "confirmed_formulas": sorted(web.keys()),
        "web": woven,
        "players": state.get("players", {}),
        "leaderboard": progression.leaderboard(woven),
    }

    if anchor and woven:
        a = anchor_chemistry(woven, notary_priv=_NOTARY_PRIV, timestamp=1)
        snap["provenance"] = {
            "target": "origintrail",
            "ual": a.ual,
            "state_root": a.state_root,
            "receipt_cid": a.receipt_cid,
            "verified": a.verified,
            "bonds": a.bonds,
        }

    return snap
