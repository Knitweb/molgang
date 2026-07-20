"""Cross-region fleet aggregation (#131) — union-dedup by pubkey per docs/MEASUREMENT.md rule 1."""
from molgang import fleet


def _stub(telemetry_by_base):
    """An opener that serves canned telemetry for <base>/telemetry, else raises (unreachable)."""
    def opener(url, data=None):
        base = url[: -len("/telemetry")]
        if base in telemetry_by_base:
            return telemetry_by_base[base]
        raise OSError("unreachable")
    return opener


def test_a_wallet_on_two_relays_counts_once():
    # peer "AA" is active on BOTH relays; the fleet total must dedup it to ONE.
    tel = {
        "https://eu/api/relay":  {"peer_pubkeys": ["AA", "BB"], "knits_per_sec": 2.0, "peers_online": 2},
        "https://us/api/relay":  {"peer_pubkeys": ["AA", "CC"], "knits_per_sec": 1.0, "peers_online": 2},
    }
    out = fleet.aggregate(list(tel), opener=_stub(tel))
    assert out["concurrent_peers_total"] == 3          # {AA, BB, CC} — NOT 2+2=4
    assert out["concurrent_peers_deduped"] == 3
    assert out["scope"] == "fleet"
    assert out["knits_per_sec"] == 3.0                 # useful work IS additive
    assert out["reachable"] == 2 and out["total"] == 2
    assert out["degraded"] is False


def test_unreachable_relay_is_skipped_not_fatal():
    tel = {"https://eu/api/relay": {"peer_pubkeys": ["AA"], "knits_per_sec": 1.0}}
    out = fleet.aggregate(["https://eu/api/relay", "https://down/api/relay"], opener=_stub(tel))
    assert out["concurrent_peers_total"] == 1
    assert out["reachable"] == 1 and out["total"] == 2
    down = next(r for r in out["relays"] if "down" in r["base"])
    assert down["reachable"] is False


def test_degraded_relay_without_pubkeys_is_lower_bound_flagged():
    # an older relay exposes only the count → additive lower bound, flagged degraded
    tel = {
        "https://eu/api/relay":  {"peer_pubkeys": ["AA", "BB"], "knits_per_sec": 0.0},
        "https://old/api/relay": {"peers_online": 5, "knits_per_sec": 0.0},   # no peer_pubkeys
    }
    out = fleet.aggregate(list(tel), opener=_stub(tel))
    assert out["degraded"] is True
    assert out["concurrent_peers_deduped"] == 2
    assert out["concurrent_peers_lower_bound_add"] == 5
    assert out["concurrent_peers_total"] == 7          # 2 exact + 5 lower-bound
    old = next(r for r in out["relays"] if "old" in r["base"])
    assert old["degraded"] is True


def test_empty_pool_is_zero_not_error():
    out = fleet.aggregate([], opener=_stub({}))
    assert out["concurrent_peers_total"] == 0 and out["reachable"] == 0
    assert out["scope"] == "fleet" and out["gta6_reference_peers"] == 1_000_000
