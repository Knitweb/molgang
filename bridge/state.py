"""Persistent MOLGANG↔Knitweb projection shared by the two-way bridge.

A small JSON the bridge carries between sync cycles so balances and woven bonds accumulate:

    cursor   : alternation counter (even ⇒ next step uploads, odd ⇒ next downloads)
    players  : roblox_id -> {address, pulses, silk}     (continued across cycles)
    web      : formula   -> {name, fiber_cid, by, confirmations, ts}  (the woven chemistry)

For production, the authoritative accounts/braids persist via ``knitweb.store``; this
projection is the molgang-facing view both directions sync on.
"""

from __future__ import annotations

import json
import os


def _default() -> dict:
    return {"cursor": 0, "updated_at": None, "players": {}, "web": {}}


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return _default()


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
