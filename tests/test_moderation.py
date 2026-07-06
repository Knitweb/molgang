"""#140 — content moderation: pre-weave filter + report -> takedown -> tombstone."""
import pytest

from molgang.bar import Bar
from molgang.moderation import ModerationError, screen


def test_screen_passes_chemistry_blocks_pii_and_profanity():
    assert screen("H2O") == (True, "")
    assert screen("V2O3 + O2 -> V2O5 @ 850C roast")[0]
    assert screen("mail me a@b.com") == (False, "pii:email")
    assert screen("call 0612345678") == (False, "pii:digits")
    assert screen("you idiot kut")[1] == "profanity"
    assert screen("glucose")[0]                          # a real term with no false positive


def test_abusive_term_is_blocked_at_propose_before_weaving():
    bar = Bar(world_path=None)
    me = bar.join("P", table_id="periodic", device="d")
    bar.sit(me.sid, "periodic")
    silk_before = me.player.silk
    with pytest.raises(ModerationError):
        bar.propose(me.sid, "contact me at kid@school.com")
    assert me.player.silk == silk_before                 # no silk spent on a blocked term


def test_report_takedown_tombstones_and_audits():
    bar = Bar(world_path=None)
    a = bar.join("A", table_id="periodic", device="da")
    bar.sit(a.sid, "periodic")
    prop = bar.propose(a.sid, "H2O")
    assert prop.woven
    cid = prop.fiber_cid

    b = bar.join("B", table_id="periodic", device="db")
    r = bar.report_term(b.sid, cid, "test")
    assert r["total_reports"] == 1

    # graph shows the term until takedown
    assert any(not x["redacted"] and x["fiber"] == cid for x in bar.world.graph()["recent"])
    entry = bar.takedown(cid, moderator="mod-1")
    assert entry["action"] == "takedown" and entry["moderator"] == "mod-1"
    # redacted in the fabric display, audit recorded, report queue cleared
    row = next(x for x in bar.world.graph()["recent"] if x["fiber"] == cid)
    assert row["redacted"] and row["label"] == "[redacted]"
    assert bar.moderation_audit()[-1]["cid"] == cid
    assert not [x for x in bar.reports() if x["cid"] == cid]


def test_report_channel_is_rate_limited():
    bar = Bar(world_path=None)
    s = bar.join("S", table_id="periodic", device="ds")
    for i in range(bar.MAX_REPORTS_PER_PLAYER):
        bar.report_term(s.sid, f"cid{i}", "x")
    with pytest.raises(RuntimeError):
        bar.report_term(s.sid, "one-too-many", "x")


def test_takedown_keeps_state_root_stable_append_only():
    bar = Bar(world_path=None)
    a = bar.join("A", table_id="periodic", device="da")
    bar.sit(a.sid, "periodic")
    cid = bar.propose(a.sid, "H2O").fiber_cid
    root_before = bar.world.state_root()
    bar.takedown(cid, moderator="m")
    assert bar.world.state_root() == root_before         # redaction never rewrites history
