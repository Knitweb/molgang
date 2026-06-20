"""URL map for the MOLGANG bar — dual-play API + the dapp UI served at the root.

API routes are registered first; the static catch-all only matches non-``api/`` asset
paths (``app.js``, ``style.css``, ``avatars/<x>.svg``), so the existing client — which uses
relative asset URLs and a path-prefix-safe BASE — runs over Django unchanged.
"""

from __future__ import annotations

from django.urls import path, re_path

from . import views

urlpatterns = [
    # --- dual-play JSON API (mirrors molgang/webserver.py) ---
    path("api/version", views.version),
    path("api/state", views.state),
    path("api/pulse", views.pulse),
    path("api/suggested", views.suggested),
    path("api/web", views.web),
    path("api/device", views.device),
    path("api/graph", views.graph),
    path("api/join", views.join),
    path("api/sit", views.sit),
    path("api/propose", views.propose),
    path("api/vote", views.vote),
    path("api/spiral/propose", views.spiral_propose),
    path("api/spiral/vote", views.spiral_vote),
    # --- server-rendered HTMX partials (#28 slices) ---
    path("partials/account-pill", views.account_pill),
    # --- dapp UI (the shared web/ folder, at the site root) ---
    path("", views.index),
    # any non-api asset path (app.js, style.css, avatars/foo.svg)
    re_path(r"^(?!api/)(?P<path>.+)$", views.static_asset),
]
