"""Make `import molgang` work without hand-setting PYTHONPATH.

MOLGANG runs on the `knitweb` package (github.com/knitweb/pulse), which isn't on PyPI yet.
Rather than force every user to export ``PYTHONPATH``, we locate a knitweb checkout
automatically: if `knitweb` already imports (installed or already on the path) we do nothing;
otherwise we try, in order, ``$KNITWEB_SRC``, a sibling ``../pulse/src``, and ``~/repo/pulse/src``.
"""

from __future__ import annotations

import importlib.util
import os
import sys

_HINT = (
    "knitweb not found. Either:\n"
    "  • install it:        pip install -e /path/to/pulse\n"
    "  • or set the source:  export KNITWEB_SRC=/path/to/pulse/src\n"
    "  • or check out github.com/knitweb/pulse next to this repo (../pulse).\n"
)


def _candidates() -> list[str]:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
    out = []
    if os.environ.get("KNITWEB_SRC"):
        out.append(os.environ["KNITWEB_SRC"])
    out += [
        os.path.join(os.path.dirname(here), "pulse", "src"),  # sibling ../pulse/src
        os.path.join(here, "pulse", "src"),                   # nested ./pulse/src
        os.path.expanduser("~/repo/pulse/src"),
    ]
    return out


def ensure_knitweb() -> None:
    """Ensure the `knitweb` package is importable, adding a located checkout to sys.path."""
    if importlib.util.find_spec("knitweb") is not None:
        return
    for path in _candidates():
        if path and os.path.isdir(os.path.join(path, "knitweb")):
            sys.path.insert(0, os.path.abspath(path))
            if importlib.util.find_spec("knitweb") is not None:
                return
    raise ImportError(_HINT)
