# MOLGANG launch runbook + live-ops (#135)

The go/no-go gate and operating procedure for a public launch. It composes the
other launch docs: the [measurement standard](MEASUREMENT_STANDARD.md), the
[cost model](COST_MODEL.md), the [SLOs](../SLOS.md), the
[compliance gate](../COMPLIANCE.md), and the security hardening (#130).

## Go / no-go gate (all must be GREEN)

- [ ] **Compliance** — every box in `docs/COMPLIANCE.md` checked (age gate,
      erasure path, no trackers). Legal blocker for a kids' game.
- [ ] **Measurement** — the headline concurrency figure was measured under
      `docs/launch/MEASUREMENT_STANDARD.md` with a published raw scrape.
- [ ] **SLOs** — p99 quorum-settle + sync-convergence within
      `docs/SLOS.md` budgets under the load-test workload.
- [ ] **Security** — faucet + relay hardened for a launch-wave flash crowd
      (#130): per-source faucet cap, relay rate limits, equivocation quarantine
      (#90) live.
- [ ] **Cost** — projected launch-wave spend within the bound in
      `docs/launch/COST_MODEL.md`; a kill-switch for the faucet exists.
- [ ] **Rollback** — the previous deploy is one command away (static bundles are
      content-addressed; the pure-P2P dapp needs no server rollback).

## On-call rotation

- Primary + secondary per shift; a shared incident channel; the `/metrics`
  Prometheus surface (#121) + the mesh dashboard (#99) are the eyes.
- Escalation ladder: relay saturation → add relays / raise caps → shed load via
  faucet throttle → (last resort) faucet kill-switch.

## Runbook — the launch wave

1. **T-24h** — freeze; run the full load test at target concurrency; confirm all
   go/no-go boxes; pre-warm the relay fleet (#129).
2. **T-0** — open the faucet; watch RED metrics + faucet spend live.
3. **Steady state** — hold; the anti-entropy fan-out (#93) and range-proof
   catch-up (#91) keep reconvergence cost bounded as peers grow.
4. **Incident** — follow the escalation ladder; a divergent `web_state_root`
   across peers is a SEV-1 (points at a canonical-byte or equivocation issue) →
   check `equivocations_detected` and `records_quarantined` first.

## Post-launch live-ops

- Daily: faucet spend vs the cost-model bound; SLO adherence; new
  `equivocations_detected`.
- Weekly: the source-seeded chemistry fabric grows (#56 seed re-run); the
  KG-source catalog refresh (ChemField) stays current.
- Retro after the wave: publish the measured concurrency + the raw scrape.
