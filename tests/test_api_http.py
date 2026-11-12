"""backend.api: end-to-end tests through a real HTTP server.

The server listens on a free random port (port 0). The simulator thread is not
started; the tests advance the state themselves with `sim.step()` / `sim.publish()`.
"""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_api_http.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend import config
from backend.api import AppContext, create_server
from backend.routes import ROUTES, VEHICLES
from backend.simulation import Simulator
from backend.storage import Database
from tests.support import make_alarm


class HttpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db = Database(Path(cls._tmp.name) / "api.db")
        cls.db.vehicles.seed(VEHICLES)
        cls.db.settings.seed_defaults(config.DEFAULT_SETTINGS)
        cls.sim = Simulator(cls.db, cls.db.settings.get_all())
        for i in range(3):
            cls.sim.step(1.0, time.monotonic() + i)
        cls.sim.publish()

        cls.server = create_server("127.0.0.1", 0, AppContext(db=cls.db, sim=cls.sim))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05})
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_event.set()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.db.close()
        cls._tmp.cleanup()

    # ------------------------------------------------------------------ helpers
    def request(self, method, path, body=None, raw_body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = raw_body if raw_body is not None else (json.dumps(body) if body is not None else None)
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def get_json(self, path, expected=200):
        resp, data = self.request("GET", path)
        self.assertEqual(resp.status, expected, data)
        return json.loads(data)

    def post_json(self, path, body=None, expected=200):
        resp, data = self.request("POST", path, body=body if body is not None else {})
        self.assertEqual(resp.status, expected, data)
        return json.loads(data)

    # ------------------------------------------------------------------ general
    def test_health(self):
        self.assertTrue(self.get_json("/api/health")["ok"])

    def test_bootstrap(self):
        data = self.get_json("/api/bootstrap")
        self.assertEqual(set(data["routes"]), set(ROUTES))
        self.assertEqual(len(data["vehicles"]), len(VEHICLES))
        self.assertIn("vehicles", data["state"])

    def test_state_and_vehicles(self):
        self.assertEqual(len(self.get_json("/api/state")["vehicles"]), len(VEHICLES))
        self.assertEqual(len(self.get_json("/api/vehicles")["vehicles"]), len(VEHICLES))

    def test_storage(self):
        self.assertGreaterEqual(self.get_json("/api/storage")["positions"], 3 * len(VEHICLES))

    def test_unknown_api_path_is_404_json(self):
        data = self.get_json("/api/missing", expected=404)
        self.assertEqual(data["status"], 404)
        self.assertEqual(data["error"], "API endpoint not found")

    def test_wrong_method_is_405(self):
        self.post_json("/api/health", expected=405)

    # ------------------------------------------------------------------ vehicles
    def test_vehicle_detail(self):
        data = self.get_json("/api/vehicles/V-01")
        self.assertEqual(data["vehicle"]["id"], "V-01")
        self.assertEqual(data["current"]["vehicle_id"], "V-01")
        self.assertEqual(set(data["today"]), {"samples", "avg_speed", "max_speed", "alarms"})
        self.assertGreaterEqual(data["today"]["samples"], 3)

    def test_unknown_vehicle_is_404(self):
        for path in ("/api/vehicles/V-99", "/api/vehicles/V-99/history", "/api/vehicles/V-99/series"):
            with self.subTest(path=path):
                self.get_json(path, expected=404)

    def test_history_and_series(self):
        history = self.get_json("/api/vehicles/V-01/history?minutes=5")
        self.assertEqual(history["minutes"], 5)
        self.assertGreaterEqual(len(history["points"]), 1)
        series = self.get_json("/api/vehicles/V-01/series?minutes=5&bucket=1")
        self.assertEqual(series["bucket_seconds"], 5)  # clamped to the minimum
        self.assertGreaterEqual(len(series["series"]), 1)

    def test_csv_export_routes(self):
        for path in ("/api/vehicles/V-01/export.csv?minutes=5", "/api/export.csv?vehicle_id=V-01"):
            with self.subTest(path=path):
                resp, data = self.request("GET", path)
                self.assertEqual(resp.status, 200)
                self.assertTrue(resp.getheader("Content-Type").startswith("text/csv"))
                self.assertIn('filename="filotrack_V-01_', resp.getheader("Content-Disposition"))
                self.assertGreaterEqual(len(data.decode("utf-8").splitlines()), 2)

    def test_csv_export_invalid_vehicle(self):
        self.assertEqual(self.request("GET", "/api/vehicles/V-99/export.csv")[0].status, 404)
        self.assertEqual(self.request("GET", "/api/export.csv")[0].status, 400)

    def test_trigger(self):
        self.assertTrue(self.post_json("/api/vehicles/V-02/trigger", {"type": "deviation"})["ok"])
        self.post_json("/api/vehicles/V-02/trigger", {"type": "flight"}, expected=400)
        self.post_json("/api/vehicles/V-99/trigger", {"type": "speed"}, expected=404)

    # ------------------------------------------------------------------ alarms
    def test_alarm_ack_flow(self):
        alarm_id = self.db.alarms.create(make_alarm("V-05"))
        open_ids = [a["id"] for a in self.get_json("/api/alarms?status=open")["alarms"]]
        self.assertIn(alarm_id, open_ids)

        self.assertTrue(self.post_json(f"/api/alarms/{alarm_id}/ack")["ok"])
        self.assertFalse(self.post_json(f"/api/alarms/{alarm_id}/ack")["ok"])  # already acknowledged
        self.post_json("/api/alarms/abc/ack", expected=404)

        history = self.get_json("/api/alarms?status=all&vehicle_id=V-05")["alarms"]
        self.assertEqual(history[0]["status"], "acked")

    def test_ack_all(self):
        self.db.alarms.create(make_alarm("V-06"))
        self.assertGreaterEqual(self.post_json("/api/alarms/ack-all")["acknowledged"], 1)

    # ------------------------------------------------------------------ simulation
    def test_simulation_control(self):
        self.assertFalse(self.post_json("/api/simulation", {"action": "pause"})["simulation"]["running"])
        self.assertTrue(self.post_json("/api/simulation", {"action": "resume"})["simulation"]["running"])
        speed = self.post_json("/api/simulation", {"action": "speed", "value": 2})["simulation"]["speed"]
        self.assertEqual(speed, 2.0)
        self.post_json("/api/simulation", {"action": "speed", "value": "fast"}, expected=400)
        self.post_json("/api/simulation", {"action": "fly"}, expected=400)
        self.post_json("/api/simulation", {"action": "speed", "value": 1})

    # ------------------------------------------------------------------ settings
    def test_settings_update_and_validation(self):
        data = self.post_json("/api/settings", {"deviation_threshold_m": 150})
        self.assertEqual(data["settings"]["deviation_threshold_m"], 150.0)
        self.assertEqual(self.get_json("/api/settings")["settings"]["deviation_threshold_m"], 150.0)
        self.assertEqual(self.sim.alarm_engine.deviation_threshold, 150.0)

        self.post_json("/api/settings", {"deviation_threshold_m": 1}, expected=400)
        self.post_json("/api/settings", {"deviation_threshold_m": "x"}, expected=400)
        self.post_json("/api/settings", {}, expected=400)
        self.post_json("/api/settings", {"deviation_threshold_m": 120})

    def test_invalid_json_body(self):
        resp, data = self.request("POST", "/api/settings", raw_body="{broken")
        self.assertEqual(resp.status, 400)
        self.assertEqual(json.loads(data)["error"], "Invalid JSON")
        resp, _ = self.request("POST", "/api/settings", raw_body="[1, 2]")
        self.assertEqual(resp.status, 400)

    # ------------------------------------------------------------------ static files
    def test_static_index_and_assets(self):
        resp, data = self.request("GET", "/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<html", data.lower())
        resp, _ = self.request("GET", "/js/app.js")
        self.assertEqual(resp.getheader("Content-Type"), "application/javascript; charset=utf-8")

    def test_every_stylesheet_and_script_in_index_is_served(self):
        _, html = self.request("GET", "/")
        assets = re.findall(r'(?:href|src)="(/[^"]+\.(?:css|js))"', html.decode("utf-8"))
        self.assertGreaterEqual(len(assets), 15)
        for path in assets:
            with self.subTest(path=path):
                resp, body = self.request("GET", path)
                self.assertEqual(resp.status, 200)
                self.assertGreater(len(body), 0)
                expected = "text/css" if path.endswith(".css") else "application/javascript"
                self.assertTrue(resp.getheader("Content-Type").startswith(expected))

    def test_static_missing_file_is_404(self):
        self.assertEqual(self.request("GET", "/missing.html")[0].status, 404)

    def test_static_path_traversal_is_blocked(self):
        resp, _ = self.request("GET", "/../app.py")
        self.assertIn(resp.status, (403, 404))
        resp, _ = self.request("GET", "/%2e%2e/backend/config.py")
        self.assertIn(resp.status, (403, 404))

    def test_head_has_no_body(self):
        resp, data = self.request("HEAD", "/api/health")
        self.assertEqual(resp.status, 200)
        self.assertEqual(data, b"")
        self.assertGreater(int(resp.getheader("Content-Length")), 0)

    # ------------------------------------------------------------------ SSE
    def test_sse_stream_sends_snapshot(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/stream")
        resp = conn.getresponse()
        self.assertEqual(resp.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        lines = []
        while len(lines) < 2:
            line = resp.fp.readline().decode("utf-8").strip()
            if line:
                lines.append(line)
        conn.close()
        self.assertTrue(lines[0].startswith("id: "))
        snapshot = json.loads(lines[1][len("data: "):])
        self.assertEqual(len(snapshot["vehicles"]), len(VEHICLES))


if __name__ == "__main__":
    unittest.main()
