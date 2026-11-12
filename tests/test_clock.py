"""backend.clock: timestamps and local day start."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_clock.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import time
import unittest

from backend.clock import DAY_MS, local_day_start_ms, now_ms


class ClockTest(unittest.TestCase):
    def test_now_ms_matches_system_time(self):
        self.assertAlmostEqual(now_ms(), time.time() * 1000, delta=50)

    def test_local_day_start_is_local_midnight(self):
        ts = now_ms()
        start = local_day_start_ms(ts)
        self.assertLessEqual(start, ts)
        self.assertLess(ts - start, DAY_MS)
        lt = time.localtime(start / 1000)
        self.assertEqual((lt.tm_hour, lt.tm_min, lt.tm_sec), (0, 0, 0))
        self.assertEqual(time.localtime(ts / 1000).tm_mday, lt.tm_mday)

    def test_local_day_start_defaults_to_now(self):
        self.assertEqual(local_day_start_ms(), local_day_start_ms(now_ms()))

    def test_midnight_maps_to_itself(self):
        start = local_day_start_ms()
        self.assertEqual(local_day_start_ms(start), start)
        self.assertEqual(local_day_start_ms(start - 1), local_day_start_ms(start - DAY_MS // 2))


if __name__ == "__main__":
    unittest.main()
