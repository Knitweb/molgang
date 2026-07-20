"""Fleet telemetry (#131) — node-scoped 1M/GTA6 scoreboard, keyed to docs/MEASUREMENT.md.

The count is HONEST: a concurrent peer is a distinct HUMAN session, live in-window AND past the
activity floor (has woven a real Fiber). Bots (synthetic) and idle-but-present humans do not count.
"""
from molgang.bar import Bar


def _weave_a_term(bar, sess):
    """Propose a term at a full NPC table so the quorum weaves it immediately."""
    # 3 seeded bots per table back a proposal to quorum on propose.
    bar.propose(sess.sid, "H2O")


def test_telemetry_shape_and_reference(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    t = bar.telemetry()
    # metric names + GTA6 reference exactly as the dashboard/MEASUREMENT.md expect
    for k in ("peers_online", "knits_per_sec", "useful_work_per_sec", "window_s", "scope",
              "gta6_reference_peers", "win_target_peers", "win_sustain_min"):
        assert k in t, k
    assert t["scope"] == "node"
    assert t["gta6_reference_peers"] == 1_000_000
    assert t["win_target_peers"] == 1_000_000


def test_presence_alone_does_not_count_activity_floor(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    me = bar.join("Edwin", "laser-maxi", "periodic")
    # present but has woven nothing yet → below the activity floor, not concurrent
    assert bar.telemetry()["peers_online"] == 0
    assert bar.telemetry()["peers_present_human"] == 1


def test_a_human_who_wove_counts_once(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    me = bar.join("Edwin", "laser-maxi", "periodic")
    _weave_a_term(bar, me)
    t = bar.telemetry()
    assert t["peers_online"] == 1                 # now past the activity floor
    assert t["useful_work_events"] >= 1           # the woven Fiber is in-window
    assert t["useful_work_per_sec"] > 0


def test_bots_are_excluded_as_synthetic(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))           # seeds 3 NPC bots per table
    # no human has joined/woven → the synthetic bots must never inflate the human count
    assert bar.telemetry()["peers_online"] == 0
    assert bar.telemetry()["peers_present_human"] == 0
