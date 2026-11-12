"""backend.storage: time series, alarm, settings and vehicle repositories."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_storage.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile
import unittest
from pathlib import Path

from backend.clock import DAY_MS, now_ms
from backend.routes import VEHICLES
from backend.storage import Database, migrate_legacy_file
from tests.support import DatabaseTestCase, make_alarm, make_position

HOUR_MS = 3_600_000


class PositionRepositoryTest(DatabaseTestCase):
    def test_insert_and_query_raw(self):
        ts = now_ms()
        added = self.db.positions.add(
            [make_position(ts=ts + i * 1000, speed=40 + i, lat=41.0 + i * 0.0001) for i in range(3)]
        )
        self.assertEqual(added, 3)
        raw = self.db.positions.raw("V-01", ts - 1000, ts + 10_000)
        self.assertEqual([r["speed"] for r in raw], [40, 41, 42])  # ordered by time
        self.assertEqual(self.db.positions.count(), 3)

    def test_add_empty_is_noop(self):
        self.assertEqual(self.db.positions.add([]), 0)
        self.assertEqual(self.db.positions.count(), 0)

    def test_queries_are_filtered_by_vehicle_and_time(self):
        ts = now_ms()
        self.db.positions.add(
            [
                make_position("V-01", ts),
                make_position("V-02", ts),
                make_position("V-01", ts - 2 * HOUR_MS),  # outside the window
            ]
        )
        raw = self.db.positions.raw("V-01", ts - HOUR_MS, ts + 1000)
        self.assertEqual(len(raw), 1)

    def test_history_is_downsampled(self):
        start = now_ms() - 3000 * 1000
        self.db.positions.add([make_position(ts=start + i * 1000) for i in range(3000)])
        points = self.db.positions.history("V-01", start, start + 3000 * 1000, max_points=100)
        self.assertLessEqual(len(points), 101)
        self.assertGreater(len(points), 50)
        self.assertEqual(points, sorted(points, key=lambda p: p["ts"]))

    def test_history_averages_within_bucket(self):
        ts = 1_000_000_000_000  # aligned to a bucket boundary
        self.db.positions.add(
            [make_position(ts=ts, lat=41.0), make_position(ts=ts + 100, lat=41.002)]
        )
        points = self.db.positions.history("V-01", ts, ts + 400, max_points=1)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0]["lat"], 41.001, places=6)
        self.assertEqual(points[0]["ts"], ts)

    def test_speed_series_aggregates(self):
        ts = 1_000_000_020_000  # aligned to a 30 s bucket
        self.db.positions.add(
            [make_position(ts=ts + i * 1000, speed=s) for i, s in enumerate((10, 20, 30))]
        )
        series = self.db.positions.speed_series("V-01", ts, ts + 10_000, bucket_ms=30_000)
        self.assertEqual(len(series), 1)
        self.assertEqual((series[0]["avg"], series[0]["max"], series[0]["min"]), (20, 30, 10))

    def test_vehicle_and_fleet_stats(self):
        ts = now_ms()
        self.db.positions.add(
            [
                make_position("V-01", ts, speed=30),
                make_position("V-01", ts + 1, speed=50),
                make_position("V-02", ts, speed=70),
            ]
        )
        self.assertEqual(
            self.db.positions.vehicle_stats("V-01", ts - 1000),
            {"samples": 2, "avg_speed": 40.0, "max_speed": 50.0},
        )
        self.assertEqual(
            self.db.positions.fleet_stats(ts - 1000), {"samples_today": 3, "avg_speed": 50.0}
        )

    def test_stats_on_empty_table(self):
        self.assertEqual(self.db.positions.vehicle_stats("V-01", 0)["samples"], 0)
        self.assertEqual(self.db.positions.fleet_stats(0)["avg_speed"], 0)


class AlarmRepositoryTest(DatabaseTestCase):
    def test_create_and_open(self):
        alarm_id = self.db.alarms.create(make_alarm())
        open_alarms = self.db.alarms.open()
        self.assertEqual(len(open_alarms), 1)
        self.assertEqual(open_alarms[0]["id"], alarm_id)
        self.assertEqual(open_alarms[0]["status"], "active")
        self.assertEqual(open_alarms[0]["plate"], VEHICLES[0]["plate"])  # joined with vehicles

    def test_resolve_closes_alarm(self):
        alarm_id = self.db.alarms.create(make_alarm())
        self.db.alarms.resolve(alarm_id, now_ms())
        self.assertEqual(self.db.alarms.open(), [])
        alarm = self.db.alarms.get(alarm_id)
        self.assertEqual(alarm["status"], "resolved")
        self.assertIsNotNone(alarm["resolved_ts"])

    def test_resolving_acked_alarm_keeps_acked_status(self):
        alarm_id = self.db.alarms.create(make_alarm())
        self.assertTrue(self.db.alarms.acknowledge(alarm_id))
        self.db.alarms.resolve(alarm_id, now_ms())
        self.assertEqual(self.db.alarms.get(alarm_id)["status"], "acked")

    def test_cannot_acknowledge_twice_or_after_resolution(self):
        acked = self.db.alarms.create(make_alarm())
        self.assertTrue(self.db.alarms.acknowledge(acked))
        self.assertFalse(self.db.alarms.acknowledge(acked))
        resolved = self.db.alarms.create(make_alarm("V-02"))
        self.db.alarms.resolve(resolved, now_ms())
        self.assertFalse(self.db.alarms.acknowledge(resolved))
        self.assertFalse(self.db.alarms.acknowledge(999_999))

    def test_acknowledge_all(self):
        for vid in ("V-01", "V-02", "V-03"):
            self.db.alarms.create(make_alarm(vid))
        self.assertEqual(self.db.alarms.acknowledge_all(), 3)
        self.assertEqual(self.db.alarms.acknowledge_all(), 0)
        self.assertTrue(all(a["status"] == "acked" for a in self.db.alarms.open()))

    def test_resolve_all_open(self):
        for vid in ("V-01", "V-02"):
            self.db.alarms.create(make_alarm(vid))
        self.db.alarms.resolve_all_open(now_ms())
        self.assertEqual(self.db.alarms.count_open(), 0)
        self.assertEqual(self.db.alarms.count(), 2)

    def test_history_order_and_vehicle_filter(self):
        ts = now_ms()
        self.db.alarms.create(make_alarm("V-01", ts=ts - 2000))
        self.db.alarms.create(make_alarm("V-02", ts=ts - 1000))
        self.db.alarms.create(make_alarm("V-01", ts=ts))
        history = self.db.alarms.history(10)
        self.assertEqual([a["ts"] for a in history], [ts, ts - 1000, ts - 2000])  # newest first
        self.assertEqual(len(self.db.alarms.history(10, "V-01")), 2)
        self.assertEqual(len(self.db.alarms.history(1)), 1)

    def test_count_since(self):
        ts = now_ms()
        self.db.alarms.create(make_alarm("V-01", ts=ts - DAY_MS))
        self.db.alarms.create(make_alarm("V-01", ts=ts))
        self.db.alarms.create(make_alarm("V-02", ts=ts))
        self.assertEqual(self.db.alarms.count_since(ts - 1000), 2)
        self.assertEqual(self.db.alarms.count_since(ts - 1000, "V-01"), 1)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.db.alarms.get(12345))


class SettingsRepositoryTest(DatabaseTestCase):
    def test_defaults_are_seeded(self):
        self.assertEqual(self.db.settings.get_all()["deviation_threshold_m"], 120.0)

    def test_update_persists_and_seeding_does_not_overwrite(self):
        self.db.settings.update({"deviation_threshold_m": 200})
        self.db.settings.seed_defaults({"deviation_threshold_m": 120, "new_setting": 1})
        settings = self.db.settings.get_all()
        self.assertEqual(settings["deviation_threshold_m"], 200.0)
        self.assertEqual(settings["new_setting"], 1.0)


class VehicleRepositoryTest(DatabaseTestCase):
    def test_seed_is_idempotent_and_keeps_odometer(self):
        self.db.vehicles.update_odometers({"V-01": 1234.56})
        self.db.vehicles.seed(VEHICLES)
        vehicles = self.db.vehicles.all()
        self.assertEqual(len(vehicles), len(VEHICLES))
        self.assertEqual(vehicles[0]["odometer_m"], 1234.6)

    def test_seed_updates_changed_definition(self):
        changed = [{**VEHICLES[0], "driver": "New Driver"}]
        self.db.vehicles.seed(changed)
        self.assertEqual(self.db.vehicles.all()[0]["driver"], "New Driver")


class DatabaseMaintenanceTest(DatabaseTestCase):
    def test_prune_removes_only_old_positions(self):
        self.db.positions.add([make_position(ts=now_ms() - 3 * HOUR_MS), make_position()])
        self.assertEqual(self.db.prune(retention_hours=1), 1)
        self.assertEqual(self.db.positions.count(), 1)

    def test_prune_removes_old_resolved_alarms_but_keeps_open_ones(self):
        old = now_ms() - 10 * DAY_MS
        resolved = self.db.alarms.create(make_alarm("V-01", ts=old))
        self.db.alarms.resolve(resolved, old + 1000)
        still_open = self.db.alarms.create(make_alarm("V-02", ts=old))
        recent = self.db.alarms.create(make_alarm("V-03"))
        self.db.alarms.resolve(recent, now_ms())

        self.db.prune(retention_hours=24, alarm_retention_days=7)

        self.assertIsNone(self.db.alarms.get(resolved))
        self.assertIsNotNone(self.db.alarms.get(still_open))
        self.assertIsNotNone(self.db.alarms.get(recent))

    def test_counts(self):
        self.db.positions.add([make_position(), make_position("V-02")])
        self.db.alarms.create(make_alarm())
        counts = self.db.counts()
        self.assertEqual((counts["positions"], counts["alarms"]), (2, 1))
        self.assertGreaterEqual(counts["db_size_mb"], 0)


class LegacyMigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.legacy = self.dir / "filotakip.db"
        self.current = self.dir / "filotrack.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_legacy_database_is_renamed_with_its_data(self):
        db = Database(self.legacy)
        db.positions.add([make_position()])
        db.close()

        self.assertTrue(migrate_legacy_file(self.legacy, self.current))
        self.assertFalse(self.legacy.exists())
        migrated = Database(self.current)
        self.assertEqual(migrated.positions.count(), 1)
        migrated.close()

    def test_companion_files_are_renamed_too(self):
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.legacy) + suffix).write_bytes(b"x")
        migrate_legacy_file(self.legacy, self.current)
        for suffix in ("", "-wal", "-shm"):
            self.assertTrue(Path(str(self.current) + suffix).exists(), suffix)
            self.assertFalse(Path(str(self.legacy) + suffix).exists(), suffix)

    def test_existing_current_database_is_never_overwritten(self):
        self.legacy.write_bytes(b"old")
        self.current.write_bytes(b"new")
        self.assertFalse(migrate_legacy_file(self.legacy, self.current))
        self.assertEqual(self.current.read_bytes(), b"new")
        self.assertTrue(self.legacy.exists())

    def test_nothing_to_migrate(self):
        self.assertFalse(migrate_legacy_file(self.legacy, self.current))
        self.assertFalse(self.current.exists())


if __name__ == "__main__":
    unittest.main()
