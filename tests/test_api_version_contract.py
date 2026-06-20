"""Sprint 3 #58 — /api contract conformance.

The frozen /api contract (docs/API.md) declares a single `api_version`. All engines that serve
`/api/version` MUST agree on it, or a client cannot trust drift detection. This is a *textual*
cross-file check (no server start, no knitweb import) so it runs in any environment and catches the
most common drift: someone bumps one engine's version and forgets the others.

Engines checked:
  - canonical Python bar   src/molgang/webserver.py   (API_VERSION = "...")
  - PHP node               php/public/index.php       ('api_version' => '...')
  - contract doc           docs/API.md                ("api_version": "...")
The Django dapp reuses the Python `api_version_info()` (so it cannot diverge); we assert that reuse
structurally instead of parsing a literal.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _first(pattern: str, text: str, label: str) -> str:
    m = re.search(pattern, text)
    assert m, f"could not find api_version in {label}"
    return m.group(1)


def test_api_version_agrees_across_engines():
    python_v = _first(r'API_VERSION\s*=\s*["\']([^"\']+)["\']',
                      _read("src/molgang/webserver.py"), "webserver.py")
    php_v = _first(r"'api_version'\s*=>\s*'([^']+)'",
                   _read("php/public/index.php"), "php/public/index.php")
    doc_v = _first(r'"api_version":\s*"([^"]+)"',
                   _read("docs/API.md"), "docs/API.md")
    assert python_v == php_v == doc_v, (
        f"api_version drift — python={python_v!r} php={php_v!r} docs={doc_v!r}; "
        f"bump them together (Sprint 3 #58)."
    )


def test_django_reuses_canonical_version():
    views = _read("molgang_web/bar/views.py")
    # The Django version view must reuse api_version_info() (single source of truth),
    # not hardcode its own api_version literal that could silently diverge.
    assert "def version(" in views, "Django bar/views.py is missing the version view"
    assert "api_version_info" in views, (
        "Django version view must reuse molgang.webserver.api_version_info() so it stays in lockstep"
    )
    assert not re.search(r'["\']api_version["\']\s*[:=]', views), (
        "Django version view should not hardcode an api_version literal — reuse api_version_info()"
    )
