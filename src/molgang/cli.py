"""MOLGANG command-line client.

    molgang            a narrated demo session (faucet → propose → vote → woven Fiber →
                       collection/XP → leaderboard → OriginTrail anchor)
    molgang play       interactive: propose bonds, a class of peers votes, you collect molecules
    molgang merge      merge every locally-woven knitwork into ONE combined knitweb + anchor it
    molgang serve      browser bar; supports --relay, --relay-wallet, --relay-interval,
                       --monitor and --monitor-nodes for operator convergence
"""

from __future__ import annotations

import sys

from . import progression
from .anchor import anchor_chemistry
from .game import Player, cast_vote, propose, settle

BAR = "─" * 64


def _round(proposer: Player, peers: list[Player], formula: str, name: str) -> dict | None:
    rnd = propose(proposer, formula, name)
    for p in peers:
        cast_vote(rnd, p)                       # honest verdict from real chemistry; stakes 1 PLS
    s = settle(rnd)
    if s.woven:
        return {"formula": formula, "name": name, "fiber_cid": s.woven_fiber_cid,
                "by": proposer.name, "confirmations": s.result.confirms}
    return None


def demo() -> int:
    print(f"\n  🧪  MOLGANG — peer-to-peer chemistry on the Knitweb\n{BAR}")
    alice = Player.join("Alice")
    peers = [Player.join(n) for n in ("Bob", "Carol", "Dave")]
    print(f"  faucet · Alice opens a wallet: {alice.pulses} PLS + {alice.silk} silk (free)")
    print(f"  3 classmates join the table (each {peers[0].pulses} PLS)\n")

    woven: list[dict] = []
    for formula, name in (("H2O", "Water"), ("CO2", "Carbon dioxide"), ("NaCl", "Table salt")):
        rnd = propose(alice, formula, name)
        verds = [cast_vote(rnd, p).verdict.value for p in peers]
        s = settle(rnd)
        mark = "✅ woven" if s.woven else f"✗ {s.outcome.value}"
        print(f"  bond {formula:<5} ({name:<15}) votes={verds} → {mark}"
              + (f"  Fiber {s.woven_fiber_cid[:14]}…" if s.woven else ""))
        if s.woven:
            woven.append({"formula": formula, "name": name, "fiber_cid": s.woven_fiber_cid,
                          "by": alice.name, "confirmations": s.result.confirms})

    # a wrong bond — peers who know chemistry catch it
    bad = propose(alice, "NaCl2", "Bogus salt")
    for p in peers:
        cast_vote(bad, p)
    sb = settle(bad)
    print(f"  bond NaCl2 (Bogus salt    ) → ✗ {sb.outcome.value} (peers rejected it)\n")

    cols = progression.collections(woven)
    me = cols.get(alice.name, {"molecules": [], "xp": 0, "level": 1, "title": "Apprentice"})
    print(f"{BAR}\n  Alice · {alice.pulses} PLS · level {me['level']} {me['title']} · {me['xp']} XP")
    print(f"  collection: {', '.join(m['formula'] for m in me['molecules']) or '—'}")

    print("\n  🏆 leaderboard")
    for r in progression.leaderboard(woven):
        print(f"    #{r['rank']} {r['player']:<8} {r['molecules']} molecules · {r['xp']} XP · {r['title']}")

    a = anchor_chemistry(woven)
    print("\n  🔗 anchored to OriginTrail (web3 provenance):")
    print(f"    UAL {a.ual}")
    print(f"    {a.bonds} bonds · receipt {a.receipt_cid[:16]}… · verified={a.verified}")
    print(f"{BAR}\n  ▶ try `molgang play`, or run examples/p2p_demo.py for a real P2P round.\n")
    return 0


def play() -> int:
    print("\n  🧪 MOLGANG — propose bonds; a class of peers votes. Ctrl-D to quit.\n")
    you = Player.join("you")
    peers = [Player.join(n) for n in ("Mara", "Tom", "Iris")]
    woven: list[dict] = []
    try:
        while you.silk > 0:
            formula = input(f"  [{you.pulses} PLS, {you.silk} silk] formula (e.g. H2O): ").strip()
            if not formula:
                continue
            name = input("  name it: ").strip() or formula
            got = _round(you, peers, formula, name)
            if got:
                woven.append(got)
                print(f"  ✅ woven! Fiber {got['fiber_cid'][:16]}…  collection: "
                      f"{', '.join(m['formula'] for m in woven)}\n")
            else:
                print("  ✗ the class did not confirm that bond — check your chemistry.\n")
    except (EOFError, KeyboardInterrupt):
        pass
    me = progression.collections(woven).get("you", {"xp": 0, "level": 1, "title": "Apprentice"})
    print(f"\n  thanks for playing — level {me['level']} {me['title']}, {me['xp']} XP, "
          f"{len(woven)} molecules.\n")
    return 0


