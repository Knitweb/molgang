"""MOLGANG ⇄ Knitweb — the two-way bridge, alternating every 30 minutes.

Run this every 30 min (cron). It **alternates direction** by an internal cursor:

    even tick  → UPLOAD   : ingest the latest Roblox votes export → weave into the knitweb
    odd  tick  → DOWNLOAD : write the canonical knitweb snapshot for molgang/Roblox to apply

So each direction syncs **hourly**, and *something* syncs every **30 minutes** — uploads and
downloads never run in the same tick (no write/read race on a half-hour boundary).

    # cron: */30 * * * *
    PYTHONPATH=src:/path/to/pulse/src python3 bridge/sync.py \
        --state .molgang/state.json \
        --export .molgang/inbox_votes.json \
        --snapshot .molgang/outbox_snapshot.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from bridge.ingest import ingest
from bridge.snapshot import snapshot
from bridge.state import load_state, save_state


def step(state_path: str, export_path: str, snapshot_path: str,
         *, now: str | None = None) -> dict:
    """Run exactly one sync step (upload or download) and flip the cursor."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = load_state(state_path)
    cursor = int(state.get("cursor", 0))
    direction = "upload" if cursor % 2 == 0 else "download"

    if direction == "upload":
        with open(export_path, encoding="utf-8") as fh:
            export = json.load(fh)
        prior_balances = {rid: p["pulses"] for rid, p in state["players"].items()}
        prior_silk = {rid: p["silk"] for rid, p in state["players"].items()}
        summ = ingest(export, prior_balances=prior_balances, prior_silk=prior_silk)
        for rid, addr in summ["knitweb_addresses"].items():
            state["players"][rid] = {
                "address": addr, "pulses": summ["balances"][rid], "silk": summ["silk"][rid],
            }
        for w in summ["bonds_woven"]:
            state["web"][w["formula"]] = {
                "name": w["name"], "fiber_cid": w["fiber_cid"],
                "by": w["by"], "confirmations": w["confirmations"], "ts": now,
            }
        info = {"direction": direction, "wallets": summ["roblox_wallets_ingested"],
                "woven_now": len(summ["bonds_woven"]), "web_size": len(state["web"])}
    else:  # download
        snap = snapshot(state, ts=now)
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=2, ensure_ascii=False)
        info = {"direction": direction, "confirmed": len(snap["confirmed_formulas"]),
                "players": len(snap["players"]), "snapshot": snapshot_path}

    state["cursor"] = cursor + 1
    state["updated_at"] = now
    save_state(state_path, state)
    return info


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG two-way bridge (alternating, every 30 min)")
    ap.add_argument("--state", default=".molgang/state.json")
    ap.add_argument("--export", default="bridge/sample_roblox_votes.json")
    ap.add_argument("--snapshot", default=".molgang/outbox_snapshot.json")
    ap.add_argument("--now", default=None, help="override timestamp (tests)")
    a = ap.parse_args(argv[1:])
    info = step(a.state, a.export, a.snapshot, now=a.now)
    arrow = "Roblox → Knitweb" if info["direction"] == "upload" else "Knitweb → molgang"
    print(f"MOLGANG sync [{info['direction']:<8}] {arrow}  {info}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
