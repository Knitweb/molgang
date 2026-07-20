"""Cross-region fleet aggregation — the 1M/GTA6 total across a pool of relays (#131).

A single relay reports only *its own* concurrent-peer slice (``Relay::telemetry`` /
``Bar.telemetry``, both ``scope`` != ``fleet``). The honest cross-region total is **not** a sum
of those counts — a wallet active from two regions would be double-counted, violating rule 1 of
``docs/MEASUREMENT.md`` ("one wallet = one peer, no matter how many regions it appears from").

So :func:`aggregate` **unions the deduped pubkey sets** each relay exposes in
``telemetry.peer_pubkeys`` and counts the union — a wallet on relay A *and* relay B is one peer.
Useful-work throughput *is* additive (distinct events on distinct relays), so ``knits_per_sec``
sums. The result is labelled ``scope="fleet"`` so it is never confused with a single relay.

Relays whose ``peer_pubkeys`` is absent (an older relay that only exposes the count) fall back to
their reported ``peers_online`` as a **lower bound** contribution, flagged in ``degraded`` — an
honest under-or-at count, never an inflated one.

The relay list comes from :func:`molgang.relay_sync.discover_relays` (#98 bootstrap) or an
explicit pool; this module only reads ``/api/relay/telemetry`` and never writes.
"""

from __future__ import annotations

import json
import ssl
import urllib.request

_HTTP_TIMEOUT = 8


def _tls_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch_telemetry(base: str, opener=None) -> dict | None:
    """GET ``<base>/telemetry`` → parsed dict, or None on any transport/parse error."""
    url = base.rstrip("/") + "/telemetry"
    if opener is not None:
        try:
            return opener(url, None)
        except Exception:
            return None
    try:
        req = urllib.request.Request(url)
        ctx = _tls_context() if url.lower().startswith("https") else None
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as r:
            data = json.loads(r.read() or b"{}")
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# The GTA6 win condition (docs/MEASUREMENT.md) — mirrored so the fleet total is self-describing.
GTA6_REFERENCE_PEERS = 1_000_000
WIN_TARGET_PEERS = 1_000_000
WIN_SUSTAIN_MIN = 30


def aggregate(relay_bases, *, opener=None) -> dict:
    """Union the per-relay telemetry into ONE fleet total (``scope="fleet"``).

    ``relay_bases`` is a list of relay API bases (e.g. from
    :func:`molgang.relay_sync.discover_relays`). Returns:

    * ``concurrent_peers_total`` — size of the UNION of every relay's ``peer_pubkeys`` (dedup by
      pubkey across regions), plus any degraded relays' ``peers_online`` lower bound;
    * ``knits_per_sec`` / ``useful_work_per_sec`` — summed across reachable relays (additive);
    * ``relays`` — per-relay ``{base, peers, reachable, degraded}`` breakdown;
    * ``reachable`` / ``total`` relay counts, and the GTA6 reference/win fields.
    """
    bases = list(relay_bases)
    union: set[str] = set()
    degraded_lb = 0            # lower-bound contribution from relays without a pubkey set
    knits = 0.0
    per_relay: list[dict] = []
    reachable = 0
    degraded_any = False

    for base in bases:
        t = _fetch_telemetry(base, opener=opener)
        if not isinstance(t, dict):
            per_relay.append({"base": base, "peers": 0, "reachable": False, "degraded": False})
            continue
        reachable += 1
        knits += float(t.get("knits_per_sec") or 0.0)
        pubs = t.get("peer_pubkeys")
        if isinstance(pubs, list) and all(isinstance(p, str) for p in pubs):
            before = len(union)
            union.update(pubs)
            per_relay.append({"base": base, "peers": len(pubs), "reachable": True,
                              "degraded": False, "new_unique": len(union) - before})
        else:
            # older relay: only a count is available → additive LOWER BOUND (may double-count a
            # cross-region wallet, so it is flagged, never silently folded into the exact union)
            lb = int(t.get("peers_online") or 0)
            degraded_lb += lb
            degraded_any = True
            per_relay.append({"base": base, "peers": lb, "reachable": True, "degraded": True})

    total = len(union) + degraded_lb
    return {
        "concurrent_peers_total": total,
        "concurrent_peers_deduped": len(union),      # exact union (relays exposing the set)
        "concurrent_peers_lower_bound_add": degraded_lb,
        "knits_per_sec": round(knits, 3),
        "useful_work_per_sec": round(knits, 3),
        "scope": "fleet",
        "degraded": degraded_any,                    # True if any relay lacked the pubkey set
        "relays": per_relay,
        "reachable": reachable,
        "total": len(bases),
        "gta6_reference_peers": GTA6_REFERENCE_PEERS,
        "win_target_peers": WIN_TARGET_PEERS,
        "win_sustain_min": WIN_SUSTAIN_MIN,
    }
