"""FIBER TENSION (v1): integer tautness math, tension-weighted routing + slack pruning.

Everything here is asserted as exact integers — the module must be float-free so two nodes
always compute the identical value (consensus-safe).
"""

from __future__ import annotations

from molgang import graphx
from molgang import tension as T
from molgang.world import WovenItem


# -- tautness / tension / band math (pure integer) ----------------------------
def test_outputs_are_integers_never_float():
    f = T.Fiber(confirms=9, mismatches=2, anchor_rel=200, anchor_ts=0)
    for v in (T.tautness(f), T.tension(f), T.friction(f), T.edge_cost(f)):
        assert isinstance(v, int)          # no floats anywhere
    assert T.tautness(f) == (7 * 200 * T.S) // (7 * 200 + T.K_ANCHOR * T.S)


def test_tautness_bounds_and_monotonic_in_confirms():
    weak = T.Fiber(confirms=1, mismatches=0, anchor_rel=100)
    strong = T.Fiber(confirms=500, mismatches=0, anchor_rel=1000)
    assert 0 <= T.tautness(weak) <= T.S
    assert 0 <= T.tautness(strong) <= T.S
    assert T.tautness(strong) > T.tautness(weak)     # more agreeing evidence → tauter
    # more confirms only ever raises (or holds) T, never lowers it
    prev = -1
    for c in range(1, 40):
        t = T.tautness(T.Fiber(confirms=c, mismatches=0, anchor_rel=300))
        assert t >= prev
        prev = t


def test_net_evidence_zero_or_negative_is_slack():
    # mismatches >= confirms → net<=0 → T=0 → SLACK
    f = T.Fiber(confirms=3, mismatches=3, anchor_rel=500)
    assert T.tautness(f) == 0
    assert T.band(f) == T.SLACK
    assert T.tautness(T.Fiber(confirms=2, mismatches=5, anchor_rel=500)) == 0


def test_no_anchor_starts_slack_ish():
    # anchor_rel == 0 (no anchor) → T = 0 regardless of confirms
    assert T.tautness(T.Fiber(confirms=50, mismatches=0, anchor_rel=0)) == 0


def test_band_cutoffs_taut_neutral_slack():
    # a well-anchored, well-voted fiber is TAUT
    taut = T.Fiber(confirms=200, mismatches=0, anchor_rel=1000)
    assert T.tautness(taut) >= T.TAUT_T and T.band(taut) == T.TAUT
    # a thinly-voted one sits NEUTRAL
    neutral = T.Fiber(confirms=3, mismatches=0, anchor_rel=400)
    assert T.SLACK_T <= T.tautness(neutral) < T.TAUT_T
    assert T.band(neutral) == T.NEUTRAL
    # a barely-net fiber is SLACK
    slack = T.Fiber(confirms=1, mismatches=0, anchor_rel=20)
    assert T.tautness(slack) < T.SLACK_T and T.band(slack) == T.SLACK


def test_hysteresis_prevents_band_flap():
    # a fiber whose T sits in the [TAUT_T-HYST, TAUT_T) window stays TAUT if it was TAUT
    f = T.Fiber(confirms=7, mismatches=0, anchor_rel=300)
    t = T.tautness(f)
    assert T.TAUT_T - T.HYST <= t < T.TAUT_T          # land it inside the hysteresis band
    assert T.band(f, prev=T.TAUT) == T.TAUT           # was taut → stays taut
    assert T.band(f, prev=T.NEUTRAL) == T.NEUTRAL     # was neutral → not promoted yet


def test_tension_and_snap_quality_gate():
    # low reliability + counter-evidence → tension crosses SNAP_CRIT → CONTESTED
    bad = T.Fiber(confirms=2, mismatches=10, anchor_rel=5)
    assert T.tension(bad) == (10 * T.S) // (5 + 1)
    assert T.tension(bad) >= T.SNAP_CRIT
    assert T.is_snap(bad) and T.band(bad) == T.CONTESTED
    # a well-anchored fiber resists snapping under the SAME counter-evidence
    anchored = T.Fiber(confirms=2, mismatches=10, anchor_rel=1000)
    assert T.tension(anchored) < T.SNAP_CRIT and not T.is_snap(anchored)


def test_age_decay_lowers_tautness_at_read_time_only():
    now = 100 * T.HALF_LIFE_SECS
    fresh = T.Fiber(confirms=20, mismatches=0, anchor_rel=800, anchor_ts=now)
    stale = T.Fiber(confirms=20, mismatches=0, anchor_rel=800, anchor_ts=1)  # ancient (epoch 1s)
    assert T.tautness(stale, now) < T.tautness(fresh, now)
    # decay never mutated the stored counters
    assert stale.confirms == 20 and stale.mismatches == 0


def test_edge_cost_inverse_of_tautness():
    taut = T.Fiber(confirms=300, mismatches=0, anchor_rel=1000)
    slack = T.Fiber(confirms=1, mismatches=0, anchor_rel=15)
    assert T.edge_cost(taut) < T.edge_cost(slack)     # taut = cheap, slack = dear
    assert T.edge_cost(taut) >= T.BASE                # never zero/negative (Dijkstra-safe)
    assert T.edge_cost(T.Fiber(snapped=True)) is None  # snapped → excluded (infinite)


