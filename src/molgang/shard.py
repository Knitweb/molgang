"""Deterministic concept sharding for the shared web (knitweb/molgang#97).

At 1M peers a relay's ``relay_message`` table and every peer's :class:`~molgang.world.World`
carrying the WHOLE concept graph is unbounded per-node memory and a single-topic fetch firehose.
This module partitions the graph by concept so a relay/node can hold and serve a SUBSET.

The shard key is a SHA-256 over the **same casefold term key** the World and relay-sync already
dedup on (:func:`molgang.relay_sync._term_key`), so a subject/object maps to the SAME shard on
every process and in every language — no reliance on ``hash()``/``PYTHONHASHSEED`` (that was the
#211 non-determinism bug). Items route to per-shard relay topics ``<base>.sNN``; a node subscribes
to the shards it cares about (default: all, so single-node installs are unchanged).
"""

from __future__ import annotations

import hashlib

from .relay_sync import WEB_TOPIC, _term_key

__all__ = ["shard_of", "item_shard", "shard_topic", "shard_topics", "WEB_TOPIC"]


def shard_of(term: str, n: int) -> int:
    """Shard index in ``[0, n)`` for ``term`` — SHA-256 over its casefold key, mod ``n``.

    Deterministic and stable across processes/languages: the same casefold key always
    maps to the same shard. ``n <= 1`` collapses to a single shard (index 0).
    """
    if n <= 1:
        return 0
    digest = hashlib.sha256(_term_key(term).encode("utf-8")).hexdigest()
    return int(digest, 16) % n


def item_shard(item, n: int) -> int:
    """The home shard of a woven item, keyed by its primary term.

    A term's own key; an edge/spiral by its **subject** (so both endpoints route stably and
    an edge has exactly one home shard). ``n <= 1`` ⇒ shard 0.
    """
    if n <= 1:
        return 0
    if item.kind == "link":
        primary = item.subject
    elif item.kind == "spiral":
        primary = item.links[0]["subject"] if item.links else item.term
    else:
        primary = item.term
    return shard_of(primary, n)


def shard_topic(base: str, shard: int) -> str:
    """The per-shard relay topic for ``base``, e.g. ``knitweb.web.s03``."""
    return f"{base}.s{shard:02d}"


def shard_topics(base: str, shards: int, subscribe=None) -> list[str]:
    """The topic list a node reads/writes.

    ``shards <= 1`` ⇒ ``[base]`` (exact back-compat, the un-suffixed topic). Otherwise one
    ``<base>.sNN`` per shard in ``subscribe`` (default: all shards).
    """
    if shards <= 1:
        return [base]
    idxs = range(shards) if subscribe is None else sorted({int(i) for i in subscribe})
    return [shard_topic(base, i) for i in idxs if 0 <= i < shards]
