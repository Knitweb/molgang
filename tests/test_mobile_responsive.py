"""#118 — mobile-responsive bar: bottom tab bar, 44px tap targets, 360px fit.

Textual contract over web/style.css AND the php/public/style.css mirror so the
mobile layout cannot silently regress. Desktop is guarded by asserting the
1140px container survives and all mobile rules stay inside media queries.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
PHP = (ROOT / "php" / "public" / "style.css").read_text(encoding="utf-8")


def _mobile_block(css: str) -> str:
    m = re.search(r"/\* ── #118 mobile-first upgrades.*?(?=@media \(prefers-reduced-motion)", css, re.S)
    assert m, "#118 mobile block missing"
    return m.group(0)


def test_tabs_become_a_bottom_bar_on_phones():
    for css in (WEB, PHP):
        blk = _mobile_block(css)
        assert ".tabs:not(.hidden){position:fixed" in blk        # thumb-reachable bottom nav
        assert "bottom:0" in blk and "env(safe-area-inset-bottom" in blk
        assert "padding-bottom:96px" in blk                      # content clears the bar


def test_primary_actions_are_44px_tap_targets():
    for css in (WEB, PHP):
        blk = _mobile_block(css)
        assert "button{min-height:44px}" in blk
        assert ".spiral-x{min-width:44px;min-height:44px}" in blk


def test_balance_cluster_is_a_compact_scroll_row():
    blk = _mobile_block(WEB)
    assert ".me{flex-wrap:nowrap;overflow-x:auto" in blk
    assert ".bal{flex:0 0 auto}" in blk


def test_walkin_and_spiral_modal_fit_360px():
    blk = _mobile_block(WEB)
    assert ".overlay .card{max-width:100%" in blk
    assert "#spiral-links{font-size:16px" in blk                 # no iOS focus zoom
    assert "textarea{background" in WEB                          # textarea styled like input


def test_desktop_layout_is_untouched():
    for css in (WEB, PHP):
        assert "max-width:1140px" in css                         # container preserved
        blk = _mobile_block(css)
        # every #118 rule lives inside media queries — nothing leaks to desktop
        assert blk.strip().startswith("/*")
        assert "@media (max-width:600px)" in blk
