"""Channels websocket consumers for live MOLGANG world updates."""

from __future__ import annotations

from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .events import WORLD_GROUP, world_state_event


class WorldConsumer(AsyncJsonWebsocketConsumer):
    """Send canonical `/api/state` snapshots whenever the Django world changes."""

    sid: str | None = None

    async def connect(self) -> None:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        self.sid = (query.get("sid") or [None])[0] or None
        await self.channel_layer.group_add(WORLD_GROUP, self.channel_name)
        await self.accept()
        await self._send_state({"kind": "connect"})

    async def disconnect(self, code: int) -> None:
        await self.channel_layer.group_discard(WORLD_GROUP, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        if content.get("type") == "refresh":
            self.sid = content.get("sid") or self.sid
            await self._send_state({"kind": "refresh"})

    async def world_changed(self, event: dict) -> None:
        await self._send_state(
            {
                "kind": event.get("kind") or "world.changed",
                "actor_sid": event.get("actor_sid") or "",
            }
        )

    async def _send_state(self, trigger: dict) -> None:
        payload = await sync_to_async(world_state_event, thread_sensitive=True)(self.sid, trigger)
        await self.send_json(payload)
