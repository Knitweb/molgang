"""PHP-UI Monitor tab parity (#83): the php/public dapp carries the same Monitor tab
surface as the static web/ UI — tab button, section, render functions over GET
/api/monitor — and every server-supplied string it renders is escaped."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "php/public/index.html").read_text()
APP = (ROOT / "php/public/app.js").read_text()


def test_monitor_tab_button_and_section_exist() -> None:
    assert 'data-view="monitor"' in HTML                  # tab chrome, like web/index.html
    assert 'id="monitor"' in HTML
    for anchor in ("mon-node", "mon-roster", "mon-relay", "mon-web", "mon-anchor",
                   "mon-game", "mon-telemetry"):
        assert f'id="{anchor}"' in HTML, anchor


def test_monitor_view_is_wired_into_the_tab_switch() -> None:
    # both hidden-view lists know the new view, and the switch shows/renders it
    assert APP.count('"monitor"]') >= 2
    assert 'view === "monitor"' in APP
    assert "renderMonitor()" in APP


def test_render_functions_read_the_php_monitor_shape() -> None:
    # the issue's canonical trio, reading Monitor::summary() fields
    for fn in ("async function renderMonitor", "function renderMonStatus",
               "function renderMonKg"):
        assert fn in APP, fn
    assert '"/api/monitor"' in APP
    for field in ("registry", "online_list", "telemetry", "state_root", "game"):
        assert field in APP, field


def test_monitor_rendering_escapes_server_strings() -> None:
    # every interpolated server string goes through mesc() — no raw innerHTML sinks
    assert "const mesc" in APP
    for sink in ("mesc(p.address)", "mesc(p.endpoint", "mesc(w.ual)",
                 "mesc((w.state_root"):
        assert sink in APP, sink


def test_full_monitor_page_still_linked() -> None:
    # the standalone monitor.html stays reachable from the tab (deep-dive view)
    assert 'href="monitor.html"' in HTML
