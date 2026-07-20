"""molgang#255 — the classic render layer must escape peer-influenced data.

Player names, terms, cids and other peer-supplied strings replicate between
clients, so any interpolation into ``innerHTML`` without ``esc()`` is a stored
XSS surface. These tests pin the sanitation pass across all three copies of the
client (web/, the serverless vendored byte-copy, and the PHP dapp) and the
allowlist sanitizer that replaced the raw ``innerHTML`` sink in i18n.js.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APP_COPIES = [
    ROOT / "web" / "app.js",
    ROOT / "serverless" / "web" / "app.js",
    ROOT / "php" / "public" / "app.js",
]
I18N_COPIES = [
    ROOT / "web" / "i18n.js",
    ROOT / "serverless" / "web" / "i18n.js",
]

# fields that carry peer-supplied or replicated strings; a bare `${x.<field>}`
# interpolation is exactly the pattern CodeQL flagged as js/xss.
PEER_FIELDS = (
    "name|by|term|title|topic|pid|cid|fiber_cid|fiber|label|ual|address|"
    "subject|object|relation|outcome|state_root"
)
RAW_SINK = re.compile(r"\$\{\s*[A-Za-z_$][\w$]*\.(?:%s)\s*\}" % PEER_FIELDS)

# known text-only sinks (never parsed as HTML): showToast() renders via
# textContent, and vis.js node titles are plain-text tooltips. Keyed by the
# exact line so any new use of the raw pattern still fails the scan.
ALLOWED_TEXT_SINKS = (
    'links · ${sp.by}`',                      # detectCaptures → showToast (textContent)
    'title: `${nd.address}\\n',               # runSim → vis.DataSet tooltip (plain text)
)


def test_no_raw_peer_field_interpolations():
    for path in APP_COPIES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if any(allowed in line for allowed in ALLOWED_TEXT_SINKS):
                continue
            hits = RAW_SINK.findall(line)
            assert not hits, f"unescaped peer-field interpolation in {path.name}: {line.strip()}"


def test_esc_helper_defined_and_used_everywhere():
    for path in APP_COPIES:
        js = path.read_text(encoding="utf-8")
        assert re.search(r"const esc = ", js), f"esc() helper missing in {path}"
        assert js.count("esc(") >= 40, (
            f"{path} uses esc() only {js.count('esc(')}× — sanitation pass looks reverted")


def test_serverless_copies_stay_in_vendored_parity():
    for name in ("app.js", "i18n.js"):
        web = (ROOT / "web" / name).read_bytes()
        vendored = (ROOT / "serverless" / "web" / name).read_bytes()
        assert web == vendored, f"serverless/web/{name} drifted from web/{name} — re-vendor"


def test_i18n_html_goes_through_the_allowlist_sanitizer():
    for path in I18N_COPIES:
        js = path.read_text(encoding="utf-8")
        assert "el.innerHTML = v" not in js, f"raw data-i18n-html innerHTML sink back in {path}"
        assert "sanitize" in js and "DOMParser" in js, f"allowlist sanitizer missing in {path}"
        # script/event vectors must not be allowlisted
        m = re.search(r"HTML_TAGS = new Set\(\[(.*?)\]\)", js, re.S)
        assert m and "SCRIPT" not in m.group(1) and "IMG" not in m.group(1)
        m = re.search(r"HTML_ATTRS = new Set\(\[(.*?)\]\)", js, re.S)
        assert m and "on" not in re.findall(r'"(\w+)"', m.group(1))


def test_hostile_name_fixture_is_escaped_by_esc():
    """The esc() table neutralizes the canonical payload from the issue."""
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    for entity in ('"&": "&amp;"', '"<": "&lt;"', '">": "&gt;"', "'\"': \"&quot;\""):
        assert entity in js, f"esc() replacement table lost {entity!r}"
