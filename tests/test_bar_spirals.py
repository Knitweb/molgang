"""Spirals in the bar — propose, NPC backing, capture, web growth, leaderboard."""
from molgang.bar import Bar


def test_solo_leader_captures_a_spiral(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))                 # 3 NPC bots auto-seated per table
    me = bar.join("Edwin", "laser-maxi", "periodic")
    sv = bar.propose_spiral(me.sid, ["H2O -> O2", "O2 -> O3"])   # bots back it immediately
    assert sv.settled and sv.captured                   # 3 bots → ≥3 quorum → captured
    assert bar.web_view()["edges"] >= 2                 # both links woven as edges
    st = bar.state(me.sid)
    tbl = next(t for t in st["tables"] if t["id"] == "periodic")
    assert tbl["spiral_record"] >= 2
    assert any(row["length"] >= 2 for row in st["spiral_leaderboard"])


def test_spiral_needs_links(tmp_path):
    bar = Bar(str(tmp_path / "w2.json"))
    me = bar.join("A", table_id="organic")
    try:
        bar.propose_spiral(me.sid, ["just one term"])   # not a link
        assert False, "should reject non-link lines"
    except ValueError:
        pass
