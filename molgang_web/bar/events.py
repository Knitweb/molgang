"""World websocket events for the Django dapp.

The payload deliberately reuses the canonical `/api/state` shape. Group
broadcasts only announce that the world changed; each connected consumer then
serializes state for its own `sid`, so `state["you"]` remains client-specific.
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .engine import state_snapshot

WORLD_GROUP = "molgang.world"


def world_state_event(sid: str | None = None, trigger: dict | None = None) -> dict:
    return {
        "type": "world.state",
        "sid": sid,
        "trigger": trigger or {},
        "state": state_snapshot(sid),
    }


def broadcast_world(kind: str, sid: str | None = None) -> None:
    """Notify every websocket client that it should receive a fresh state snapshot."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        WORLD_GROUP,
        {
            "type": "world.changed",
            "kind": kind,
            "actor_sid": sid or "",
        },
    )
