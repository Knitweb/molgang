#!/usr/bin/env python3
"""Django's command-line utility for the MOLGANG web front-end.

Run from anywhere with the engine on PYTHONPATH, e.g.::

    PYTHONPATH=src:/tmp/knitweb-py/src python3 molgang_web/manage.py runserver 8799
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # Make the project package (molgang_web/) importable without installing it,
    # so `manage.py` works regardless of the current working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "molgang_web.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available on your "
            "PYTHONPATH environment variable? Did you forget to activate a virtual "
            "environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
