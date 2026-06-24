# Features

Tracks shipped and planned capabilities by epic. Completed items reflect merged PRs as of 2026-06-24.

---

## Epic 1 — Security Hardening

### Shipped
- Redact public certificate endpoint (#188)
- Bearer certificate CLI export hardened (#192)
- Cap fresh faucet claims by source (#195)
- Rate limit API write routes (#196)
- Harden device wallet derivation (#197)
- Bridge: bind loopback by default + cap upload body (#202)
- Raise vulnerable dependency lower bounds (#203)
- Mechanical Python lint cleanup (#204)

---

## Epic 2 — Relay & Identity

### Shipped
- Reuse Pulse wallet identity for relay signing (#189)
- Save shared world files atomically (#190)
- PHP relay: read-only Monitor dashboard for live 5mart.ml node (#187)
- Make PHP relay onboarding host-neutral (#193)
- Require explicit desktop bridge dapp target (#194)
- Remove subprocess — use direct Python import or localhost HTTP (#205)

---

## Epic 3 — 3D Graph / Explorer

### Shipped
- In-game 3D knitweb knowledge-graph explorer (live chem-web visualization) (#191)
- WebXR/VR support for intuitive node/edge interaction (#199)

---

## Epic 4 — NPC / Autonomous Agents

### Shipped
- NPC bots vote an honest chemistry verdict on knits (anti-rubber-stamp) (#200)
- Clamp relayed item confirmations/validators on ingest (anti-forgery) (#201)

---

## Epic 5 — Serverless / Browser

### Shipped
- Webnode package: browser-tab peer, WebRTC carrier (#206)

---

## Epic 6 — Monitor & Observability

### Shipped
- P2P simulation mode + fix loading-stuck state in monitor (#207)

---

## Planned
- Full Postgres migration for in-memory chemistry state
- Molgang ↔ Pulse wallet bridge (bidirectional PLS ↔ MolCoin swap)
- External dev onboarding: clean contrib guide + sandbox environment
