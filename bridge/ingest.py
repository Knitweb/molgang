"""MOLGANG bridge — UPLOAD: ingest Roblox votes and weave them into the Knitweb.

The Roblox counterpart (`roblox/`) plays the same game locally and exports the votes its
players cast (`roblox/VoteExport.lua` → a JSON like `sample_roblox_votes.json`). This module
**brei/weaves** that export into the real Knitweb:

  * each unique **Roblox wallet ID** maps to a *stable* knitweb account
    (`Player.from_roblox`), its balance continued from prior sync cycles;
  * every exported vote is replayed as a *real* Knit (a staked pulse);
  * the real `pouw.quorum` tallies each bond; confirmed bonds are woven (a Fiber).

This is the **upload** half of the two-way sync (see `bridge/sync.py`); the **download** half
lives in `bridge/snapshot.py`.
"""

from __future__ import annotations

import json
import sys

from knitweb.pouw import quorum

from molgang.game import Player, cast_vote, propose, settle


def ingest(export: dict, *, prior_balances: dict | None = None,
           prior_silk: dict | None = None) -> dict:
    """Weave one export into the Knitweb. ``prior_*`` continue players across cycles."""
    prior_balances = prior_balances or {}
    prior_silk = prior_silk or {}
    players: dict[str, Player] = {}

    def player_for(roblox_id: str) -> Player:
        if roblox_id not in players:
            players[roblox_id] = Player.from_roblox(
                roblox_id,
                pulses=int(prior_balances.get(roblox_id, 50)),
                silk=int(prior_silk.get(roblox_id, 10)),
            )
        return players[roblox_id]

    woven, rejected = [], []
    for r in export.get("rounds", []):
        bond = r["bond"]
        proposer = player_for(r["proposer_roblox_id"])
        rnd = propose(proposer, bond["formula"], bond["name"])
        for vote in r["votes"]:
            voter = player_for(vote["roblox_id"])
            cast_vote(rnd, voter, quorum.Verdict(vote["verdict"]))  # replay the real vote
        s = settle(rnd)
        rec = {"formula": bond["formula"], "name": bond["name"], "by": r["proposer_roblox_id"],
               "outcome": s.outcome.value, "confirmations": s.result.confirms}
        if s.woven:
            rec["fiber_cid"] = s.woven_fiber_cid
            woven.append(rec)
        else:
            rejected.append(rec)

    return {
        "roblox_wallets_ingested": len(players),
        "knitweb_addresses": {rid: p.address for rid, p in players.items()},
        "balances": {rid: p.pulses for rid, p in players.items()},
        "silk": {rid: p.silk for rid, p in players.items()},
        "bonds_woven": woven,
        "bonds_rejected": rejected,
    }


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "bridge/sample_roblox_votes.json"
    summary = ingest(json.load(open(path, encoding="utf-8")))
    print(f"== MOLGANG upload — wove {len(summary['bonds_woven'])} bond(s) from "
          f"{summary['roblox_wallets_ingested']} Roblox wallet(s) ==\n")
    for rid, addr in summary["knitweb_addresses"].items():
        print(f"  roblox {rid!r:>16} → knitweb {addr[:22]}…  ({summary['balances'][rid]} PLS)")
    print()
    for b in summary["bonds_woven"]:
        print(f"  ✅ {b['formula']:<8} {b['name']:<18} woven Fiber {b['fiber_cid'][:18]}…")
    for b in summary["bonds_rejected"]:
        print(f"  ❌ {b['formula']:<8} {b['name']:<18} {b['outcome']} (not woven)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
