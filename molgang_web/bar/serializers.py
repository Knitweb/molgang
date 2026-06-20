"""Serializer-shaped view data for the Django dapp partials.

These serializers describe the canonical Bar state for server-rendered HTMX
partials. They do not compute balances; they only validate and name fields that
already came from ``Bar.state(sid)``.
"""

from __future__ import annotations

from rest_framework import serializers


class AccountPillSerializer(serializers.Serializer):
    name = serializers.CharField()
    avatar = serializers.CharField(allow_blank=True, required=False)
    wallet = serializers.CharField(allow_blank=True)
    wallet_short = serializers.CharField(allow_blank=True)
    pulses = serializers.IntegerField(min_value=0)
    silk = serializers.IntegerField(min_value=0)
    knits = serializers.IntegerField(min_value=0)
    woven = serializers.IntegerField(min_value=0)
    level = serializers.IntegerField(min_value=1)
    title = serializers.CharField(allow_blank=True)
    xp = serializers.IntegerField(min_value=0)
    table = serializers.CharField(allow_blank=True, allow_null=True, required=False)


def account_pill_from_state(snapshot: dict) -> dict | None:
    """Return validated AccountPill data from the canonical ``/api/state`` shape."""
    you = snapshot.get("you")
    if not you:
        return None
    wallet = str(you.get("address") or "")
    data = {
        "name": str(you.get("name") or "player"),
        "avatar": str(you.get("avatar") or ""),
        "wallet": wallet,
        "wallet_short": f"{wallet[:10]}..." if wallet else "",
        "pulses": int(you.get("pulses") or 0),
        "silk": int(you.get("silk") or 0),
        "knits": int(you.get("knits_made") or 0),
        "woven": int(you.get("woven") or 0),
        "level": int(you.get("level") or 1),
        "title": str(you.get("title") or ""),
        "xp": int(you.get("xp") or 0),
        "table": you.get("table"),
    }
    serializer = AccountPillSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.data)
