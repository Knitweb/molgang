"""#128/#135/#145 — the launch documentation set exists and is internally linked."""
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs" / "launch"


def _read(name):
    return (DOCS / name).read_text(encoding="utf-8")


def test_measurement_standard_defines_concurrent_peer_workload():
    d = _read("MEASUREMENT_STANDARD.md")
    for k in ("Peer", "Concurrent", "workload", "reproducib", "go/no-go"):
        assert k.lower() in d.lower(), k


def test_runbook_has_a_go_no_go_gate_and_oncall():
    d = _read("RUNBOOK.md")
    for k in ("go / no-go", "on-call", "rollback", "kill-switch", "SEV-1"):
        assert k.lower() in d.lower(), k
    # composes the other launch docs
    assert "MEASUREMENT_STANDARD.md" in d and "COST_MODEL.md" in d and "COMPLIANCE.md" in d


def test_cost_model_bounds_spend_and_states_crossover():
    d = _read("COST_MODEL.md")
    for k in ("relay", "crossover", "kill-switch", "emission", "hosting"):
        assert k.lower() in d.lower(), k
