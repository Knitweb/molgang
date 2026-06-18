"""Root URLConf — delegate everything to the ``bar`` app.

The ``bar`` app serves both the dapp UI (the shared ``web/`` folder) at the site root
and the dual-play JSON API under ``/api/``.
"""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("", include("bar.urls")),
]
