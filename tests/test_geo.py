"""backend.geo: distance, bearing, polyline projection and offset calculations."""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_geo.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from backend.geo import (
    RouteGeometry,
    bearing_deg,
    cumulative_lengths,
    distance_to_polyline_m,
    haversine_m,
    offset_point,
)

# A straight east-west line on the equator, 0.01° ≈ 1112 m long
LINE = [(0.0, 0.0), (0.0, 0.01)]


class HaversineTest(unittest.TestCase):
    def test_one_degree_at_equator(self):
        self.assertAlmostEqual(haversine_m((0.0, 0.0), (0.0, 1.0)), 111_195, delta=500)

    def test_same_point_is_zero(self):
        self.assertEqual(haversine_m((41.0, 29.0), (41.0, 29.0)), 0.0)

    def test_is_symmetric(self):
        a, b = (41.0, 29.0), (41.1, 29.2)
        self.assertAlmostEqual(haversine_m(a, b), haversine_m(b, a), places=6)


class BearingTest(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertAlmostEqual(bearing_deg((0, 0), (1, 0)), 0.0, places=3)     # north
        self.assertAlmostEqual(bearing_deg((0, 0), (0, 1)), 90.0, places=3)    # east
        self.assertAlmostEqual(bearing_deg((0, 0), (-1, 0)), 180.0, places=3)  # south
        self.assertAlmostEqual(bearing_deg((0, 0), (0, -1)), 270.0, places=3)  # west


class PolylineTest(unittest.TestCase):
    def test_distance_to_polyline(self):
        # 0.001° north ≈ 111.2 m
        self.assertAlmostEqual(distance_to_polyline_m((0.001, 0.005), LINE), 111.2, delta=1.0)

    def test_point_on_line_has_zero_distance(self):
        self.assertAlmostEqual(distance_to_polyline_m((0.0, 0.005), LINE), 0.0, places=3)

    def test_distance_beyond_end_is_measured_to_endpoint(self):
        beyond = (0.0, 0.011)
        self.assertAlmostEqual(
            distance_to_polyline_m(beyond, LINE), haversine_m(beyond, LINE[-1]), delta=1.0
        )

    def test_cumulative_lengths_are_monotonic(self):
        points = [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01)]
        cum = cumulative_lengths(points)
        self.assertEqual(cum[0], 0.0)
        self.assertEqual(cum, sorted(cum))
        self.assertEqual(len(cum), len(points))


class OffsetPointTest(unittest.TestCase):
    def test_offset_is_perpendicular_to_heading(self):
        # A vehicle heading east (90°) is shifted 100 m to its right (south)
        lat, lng = offset_point(0.0, 0.005, 90.0, 100.0)
        self.assertLess(lat, 0.0)
        self.assertAlmostEqual(lng, 0.005, places=6)
        self.assertAlmostEqual(distance_to_polyline_m((lat, lng), LINE), 100.0, delta=0.5)

    def test_zero_offset_returns_same_point(self):
        self.assertEqual(offset_point(41.0, 29.0, 45.0, 0.0), (41.0, 29.0))


class RouteGeometryTest(unittest.TestCase):
    def setUp(self):
        self.geom = RouteGeometry(LINE)

    def test_position_at_midpoint(self):
        lat, lng, heading = self.geom.position_at(self.geom.total_m / 2)
        self.assertAlmostEqual(lat, 0.0, places=6)
        self.assertAlmostEqual(lng, 0.005, places=4)
        self.assertAlmostEqual(heading, 90.0, places=2)

    def test_position_is_clamped_to_route(self):
        self.assertAlmostEqual(self.geom.position_at(-50)[1], 0.0, places=6)
        self.assertAlmostEqual(self.geom.position_at(self.geom.total_m + 50)[1], 0.01, places=6)

    def test_project_returns_distance_along_route(self):
        quarter = self.geom.project((0.0005, 0.0025))  # a quarter of the way, slightly north
        self.assertAlmostEqual(quarter, self.geom.total_m / 4, delta=1.0)

    def test_as_dict(self):
        data = self.geom.as_dict()
        self.assertEqual(len(data["points"]), 2)
        self.assertAlmostEqual(data["length_m"], self.geom.total_m, delta=0.1)


if __name__ == "__main__":
    unittest.main()
