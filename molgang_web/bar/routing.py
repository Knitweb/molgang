"""Websocket routes for the MOLGANG Django dapp."""

from __future__ import annotations

from django.urls import path

from .consumers import WorldConsumer

websocket_urlpatterns = [
    path("ws/world/", WorldConsumer.as_asgi()),
]
