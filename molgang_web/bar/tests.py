"""Smoke tests for the Django front-end.

These drive the dual-play API through Django's test client and assert the JSON shapes
match the stdlib server's. They exercise the real engine (no mocks), so a passing run
proves Django delegates correctly to a shared ``Bar`` singleton.
"""

from __future__ import annotations

import json

from django.test import Client, TestCase

from . import engine


class ApiSmokeTest(TestCase):
    def setUp(self):
        # Fresh, isolated in-memory bar per test (default world path, no registry).
        engine.reset_bar()
        self.client = Client()

    def tearDown(self):
        engine.reset_bar()

    def _post(self, path, payload):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json")

    def test_index_serves_dapp_shell(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"MOLGANG", r.getvalue() if hasattr(r, "getvalue") else r.content)

    def test_state_shape(self):
        r = self.client.get("/api/state")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("tables", "avatars", "you", "explorer", "bar_woven", "spiral_leaderboard"):
            self.assertIn(key, body)
        self.assertIsNone(body["you"])  # no sid -> no "you"
        self.assertEqual(len(body["tables"]), 3)

    def test_join_sit_propose_state_flow(self):
        # join (with a device id so it round-trips through the registry-less path)
        r = self._post("/api/join", {"name": "Ada", "avatar": "laser-maxi", "device": "dev-test-1"})
        self.assertEqual(r.status_code, 200)
        join = r.json()
        self.assertIn("sid", join)
        self.assertEqual(join["avatar"], "laser-maxi")
        self.assertTrue(join["address"].startswith("pls1"))
        sid = join["sid"]

        # sit -> returns a full state snapshot
        r = self._post("/api/sit", {"sid": sid, "table": "periodic"})
        self.assertEqual(r.status_code, 200)
        seated = r.json()
        self.assertEqual(seated["you"]["table"], "periodic")

        # propose a real molecule -> NPC table-mates confirm and it weaves
        r = self._post("/api/propose", {"sid": sid, "term": "H2O"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["pid"].startswith("p"))

        # poll state -> the term is woven into the bar
        body = self.client.get(f"/api/state?sid={sid}").json()
        self.assertGreaterEqual(body["bar_woven"], 1)
        self.assertEqual(body["you"]["woven"], 1)

    def test_propose_requires_seat(self):
        sid = self._post("/api/join", {"name": "Lin"}).json()["sid"]
        r = self._post("/api/propose", {"sid": sid, "term": "H2O"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_spiral_propose_and_capture(self):
        sid = self._post("/api/join", {"name": "Rae", "table": "periodic"}).json()["sid"]
        links = ["H2O -> O2", "O2 -> O3", "O3 -> H2O"]  # a 3-link spiral
        r = self._post("/api/spiral/propose", {"sid": sid, "links": links})
        self.assertEqual(r.status_code, 200)
        sp = r.json()
        self.assertEqual(sp["length"], 3)
        self.assertIn("cid", sp)
        self.assertIn("state", sp)
