"""Device registry — maps a device id to its (deterministic) PLS wallet, in a sqlite DB.

A phone can't expose its IMEI to a browser (privacy), so the web client stores a stable
per-device id (a UUID in localStorage) and sends it on join. We register that id here against
its knitweb wallet address + chosen name, so the *same device* always returns to the *same
wallet* — the browser-legal equivalent of "this device = this wallet".
"""

from __future__ import annotations

import os
import sqlite3
import time

DEFAULT_DB = os.environ.get("MOLGANG_DB", os.path.expanduser("~/.molgang/registry.db"))


class Registry:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or DEFAULT_DB
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS device ("
            "  device_id TEXT PRIMARY KEY, address TEXT NOT NULL, name TEXT,"
            "  first_seen REAL NOT NULL, last_seen REAL NOT NULL, visits INTEGER NOT NULL DEFAULT 1)")
        # A per-device balance snapshot so a wallet's pulses + silk survive a server restart
        # (the Bar engine is otherwise in-memory). Keyed by the same stable device id.
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS balance ("
            "  device_id TEXT PRIMARY KEY, pulses INTEGER NOT NULL, silk INTEGER NOT NULL,"
            "  updated REAL NOT NULL)")
        self._db.commit()

    def register(self, device_id: str, address: str, name: str, *, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        cur = self._db.execute("SELECT visits FROM device WHERE device_id=?", (device_id,))
        row = cur.fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO device (device_id,address,name,first_seen,last_seen,visits) VALUES (?,?,?,?,?,1)",
                (device_id, address, name, now, now))
            new = True
        else:
            self._db.execute(
                "UPDATE device SET address=?, name=?, last_seen=?, visits=visits+1 WHERE device_id=?",
                (address, name, now, device_id))
            new = False
        self._db.commit()
        return {**self.get(device_id), "new": new}

    def get(self, device_id: str) -> dict | None:
        cur = self._db.execute(
            "SELECT device_id,address,name,first_seen,last_seen,visits FROM device WHERE device_id=?",
            (device_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {"device_id": r[0], "address": r[1], "name": r[2],
                "first_seen": r[3], "last_seen": r[4], "visits": r[5]}

    def save_balance(self, device_id: str, pulses: int, silk: int, *, now: float | None = None) -> None:
        """Persist a device's current PLS + silk so it can be restored after a restart."""
        now = time.time() if now is None else now
        self._db.execute(
            "INSERT INTO balance (device_id,pulses,silk,updated) VALUES (?,?,?,?) "
            "ON CONFLICT(device_id) DO UPDATE SET pulses=excluded.pulses, silk=excluded.silk, "
            "updated=excluded.updated",
            (device_id, int(pulses), int(silk), now))
        self._db.commit()

    def get_balance(self, device_id: str) -> dict | None:
        """The saved {pulses, silk} snapshot for a device, or None if never persisted."""
        r = self._db.execute(
            "SELECT pulses,silk FROM balance WHERE device_id=?", (device_id,)).fetchone()
        if not r:
            return None
        return {"pulses": r[0], "silk": r[1]}

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM device").fetchone()[0]
