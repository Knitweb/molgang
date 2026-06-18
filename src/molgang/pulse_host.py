"""MOLGANG's host-side Pulse CLI integration."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def default_wallet_path() -> str:
    return os.environ.get(
        "MOLGANG_PULSE_WALLET",
        os.path.expanduser("~/.molgang/pulse-identity.json"),
    )


def _pulse_cli() -> list[str]:
    """Return the Pulse CLI command Molgang should call."""
    override = os.environ.get("PULSE_CLI")
    if override:
        return override.split()
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "pulse" / "tools" / "cli" / "index.mjs",
        here.parents[4] / "pulse" / "tools" / "cli" / "index.mjs",
        Path.home() / "repo" / "pulse" / "tools" / "cli" / "index.mjs",
    ]
    for path in candidates:
        if path.exists():
            return ["node", str(path)]
    raise RuntimeError("Pulse CLI not found; set PULSE_CLI or check out knitweb/pulse next to molgang")


def _run_pulse(args: list[str]) -> dict:
    cmd = _pulse_cli() + args + ["--json"]
    proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return json.loads(proc.stdout)


def bootstrap_host(
    wallet: str | None = None,
    *,
    listen: str | None = None,
    genesis: int = 0,
) -> dict:
    """Create/reuse the game host's Pulse identity through the Pulse CLI."""
    wallet_path = wallet or default_wallet_path()
    identity = _run_pulse([
        "identity", "create", "--out", wallet_path, "--genesis", str(genesis)
    ])
    status_args = ["host", "status", "--identity", wallet_path]
    if listen:
        status_args += ["--listen", listen]
    status = _run_pulse(status_args)
    balance = status.get("balance", identity.get("balance", 0))
    return {
        "kind": "host-status",
        "wallet": wallet_path,
        "identity": status.get("identity", identity.get("path", wallet_path)),
        "listen": status.get("listen"),
        "account": {
            "address": status.get("address", identity["address"]),
            "balance_pls": balance,
            "pub": identity.get("publicKey"),
            "braid_head": None,
            "network": "pulse",
        },
        "known_peers": [],
        "pages": status.get("pages", 0),
        "identity_created": identity["created"],
    }
