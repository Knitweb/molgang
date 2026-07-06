"""#117 — i18n layer for the bar chrome (EN + NL), no framework.

Pins the acceptance criteria: locale files stay in key-parity (a missing key can
only fall back EN → key, never a blank label), canonical protocol vocabulary is
never translated, the static chrome is data-i18n-annotated, the switcher
persists, and the service worker precaches the locale assets for offline boots.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "web" / "locales" / "en.json").read_text(encoding="utf-8"))
NL = json.loads((ROOT / "web" / "locales" / "nl.json").read_text(encoding="utf-8"))


def test_locales_have_identical_key_sets():
    assert set(EN) == set(NL), (
        f"only in en: {sorted(set(EN)-set(NL))}; only in nl: {sorted(set(NL)-set(EN))}")
    assert all(isinstance(v, str) and v for v in EN.values())
    assert all(isinstance(v, str) and v for v in NL.values())


def test_protocol_vocabulary_is_never_translated():
    """Canonical nouns (Knit, Pulse, Fiber, silk, PLS, Knitweb, spider) stay as-is
    in every locale — only the copy around them is translated."""
    for noun in ("Knit", "Fiber", "silk", "PLS", "pulse", "spider"):
        for key, en_val in EN.items():
            if noun.lower() in en_val.lower():
                assert noun.lower() in NL[key].lower(), (
                    f"protocol noun {noun!r} lost in nl[{key}]: {NL[key]!r}")


def test_index_chrome_is_annotated_and_has_a_switcher():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-title|-placeholder)?="([^"]+)"', html))
    used.discard("")  # bare data-i18n-html flag carries no key
    assert len(used) >= 40, f"chrome annotation looks thin: {len(used)} keys"
    missing = sorted(k for k in used if k not in EN)
    assert not missing, f"data-i18n keys without locale entries: {missing}"
    assert 'id="lang-switch"' in html
    # i18n.js must load before app.js so t() exists at boot
    assert html.index('src="i18n.js"') < html.index('src="app.js"')


def test_i18n_module_contract():
    js = (ROOT / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "molgang_locale" in js                          # persists the choice
    assert "documentElement.lang" in js                    # sets <html lang>
    assert "navigator.language" in js                      # default from browser
    assert "data-i18n" in js and "data-i18n-placeholder" in js and "data-i18n-title" in js
    assert 'en[key] ?? key' in js                          # missing key → EN → key


def test_app_delegates_and_dynamic_strings_use_keys():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "I18N.t(key" in js                              # t() delegates
    assert 'showToast(t("toast.reconnecting"))' in js
    assert 't("err.tooMany")' in js
    # the old inline dictionary is gone — locales/*.json are the single source
    assert "const STRINGS" not in js


def test_sw_precaches_locale_assets():
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    for asset in ("i18n.js", "locales/en.json", "locales/nl.json"):
        assert asset in sw, f"{asset} missing from the offline shell precache"
