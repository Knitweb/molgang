"""MOLGANG hourly bridge — ingest Roblox votes and weave them into the Knitweb.

The Roblox counterpart (`roblox/`) plays the same game locally and, once an hour,
exports the votes its players cast (`roblox/VoteExport.lua` → a JSON like
`sample_roblox_votes.json`). This bridge reads that export and **brei/weaves** it into
the real Knitweb:

  * each unique **Roblox wallet ID** maps to a *stable* knitweb account
    (`Player.from_roblox`), so a Roblox player has one consistent on-web identity;
  * every exported vote is replayed as a *real* Knit (a staked pulse);
  * the real `pouw.quorum` tallies each bond; confirmed bonds are woven (a Fiber).

Run hourly (cron):  PYTHONPATH=src:../pulse/src python3 bridge/ingest.py bridge/sample_roblox_votes.json
"""

from __future__ import annotations

import json
import sys

from knitweb.pouw import quorum

from molgang.game import Player, cast_vote, propose, settle


def ingest(export: dict) -> dict:
    """Weave one hourly Roblox export into the Knitweb. Returns a summary."""
    players: dict[str, Player] = {}

    def player_for(roblox_id: str) -> Player:
        # stable, deterministic account per unique Roblox wallet ID (persists across hours)
        if roblox_id not in players:
            players[roblox_id] = Player.from_roblox(roblox_id)
        return players[roblox_id]

    woven, rejected = [], []
    for r in export.get("rounds", []):
        bond = r["bond"]
        proposer = player_for(r["proposer_roblox_id"])
        rnd = propose(proposer, bond["formula"], bond["name"])
        for vote in r["votes"]:
            voter = player_for(vote["roblox_id"])
            verdict = quorum.Verdict(vote["verdict"])      # replay the Roblox player's real vote
            cast_vote(rnd, voter, verdict)
        s = settle(rnd)
        rec = {"formula": bond["formula"], "name": bond["name"],
               "outcome": s.outcome.value, "votes": len(rnd.votes)}
        if s.woven:
            rec["woven_fiber_cid"] = s.woven_fiber_cid
            woven.append(rec)
        else:
            rejected.append(rec)

    return {
        "roblox_wallets_ingested": len(players),
        "knitweb_addresses": {rid: p.address for rid, p in players.items()},
        "bonds_woven": woven,
        "bonds_rejected": rejected,
    }


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "bridge/sample_roblox_votes.json"
    export = json.load(open(path, encoding="utf-8"))
    summary = ingest(export)
    print(f"== MOLGANG bridge — wove {len(summary['bonds_woven'])} bond(s) from "
          f"{summary['roblox_wallets_ingested']} Roblox wallet(s) ==\n")
    for rid, addr in summary["knitweb_addresses"].items():
        print(f"  roblox {rid!r:>16} → knitweb {addr[:22]}…")
    print()
    for b in summary["bonds_woven"]:
        print(f"  ✅ {b['formula']:<8} {b['name']:<18} {b['outcome']:<10} "
              f"woven Fiber {b['woven_fiber_cid'][:18]}…")
    for b in summary["bonds_rejected"]:
        print(f"  ❌ {b['formula']:<8} {b['name']:<18} {b['outcome']} (not woven)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
