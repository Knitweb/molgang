"""Owner: 'na levels moeten weer knits (silk) verdiend worden' — level-up silk grants."""
from molgang import game
from molgang.bar import Bar
from molgang.registry import Registry


def test_level_up_grants_fresh_silk_once(tmp_path):
    reg = Registry(str(tmp_path / "reg.db"))
    bar = Bar(str(tmp_path / "world.json"), registry=reg)
    me = bar.join("Leveler", "laser-maxi", "periodic", device="dev-lvl-1")
    start = me.player.silk

    bar.propose(me.sid, "H2O")                     # woven -> 100 XP -> level 2
    # -1 spun, +1 restored on weave, +LEVEL_SILK_GRANT for the level-up
    assert me.player.silk == start + game.LEVEL_SILK_GRANT

    bar.propose(me.sid, "CO2")                     # 200 XP -> still level 2: no new grant
    assert me.player.silk == start + game.LEVEL_SILK_GRANT
    assert reg.get_granted_level("dev-lvl-1") == 2


def test_grants_survive_restart_without_double_paying(tmp_path):
    reg = Registry(str(tmp_path / "reg.db"))
    bar1 = Bar(str(tmp_path / "world.json"), registry=reg)
    a = bar1.join("Restarter", "laser-maxi", "periodic", device="dev-lvl-2")
    bar1.propose(a.sid, "H2O")                     # level 2 granted
    silk_after = a.player.silk

    bar2 = Bar(str(tmp_path / "world.json"), registry=reg)   # the restart
    b = bar2.join("Restarter", "laser-maxi", "periodic", device="dev-lvl-2")
    assert b.player.silk == silk_after             # restored, not re-granted
    bar2.propose(b.sid, "NaCl")                    # 200 XP: still level 2 -> no grant
    assert b.player.silk == silk_after
    bar2.propose(b.sid, "CH4")                     # 300 XP -> level 3 -> one grant
    assert b.player.silk == silk_after + game.LEVEL_SILK_GRANT


def test_rejected_knits_really_cost_silk(tmp_path):
    """The counter DOES go down when peers reject — only confirmed work restores silk."""
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Sloppy", "laser-maxi", "periodic", device="dev-lvl-3")
    start = me.player.silk
    prop = bar.propose(me.sid, "H2 + O2 -> H2O @ spark")     # unbalanced -> rejected
    assert not prop.woven
    assert me.player.silk == start - game.SILK_PER_BOND
