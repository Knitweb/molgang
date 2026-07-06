# Load harness (#122/#125)

`molgang.slo.check_budgets(metrics_text)` is the budget gate every ramp step
asserts. A ramp driver (in-process or against a live `/metrics`) scrapes the
exposition per step and fails at the first breaching step, naming the SLO. See
`docs/BUDGETS.md` for ceilings + the committed baseline.
