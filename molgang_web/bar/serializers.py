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


class TxToastSerializer(serializers.Serializer):
    kind = serializers.CharField()
    tone = serializers.ChoiceField(choices=["info", "success", "warning", "error"])
    title = serializers.CharField()
    message = serializers.CharField(allow_blank=True)
    subject = serializers.CharField(allow_blank=True)
    fiber_cid = serializers.CharField(allow_blank=True)
    fiber_short = serializers.CharField(allow_blank=True)
    pulses = serializers.IntegerField(min_value=0)
    woven = serializers.BooleanField()


class ExplorerColumnSerializer(serializers.Serializer):
    rank = serializers.IntegerField(min_value=1)
    pid = serializers.CharField(allow_blank=True)
    term = serializers.CharField()
    lang = serializers.CharField()
    dir = serializers.ChoiceField(choices=["ltr", "rtl"])
    by = serializers.CharField(allow_blank=True)
    net = serializers.IntegerField()
    woven = serializers.BooleanField()
    settled = serializers.BooleanField()
    outcome = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    fiber_cid = serializers.CharField(allow_blank=True)
    fiber_short = serializers.CharField(allow_blank=True)
    votes = serializers.DictField(child=serializers.IntegerField(min_value=0))


class ExplorerTopicSerializer(serializers.Serializer):
    topic = serializers.CharField()
    lang = serializers.CharField()
    dir = serializers.ChoiceField(choices=["ltr", "rtl"])
    competing = serializers.IntegerField(min_value=0)
    columns = ExplorerColumnSerializer(many=True)


class ExplorerSerializer(serializers.Serializer):
    lang = serializers.CharField()
    empty = serializers.BooleanField()
    rows = ExplorerTopicSerializer(many=True)


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


def _clean_lang(lang: str | None) -> str:
    code = (lang or "en").split(",", 1)[0].strip().lower()
    return (code or "en")[:16]


def base_direction(label: str) -> str:
    """Return the Unicode base direction for a label without external dependencies."""
    for char in str(label or ""):
        cp = ord(char)
        if 0x0590 <= cp <= 0x08FF or 0xFB1D <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF:
            return "rtl"
    return "ltr"


def explorer_from_state(snapshot: dict, *, lang: str | None = None) -> dict:
    """Return validated Explorer data from the canonical ``/api/state`` shape."""
    code = _clean_lang(lang)
    rows = []
    for group in snapshot.get("explorer") or []:
        columns = []
        for rank, col in enumerate(group.get("columns") or [], start=1):
            term = str(col.get("term") or "")
            fiber = str(col.get("fiber_cid") or "")
            votes = col.get("votes") or {}
            columns.append(
                {
                    "rank": rank,
                    "pid": str(col.get("pid") or ""),
                    "term": term,
                    "lang": code,
                    "dir": base_direction(term),
                    "by": str(col.get("by") or ""),
                    "net": int(col.get("net") or 0),
                    "woven": bool(col.get("woven")),
                    "settled": bool(col.get("settled")),
                    "outcome": col.get("outcome"),
                    "fiber_cid": fiber,
                    "fiber_short": f"{fiber[:16]}..." if fiber else "",
                    "votes": {
                        "confirm": int(votes.get("confirm") or 0),
                        "mismatch": int(votes.get("mismatch") or 0),
                        "abstain": int(votes.get("abstain") or 0),
                        "total": int(votes.get("total") or 0),
                    },
                }
            )
        topic = str(group.get("topic") or "")
        rows.append(
            {
                "topic": topic,
                "lang": code,
                "dir": base_direction(topic),
                "competing": int(group.get("competing") or len(columns)),
                "columns": columns,
            }
        )
    data = {"lang": code, "empty": not rows, "rows": rows}
    serializer = ExplorerSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.data)


def _find_knit(snapshot: dict, pid: str) -> dict | None:
    if not pid:
        return None
    mine = (snapshot.get("my_knits") or {}).get("knits") or []
    for row in mine:
        if row.get("pid") == pid:
            return row
    for group in snapshot.get("explorer") or []:
        for row in group.get("columns") or []:
            if row.get("pid") == pid:
                return row
    for table in snapshot.get("tables") or []:
        for row in table.get("open") or []:
            if row.get("pid") == pid:
                return row
    return None


