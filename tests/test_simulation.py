"""backend.simulation: vehicle motion model, snapshot and simulator loop."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_simulation.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import time
import unittest

from backend import config
from backend.routes import ROUTES, VEHICLES
from backend.simulation import Simulator, VehicleSim
from backend.simulation.snapshot import build_snapshot, vehicle_status
from tests.support import DatabaseTestCase, make_alarm


def vehicle_on(mode: str) -> VehicleSim:
    """The first vehicle on a `loop` or `pingpong` route."""
    cfg = next(v for v in VEHICLES if ROUTES[v["route_id"]]["mode"] == mode)
    return VehicleSim(cfg, ROUTES[cfg["route_id"]])


class VehicleSimTest(unittest.TestCase):
    def setUp(self):
        self.vehicle = vehicle_on("pingpong")
        self.now = time.monotonic()

    def run_steps(self, n, dt=1.0):
        for i in range(1, n + 1):
            self.vehicle.step(dt, self.now + i, natural_events=False)

    def test_starts_at_cruise_speed(self):
        self.assertGreater(self.vehicle.speed, 0.5 * self.vehicle.speed_limit)
        self.assertLess(self.vehicle.speed, self.vehicle.speed_limit)

    def test_cruise_stays_under_limit(self):
        self.run_steps(60)
        self.assertLessEqual(self.vehicle.speed, self.vehicle.speed_limit)

    def test_speed_trigger_exceeds_limit(self):
        self.vehicle.trigger_speed(self.now, 20)
        self.run_steps(8)
        self.assertGreater(self.vehicle.speed, self.vehicle.speed_limit + 5)

    def test_speed_trigger_overrides_traffic_stop(self):
        self.vehicle.stopped_until = self.now + 60
        self.vehicle.trigger_speed(self.now, 20)
        self.run_steps(8)
        self.assertGreater(self.vehicle.speed, self.vehicle.speed_limit + 5)

    def test_traffic_stop_brings_vehicle_to_halt(self):
        self.vehicle.stopped_until = self.now + 60
        self.run_steps(10)
        self.assertEqual(self.vehicle.speed, 0.0)

    def test_acceleration_is_limited(self):
        self.vehicle.speed = 0.0
        self.vehicle.step(1.0, self.now + 1, natural_events=False)
        self.assertLessEqual(self.vehicle.speed, 5.0 + 1e-9)

    def test_deviation_trigger_moves_vehicle_off_route(self):
        self.vehicle.trigger_deviation(self.now, 20)
        self.vehicle.step(0.0, self.now + 10, natural_events=False)  # peak of the drift
        self.assertGreater(self.vehicle.offset_m, config.DEFAULT_SETTINGS["deviation_threshold_m"])
        self.vehicle.step(0.0, self.now + 25, natural_events=False)  # scenario over
        self.assertEqual(self.vehicle.offset_m, 0.0)

    def test_pingpong_reverses_at_end(self):
        total = self.vehicle.geom.total_m
        self.vehicle.distance_m = total - 1.0
        self.vehicle.speed = 36.0  # 10 m/s → overshoots the end by several meters
        self.vehicle.step(1.0, self.now + 1, natural_events=False)
        self.assertEqual(self.vehicle.direction, -1)
        self.assertLess(self.vehicle.distance_m, total)
        self.assertEqual(self.vehicle.speed, 0.0)

    def test_vehicle_resting_at_route_start_does_not_flip_direction(self):
        # Regression: a vehicle stopped exactly at 0 must not reverse every tick
        self.vehicle.distance_m = 0.0
        self.vehicle.direction = 1
        self.vehicle.speed = 0.0
        self.vehicle.stopped_until = self.now + 60
        self.run_steps(3)
        self.assertEqual(self.vehicle.direction, 1)

    def test_loop_route_wraps_around(self):
        vehicle = vehicle_on("loop")
        total = vehicle.geom.total_m
        vehicle.distance_m = total - 1.0
        vehicle.speed = 36.0
        vehicle.step(1.0, self.now + 1, natural_events=False)
        self.assertEqual(vehicle.direction, 1)
        self.assertGreaterEqual(vehicle.distance_m, 0.0)
        self.assertLess(vehicle.distance_m, 20.0)

    def test_odometer_accumulates(self):
        self.vehicle.stopped_until = 0
        before = self.vehicle.odometer_m
        self.run_steps(5)
        self.assertGreater(self.vehicle.odometer_m, before)

    def test_state_contains_measurement_fields(self):
        state = self.vehicle.state(123)
        for key in ("vehicle_id", "ts", "lat", "lng", "speed", "heading", "route_id",
                    "progress", "offset_m", "speed_limit", "odometer_m"):
            self.assertIn(key, state)
        self.assertEqual(state["ts"], 123)
        self.assertTrue(0.0 <= state["progress"] <= 1.0)


class SnapshotTest(unittest.TestCase):
    def test_vehicle_status_priority(self):
        self.assertEqual(vehicle_status(50, {"SPEED", "DEVIATION"}), "deviation")
        self.assertEqual(vehicle_status(50, {"SPEED"}), "speed")
        self.assertEqual(vehicle_status(50, set()), "moving")
        self.assertEqual(vehicle_status(0, set()), "stopped")

    def test_build_snapshot(self):
        states = [
            {"vehicle_id": "V-01", "speed": 60.0, "odometer_m": 1500.0},
            {"vehicle_id": "V-02", "speed": 0.0, "odometer_m": 500.0},
        ]
        snap = build_snapshot(
            seq=7, ts=1000, states=states,
            open_alarms=[{"vehicle_id": "V-01", "type": "SPEED"}],
            recent_alarms=[], today_stats={"samples_today": 42},
            settings={"x": 1}, simulation={"running": True}, storage={},
        )
        self.assertEqual(snap["seq"], 7)
        self.assertEqual([v["status"] for v in snap["vehicles"]], ["speed", "stopped"])
        self.assertEqual(snap["vehicles"][0]["active_alarm_types"], ["SPEED"])
        stats = snap["stats"]
        self.assertEqual((stats["total"], stats["moving"], stats["open_alarms"]), (2, 1, 1))
        self.assertEqual((stats["avg_speed"], stats["distance_km"]), (30.0, 2.0))
        self.assertEqual(stats["samples_today"], 42)


class SimulatorTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.sim = Simulator(self.db, self.db.settings.get_all())

    def test_step_writes_one_sample_per_vehicle(self):
        self.sim.step(1.0, time.monotonic())
        self.assertEqual(self.db.positions.count(), len(VEHICLES))

    def test_publish_builds_snapshot(self):
        self.sim.step(1.0, time.monotonic())
        self.sim.publish()
        snap = self.sim.get_snapshot()
        self.assertEqual(len(snap["vehicles"]), len(VEHICLES))
        self.assertEqual(snap["storage"]["positions"], len(VEHICLES))

    def test_snapshot_not_repeated_when_unchanged(self):
        self.sim.publish()
        seq = self.sim.get_snapshot()["seq"]
        self.assertIsNone(self.sim.get_snapshot(since_version=seq))
        self.sim.pause()  # every control action bumps the version
        self.assertIsNotNone(self.sim.get_snapshot(since_version=seq))

    def test_speed_trigger_creates_alarm(self):
        self.assertTrue(self.sim.trigger("V-01", "speed"))
        now = time.monotonic()
        created = []
        for i in range(1, 16):
            created += self.sim.step(1.0, now + i)
        self.assertIn(("V-01", "SPEED"), [(a["vehicle_id"], a["type"]) for a in created])

    def test_trigger_rejects_unknown_vehicle_or_type(self):
        self.assertFalse(self.sim.trigger("V-99", "speed"))
        self.assertFalse(self.sim.trigger("V-01", "flight"))

    def test_pause_resume_and_speed_clamp(self):
        self.sim.pause()
        self.assertFalse(self.sim.running)
        self.sim.resume()
        self.assertTrue(self.sim.running)
        self.sim.set_speed(1000)
        self.assertEqual(self.sim.speed_multiplier, 20.0)
        self.sim.set_speed(0)
        self.assertEqual(self.sim.speed_multiplier, 0.25)

    def test_update_settings_reaches_alarm_engine(self):
        self.sim.update_settings({"deviation_threshold_m": 300.0})
        self.assertEqual(self.sim.alarm_engine.deviation_threshold, 300.0)

    def test_odometer_restored_from_database(self):
        self.db.vehicles.update_odometers({"V-01": 5000.0})
        sim = Simulator(self.db, {})
        self.assertEqual(sim.vehicles[0].odometer_m, 5000.0)

    def test_today_stats_include_alarms(self):
        self.db.alarms.create(make_alarm())
        self.sim.publish()
        self.assertEqual(self.sim.get_snapshot()["stats"]["alarms_today"], 1)

    def test_thread_runs_and_stops(self):
        self.sim.start()
        deadline = time.monotonic() + 5
        while self.db.positions.count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.sim.stop()
        self.sim.join(timeout=5)
        self.assertFalse(self.sim.is_alive())
        self.assertGreater(self.db.positions.count(), 0)


if __name__ == "__main__":
    unittest.main()
