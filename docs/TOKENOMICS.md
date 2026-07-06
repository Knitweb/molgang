# MOLGANG tokenomics — the canonical no-NFT economy model

The single economy reference (#106). Every number below is the **real constant in
[`src/molgang/game.py`](../src/molgang/game.py)** — a lockstep CI test
(`tests/test_tokenomics_doc.py`) re-reads this document and fails the build if a
stated value drifts from the code. There are exactly three kinds of value, none
of them an NFT:

| Asset | What it is | Where it lives |
|---|---|---|
| **PLS** (pulses) | The pay-token: staked to vote, minted only against verified useful work | integer balances on a knitweb `AccountNode`; sub-PLS accounting is exact integer **µPLS** (`MICROPULSES_PER_PULSE = 1000000`) |
| **silk** | Weaving material: spent to propose bonds/spirals | integer per-player counter |
| **reputation** | XP / levels / badges / quest completions | derived from woven Fibers; never transferable |

**The no-NFT stance:** nothing in MOLGANG is a transferable collectible. Value is
PLS + reputation + the woven knowledge itself. A PoUW certificate is a *report*
about a wallet (redacted, verifiable), not a bearer asset.

## 1. Onboarding — the faucet

Dev/guest seed: `FAUCET_PULSES = 50` PLS and `FAUCET_SILK = 10` silk.

Production onboarding uses the **integer-only decaying faucet schedule**
(`current_faucet_pulses`): phase 1 is an exact linear ramp
`FAUCET_GENESIS_MICROPULSES` (10,000,000 PLS) → 10,000 PLS over
`FAUCET_PHASE1_DAYS = 100` days; phase 2 decays geometrically by
`FAUCET_PHASE2_DECAY_NUM/FAUCET_PHASE2_DECAY_DEN = 99/100` per day, floored at
`FAUCET_MIN_MICROPULSES = 1` µPLS so the faucet never hits zero. No wall-clock
floats anywhere — day is an integer, values are integer µPLS.

## 2. The knit round — stake, settle, mint

- Proposing a bond spins `SILK_PER_BOND = 1` silk into the round.
- Each voter stakes `VOTE_COST = 1` PLS into a **neutral escrow**.
- Settlement runs the real BFT quorum (`pouw.quorum`), then `settle()`:

**Confirmed (useful work):**
- the proposer receives the whole staked pot **plus** a protocol reward
  `PROPOSER_BASE_REWARD = 2` + `usefulness_bonus(confirms)`;
- `usefulness_bonus` is the capped exponential
  `min(MAX_USEFULNESS_BONUS, USEFULNESS_EXP_BASE ** confirms − 1)` with
  `USEFULNESS_EXP_BASE = 2` and `MAX_USEFULNESS_BONUS = 64`;
- every **confirming** voter gets their stake back plus
  `VOTER_CONFIRM_REWARD = 1` fresh PLS — *validating useful work is
  net-positive*;
- protocol rewards are paid from a per-round, transparent
  `ROUND_REWARD_BANK_PLS = 1000000` reward bank (an explicit account, not
  thin air: payments are ledger transfers out of it).

**Not confirmed (wrong bond / no quorum):**
- **nothing is minted**; every voter's stake is refunded integer-exactly from
  escrow. A failed round is economically a no-op.

### Invariants (enforced by the settle math)

1. **Confirmed useful work is net-positive** for the proposer *and* for every
   confirming voter.
2. **Failed work mints nothing** — stakes come back, no reward-bank transfer.
3. **Integer-exact settlement** — no floats anywhere on a value path.

## 3. Spirals — escalating stakes, contagion silk

- Weaving a spiral of *n* links costs escalating silk
  `spiral_silk_cost(n) = Σ(1 + i//3)` — e.g. 2 links → 2 silk, 7 links → 12.
- A backer stakes `stake_per_vote = VOTE_COST × n_links` PLS.
- Captured (≥ `MIN_SPIRAL_VOTERS = 3` backers, quorum): the whole pot pays the
  leader; each correct backer earns `CONTAGION_SILK = 1` silk back.
- Not captured: every backer is refunded integer-exactly. Spam is capped by
  `MAX_SPIRAL_LEN = 7`.

## 4. Worst-case emission bounds

Per **confirmed knit**, freshly minted PLS (reward-bank outflow, stakes are
recycled) is bounded by:

```
mint(knit) ≤ PROPOSER_BASE_REWARD + MAX_USEFULNESS_BONUS + confirms × VOTER_CONFIRM_REWARD
           =        2             +        64            + confirms × 1
```

With a 24-seat table (23 potential confirmers) that is ≤ **89 PLS per woven
knit** — bounded, auditable, and independent of table size beyond the voter
count. The `ROUND_REWARD_BANK_PLS` bank therefore funds ≥ 11,235 fully-bonused
knits per round-bank; refills are explicit ledger events, never silent.

**Scale-risk callouts (flagged, not hidden):**
- `ROUND_REWARD_BANK_PLS` is generous for a classroom; production should tie the
  refill rate to demand (see the PLS-heartbeat work in the development plan).
- The faucet phase-1 grant (up to 10M PLS/device-day at genesis) dwarfs play
  rewards by design (bootstrap liquidity); Sybil exposure is bounded by the
  per-source faucet cap in the registry (`claim_faucet`), not by the schedule.

## 5. Enforcement cross-references

- **Anti-Sybil / personhood** — registry faucet caps (`registry.claim_faucet`),
  the personhood gate in the development plan, and knitweb/molgang#130
  (faucet/relay hardening).
- **Collateral & slashing** — fiber-tension pouw collateral (knitweb/molgang#51)
  makes verification economic, not just cryptographic.
- **Certificates** — `/api/certificate` reports PLS balance + pulses staked
  (public, redacted); the tracked list (`/api/certificates`) carries each PDF's
  sha256. Reputation, never a bearer token.