def _spiral_path(links: list) -> str:
    parts: list[str] = []
    for raw in links:
        left, sep, right = str(raw).partition("→")
        if not sep:
            continue
        if not parts:
            parts.append(left.strip())
        parts.append(right.strip())
    return " → ".join(p for p in parts if p)


def _find_spiral(snapshot: dict, cid: str) -> dict | None:
    if not cid:
        return None
    for table in snapshot.get("tables") or []:
        table_name = str(table.get("name") or table.get("id") or "")
        for row in table.get("spirals") or []:
            if row.get("cid") == cid:
                votes = row.get("votes") or {}
                return {
                    "cid": cid,
                    "term": _spiral_path(row.get("links") or []),
                    "table": table_name,
                    "state": str(row.get("state") or "open"),
                    "length": int(row.get("length") or 0),
                    "pulses": int(votes.get("total") or 0),
                    "woven": False,
                    "fiber_cid": "",
                }
        for item in table.get("fabric") or []:
            if item.get("spiral") and item.get("cid") == cid:
                return {
                    "cid": cid,
                    "term": str(item.get("term") or ""),
                    "table": table_name,
                    "state": "captured",
                    "length": int(item.get("length") or str(item.get("term") or "").count("→")),
                    "pulses": int(item.get("confirmations") or 0),
                    "woven": True,
                    "fiber_cid": str(item.get("fiber_cid") or ""),
                }
    return None


def tx_toast_from_state(snapshot: dict, kind: str, *, pid: str = "", cid: str = "") -> dict | None:
    """Return an HTMX toast model derived from canonical ``/api/state`` data."""
    kind = (kind or "").strip().lower()
    data: dict | None = None

    if kind in {"knit", "propose", "proposal"}:
        row = _find_knit(snapshot, pid)
        if row:
            votes = row.get("votes") or {}
            fiber = str(row.get("fiber_cid") or "")
            woven = bool(row.get("woven"))
            data = {
                "kind": "knit",
                "tone": "success" if woven else "info",
                "title": "Knit woven" if woven else "Knit proposed",
                "message": "Peers accepted this knit into the fabric." if woven
                else "Your knit is open for peer pulses.",
                "subject": str(row.get("term") or ""),
                "fiber_cid": fiber,
                "fiber_short": f"{fiber[:16]}..." if fiber else "",
                "pulses": int(votes.get("total") or 0),
                "woven": woven,
            }
    elif kind in {"vote", "pulse"}:
        row = _find_knit(snapshot, pid)
        if row:
            votes = row.get("votes") or {}
            fiber = str(row.get("fiber_cid") or "")
            woven = bool(row.get("woven"))
            data = {
                "kind": "vote",
                "tone": "success" if woven else "info",
                "title": "Pulse recorded" if not woven else "Pulse reached quorum",
                "message": "Your pulse was counted." if not woven
                else "Quorum wove this knit into the fabric.",
                "subject": str(row.get("term") or ""),
                "fiber_cid": fiber,
                "fiber_short": f"{fiber[:16]}..." if fiber else "",
                "pulses": int(votes.get("total") or 0),
                "woven": woven,
            }
    elif kind in {"spiral", "capture"}:
        row = _find_spiral(snapshot, cid)
        if row:
            fiber = str(row.get("fiber_cid") or "")
            woven = bool(row.get("woven"))
            data = {
                "kind": "spiral",
                "tone": "success" if woven else "info",
                "title": "Spiral captured" if woven else "Spiral pulse recorded",
                "message": "The captured spiral is now woven into the fabric." if woven
                else "Your pulse is backing this open spiral.",
                "subject": str(row.get("term") or row.get("cid") or ""),
                "fiber_cid": fiber,
                "fiber_short": f"{fiber[:16]}..." if fiber else "",
                "pulses": int(row.get("pulses") or 0),
                "woven": woven,
            }

    if data is None:
        return None
    serializer = TxToastSerializer(data=data)
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
