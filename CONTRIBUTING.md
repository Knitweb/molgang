# Contributing to MOLGANG

MOLGANG is a chemistry (scheikunde) learning game on the [Knitweb](https://github.com/knitweb/pulse).
Contributions — new lessons, languages, UI, fixes — are very welcome.

## Setup

```bash
git clone https://github.com/knitweb/molgang.git && cd molgang
# MOLGANG runs on the knitweb package; for local dev point at a checkout:
export PYTHONPATH=src:/path/to/pulse/src     # (or: pip install -e /path/to/pulse)
python3 -m pytest -q
python3 examples/play_demo.py                # in-process round
python3 examples/p2p_demo.py                 # real-socket P2P round
```

## How we work

- Open an issue (templates provided), branch from `main`, keep PRs small, never push to `main`.
- **Tests stay green** and new behaviour ships with a test.
- Run the two demos before a PR that touches the engine.

## House rules

- **Vocabulary:** Web · Knitweb · Knit · Pulse · Fiber; workers are *spiders*; pay-token is
  **PLS**. **Never write "loom"/"looms" — only "knitweb."**
- **Pulses are conserved** in the engine — a confirmed bond routes the staked pot to the
  proposer (proof-of-knowledge); nothing is minted in the game layer.
- **Keep the Lua mirror in sync.** `roblox/Chemistry.lua` and `roblox/Game.lua` must mirror
  `src/molgang/chemistry.py` and `game.py` (same molecules, same quorum rule), and the
  `VoteExport` JSON must keep matching `bridge/ingest.py`.
- **Chemistry must be correct.** New entries in `MOLECULES` need a real formula; a peer's
  honest vote is the ground truth, so wrong data teaches wrong chemistry.

## License

By contributing you agree your work is licensed under **Apache-2.0** (see [`LICENSE`](LICENSE)),
and you follow the [Code of Conduct](CODE_OF_CONDUCT.md). Sign commits off (`git commit -s`).
