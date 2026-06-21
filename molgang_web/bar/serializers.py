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


class PortfolioPlayerSerializer(serializers.Serializer):
    name = serializers.CharField()
    wallet = serializers.CharField(allow_blank=True)
    wallet_short = serializers.CharField(allow_blank=True)
    level = serializers.IntegerField(min_value=1)
    title = serializers.CharField(allow_blank=True)
    xp = serializers.IntegerField(min_value=0)


class PortfolioKnitSerializer(serializers.Serializer):
    term = serializers.CharField()
    topic = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    fiber_cid = serializers.CharField(allow_blank=True)
    fiber_short = serializers.CharField(allow_blank=True)
    votes_total = serializers.IntegerField(min_value=0)


class PortfolioSpiralSerializer(serializers.Serializer):
    term = serializers.CharField()
    table = serializers.CharField(allow_blank=True)
    length = serializers.IntegerField(min_value=0)
    state = serializers.CharField()
    fiber_cid = serializers.CharField(allow_blank=True)
    fiber_short = serializers.CharField(allow_blank=True)
    confirmations = serializers.IntegerField(min_value=0)


class PortfolioOpenSpiralSerializer(serializers.Serializer):
    cid = serializers.CharField()
    table = serializers.CharField(allow_blank=True)
    by = serializers.CharField(allow_blank=True)
    length = serializers.IntegerField(min_value=0)
    state = serializers.CharField()
    votes_total = serializers.IntegerField(min_value=0)
    stake = serializers.IntegerField(min_value=0)


class PortfolioSerializer(serializers.Serializer):
    player = PortfolioPlayerSerializer()
    totals = serializers.DictField(child=serializers.IntegerField(min_value=0))
    woven_knits = PortfolioKnitSerializer(many=True)
    captured_spirals = PortfolioSpiralSerializer(many=True)
    backed_spirals = PortfolioOpenSpiralSerializer(many=True)


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


def portfolio_from_state(snapshot: dict) -> dict | None:
    """Return validated Portfolio data from the canonical ``/api/state`` shape."""
    you = snapshot.get("you")
    if not you:
        return None

    tables = list(snapshot.get("tables") or [])
    table_names = {str(t.get("id")): str(t.get("name") or t.get("id") or "") for t in tables}
    wallet = str(you.get("address") or "")
    my_knits = snapshot.get("my_knits") or {}

    woven_knits = []
    for row in my_knits.get("knits") or []:
        if not row.get("woven"):
            continue
        fiber = str(row.get("fiber_cid") or "")
        votes = row.get("votes") or {}
        woven_knits.append(
            {
                "term": str(row.get("term") or ""),
                "topic": str(row.get("topic") or ""),
                "status": "woven",
                "fiber_cid": fiber,
                "fiber_short": f"{fiber[:16]}..." if fiber else "",
                "votes_total": int(votes.get("total") or 0),
            }
        )

    captured_spirals = []
    backed_spirals = []
    for table in tables:
        table_id = str(table.get("id") or "")
        table_name = str(table.get("name") or table_id)
        for item in table.get("fabric") or []:
            if not item.get("spiral") or item.get("by") != you.get("name"):
                continue
            term = str(item.get("term") or "")
            fiber = str(item.get("fiber_cid") or "")
            captured_spirals.append(
                {
                    "term": term,
                    "table": table_name,
                    "length": term.count("→"),
                    "state": "captured",
                    "fiber_cid": fiber,
                    "fiber_short": f"{fiber[:16]}..." if fiber else "",
                    "confirmations": int(item.get("confirmations") or 0),
                }
            )
        for spiral in table.get("spirals") or []:
            if not spiral.get("backed"):
                continue
            votes = spiral.get("votes") or {}
            backed_spirals.append(
                {
                    "cid": str(spiral.get("cid") or ""),
                    "table": table_names.get(table_id, table_name),
                    "by": str(spiral.get("by") or ""),
                    "length": int(spiral.get("length") or 0),
                    "state": str(spiral.get("state") or "open"),
                    "votes_total": int(votes.get("total") or 0),
                    "stake": int(spiral.get("stake") or 0),
                }
            )

    data = {
        "player": {
            "name": str(you.get("name") or "player"),
            "wallet": wallet,
            "wallet_short": f"{wallet[:10]}..." if wallet else "",
            "level": int(you.get("level") or 1),
            "title": str(you.get("title") or ""),
            "xp": int(you.get("xp") or 0),
        },
        "totals": {
            "knits": int(my_knits.get("knits_made") or you.get("knits_made") or 0),
            "woven": int(my_knits.get("woven") or you.get("woven") or 0),
            "captured_spirals": len(captured_spirals),
            "backed_spirals": len(backed_spirals),
        },
        "woven_knits": woven_knits,
        "captured_spirals": captured_spirals,
        "backed_spirals": backed_spirals,
    }
    serializer = PortfolioSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.data)
