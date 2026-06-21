from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_3d_graph_static_copies_stay_identical() -> None:
    assert (ROOT / "web/knitweb-graph-3d.html").read_text() == (
        ROOT / "php/public/knitweb-graph-3d.html"
    ).read_text()


def test_3d_graph_live_endpoint_is_same_origin_or_operator_configured() -> None:
    html = (ROOT / "web/knitweb-graph-3d.html").read_text()

    assert "MOLGANG_GRAPH_ENDPOINTS" in html
    assert "explorer-graph.json" in html
    assert "https://5mart.ml/molgang/explorer-graph.json" not in html


def test_3d_graph_vr_hint_is_capability_gated() -> None:
    html = (ROOT / "web/knitweb-graph-3d.html").read_text()

    assert "isSessionSupported('immersive-vr')" in html
    assert "hint.style.display=ok?'block':'none'" in html
    assert "#vrbtn,#vrbtn button,#vrbtn a{top:126px!important;bottom:auto!important}" in html
