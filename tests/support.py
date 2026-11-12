"""Helpers shared by the tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend import config
from backend.clock import now_ms
from backend.routes import VEHICLES
from backend.storage import Database


def make_position(vehicle_id: str = "V-01", ts: int | None = None, **overrides) -> dict:
    """A sample measurement that can be written to the `positions` table."""
    row = {
        "vehicle_id": vehicle_id,
        "ts": now_ms() if ts is None else ts,
        "lat": 41.0,
        "lng": 29.0,
        "speed": 40.0,
        "heading": 90.0,
        "route_id": "bagdat",
        "progress": 0.1,
        "offset_m": 0.0,
        "odometer_m": 0.0,
    }
    row.update(overrides)
    return row


def make_alarm(vehicle_id: str = "V-01", alarm_type: str = "SPEED", ts: int | None = None, **overrides) -> dict:
    alarm = {
        "vehicle_id": vehicle_id,
        "type": alarm_type,
        "severity": "warning",
        "ts": now_ms() if ts is None else ts,
        "message": "test alarm",
    }
    alarm.update(overrides)
    return alarm


class DatabaseTestCase(unittest.TestCase):
    """A fresh database in a temporary folder, seeded with the real fleet definitions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.vehicles.seed(VEHICLES)
        self.db.settings.seed_defaults(config.DEFAULT_SETTINGS)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()
