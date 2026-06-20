"""Process-singleton access to the (Django-free) MOLGANG engine.

One ``Bar`` is created lazily, once per worker process, and shared across all requests.
The ``Bar`` keeps the live game state (tables, seats, open knits, the shared knitweb world);
every Django view delegates to it rather than reimplementing any game logic.

The engine knows nothing about Django — Django imports it, never the reverse.
"""

from __future__ import annotations

import threading

from django.conf import settings

from molgang.bar import Bar
from molgang.registry import Registry

_lock = threading.Lock()
_bar: Bar | None = None
PULSE_HOST: dict | None = None


def _build_bar() -> Bar:
    world_path = getattr(settings, "MOLGANG_WORLD", None)
    registry_path = getattr(settings, "MOLGANG_REGISTRY", None)
    registry = Registry(registry_path) if registry_path else None
    return Bar(world_path, registry)


def get_bar() -> Bar:
    """Return the process-wide ``Bar`` singleton, creating it on first use.

    Thread-safe: Django's dev server (and most WSGI workers) handle requests on
    multiple threads, and the engine state must be shared, not per-thread.
    """
    global _bar
    if _bar is None:
        with _lock:
            if _bar is None:
                _bar = _build_bar()
    return _bar


def state_snapshot(sid: str | None = None) -> dict:
    """Return the canonical `/api/state` shape for Django HTTP and websocket paths."""
    snapshot = get_bar().state(sid)
    snapshot["pulse_host"] = PULSE_HOST
    return snapshot


def pulse_host() -> dict | None:
    return PULSE_HOST


def reset_bar() -> None:
    """Drop the singleton so the next ``get_bar()`` rebuilds it.

    Intended for tests that want a fresh, isolated bar; not used at runtime.
    """
    global _bar
    with _lock:
        _bar = None
