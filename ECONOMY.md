# MOLGANG Economy

MOLGANG has no NFT layer. The economy is the playable proof loop around useful
chemistry work:

- **PLS** pays for validation work and is staked into real Knit transfers.
- **Silk** is the thread resource spent to propose knits and spirals.
- **Reputation** is non-transferable progress from woven knowledge: XP, levels,
  quests, achievements, leaderboard standing, Fiber CIDs, and certificates.

## Resources

| Resource | Purpose | Stored as |
| --- | --- | --- |
| PLS | Vote stake, validator reward, proposer reward | Knitweb account balance |
| Silk | Proposal fuel for knits and spirals | Player state |
| Reputation | Learning progress and trust signal | Derived from woven work |

PLS accounting is integer-only. The production faucet schedule is calculated in
integer micro-PLS (`1 PLS = 1,000,000 micro-PLS`) and credited to current account
balances as whole integer PLS. No float value is part of the settlement path.

## PLS Sources

PLS can enter a player-visible account through explicit code-defined sources:

| Source | Current rule | Code |
| --- | --- | --- |
| Device faucet | Fresh browser device wallets receive the decaying production grant: day 0 is 10,000,000 PLS, day 100 is 10,000 PLS, then -1% per day with a 1 micro-PLS floor. Persisted devices restore their saved balance instead of reopening the faucet. | `bar.py`, `game.faucet_micropulses` |
| Dev/test/bridge seed | Engine-level joins and first-seen bridged players default to 50 PLS. | `FAUCET_PULSES` |
| Useful-work reward bank | Each knit round has a transparent capped reward bank. Confirmed useful work pays the proposer a base reward plus `min(64, 2**confirms - 1)`, and confirming voters receive a positive reward. | `ROUND_REWARD_BANK_PLS`, `usefulness_bonus`, `settle` |

There is no user-facing arbitrary mint endpoint. Issuance surfaces are constants
and functions in `src/molgang/game.py`, and changes to them should be reviewed as
economy changes.

## PLS Sinks And Transfers

PLS used for votes is first a stake, not a burn.

| Action | PLS movement | Settlement rule |
| --- | --- | --- |
| Vote on a knit | Voter transfers 1 PLS into the round escrow. | If confirmed, the escrow pot pays the proposer. Confirming voters are paid from the reward bank. If rejected or no quorum, each voter stake is refunded from escrow. |
| Back a spiral | Backer stakes 1 PLS per link into the spiral escrow. | If captured, the whole pot pays the spiral leader. If rejected or no quorum, backers are refunded. |
| Failed work | No PLS reward is paid. | Current code refunds voter stakes and leaves the proposer's spent silk consumed. |

So the escrow path is conserved: PLS moves from voter to escrow to proposer or
back to voter. New PLS only appears through the explicit faucet and reward-bank
sources above.

## Silk Sources And Sinks

Silk keeps the game moving without making PLS the only pacing mechanism.

| Action | Silk movement |
| --- | --- |
| Join | A new player starts with 10 silk. |
| Propose a knit | The proposer spends 1 silk. |
| Confirmed useful knit | The proposer earns back 1 silk, so useful work can continue. |
| Propose a spiral | The leader spends escalating silk, `sum(1 + i // 3 for i in links)`, for 2-7 links. |
| Captured spiral | Correct-side backers earn 1 contagion silk each. |
| Failed work | No silk reward is paid. |

Silk is not represented as a tradable asset. It is local game fuel tied to the
player state and persisted for device-backed players.

## Reputation

Reputation is the durable value surface. It is earned from woven work and read by
the UI as:

- XP and level title.
- Quest progress and achievement badges.
- Seasonal and all-time leaderboard rank.
- Woven Fiber CIDs and Proof-of-Useful-Work certificate summaries.

Reputation is not sellable and is not an NFT. Badges and achievements expose
identity, title, and description fields, not a token id, market price, owner
transfer, or royalty.

## No-NFT Invariants

MOLGANG deliberately avoids a tradable collectible layer:

- Avatars are cosmetic choices, not owned assets.
- Molecules, knits, spirals, and Fiber CIDs are proofs of woven knowledge, not
  saleable collectibles.
- The UI has no mint, buy, sell, list, royalty, or transfer flow for achievements
  or woven molecules.
- Value is useful work: PLS utility, silk pacing, reputation, and a verifiable
  knowledge web.

## Settlement Invariants

These invariants are load-bearing:

- Integer-only PLS accounting; no floats in faucet or settlement math.
- Every vote stake is a real Knit transfer into escrow.
- A knit or spiral becomes durable only after the BFT quorum releases it.
- Useful confirmed work is net-positive but capped by `MAX_USEFULNESS_BONUS`.
- Rejected or unconfirmed work pays no PLS reward.
- Device-backed players restore persisted PLS and silk instead of receiving a new
  faucet grant on every session.
- No hash-critical ledger or bytecode format changes are needed for economy
  parameter changes unless the signed surface itself changes.

## Planned Hardening

The current economy is intentionally explicit, but not finished. Open follow-up
work tracks faucet abuse prevention, rate limits, identity recovery, slashing for
fiber-tension faults, and an economic report endpoint for minted-vs-staked and
silk-spent-vs-earned accounting.
