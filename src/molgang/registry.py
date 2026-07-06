"""Device registry — maps a device id to its stable PLS wallet metadata, in a sqlite DB.

A phone can't expose its IMEI to a browser (privacy), so the web client stores a stable
per-device id (a UUID in localStorage) and sends it on join. We register that id here against
its knitweb wallet address + chosen name, so the *same device* always returns to the *same
wallet* inside the node's domain secret. This registry never stores private keys.
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
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS faucet_grant ("
            "  device_id TEXT PRIMARY KEY, source TEXT NOT NULL,"
            "  claimed REAL NOT NULL)")
        # Tracked list of every PoUW certificate this node has issued (public data only —
        # holder/address/metrics + the PDF's sha256 so any copy can be verified later).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS certificate ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT NOT NULL, holder TEXT,"
            "  issued REAL NOT NULL, pulses_used INTEGER NOT NULL, pls_balance INTEGER,"
            "  work TEXT, sha256 TEXT NOT NULL)")
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

    def claim_faucet(self, device_id: str, source: str | None, *, cap: int,
                     now: float | None = None) -> dict:
        """Record one starter faucet grant for ``device_id``.

        A returning device is idempotent and does not consume another source slot. A new
        device from a saturated source is rejected before the Bar opens a fresh wallet.
        Set ``cap <= 0`` to disable the per-source cap for local/dev runs.
        """
        now = time.time() if now is None else now
        src = (source or "unknown").strip() or "unknown"
        row = self._db.execute(
            "SELECT source,claimed FROM faucet_grant WHERE device_id=?",
            (device_id,)).fetchone()
        if row is not None:
            return {"device_id": device_id, "source": row[0], "claimed": row[1], "new": False}
        if int(cap) > 0:
            used = self._db.execute(
                "SELECT COUNT(*) FROM faucet_grant WHERE source=?", (src,)).fetchone()[0]
            if used >= int(cap):
                raise RuntimeError("faucet source cap reached; reuse an existing wallet or try later")
        self._db.execute(
            "INSERT INTO faucet_grant (device_id,source,claimed) VALUES (?,?,?)",
            (device_id, src, now))
        self._db.commit()
        return {"device_id": device_id, "source": src, "claimed": now, "new": True}

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM device").fetchone()[0]

    def log_certificate(self, *, address: str, holder: str | None, pulses_used: int,
                        pls_balance: int | None, work: dict | None, sha256: str,
                        now: float | None = None) -> dict:
        """Append one issued PoUW certificate to the tracked list (public data only)."""
        import json as _json
        now = time.time() if now is None else now
        cur = self._db.execute(
            "INSERT INTO certificate (address,holder,issued,pulses_used,pls_balance,work,sha256) "
            "VALUES (?,?,?,?,?,?,?)",
            (address, holder, now, int(pulses_used),
             None if pls_balance is None else int(pls_balance),
             _json.dumps(work or {}, sort_keys=True), sha256))
        self._db.commit()
        return {"id": cur.lastrowid, "address": address, "holder": holder, "issued": now,
                "pulses_used": int(pulses_used), "pls_balance": pls_balance, "sha256": sha256}

    def list_certificates(self, limit: int = 100) -> list[dict]:
        """The tracked certificate list, newest first (public fields only)."""
        import json as _json
        rows = self._db.execute(
            "SELECT id,address,holder,issued,pulses_used,pls_balance,work,sha256 "
            "FROM certificate ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r[0], "address": r[1], "holder": r[2], "issued": r[3],
                 "pulses_used": r[4], "pls_balance": r[5],
                 "work": _json.loads(r[6] or "{}"), "sha256": r[7]} for r in rows]
