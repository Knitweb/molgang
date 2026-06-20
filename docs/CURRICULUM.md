# MOLGANG curriculum & teacher guide (Sprint 7 · #114)

MOLGANG teaches a graded, elementary-to-high-school chemistry curriculum **as a peer-to-peer game**:
a player proposes a chemical bond, classmates vote on it, and a confirmed bond is *woven* into the
shared knowledge graph. This document maps the in-game content to learning objectives teachers
recognise, and shows how to run a class session.

> **No tokens, no NFTs.** Everything a learner earns — XP, levels, quest completions, achievement
> badges, leaderboard standing, and the Proof-of-Useful-Work certificate — is **reputation and woven
> knowledge only**, never a tradable or monetary asset. There is nothing to buy and nothing to sell;
> the value is what a student demonstrably learned and verified with peers.

## The tier model

The chemistry ground truth lives in [`src/molgang/chemistry.py`](../src/molgang/chemistry.py) and tags
every element and compound with a curriculum **tier** (`tier_of()`), ordered easiest → hardest. The
tiers map to broad school bands:

| Tier | School band | Learning objectives |
|---|---|---|
| **elementary** | Primary / lower-secondary intro | States of matter and the air we breathe; water; the most common elements and their one- or two-letter symbols; reading a simple chemical formula as a count of atoms. |
| **middle** | Middle school | Common salts and compounds; binary-compound naming; metals and non-metals; an intro to acids (e.g. `HCl`) and combustion/air gases (`N2`, `CO`); fixed composition of a compound. |
| **high** | High school | Acids, bases and oxides; an organic first contact (`C6H12O6`); industrially important compounds (`H2SO4`, `NH3`-derived `HNO3`, `NaOH`, `KOH`); reasoning about composition toward balanced reactions (reactions land with #109). |

### Tier rosters

Every symbol/formula below has a matching entry in `chemistry.py` (a conformance test enforces this —
see [Keeping this doc honest](#keeping-this-doc-honest)).

| Tier | Elements | Molecules |
|---|---|---|
| elementary | `H` `He` `C` `N` `O` | `H2O` `CO2` `O2` `H2` |
| middle | `F` `Na` `Mg` `Cl` `Ca` `Fe` `Zn` | `NaCl` `CH4` `NH3` `HCl` `CaCO3` `N2` `CO` `SiO2` `NaF` |
| high | `Al` `Si` `P` `S` `K` `Br` `I` | `C6H12O6` `SO2` `H2SO4` `NaOH` `CaO` `MgO` `Al2O3` `KCl` `H3PO4` `H2O2` `HNO3` `H2S` `NO2` `KOH` `ZnO` `KBr` `KI` |

Every label is available in **English, Dutch, Russian, Chinese, and Arabic** (see
[MULTILINGUAL.md](MULTILINGUAL.md)), so the same lesson serves a global classroom; new content cannot
merge without all five languages.

## How a classroom plays

The bar ([`src/molgang/bar.py`](../src/molgang/bar.py)) *is* the class, and the game mechanics are the
pedagogy:

- **A table is a working group.** Students "walk in", pick a seat, and brainstorm terms to knit.
- **Voting is peer review.** Proposing a bond (e.g. `H2O`) asks the table to confirm it; a bond is
  woven only when classmates reach a Byzantine-fault-tolerant quorum. Wrong chemistry (e.g. a bogus
  salt) is caught by peers who know the material — assessment is built into play.
- **Progress is visible and motivating.** Each student accrues XP/levels, works through tier-graded
  **quests** (`/api/quests`), unlocks reputation **achievement** badges (`/api/achievements`), and
  competes on an all-time *and* a fresh **seasonal** leaderboard (`/api/leaderboard?season=current`).
- **The certificate is evidence of work.** The Proof-of-Useful-Work certificate
  ([`src/molgang/certificate.py`](../src/molgang/certificate.py)) documents a learner's knits woven,
  votes cast, and achievements unlocked — a shareable record of effort (reputation, **not** a bearer
  token; the public certificate redacts wallet private material).

## Teacher quick-start

Run a class session against a node — either the always-on community node at **5mart.ml** or your own:

```bash
# Local one-room session (laptop / classroom server):
molgang serve --host 0.0.0.0 --port 8765          # students open http://<your-ip>:8765
```

Then, in a 30–40 minute lesson:

1. **Walk in** — each student enters a name and picks an avatar (free silk + pulses from the faucet).
2. **Pick a tier** — start the class on the *elementary* roster; advance tiers as the cohort masters each.
3. **Knit & peer-review** — students propose formulas and vote on each other's bonds; the shared web
   grows on screen (the **Web** tab) as correct chemistry is woven.
4. **Check progress** — the **quests**, **achievements**, and **leaderboard** surfaces give every
   student a concrete next step and recognition (the single biggest driver of return visits — and,
   at scale, of concurrent peers).
5. **Issue certificates** — students can request a PoUW certificate as evidence of the session's work.

`molgang serve` exposes the same `/api/*` contract documented in [API.md](API.md), so a class can use
the browser bar, a tablet, or even scripted/agent players — all against one wire protocol.

## Keeping this doc honest

`tests/test_curriculum_doc.py` re-derives the per-tier rosters from `chemistry.py` and asserts the
**Tier rosters** table above lists exactly those elements and molecules — so the curriculum doc can
never silently drift from the ground truth as content grows.

## Road to 1M

Every adopting classroom is a *cohort of simultaneous peers*. Curriculum alignment and teacher framing
are what unlock that channel — the fastest path to large concurrent counts, since classrooms onboard
players in batches rather than one at a time.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md) · [MULTILINGUAL.md](MULTILINGUAL.md) ·
[ROADMAP_1M](ROADMAP_1M.html).
