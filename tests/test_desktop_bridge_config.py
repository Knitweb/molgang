import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "php" / "desktop_bridge.py"


def load_bridge(monkeypatch: pytest.MonkeyPatch, dapp: str | None = None):
    if dapp is None:
        monkeypatch.delenv("KNODE_DAPP", raising=False)
    else:
        monkeypatch.setenv("KNODE_DAPP", dapp)

    spec = importlib.util.spec_from_file_location("desktop_bridge_under_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_desktop_bridge_requires_explicit_dapp(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = load_bridge(monkeypatch)

    with pytest.raises(SystemExit, match="set KNODE_DAPP or pass --dapp"):
        bridge._url("/api/presence")


def test_desktop_bridge_rejects_relative_dapp(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = load_bridge(monkeypatch, "/molgang")

    with pytest.raises(SystemExit, match="full http\\(s\\) URL"):
        bridge._url("/api/presence")


def test_desktop_bridge_uses_configured_dapp_without_default_host(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = load_bridge(monkeypatch, "https://relay.example/molgang/")

    assert bridge._url("/api/presence") == "https://relay.example/molgang/api/presence"
    assert "5mart.ml" not in BRIDGE.read_text()
