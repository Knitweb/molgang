"""#139 — COPPA/GDPR-K: age/consent gate + no third-party trackers + compliance doc."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_walkin_has_an_age_consent_gate_that_disables_join():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="age-ok"' in html
    # the Walk-in button ships DISABLED (gate must pass before the faucet/join)
    assert re.search(r'id="go"[^>]*\bdisabled\b', html)
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "molgang_age_ok" in js                       # choice persists per device
    assert 'getElementById("age-ok")' in js and 'goBtn.disabled' in js


def test_age_gate_string_is_localised():
    import json
    for loc in ("en", "nl"):
        d = json.loads((ROOT / "web" / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "walkin.agegate" in d and d["walkin.agegate"]


def test_no_third_party_trackers_or_ad_sdks_in_shipped_web():
    """No behavioural profiling of minors: no analytics/ad/cross-site SDKs bundled."""
    # unambiguous SDK signatures (avoid physics words like "amplitude")
    banned = ("google-analytics.com", "googletagmanager.com", "gtag(", "fbq(",
              "connect.facebook.net", "doubleclick.net", "cdn.mixpanel", "cdn.segment.com",
              "cdn.amplitude", "static.hotjar", "fullstory.com", "browser.sentry-cdn")
    for f in (ROOT / "web").rglob("*"):
        if f.suffix in (".js", ".html") and f.is_file():
            text = f.read_text(encoding="utf-8", errors="ignore").lower()
            hits = [b for b in banned if b in text]
            assert not hits, f"{f.name} references a tracker/ad SDK: {hits}"


def test_compliance_doc_exists_with_launch_gate():
    doc = (ROOT / "docs" / "COMPLIANCE.md").read_text(encoding="utf-8")
    for must in ("COPPA", "GDPR-K", "Age gate", "right to erasure", "go/no-go",
                 "molgang_age_ok", "no behavioural profiling"):
        assert must.lower() in doc.lower(), must
