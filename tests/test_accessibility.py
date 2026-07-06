"""#119 — accessibility + RTL for the bar chrome."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")


def test_tabs_are_a_semantic_tablist():
    assert 'role="tablist"' in HTML
    assert HTML.count('role="tab"') >= 7          # every view tab
    assert 'aria-selected="true"' in HTML         # the active tab
    assert 'setAttribute("aria-selected"' in JS   # kept in sync on switch


def test_icon_only_controls_and_toast_are_labelled():
    assert 'id="toast"' in HTML and 'aria-live="polite"' in HTML
    for label in ('id="me-cert"', 'id="leave-table"', 'id="spiral-close"'):
        block = HTML[HTML.index(label):HTML.index(label) + 200]
        assert "aria-label=" in block, label
    assert 'role="dialog"' in HTML and 'aria-modal="true"' in HTML   # spiral modal


def test_keyboard_operability_esc_closes_modal():
    assert 'e.key === "Escape"' in JS and "closeSpiralModal()" in JS


def test_rtl_base_direction_is_applied_for_rtl_locales():
    assert 'documentElement.dir' in JS
    assert '"ar"' in JS and '"rtl"' in JS         # AR triggers rtl
    assert 'i18n:changed' in JS                   # re-applied on locale switch
    assert '[dir="rtl"]' in CSS                   # chrome mirrors


def test_visible_focus_ring_and_contrast_bump():
    assert ":focus-visible" in CSS and "outline" in CSS
    # the dimmed-text colour was lifted for AA contrast on the dark theme
    assert re.search(r"--dim:\s*#a7b6cf", CSS)
