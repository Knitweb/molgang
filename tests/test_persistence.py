"""Device balance persistence — a wallet's pulses + silk survive a server restart.

The Bar engine is in-memory, so without persistence a device's PLS/silk would reset to the
faucet default on every fresh Bar. These tests drive a device-backed player through real
balance-changing events, then spin up a FRESH Bar with the same registry + device and assert
the balances are restored exactly (not the faucet default).
"""
from molgang import game
from molgang.bar import Bar, FAUCET_GENESIS_DATE
from molgang.game import FAUCET_PULSES, FAUCET_SILK
from molgang.registry import Registry


def test_initial_join_snapshots_faucet_balance(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    # a fresh device opens the faucet at the day's decaying grant; pin genesis (day 0)
    Bar(str(tmp_path / "w.json"), reg).join(
        "Edwin", "laser-maxi", "periodic", device="phone-1", today=FAUCET_GENESIS_DATE)
    saved = reg.get_balance("phone-1")
    assert saved == {"pulses": game.current_faucet_pulses(0), "silk": FAUCET_SILK}
    assert saved["pulses"] == 10_000_000


def test_knit_balance_survives_restart(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    db, world = str(tmp_path / "r.db"), str(tmp_path / "w.json")

    # --- session 1: device proposes a real molecule; bots confirm → woven → rewarded ---
    bar1 = Bar(world, reg)
    me = bar1.join("Edwin", "laser-maxi", "periodic", device="phone-1")
    bar1.propose(me.sid, "H2O")                       # spends silk; bots auto-vote confirm
    prop = next(p for p in bar1.proposals.values() if p.by == me.sid)
    assert prop.settled and prop.woven                # peer-confirmed useful work
    earned_pulses, earned_silk = me.player.pulses, me.player.silk
    assert earned_pulses > FAUCET_PULSES              # protocol reward + vote pot
    assert reg.get_balance("phone-1") == {"pulses": earned_pulses, "silk": earned_silk}

    # --- session 2: a FRESH Bar with the same registry + device restores the balance ---
    bar2 = Bar(world, Registry(db))
    me2 = bar2.join("Edwin", "laser-maxi", "periodic", device="phone-1")
    assert me2.player.node.address == me.player.node.address
    assert me2.player.pulses == earned_pulses != FAUCET_PULSES   # restored, not faucet default
    assert me2.player.silk == earned_silk


def test_spiral_spend_survives_restart(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    db, world = str(tmp_path / "r.db"), str(tmp_path / "w.json")

    bar1 = Bar(world, reg)
    me = bar1.join("Edwin", "laser-maxi", "periodic", device="phone-2")
    bar1.propose_spiral(me.sid, ["H2O -> O2", "O2 -> O3"])   # leader spends escalating silk
    spent_pulses, spent_silk = me.player.pulses, me.player.silk
    assert spent_silk < FAUCET_SILK                          # silk was spent on the spiral
    assert reg.get_balance("phone-2") == {"pulses": spent_pulses, "silk": spent_silk}

    bar2 = Bar(world, Registry(db))
    me2 = bar2.join("Edwin", "laser-maxi", "periodic", device="phone-2")
    assert me2.player.pulses == spent_pulses
    assert me2.player.silk == spent_silk != FAUCET_SILK      # restored spent silk, not faucet


def test_guest_and_bots_are_not_persisted(tmp_path):
    reg = Registry(str(tmp_path / "r.db"))
    bar = Bar(str(tmp_path / "w.json"), reg)
    guest = bar.join("Anon", "laser-maxi", "periodic")       # no device → guest
    bar.propose(guest.sid, "H2O")
    # only the device table is keyed by device; a guest has no device row at all
    assert reg.get_balance(None) is None
    # bots never get a balance snapshot
    for s in bar.sessions.values():
        if s.bot:
            assert reg.get_balance(s.sid) is None
