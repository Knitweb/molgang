"""Django settings for the MOLGANG web front-end.

This is a thin Django wrapper around the existing (Django-free) ``molgang``/``knitweb``
engine. The engine is imported lazily from a process singleton (see ``bar.engine``);
Django never reaches into the game logic beyond the public ``Bar`` API.

Dev-oriented defaults (DEBUG, ALLOWED_HOSTS=['*']). Tighten for any real deployment.
"""

from __future__ import annotations

import os
from pathlib import Path

# molgang_web/molgang_web/settings.py -> molgang_web/
BASE_DIR = Path(__file__).resolve().parent.parent
# the repo root (…/molgang) that holds the shared `web/` UI folder
REPO_ROOT = BASE_DIR.parent

SECRET_KEY = os.environ.get("MOLGANG_SECRET_KEY", "dev-insecure-molgang-key-change-me")

# Dev defaults — do NOT use as-is in production.
DEBUG = os.environ.get("MOLGANG_DEBUG", "1") != "0"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "bar",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "molgang_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "molgang_web.wsgi.application"

# The engine keeps its own state in the knitweb world file + sqlite registry, so Django's
# ORM is unused. Point at an in-memory sqlite to satisfy framework checks without a real DB.
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
}

# The shared `web/` dapp UI (index.html, app.js, style.css, avatars/) lives at the repo root.
# The vanilla JS client uses RELATIVE asset paths and a path-prefix-safe BASE, so we serve
# the whole folder at the site root (see bar.urls).
MOLGANG_WEB_DIR = Path(os.environ.get("MOLGANG_WEB_DIR", REPO_ROOT / "web"))

# Engine state locations (shared across requests via the Bar singleton). Defaults match the
# engine's own defaults (~/.molgang/...). Override per-deploy / per-test via env.
MOLGANG_WORLD = os.environ.get("MOLGANG_WORLD")        # None -> engine default world path
MOLGANG_REGISTRY = os.environ.get("MOLGANG_REGISTRY")  # None -> no device registry

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # The engine itself is the source of truth and does its own auth via PLS wallets;
    # the dual-play API is intentionally open (same as the stdlib server).
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}
