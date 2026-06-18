# Security Policy

MOLGANG is a game, but it settles on a real value-bearing web (the Knitweb) and bridges
external Roblox input, so we welcome coordinated disclosure.

## Reporting

**Do not open a public issue for security problems.** Instead open a private
[GitHub Security Advisory](https://github.com/knitweb/molgang/security/advisories/new) on this
repo, or email **security@5mart.ml**. We acknowledge within 72 hours and practice
coordinated disclosure.

## In scope

- **The bridge** (`bridge/ingest.py`) — the trust boundary where untrusted Roblox input
  enters the Knitweb: vote forgery, replay across hourly exports, Roblox-wallet-id spoofing
  that mints unearned pulses or weaves false chemistry, JSON injection.
- **Game economics** — any way to drain/duplicate pulses, bypass the quorum, or get a wrong
  bond woven (pulses must stay conserved; only a confirm quorum weaves).
- **The Lua ↔ Python ↔ knitweb mismatch** — divergence that lets a Roblox vote mean something
  different on the Knitweb.

## Out of scope / upstream

Core crypto, canonical encoding, ledger and PoUW live in **knitweb** — report those via
[knitweb/pulse](https://github.com/knitweb/pulse)'s security policy. Roblox-platform issues go
to Roblox.

## Safe harbor

Good-faith research that respects this policy and avoids privacy violations or disruption will
not be pursued. Thank you for keeping the web safe.