def test_vote_ops_mutate_counters():
    f = T.Fiber(confirms=1, mismatches=0, anchor_rel=100)
    T.vote_up(f); T.vote_up(f)
    assert f.confirms == 3
    T.vote_down(f)
    assert f.mismatches == 1
    # enough negative votes against weak reliability eventually snaps
    f2 = T.Fiber(confirms=1, mismatches=0, anchor_rel=2)
    for _ in range(20):
        T.vote_down(f2)
    assert T.is_snap(f2)


def test_overflow_caps_stay_in_int64():
    f = T.Fiber(confirms=10**9, mismatches=0, anchor_rel=10**9)  # over the caps
    c = f.clamped()
    assert c.confirms == T.COUNTER_CAP and c.anchor_rel == T.R_MAX
    assert 0 <= T.tautness(f) <= T.S                   # still bounded, no overflow blow-up


# -- tension-weighted routing prefers the taut route --------------------------
def _routing_items():
    """Two routes A→D: a TAUT 2-hop (via B) vs a SLACK 1-hop (A→D direct).

    The slack direct edge is fewer hops but high-cost; the taut detour is cheaper, so the
    tension-weighted path must pick the detour even though plain shortest-path (hops) would
    take the direct edge.
    """
    return [
        # taut spine: high confirms, strong anchor → low cost
        WovenItem("link", "n", "f1", 50, subject="A", object="B", relation="x"),
        WovenItem("link", "n", "f2", 50, subject="B", object="D", relation="x"),
        # slack shortcut: 1 confirm, weak anchor → high cost
        _slack_item("A", "D"),
    ]


def _slack_item(s, o):
    it = WovenItem("link", "n", "fs", 1, subject=s, object=o, relation="x")
    it.anchor_rel = 10        # weak anchor → low tautness → high cost
    return it


def test_taut_path_prefers_taut_route_over_slack_shortcut():
    g = graphx.build(_routing_items())
    # boost anchor reliability on the taut spine so it is clearly TAUT
    for u, v in (("A", "B"), ("B", "D")):
        g[u][v]["fiber"].anchor_rel = 1000
    res = graphx.taut_path(g, "A", "D")
    assert res["path"] == ["A", "B", "D"]             # took the tauter 2-hop, not the slack hop
    # plain hop-based shortest path would instead take the 1-hop direct edge
    plain = graphx.path(g, "A", "D")
    assert plain["path"] == ["A", "D"] and plain["hops"] == 1
    assert res["hops"] == 2 and res["cost"] is not None


def test_taut_path_excludes_snapped_fiber():
    items = [
        WovenItem("link", "n", "f1", 50, subject="A", object="B", relation="x"),
        WovenItem("link", "n", "f2", 50, subject="B", object="C", relation="x"),
        WovenItem("link", "n", "f3", 50, subject="A", object="C", relation="x"),
    ]
    g = graphx.build(items)
    for u, v in (("A", "B"), ("B", "C"), ("A", "C")):
        g[u][v]["fiber"].anchor_rel = 1000
    # snap the direct A→C fiber
    g["A"]["C"]["fiber"].snapped = True
    res = graphx.taut_path(g, "A", "C")
    assert res["path"] == ["A", "B", "C"]             # routed around the snapped fiber


# -- slack pruning ------------------------------------------------------------
def test_prune_slack_removes_slack_and_snapped_keeps_taut():
    items = [
        WovenItem("link", "n", "f1", 50, subject="A", object="B", relation="x"),  # will be taut
        _slack_item("C", "D"),                                                    # slack
        WovenItem("link", "n", "f3", 50, subject="E", object="F", relation="x"),  # will be snapped
    ]
    g = graphx.build(items)
    g["A"]["B"]["fiber"].anchor_rel = 1000            # TAUT
    g["E"]["F"]["fiber"].snapped = True               # snapped
    assert g.number_of_edges() == 3
    report = graphx.prune_slack(g)
    assert report["pruned"] == 2
    assert {"from": "C", "to": "D"} in report["slack"]
    assert {"from": "E", "to": "F"} in report["snapped"]
    assert g.has_edge("A", "B")                        # taut survives
    assert not g.has_edge("C", "D") and not g.has_edge("E", "F")


def test_tension_stats_payload():
    g = graphx.build(_routing_items())
    g["A"]["B"]["fiber"].anchor_rel = 1000
    g["B"]["D"]["fiber"].anchor_rel = 1000
    stats = graphx.tension_stats(g)
    assert stats["edges"] == 3
    assert set(stats["bands"]) == {T.TAUT, T.NEUTRAL, T.SLACK, T.CONTESTED}
    assert sum(stats["bands"].values()) == 3
    assert isinstance(stats["avg_tautness"], int) and isinstance(stats["avg_cost"], int)
    assert stats["thresholds"]["snap_crit"] == T.SNAP_CRIT


# -- back-compat: fibers synthesised from a gateway.App store (weight only) ----
def test_store_edges_get_fiber_from_weight():
    g = graphx.build_from_web(graphx.sample_web())
    # subgraph edges now carry a tension band derived from weight=confirm count
    sg = graphx.subgraph(g, "H2O", depth=1)
    assert all("tension_band" in e for e in sg["edges"])
    assert graphx.tension_stats(g)["edges"] >= 1
