#!/usr/bin/env python3
"""Desktop ↔ dapp presence bridge.

The PHP dapp at e.g. https://5mart.ml/molgang is the always-reachable rendezvous point
(the desktop can reach it; the shared host cannot reach your localhost). This tiny helper
lets the **desktop** MOLGANG client:

  * POST a heartbeat to the dapp so the browser shows "🖥️ desktop active", and
  * read the dapp's presence so the desktop can tell whether the **browser** version is
    active or was used before — for the same device→wallet identity.

It is dependency-free (urllib) and non-invasive: run it alongside the desktop bar, or
import `beat()` / `peers()` into the desktop and call them on your own timer.

Usage:
    KNODE_DAPP=https://5mart.ml/molgang \\
    MOLGANG_DEVICE=<same device id the browser uses> \\
    python3 desktop_bridge.py            # beats once, prints what it sees about the web client
    python3 desktop_bridge.py --watch    # beat every 15s and report the web client's presence
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

DAPP = os.environ.get("KNODE_DAPP", "https://5mart.ml/molgang").rstrip("/")
DEVICE = os.environ.get("MOLGANG_DEVICE", "")
INFO = os.environ.get("MOLGANG_DESKTOP_INFO", f"molgang-desktop · {sys.platform}")


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        DAPP + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def beat(device: str | None = None) -> dict:
    """Tell the dapp this desktop client is alive; returns both clients' presence."""
    dev = device or DEVICE
    if not dev:
        raise SystemExit("set MOLGANG_DEVICE to the device id the browser uses")
    return _post("/api/presence", {"device": dev, "client": "desktop", "info": INFO})


def peers(device: str | None = None) -> dict:
    """Read presence — what the desktop can learn about the web (browser) client."""
    dev = device or DEVICE
    with urllib.request.urlopen(f"{DAPP}/api/presence?device={dev}", timeout=8) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("peers", {})


def _report(p: dict) -> None:
    web = p.get("web", {})
    if web.get("active"):
        print("🌐 browser version is ACTIVE right now (same wallet).")
    elif web.get("used_before"):
        ago = web.get("last_seen")
        when = f"{round((time.time() - ago) / 60)}m ago" if ago else "before"
        print(f"🌐 browser version was used {when}.")
    else:
        print("🌐 browser version not seen yet for this device.")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        while True:
            try:
                _report(beat().get("peers", {}))
            except Exception as e:
                print("bridge error:", e)
            time.sleep(15)
    else:
        _report(beat().get("peers", {}))
