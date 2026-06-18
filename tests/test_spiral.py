"""Spirals — auxiliary→capture lifecycle, conserved PLS, contagion silk, web weave."""
from knitweb.pouw import quorum

from molgang import game, graphx, progression
from molgang.chemistry import link_is_sound
from molgang.game import Player
from molgang.knit_parse import spiral_links
from molgang.world import World


def test_spiral_links_and_soundness():
    links = spiral_links(["H2O -> O2", "O2 -> O3"])
    assert len(links) == 2 and links[0]["subject"] == "H2O" and links[0]["object"] == "O2"
    assert link_is_sound(links[0]) and link_is_sound(links[1])
    assert not link_is_sound({"kind": "link", "subject": "", "object": "x"})


def test_capture_pays_leader_and_conserves_pls():
    leader = Player.from_device("leader", pulses=0, silk=10)
    backers = [Player.from_device(f"b{i}") for i in range(3)]
    links = spiral_links(["H2O -> O2", "O2 -> O3"])
    before = leader.pulses + sum(b.pulses for b in backers)
    sr = game.propose_spiral(leader, links)
    assert sr.state == "auxiliary"
    for b in backers:
        game.cast_spiral_vote(sr, b)                      # honest → confirm (all links sound)
    s = game.settle_spiral(sr)
    assert s.captured and sr.state == "capture"
    assert s.reward == 3 * sr.stake_per_vote == 6         # 3 backers × (1 PLS × 2 links)
    assert leader.pulses == s.reward
    assert leader.pulses + sum(b.pulses for b in backers) == before   # PLS conserved
    assert all(b.silk >= 10 + game.CONTAGION_SILK for b in backers)   # contagion silk


def test_rejected_spiral_full_refund():
    leader = Player.from_device("L2", silk=10)
    backers = [Player.from_device(f"r{i}") for i in range(3)]
    sr = game.propose_spiral(leader, spiral_links(["H2O -> O2", "O2 -> O3"]))
    before = [b.pulses for b in backers]
    for b in backers:
        game.cast_spiral_vote(sr, b, quorum.Verdict.MISMATCH)
    s = game.settle_spiral(sr)
    assert not s.captured and [b.pulses for b in backers] == before   # full integer refund


def test_reputation_threshold_only_raises_when_valid():
    base = quorum.default_threshold(5)
    assert progression.reputation_threshold([1, 1, 1], 5) == base
    hi = progression.reputation_threshold([7, 7, 7, 7, 7], 5)
    assert hi >= base and hi <= 5 and 2 * hi > 5


def test_weave_spiral_grows_web_and_persists(tmp_path):
    w = World(str(tmp_path / "w.json"))
    links = spiral_links(["H2O -> O2", "O2 -> O3"])
    w.weave_spiral(links, "alice", "fcid", 3, validators=3, pls_staked=6)
    n, e = w.size()
    assert e >= 2 and n >= 3
    w2 = World(str(tmp_path / "w.json"))
    assert w2.size() == (n, e)
    g = graphx.build(w2.items)
    assert g.has_edge("H2O", "O2") and g.has_edge("O2", "O3")
