"""WSGI entrypoint for the MOLGANG web front-end."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "molgang_web.settings")

application = get_wsgi_application()
