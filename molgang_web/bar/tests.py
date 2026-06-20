"""Smoke tests for the Django front-end.

These drive the dual-play API through Django's test client and assert the JSON shapes
match the stdlib server's. They exercise the real engine (no mocks), so a passing run
proves Django delegates correctly to a shared ``Bar`` singleton.
"""

from __future__ import annotations

import json
from unittest.mock import call, patch

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase

from . import engine
from .events import world_state_event
from .serializers import account_pill_from_state


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

    def test_account_pill_serializer_uses_canonical_state(self):
        sid = self._post(
            "/api/join",
            {"name": "Ada", "avatar": "laser-maxi", "device": "dev-pill-1"},
        ).json()["sid"]
        body = self.client.get(f"/api/state?sid={sid}").json()
        pill = account_pill_from_state(body)

        self.assertEqual(pill["name"], body["you"]["name"])
        self.assertEqual(pill["wallet"], body["you"]["address"])
        self.assertEqual(pill["pulses"], body["you"]["pulses"])
        self.assertEqual(pill["silk"], body["you"]["silk"])
        self.assertEqual(pill["knits"], body["you"]["knits_made"])
        self.assertEqual(pill["level"], body["you"]["level"])
        self.assertNotIn("owner", pill)
        self.assertNotIn("token", pill)

    def test_account_pill_partial_renders_server_side(self):
        sid = self._post(
            "/api/join",
            {"name": "Ada", "avatar": "laser-maxi", "device": "dev-pill-2"},
        ).json()["sid"]
        r = self.client.get(f"/partials/account-pill?sid={sid}", HTTP_HX_REQUEST="true")

        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("data-account-pill", html)
        self.assertIn("Ada", html)
        self.assertIn("PLS", html)
        self.assertIn("silk", html)
        self.assertIn("knits", html)
        self.assertIn("wallet pls1", html)
        self.assertNotIn("NFT", html)

    def test_account_pill_partial_handles_missing_session(self):
        r = self.client.get("/partials/account-pill", HTTP_HX_REQUEST="true")

        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("data-account-pill", html)
        self.assertIn("Walk in", html)

    def test_world_state_event_uses_canonical_api_shape(self):
        sid = self._post("/api/join", {"name": "Ada", "device": "dev-ws-shape"}).json()["sid"]
        event = world_state_event(sid, {"kind": "test"})

        self.assertEqual(event["type"], "world.state")
        self.assertEqual(event["trigger"]["kind"], "test")
        self.assertEqual(event["state"]["you"]["sid"], sid)
        for key in ("tables", "avatars", "you", "explorer", "bar_woven", "pulse_host"):
            self.assertIn(key, event["state"])

    def test_world_websocket_sends_initial_state_for_sid(self):
        sid = self._post("/api/join", {"name": "Ada", "device": "dev-ws-1"}).json()["sid"]

        async def run():
            from molgang_web.asgi import application

            communicator = WebsocketCommunicator(application, f"/ws/world/?sid={sid}")
            connected, _ = await communicator.connect()
            payload = await communicator.receive_json_from()
            await communicator.disconnect()
            return connected, payload

        connected, payload = async_to_sync(run)()
        self.assertTrue(connected)
        self.assertEqual(payload["type"], "world.state")
        self.assertEqual(payload["trigger"]["kind"], "connect")
        self.assertEqual(payload["state"]["you"]["sid"], sid)

    def test_write_endpoints_broadcast_world_updates(self):
        with patch("bar.views.broadcast_world") as broadcast:
            sid = self._post(
                "/api/join",
                {"name": "Ada", "avatar": "laser-maxi", "device": "dev-ws-2"},
            ).json()["sid"]
            self._post("/api/sit", {"sid": sid, "table": "periodic"})
            self._post("/api/propose", {"sid": sid, "term": "H2O"})
            self._post(
                "/api/spiral/propose",
                {"sid": sid, "links": ["H2O -> O2", "O2 -> O3", "O3 -> H2O"]},
            )

        broadcast.assert_has_calls(
            [
                call("join", sid),
                call("sit", sid),
                call("propose", sid),
                call("spiral.propose", sid),
            ],
            any_order=False,
        )

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
