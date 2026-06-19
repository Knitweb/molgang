"""MOLGANG's host-side Pulse CLI integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import shlex
import hashlib
import secrets


def default_wallet_path() -> str:
    return os.environ.get(
        "MOLGANG_PULSE_WALLET",
        os.path.expanduser("~/.molgang/pulse-identity.json"),
    )


def _local_fallback(path: str, *, genesis: int) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return {
                "created": False,
                "address": data["address"],
                "publicKey": data.get("publicKey", _derive_public_key(data["address"])),
                "balance": int(data.get("balance", 0)),
                "path": path,
            }
    seed = secrets.token_hex(16)
    pub = _derive_public_key(seed)
    record = {
        "created": True,
        "address": f"0x{pub[-40:]}",
        "publicKey": pub,
        "balance": int(genesis),
        "path": path,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    return record


def _derive_public_key(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _pulse_cli() -> list[str]:
    """Return the Pulse CLI command Molgang should call."""
    override = os.environ.get("PULSE_CLI")
    if override:
        return shlex.split(override)
    return [sys.executable, "-m", "knitweb.app.cli"]


def _load_cli_module():
    """Load the local Pulse Python CLI module if available."""
    try:
        from knitweb.app import cli as cli_module
        return cli_module
    except Exception:
        try:
            from knitweb.tools import cli as cli_module
            return cli_module
        except Exception:
            return None


def _arg_value(args: list[str], *names: str, default=None) -> str | None:
    for i, item in enumerate(args):
        if item in names:
            return args[i + 1] if i + 1 < len(args) else default
    return default


def _run_pulse(args: list[str]) -> dict:
    cli_module = _load_cli_module()
    if cli_module:
        if args[:2] == ["identity", "create"]:
            path = _arg_value(args, "--out", "--wallet", default=default_wallet_path())
            identity = _invoke_identity_create(
                cli_module,
                path,
                genesis=int(_arg_value(args, "--genesis", default="0")),
                network=int(_arg_value(args, "--network", default="1")),
                force="--force" in args,
            )
            return _normalize_identity(identity, path)
        if args[:2] == ["host", "status"]:
            path = _arg_value(args, "--identity", "--wallet", default=default_wallet_path())
            listen = _arg_value(args, "--listen")
            host_status = _invoke_host_status(cli_module, path, listen)
            return _normalize_host_status(
                host_status,
                path,
                listen=listen,
            )

    if os.environ.get("PULSE_CLI"):
        cmd = _pulse_cli() + args + ["--json"]
        proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
        return json.loads(proc.stdout)

    path = _arg_value(args, "--out", "--wallet", "--identity", default=default_wallet_path())
    if args[:2] == ["identity", "create"]:
        return _normalize_identity(
            _local_fallback(path, genesis=int(_arg_value(args, "--genesis", default="0"))),
            path,
        )
    if args[:2] == ["host", "status"]:
        return _normalize_host_status(
            _local_fallback(path, genesis=0),
            path,
            listen=_arg_value(args, "--listen"),
        )
    raise RuntimeError(f"Unsupported Pulse command: {' '.join(args)}")


def _invoke_identity_create(
    cli_module, wallet_path: str, *, genesis: int, network: int, force: bool
) -> dict:
    try:
        return cli_module.cmd_identity_create(
            wallet_path,
            genesis=genesis,
            network=network,
            force=force,
        )
    except TypeError:
        return cli_module.cmd_identity_create(wallet_path, genesis=genesis, network=network)


def _invoke_host_status(cli_module, wallet_path: str, listen: str | None) -> dict:
    try:
        return cli_module.cmd_host_status(identity_path=wallet_path, listen=listen)  # app CLI surface
    except TypeError:
        return cli_module.cmd_host_status(wallet_path, listen=listen)         # tools CLI surface


def _normalize_identity(record: dict, wallet_path: str) -> dict:
    address = record.get("address")
    if not address:
        raise ValueError("Pulse identity response missing address")
    return {
        "kind": "identity",
        "version": record.get("version", 1),
        "createdAt": record.get("createdAt"),
        "publicKey": record.get("publicKey", _derive_public_key(address)),
        "address": address,
        "balance": int(record.get("balance", 0)),
        "path": record.get("path", record.get("wallet", wallet_path)),
        "created": bool(record.get("created", False)),
    }


def _normalize_host_status(
    status: dict,
    path: str,
    *,
    listen: str | None = None,
    pages: int | None = None,
    identity_path: str | None = None,
) -> dict:
    if "account" in status:
        account = status["account"]
        address = account.get("address")
        balance = account.get("balance_pls")
    else:
        address = status.get("address")
        balance = status.get("balance")
    if address is None:
        raise ValueError("Pulse host status missing address")
    if balance is None:
        balance = 0
    return {
        "kind": "host-status",
        "address": address,
        "identity": status.get("identity", identity_path or status.get("wallet", path)),
        "listen": status.get("listen", listen),
        "balance": int(balance),
        "pages": int(status.get("pages", pages or 0)),
    }


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
