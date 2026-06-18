"""MOLGANG uses the Pulse CLI command bodies for its host identity."""

from molgang.pulse_host import bootstrap_host


def test_bootstrap_host_creates_and_reuses_pulse_identity(tmp_path):
    wallet = str(tmp_path / "pulse-host.cbor")
    first = bootstrap_host(wallet, listen="127.0.0.1:8765", genesis=11)
    second = bootstrap_host(wallet, listen="127.0.0.1:8765", genesis=99)
    assert first["identity_created"] is True
    assert second["identity_created"] is False
    assert second["account"]["address"] == first["account"]["address"]
    assert second["account"]["balance_pls"] == 11
    assert second["listen"] == "127.0.0.1:8765"
