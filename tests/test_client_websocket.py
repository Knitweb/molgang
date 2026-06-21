from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "web" / "app.js"


def test_browser_client_subscribes_to_world_websocket() -> None:
    source = APP_JS.read_text()

    assert 'BASE + "/ws/world/"' in source
    assert 'url.searchParams.set("sid", sid || "")' in source
    assert "new WebSocket(worldSocketUrl())" in source


def test_world_state_messages_use_shared_render_path() -> None:
    source = APP_JS.read_text()

    assert 'payload.type === "world.state"' in source
    assert "renderState(payload.state)" in source
    assert "async function renderState(s)" in source
    assert "async function refresh()" in source
    assert "return renderState(s)" in source


def test_http_polling_is_fallback_when_websocket_is_closed() -> None:
    source = APP_JS.read_text()

    assert "if (isWorldSocketOpen()) return;" in source
    assert "refresh();" in source
    assert "connectWorldSocket();" in source
    assert "socket.onclose" in source
    assert "scheduleWorldSocketReconnect()" in source
