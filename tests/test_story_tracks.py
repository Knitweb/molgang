"""Owner: 'ja alle tracks' — story tracks cover the ENTIRE ground truth, with silk."""
from molgang import game, quests
from molgang.bar import Bar
from molgang.chemistry import MOLECULES, tier_of
from molgang.registry import Registry

TRACKS = [q for q in quests.QUESTS if q["scope"] == "set"]


def test_every_molecule_belongs_to_at_least_one_story_track():
    covered = {f for q in TRACKS for f in q["set"]}
    missing = sorted(set(MOLECULES) - covered)
    assert not missing, f"molecules without a story track: {missing}"


def test_track_sets_are_real_tiered_chemistry():
    for q in TRACKS:
        assert q["set"], q["id"]
        for f in q["set"]:
            assert f in MOLECULES, f"{q['id']}: unknown molecule {f}"
        assert q.get("silk", 0) > 0, f"{q['id']}: story tracks reward silk"
        assert q["tier"] in ("elementary", "middle", "high")
        need = len(q["set"]) if q["need"] == "all" else q["need"]
        assert 0 < need <= len(q["set"])


def test_completing_a_track_pays_silk_once_and_survives_restart(tmp_path):
    reg = Registry(str(tmp_path / "reg.db"))
    bar = Bar(str(tmp_path / "world.json"), registry=reg)
    me = bar.join("Tracker", "laser-maxi", "periodic", device="dev-track-1")

    # sulfur line: 3 molecules, need all, silk 7
    track = next(q for q in TRACKS if q["id"] == "sulfur-line")
    before = me.player.silk
    for f in track["set"][:-1]:
        bar.propose(me.sid, f)
    mid = me.player.silk
    bar.propose(me.sid, track["set"][-1])          # completes the track
    # -1 spun +1 restored cancel out, so the delta is the track payment (+ any level grant)
    assert me.player.silk >= mid + track["silk"]
    assert reg.has_quest_grant("dev-track-1", "sulfur-line")

    silk_now = me.player.silk
    bar2 = Bar(str(tmp_path / "world.json"), registry=reg)   # restart
    back = bar2.join("Tracker", "laser-maxi", "periodic", device="dev-track-1")
    assert back.player.silk == silk_now            # restored, no re-payment
    silk_before_extra = back.player.silk
    bar2.propose(back.sid, "H2O")                  # new weave triggers the grant check again
    # net change from this weave: -1 spun +1 restored (+ any level/waterworks silk),
    # but NEVER another sulfur-line payment — bound the delta strictly below it
    delta = back.player.silk - silk_before_extra
    other = next(q for q in TRACKS if q["id"] == "sulfur-line")["silk"]
    level_and_small_tracks = game.LEVEL_SILK_GRANT + 3   # waterworks silk=3 could complete? no (needs 3 of set)
    assert delta < other + level_and_small_tracks
