# MOLGANG dApp — 3D-asset storage & retrieval: architecture + budgets

*How we serve game assets fast and cheap while staying a real, content-addressed dApp.
Owner-locked: **Hybrid** storage, **browser-first** rendering, **MVP/near-free (~€15/mo)** default.*

## TL;DR — the one principle

**Cold storage ≠ hot retrieval.** Filecoin and Arweave are *durability/permanence* tiers, not
the path a player's browser hits to load a scene. Short load times come from a **content-addressed
retrieval waterfall** with a **zero-egress edge cache in front**, and from **shrinking the assets**
(Draco/KTX2) — not from picking one storage network. Every asset is keyed by its **CID**, so any
tier is interchangeable and integrity is verifiable end-to-end.

## The retrieval waterfall (first hit wins)

| # | Tier | Latency | Role | Cost shape |
|---|------|---------|------|-----------|
| 1 | **Browser IndexedDB** (by CID, `serverless/web/store_idb.js`) | ~0 ms | repeat visits / same session | free |
| 2 | **Cloudflare R2 + CDN** (zero egress) | <50 ms TTFB | **hot path, first load** | $0.015/GB-mo, **$0 egress** |
| 3 | **IPFS pin — Filebase** (S3-API, 3× geo) | ~100–400 ms (gateway) | decentralized content-addressing | free ≤5 GB, then ~$6/TB-mo, free egress |
| 4 | **Filecoin (Saturn CDN) / Arweave** | Saturn <100 ms goal¹; Arweave gw ~100–500 ms | durable/permanent backstop, cold-start refill | Filecoin ≈ free storage; Arweave one-time ~$5–8/GB |
| 5 | **knitweb relay + peers** (`relay_sync.py`, 5mart) | ~1–2 s (mailbox) | censorship-resistant fallback + the **registration ledger** | already paid |

¹ Saturn targets sub-100 ms TTFB but its operator network has had reliability wobble — treat it as
*optional redundancy*, never the sole hot path.

A `GET /assets/<cid>` miss walks the waterfall server-side (local → peer/pin → cold), **verifies
bytes against the CID**, then caches. The browser also verifies (`verifyCid`) before trusting bytes.

## Provider snapshot (2026, grounded)

| Provider | Storage | Egress | Verifiable/CID | Best used as |
|----------|---------|--------|----------------|--------------|
| **Cloudflare R2** | $0.015/GB-mo (free ≤10 GB) | **$0, any volume** | via our CID layer | **hot tier (2)** |
| **Filebase (IPFS)** | ~$6/TB-mo (free ≤5 GB) | free | native IPFS CID | **decentralized pin (3)** |
| **Arweave** (Irys/Turbo) | **one-time** ~$5–8/GB | free (gateways) | native | **permanence (4)** |
| **Filecoin / Saturn** | ~free deals (cold) | pay-per-retrieval, variable | native | **cold durability + optional CDN** |
| **S3 (reference)** | $0.023/GB-mo | **$0.09/GB** ← the trap | no | *avoid for media egress* |
| **5mart relay + laptop node** | fixed (owned) | included | our CID | **P2P ledger + fallback (5)** |

The single biggest cost lever at scale is **egress**: R2's $0-egress vs S3's $0.09/GB is the
difference between a €0.75/mo and a €90–450/mo bill for the same 1–5 TB of monthly asset traffic.

## Load-time engineering (short game load times)

Storage tier gets bytes *close*; these get them *small and lazy*:
- **Asset budget:** first meaningful paint ≤ **~15 MB gzip**; everything else lazy.
- **Compress meshes:** Draco/meshopt → 10–20× smaller `.glb`. **Compress textures:** KTX2/Basis →
  GPU-native, ~4–8× smaller *and* faster upload (no client decode).
- **CID manifest preload:** one `manifest.json` of the scene's CIDs → warm tiers 1–2 in parallel
  before the player needs them; **lazy-load by proximity/LOD** for the rest.
- **Immutable caching:** `/assets/<cid>` is content-addressed → `Cache-Control: immutable, max-age=1y`
  + SW `cache-first` (`web/sw.js`). Repeat loads never re-download.
- **IndexedDB by CID** (already in `store_idb.js`): 0 ms on return visits.

## Budget scenarios

| Scenario | Hot assets | Players | Monthly egress | **Monthly €** | One-time (Arweave permanence) |
|----------|-----------|---------|----------------|---------------|-------------------------------|
| **MVP (default)** | ≤5–10 GB | early | <50 GB | **~€0–15** (R2 + Filebase free tiers, existing relay) | ~€2–30 (≈200 MB–5 GB canonical set) |
| **Growth** | ~5 GB | ~10 k | ~50–200 GB | **~€30–60** (R2 storage + $0 egress + Filebase pin + optional Saturn) | ~€30 (5 GB) |
| **Scale** | ~50 GB | ~100 k+ | ~1–5 TB | **~€150–400** (R2 $0.75 + **$0 egress** + redundant CDN/pin + ops) | ~€300 (50 GB) |

**MVP is genuinely near-free**: the current game's assets are tiny (molecule JSON + *procedural*
scenes with no external meshes), so R2's 10 GB and Filebase's 5 GB free tiers cover it, egress is
$0, and the 5mart relay + laptop node already run. The ~€15/mo is headroom, not a hard cost.

## Recommendation & phased rollout

1. **Now (MVP):** ship the CID asset layer (`assets.py` + `/assets/<cid>` + `p2p-assets.js`);
   serve from the repo/relay; pin the canonical set to Filebase (free) and push a one-time Arweave
   copy for permanence. No paid tier yet.
2. **When first HD/glTF assets land:** put R2 in front as the hot tier (still free ≤10 GB), keep
   Filebase pin + Arweave permanence, all keyed by the same CID.
3. **At Growth/Scale:** lean on R2's zero egress; add Saturn/second gateway only as redundancy.
   Filecoin cold deals for archival if the permanent set grows large.

## How it maps to what MOLGANG already has

- **Registration ledger = the existing fabric:** assets are announced as `kind="asset"` `WovenItem`s
  over `relay_sync.py` and content-addressed via the knitweb `canonical.cid` / `Web.weave`. No new
  chain.
- **P2P fallback (tier 5)** is the relay we already run at `https://5mart.ml/molgang/api/relay`.
- **Anchor:** the OriginTrail `Anchor` (`src/molgang/anchor.py`) can notarise the **asset-registry
  root** so the whole CID set is provenance-checkpointed.
- **Gap this fills:** today the only byte transport is the store-and-forward relay mailbox (fine for
  small records, not for MBs of mesh/texture). Tiers 2–4 are the CDN/pin/permanence layer we add.

## Sources
- Cloudflare R2 pricing (storage $0.015/GB-mo, **$0 egress**, free 10 GB) — <https://developers.cloudflare.com/r2/pricing/>
- Filebase IPFS (free 5 GB, 3× geo, free egress) — <https://filebase.com/blog/introducing-filebase-object-storage-with-free-egress/>
- Arweave permanent one-time pricing + Irys/Turbo — <https://www.arweave.com/builder-hub/storage>
- Filecoin Saturn CDN (sub-100 ms TTFB target) — <https://docs.filecoin.io/basics/how-retrieval-works/saturn>
