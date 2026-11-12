"""backend.alarms.AlarmEngine: speeding and off-route rules."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_alarm_engine.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from backend import config
from backend.alarms import AlarmEngine
from backend.clock import now_ms
from tests.support import DatabaseTestCase

LIMIT = 50.0
TOLERANCE = 5.0
THRESHOLD = 120.0


def sample(vehicle_id="V-01", speed=40.0, offset_m=0.0):
    return {"vehicle_id": vehicle_id, "speed": speed, "speed_limit": LIMIT, "offset_m": offset_m}


class AlarmEngineTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.engine = AlarmEngine(
            self.db.alarms, {"speed_tolerance_kmh": TOLERANCE, "deviation_threshold_m": THRESHOLD}
        )
        self.ts = now_ms()
        self.tick = 0

    def feed(self, *states) -> list[dict]:
        """Feeds one tick of measurements to the engine (each call is 1 s later)."""
        self.tick += 1
        return self.engine.evaluate(list(states), self.ts + self.tick * 1000)

    def feed_n(self, n, *states) -> list[dict]:
        created = []
        for _ in range(n):
            created += self.feed(*states)
        return created

    # ------------------------------------------------------------------ speeding
    def test_speed_alarm_after_consecutive_samples_then_resolves(self):
        fast = sample(speed=75)
        self.assertEqual(self.feed_n(config.SPEED_ALARM_TICKS - 1, fast), [])
        created = self.feed(fast)
        self.assertEqual([a["type"] for a in created], ["SPEED"])
        self.assertEqual(len(self.db.alarms.open()), 1)

        self.feed(sample(speed=45))
        self.assertEqual(self.db.alarms.open(), [])
        history = self.db.alarms.history(10)
        self.assertEqual(history[0]["status"], "resolved")
        self.assertIsNotNone(history[0]["resolved_ts"])

    def test_speed_within_tolerance_is_not_a_violation(self):
        self.assertEqual(self.feed_n(10, sample(speed=LIMIT + TOLERANCE)), [])

    def test_streak_resets_on_normal_sample(self):
        fast, normal = sample(speed=80), sample(speed=40)
        created = self.feed_n(2, fast) + self.feed(normal) + self.feed_n(2, fast)
        self.assertEqual(created, [])

    def test_speed_severity(self):
        warning = self.feed_n(3, sample("V-01", speed=LIMIT + 10))
        critical = self.feed_n(3, sample("V-02", speed=LIMIT + 25))
        self.assertEqual(warning[0]["severity"], "warning")
        self.assertEqual(critical[0]["severity"], "critical")

    def test_speed_alarm_stores_structured_fields_and_english_message(self):
        alarm = self.feed_n(3, sample(speed=72))[0]
        self.assertEqual((alarm["speed"], alarm["speed_limit"]), (72.0, LIMIT))
        self.assertEqual(alarm["message"], "Speeding: 72 km/h (limit 50 km/h, +22 km/h)")
        self.assertEqual(self.db.alarms.get(alarm["id"])["message"], alarm["message"])

    def test_alarm_not_duplicated_while_condition_persists(self):
        self.assertEqual(len(self.feed_n(10, sample(speed=80))), 1)
        self.assertEqual(len(self.db.alarms.open()), 1)

    def test_new_alarm_after_previous_resolved(self):
        self.feed_n(3, sample(speed=80))
        self.feed(sample(speed=40))
        self.assertEqual(len(self.feed_n(3, sample(speed=80))), 1)
        self.assertEqual(self.db.alarms.count(), 2)

    # ------------------------------------------------------------------ off route
    def test_deviation_alarm_requires_consecutive_samples(self):
        off = sample(offset_m=200)
        self.assertEqual(self.feed(off), [])
        created = self.feed(off)
        self.assertEqual([(a["type"], a["severity"]) for a in created], [("DEVIATION", "warning")])

    def test_deviation_alarm_stores_structured_fields_and_english_message(self):
        alarm = self.feed_n(2, sample(offset_m=156))[0]
        self.assertEqual((alarm["offset_m"], alarm["threshold_m"]), (156.0, THRESHOLD))
        self.assertEqual(alarm["message"], "Off route: 156 m from the route centerline (threshold 120 m)")

    def test_deviation_critical_severity(self):
        created = self.feed_n(2, sample(offset_m=THRESHOLD * 2))
        self.assertEqual(created[0]["severity"], "critical")

    def test_deviation_resolves_when_back_on_route(self):
        self.feed_n(2, sample(offset_m=200))
        self.feed(sample(offset_m=10))
        self.assertEqual(self.db.alarms.count_open(), 0)

    def test_speed_and_deviation_can_be_open_together(self):
        created = self.feed_n(3, sample(speed=90, offset_m=300))
        self.assertEqual(sorted(a["type"] for a in created), ["DEVIATION", "SPEED"])

    # ------------------------------------------------------------------ general
    def test_vehicles_are_independent(self):
        created = self.feed_n(3, sample("V-01", speed=80), sample("V-02", speed=40))
        self.assertEqual([a["vehicle_id"] for a in created], ["V-01"])

    def test_update_settings_changes_thresholds(self):
        self.engine.update_settings({"speed_tolerance_kmh": 30, "deviation_threshold_m": 500})
        self.assertEqual(self.feed_n(5, sample(speed=75, offset_m=300)), [])

    def test_acknowledged_alarm_stays_open_until_resolved(self):
        self.feed_n(3, sample(speed=90))
        alarm = self.db.alarms.open()[0]
        self.assertTrue(self.db.alarms.acknowledge(alarm["id"]))
        self.assertEqual(self.feed_n(3, sample(speed=90)), [])  # acknowledging creates no new alarm
        self.assertEqual(self.db.alarms.open()[0]["status"], "acked")

    def test_on_alarm_callback(self):
        received = []
        self.engine.on_alarm = received.append
        self.feed_n(3, sample(speed=90))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["id"], self.db.alarms.open()[0]["id"])


if __name__ == "__main__":
    unittest.main()