def doctor() -> int:
    import importlib.util
    import os

    from .engine_compat import check_knitweb_compatibility

    print("  🧪 MOLGANG doctor")
    print(f"  python    {sys.version.split()[0]}")
    spec = importlib.util.find_spec("knitweb")
    if spec is not None:
        import knitweb
        verdict = check_knitweb_compatibility()
        print(f"  knitweb   ✓ found  ({os.path.dirname(knitweb.__file__)})")
        print(f"  version   {verdict.resolved} against {verdict.requirement} [{verdict.status}]")
        print(f"  compat    {verdict.message}")
        if not verdict.compatible:
            print("  fix       install the pinned pulse/knitweb engine or update molgang's range")
            return 1
        print("  status    ✓ ready — run `molgang` to play, or `molgang serve` for the browser bar")
        return 0
    print("  knitweb   ✗ NOT found")
    print("  fix       ./install.sh   (or: pip install -e /path/to/pulse,")
    print("            or set KNITWEB_SRC=/path/to/pulse/src)")
    return 1


def serve(argv: list[str]) -> int:
    from .webserver import main as serve_main
    return serve_main(argv)


def certificate(argv: list[str]) -> int:
    """Generate a PoUW Certificate PDF for a standalone knitweb wallet (a persisted node).

        molgang certificate --wallet wallet.json [--out cert.pdf] [--faucet 50]
        [--holder NAME] [--private --confirm-private-key-export]
    """
    import argparse

    from knitweb.store import load_node

    from .certificate import certificate_for_node
    from .game import FAUCET_PULSES

    ap = argparse.ArgumentParser(prog="molgang certificate",
                                 description="PoUW Certificate PDF for a knitweb wallet")
    ap.add_argument("--wallet", required=True, help="path to a persisted AccountNode (knode.json)")
    ap.add_argument("--out", default="pouw_certificate.pdf", help="output PDF path")
    ap.add_argument("--holder", default=None, help="display name for the wallet holder")
    ap.add_argument("--private", action="store_true",
                    help="print wallet PRIVATE key in the PDF (bearer mode)")
    ap.add_argument("--confirm-private-key-export", action="store_true",
                    help="required with --private; confirms this bearer PDF exposes wallet control")
    ap.add_argument("--faucet", type=int, default=FAUCET_PULSES,
                    help="faucet baseline for pulses_used = faucet - balance (default the molgang faucet)")
    a = ap.parse_args([x for x in argv if x != "certificate"])
    if a.private and not a.confirm_private_key_export:
        ap.error("--private requires --confirm-private-key-export because the PDF becomes a bearer key")
    node = load_node(a.wallet)
    out = certificate_for_node(
        node, out_path=a.out, faucet_pulses=a.faucet, holder=a.holder,
        include_private_key=a.private,
    )
    used = max(0, a.faucet - node.balance("PLS"))
    print(f"  🏅 PoUW certificate → {out}")
    print(f"     wallet {node.address}  ·  pulses used {used}  ·  PLS balance {node.balance('PLS')}")
    if a.private:
        print("  ⚠  bearer mode enabled: this PDF exposes the wallet PRIVATE key.")
    else:
        print("  🔓 public mode: private key redacted.")
    return 0


def explore(argv: list[str]) -> int:
    from .explorer import main as explore_main
    return explore_main(argv)


def merge(argv: list[str]) -> int:
    """Merge locally-woven knitworks into ONE knitweb (see molgang.merge)."""
    from .merge import main as merge_main
    return merge_main(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    cmd = argv[1] if len(argv) > 1 else "demo"
    if cmd == "play":
        return play()
    if cmd == "doctor":
        return doctor()
    if cmd == "serve":
        return serve(argv[1:])
    if cmd == "explore":
        return explore(argv[1:])
    if cmd == "merge":
        return merge(argv[2:])
    if cmd == "certificate":
        return certificate(argv[2:])
    return demo()


if __name__ == "__main__":
    raise SystemExit(main())
