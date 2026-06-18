"""ASGI entrypoint for the MOLGANG web front-end.

Plain Django ASGI for now. Live updates (Channels/websockets) are deferred to a
follow-up increment; this file gives that work a home to grow into.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "molgang_web.settings")

application = get_asgi_application()
