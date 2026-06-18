"""MOLGANG's host-side Pulse CLI integration."""

from __future__ import annotations

import os

from knitweb.tools import cli as pulse_cli


def default_wallet_path() -> str:
    return os.environ.get(
        "MOLGANG_PULSE_WALLET",
        os.path.expanduser("~/.molgang/pulse-identity.cbor"),
    )


def bootstrap_host(
    wallet: str | None = None,
    *,
    listen: str | None = None,
    genesis: int = 0,
) -> dict:
    """Create/reuse the game host's Pulse identity through the Pulse CLI path."""
    wallet_path = wallet or default_wallet_path()
    identity = pulse_cli.cmd_identity_create(wallet_path, genesis=genesis)
    status = pulse_cli.cmd_host_status(wallet_path, listen=listen)
    return {**status, "identity_created": identity["created"]}

