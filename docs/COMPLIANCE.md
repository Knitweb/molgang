# MOLGANG — child-safety & privacy compliance (COPPA / GDPR-K)

MOLGANG is a school chemistry game (teacher-framed), so its audience includes
minors. COPPA (US, under-13) and GDPR-K (EU, under-16, member-state floor 13)
make age-gating, guardian consent, data-retention limits, and "no behavioural
profiling of children" **launch blockers**, not optional. This document is the
compliance model and the launch go/no-go gate.

## Why the architecture makes this tractable

MOLGANG's design is *privacy-by-construction*, which removes most of the usual
COPPA/GDPR surface:

| Concern | How the design handles it |
|---|---|
| **No account, no server PII** | Identity is a **device-derived pseudonymous wallet** (`sha256("knitweb:account:seed:"+seed)`). No name, email, age, or contact is required or stored server-side — the pure-P2P dapp has **no backend** at all. |
| **Data is local-first** | Wallet, balances and progress live in the browser (localStorage / IndexedDB). "Right to erasure" of local data = clearing site data (documented in-app). |
| **The public fabric holds no PII** | Woven Fibers are **chemistry knits** (`H2O`, `V2O3 + O2 -> V2O5`) attributed to a pseudonymous `pls1…` address — not a person. No behavioural events, no tracking, no profiling. |
| **No behavioural profiling** | Progression/levels are derived from *woven chemistry*, computed locally. There is no ad tech, no third-party analytics, no cross-site identifiers, no engagement telemetry on individuals. |
| **The one PII touchpoint is opt-in + encrypted** | The email-subscribe path (#76) is the only place an email can be entered; it is explicit opt-in and Blowfish-encrypted. It MUST be gated behind guardian consent and excluded for self-declared minors — see the checklist. |

## Age gate + consent

- The walk-in overlay carries an **age/consent gate**: a player must confirm they
  are **13 or older, or have a parent/guardian's permission**, before the "Walk
  in" (faucet) action is enabled. The choice persists locally
  (`molgang_age_ok`), so it is asked once per device. This is a lightweight
  neutral gate (no birthdate collected — collecting a birthdate would itself be
  data minimisation-adverse); it blocks the faucet/join until acknowledged.
- Any PII-touching feature (email subscribe) is additionally gated behind an
  explicit guardian-consent step and is **never offered** to a session that only
  passed the "has guardian permission" branch as a minor.

## Right to erasure against an append-only fabric

The fabric is append-only and public — a woven Fiber cannot be un-woven. This is
compatible with erasure because **the fabric contains no personal data**: a knit
is a chemistry fact bound to a pseudonymous key, not to an identifiable child.
Erasure therefore means:

1. **Local erasure** — clear the device's localStorage/IndexedDB (wallet +
   progress). Documented in-app; a one-click "forget this device" affordance is
   the implementation target.
2. **De-linking** — because the on-fabric identity is a device-derived
   pseudonym with no PII attached, discarding the local seed makes the pseudonym
   unlinkable to the person. No server holds a seed→person mapping.
3. **PII stores (email, #76)** — the only erasable *personal* record; its store
   MUST support delete-on-request (encrypted-at-rest, opt-in only).

## Data collected / not collected

- **Collected:** nothing server-side by default. Local-only: the device wallet
  seed, PLS/silk balances, level, and the player's woven knits (pseudonymous).
- **NOT collected:** name, birthdate, email (unless the opt-in #76 flow is used
  with consent), IP-based tracking, device fingerprinting, behavioural analytics,
  location, or any cross-site identifier.

## Launch go/no-go checklist (S10 gate)

- [ ] Age/consent gate present on the join/faucet path (`molgang_age_ok`).
- [ ] "Forget this device" local-erasure affordance shipped + documented.
- [ ] Email-subscribe (#76) gated behind explicit guardian consent; excluded for
      self-declared minors; store supports delete-on-request.
- [ ] Privacy notice reachable from the walk-in overlay (this document, plainly
      worded for teachers/guardians).
- [ ] No third-party analytics / ad SDKs / cross-site identifiers in any shipped
      bundle (grep-gate in CI).
- [ ] Data-retention: no server-side PII store beyond the opt-in email path;
      that store has a documented retention window + erasure path.

Until every box is checked, the S10 launch runbook is **no-go**.
