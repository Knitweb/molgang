"""Django views mirroring the stdlib server's endpoints (``molgang/webserver.py``).

These views delegate to the shared ``Bar`` singleton and return the SAME JSON shapes as
the stdlib server, so the existing ``web/`` client (and any bot) works unchanged. No game
logic lives here — only request parsing + delegation.

API (dual-play: humans via the browser, machines via JSON):

    GET  /api/state?sid=…                 full bar snapshot
    POST /api/join     {name,avatar,table,device}   walk in (+ optionally sit)
    POST /api/sit      {sid,table}
    POST /api/propose  {sid,term}
    POST /api/vote     {sid,pid,verdict}
    POST /api/spiral/propose {sid,links|text}
    POST /api/spiral/vote    {sid,cid,verdict}
    GET  /api/web                          shared web view + anchor
    GET  /api/graph?term=&from=&to=        explore the woven graph
    GET  /api/device?id=…                  device -> wallet registration lookup

Plus the stdlib server's extras (kept for client parity): /api/pulse, /api/suggested.
"""

from __future__ import annotations

import mimetypes
import os

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from molgang.bar import suggested_terms

from .engine import get_bar

# This Django wrapper does not bootstrap a host Pulse identity (that needs the external Pulse
# CLI/node). The stdlib server attaches its host status here; we attach None, which the
# client and state shape already tolerate (`state["pulse_host"] = pulse_host`).
PULSE_HOST: dict | None = None


def _error(exc: Exception):
    return Response({"error": str(exc)}, status=400)


# ---- read endpoints --------------------------------------------------------
@api_view(["GET"])
def state(request):
    bar = get_bar()
    sid = request.GET.get("sid")
    snapshot = bar.state(sid)
    snapshot["pulse_host"] = PULSE_HOST
    return Response(snapshot)


@api_view(["GET"])
def pulse(request):
    return Response(PULSE_HOST or {})


@api_view(["GET"])
def version(request):
    # /api/version — contract drift check (Sprint 3 #58). Reuse the canonical bar's version
    # computation so api_version/molgang/knitweb stay in lockstep; only the engine differs.
    from molgang.webserver import api_version_info
    return Response({**api_version_info(), "engine": "django"})


@api_view(["GET"])
def suggested(request):
    return Response({"terms": suggested_terms()})


@api_view(["GET"])
def web(request):
    return Response(get_bar().web_view())


@api_view(["GET"])
def device(request):
    bar = get_bar()
    did = request.GET.get("id", "") or ""
    reg = bar.registry.get(did) if (bar.registry and did) else None
    return Response({"registered": bool(reg), "wallet": reg})


@api_view(["GET"])
def graph(request):
    bar = get_bar()
    return Response(
        bar.world.explore(
            term=request.GET.get("term"),
            frm=request.GET.get("from"),
            to=request.GET.get("to"),
        )
    )


# ---- write endpoints -------------------------------------------------------
@api_view(["POST"])
def join(request):
    bar = get_bar()
    b = request.data or {}
    try:
        s = bar.join(
            b.get("name", "guest"),
            b.get("avatar"),
            b.get("table"),
            device=b.get("device"),
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)
    return Response(
        {"sid": s.sid, "avatar": s.avatar, "address": s.player.node.address}
    )


@api_view(["POST"])
def sit(request):
    bar = get_bar()
    b = request.data or {}
    try:
        bar.sit(b["sid"], b["table"])
        return Response(bar.state(b["sid"]))
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)


@api_view(["POST"])
def propose(request):
    bar = get_bar()
    b = request.data or {}
    try:
        p = bar.propose(b["sid"], b["term"])
        return Response({"pid": p.pid})
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)


@api_view(["POST"])
def vote(request):
    bar = get_bar()
    b = request.data or {}
    try:
        p = bar.vote(b["sid"], b["pid"], b.get("verdict", "confirm"))
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)
    return Response(
        {"pid": p.pid, "settled": p.settled, "outcome": p.outcome, "woven": p.woven}
    )


@api_view(["POST"])
def spiral_propose(request):
    bar = get_bar()
    b = request.data or {}
    links = b.get("links") or [x for x in (b.get("text", "")).splitlines() if x.strip()]
    try:
        sv = bar.propose_spiral(b["sid"], links)
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)
    return Response({"cid": sv.cid, "length": sv.length, "state": sv.round.state})


@api_view(["POST"])
def spiral_vote(request):
    bar = get_bar()
    b = request.data or {}
    try:
        sv = bar.vote_spiral(b["sid"], b["cid"], b.get("verdict", "confirm"))
    except (KeyError, RuntimeError, ValueError) as exc:
        return _error(exc)
    return Response(
        {
            "cid": sv.cid,
            "settled": sv.settled,
            "captured": sv.captured,
            "votes": sv.breakdown(),
        }
    )


# ---- static dapp UI (the shared web/ folder, served at the site root) -------
def _safe_web_path(rel: str) -> str:
    web_dir = os.path.abspath(str(settings.MOLGANG_WEB_DIR))
    rel = "index.html" if rel in ("", "/") else rel.lstrip("/")
    full = os.path.normpath(os.path.join(web_dir, rel))
    if not full.startswith(web_dir) or not os.path.isfile(full):
        raise Http404("not found")
    return full


def index(request):
    """Serve the dapp shell (``web/index.html``) at the site root."""
    return _serve_file(_safe_web_path("index.html"))


def static_asset(request, path: str):
    """Serve a sibling asset (``app.js``, ``style.css``, ``avatars/<x>.svg``) at the root.

    The vanilla JS client requests these with relative paths, so they must resolve at the
    same path level as ``index.html``.
    """
    return _serve_file(_safe_web_path(path))


def _serve_file(full: str) -> FileResponse:
    ctype, _ = mimetypes.guess_type(full)
    if full.endswith(".js"):
        ctype = "text/javascript"
    return FileResponse(open(full, "rb"), content_type=ctype or "application/octet-stream")
