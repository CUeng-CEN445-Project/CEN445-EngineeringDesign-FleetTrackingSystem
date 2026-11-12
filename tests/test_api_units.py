"""backend.api: router, CSV export and settings validation (without sockets)."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_api_units.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import csv
import io
import unittest

from backend.api.csv_export import CSV_HEADER, positions_to_csv
from backend.api.endpoints import router as app_router
from backend.api.endpoints import validate_settings
from backend.api.router import ApiError, Request, Response, Router, compile_pattern


def make_request(query=None) -> Request:
    return Request("GET", "/", {}, query or {}, {}, app=None)


class CompilePatternTest(unittest.TestCase):
    def test_placeholder_captures_one_segment(self):
        regex = compile_pattern("/api/vehicles/{vehicle_id}/history")
        self.assertEqual(regex.match("/api/vehicles/V-01/history").groupdict(), {"vehicle_id": "V-01"})
        self.assertIsNone(regex.match("/api/vehicles/V-01/x/history"))
        self.assertIsNone(regex.match("/api/vehicles//history"))

    def test_literal_dot_is_escaped(self):
        regex = compile_pattern("/api/vehicles/{vehicle_id}/export.csv")
        self.assertIsNotNone(regex.match("/api/vehicles/V-01/export.csv"))
        self.assertIsNone(regex.match("/api/vehicles/V-01/exportXcsv"))

    def test_match_is_anchored(self):
        regex = compile_pattern("/api/state")
        self.assertIsNone(regex.match("/api/state/extra"))
        self.assertIsNone(regex.match("/prefix/api/state"))


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.router = Router()

        @self.router.get("/items/{item_id}")
        def get_item(req):
            return Response(json={"id": req.params["item_id"]})

        @self.router.post("/items")
        def create_item(req):
            return Response(status=201)

        self.get_item = get_item

    def test_resolve_returns_handler_and_params(self):
        handler, params = self.router.resolve("GET", "/items/42")
        self.assertIs(handler, self.get_item)
        self.assertEqual(params, {"item_id": "42"})

    def test_unknown_path_is_404(self):
        with self.assertRaises(ApiError) as ctx:
            self.router.resolve("GET", "/nope")
        self.assertEqual(ctx.exception.status, 404)

    def test_wrong_method_is_405(self):
        with self.assertRaises(ApiError) as ctx:
            self.router.resolve("GET", "/items")
        self.assertEqual(ctx.exception.status, 405)

    def test_application_routes_resolve(self):
        cases = [
            ("GET", "/api/health"),
            ("GET", "/api/vehicles/V-01"),
            ("GET", "/api/vehicles/V-01/history"),
            ("GET", "/api/vehicles/V-01/series"),
            ("GET", "/api/vehicles/V-01/export.csv"),
            ("GET", "/api/export.csv"),
            ("POST", "/api/vehicles/V-01/trigger"),
            ("POST", "/api/alarms/5/ack"),
            ("POST", "/api/alarms/ack-all"),
            ("GET", "/api/settings"),
            ("POST", "/api/settings"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                handler, _ = app_router.resolve(method, path)
                self.assertTrue(callable(handler))


class RequestTest(unittest.TestCase):
    def test_query_int_default_clamp_and_invalid(self):
        self.assertEqual(make_request().query_int("m", 15, 1, 100), 15)
        self.assertEqual(make_request({"m": ["50"]}).query_int("m", 15, 1, 100), 50)
        self.assertEqual(make_request({"m": ["9999"]}).query_int("m", 15, 1, 100), 100)
        self.assertEqual(make_request({"m": ["-3"]}).query_int("m", 15, 1, 100), 1)
        self.assertEqual(make_request({"m": ["abc"]}).query_int("m", 15, 1, 100), 15)

    def test_query_value(self):
        req = make_request({"status": ["all", "open"]})
        self.assertEqual(req.query_value("status"), "all")
        self.assertIsNone(req.query_value("missing"))
        self.assertEqual(req.query_value("missing", "x"), "x")


class ValidateSettingsTest(unittest.TestCase):
    def assert_rejected(self, body):
        with self.assertRaises(ApiError) as ctx:
            validate_settings(body)
        self.assertEqual(ctx.exception.status, 400)

    def test_valid_values_are_converted_to_float(self):
        self.assertEqual(
            validate_settings({"speed_tolerance_kmh": "10", "deviation_threshold_m": 150}),
            {"speed_tolerance_kmh": 10.0, "deviation_threshold_m": 150.0},
        )

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(validate_settings({"alarm_sound": 0, "hack": 1}), {"alarm_sound": 0.0})

    def test_rejections(self):
        self.assert_rejected({})
        self.assert_rejected({"unknown": 1})
        self.assert_rejected({"deviation_threshold_m": "lots"})
        self.assert_rejected({"deviation_threshold_m": None})
        self.assert_rejected({"deviation_threshold_m": 5})        # below the minimum
        self.assert_rejected({"retention_hours": 1000})           # above the maximum

    def test_bounds_are_inclusive(self):
        self.assertEqual(validate_settings({"retention_hours": 168})["retention_hours"], 168.0)


class CsvExportTest(unittest.TestCase):
    ROW = {
        "ts": 1_700_000_000_000, "lat": 41.0123456, "lng": 29.0, "speed": 55.55,
        "heading": 90.0, "offset_m": 3.21, "odometer_m": 1000.0,
    }

    def parse(self, data: bytes) -> list[list[str]]:
        text = data.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))  # BOM for Excel
        return list(csv.reader(io.StringIO(text.lstrip("﻿"))))

    def test_header_and_formatting(self):
        rows = self.parse(positions_to_csv([self.ROW]))
        self.assertEqual(rows[0], CSV_HEADER)
        self.assertEqual(rows[1][0], "2023-11-14T22:13:20+00:00")
        self.assertEqual(rows[1][2], "41.012346")
        self.assertEqual(rows[1][4], "55.5")

    def test_empty_export_has_only_header(self):
        self.assertEqual(self.parse(positions_to_csv([])), [CSV_HEADER])


if __name__ == "__main__":
    unittest.main()
