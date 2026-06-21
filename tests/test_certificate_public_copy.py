from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_certificate_ui_promises_redaction_not_bearer_export() -> None:
    app = _read("web/app.js")
    index = _read("web/index.html")

    assert "browser endpoint is always redacted" in app
    assert "redacts private wallet material" in app
    assert "private wallet material is redacted" in index
    assert "exposes your wallet's PRIVATE key" not in app
    assert "exposes your wallet's PRIVATE key" not in index


def test_public_certificate_api_contract_has_no_client_bearer_mode() -> None:
    api = _read("docs/API.md")
    webserver = _read("src/molgang/webserver.py")

    assert "| `/api/certificate` | `{sid}` |" in api
    assert "always redacted" in api
    assert "bearer/private-key export is local CLI/operator-only" in api
    assert "bearer export is CLI/local only" in webserver
    assert "`{sid, mode?}`" not in api


def test_bearer_certificate_docs_require_explicit_cli_confirmation() -> None:
    readme = _read("README.md")
    architecture = _read("docs/ARCHITECTURE.md")
    cli = _read("src/molgang/cli.py")

    assert "--private --confirm-private-key-export" in readme
    assert "--private --confirm-private-key-export" in architecture
    assert "--private requires --confirm-private-key-export" in cli
