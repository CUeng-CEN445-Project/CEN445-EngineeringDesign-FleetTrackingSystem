"""Small geographic helpers (no external libraries).

Points are (lat, lng) tuples in degrees; distances are meters; headings are
degrees clockwise from north.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    """Great-circle distance between two (lat, lng) points, in meters."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """Initial bearing from a to b; 0 = north, clockwise, in degrees."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _local_xy(point: Sequence[float], origin: Sequence[float]) -> tuple[float, float]:
    """Planar (equirectangular) approximation in meters, accurate for short distances."""
    lat0 = math.radians(origin[0])
    x = math.radians(point[1] - origin[1]) * math.cos(lat0) * EARTH_RADIUS_M
    y = math.radians(point[0] - origin[0]) * EARTH_RADIUS_M
    return x, y


def _project_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """Closest point to P on segment AB → (distance, t) where t ∈ [0, 1] along AB."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


def cumulative_lengths(points: Sequence[Sequence[float]]) -> list[float]:
    """Distance of each polyline vertex from the start, in meters."""
    acc = [0.0]
    for i in range(1, len(points)):
        acc.append(acc[-1] + haversine_m(points[i - 1], points[i]))
    return acc


def point_at_distance(
    points: Sequence[Sequence[float]], cum: Sequence[float], distance: float
) -> tuple[float, float, float]:
    """(lat, lng, heading) at `distance` meters along the polyline (clamped to its ends)."""
    total = cum[-1]
    if total <= 0:
        return points[0][0], points[0][1], 0.0
    d = max(0.0, min(total, distance))

    # Binary search for the segment that contains d
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= d:
            lo = mid
        else:
            hi = mid

    seg_len = cum[lo + 1] - cum[lo]
    t = 0.0 if seg_len == 0 else (d - cum[lo]) / seg_len
    a, b = points[lo], points[lo + 1]
    lat = a[0] + (b[0] - a[0]) * t
    lng = a[1] + (b[1] - a[1]) * t
    return lat, lng, bearing_deg(a, b)


def offset_point(lat: float, lng: float, heading_deg: float, offset_m: float) -> tuple[float, float]:
    """Moves a point `offset_m` meters perpendicular to its heading (positive = to the right)."""
    if offset_m == 0:
        return lat, lng
    rad = math.radians(heading_deg)
    east = math.cos(rad) * offset_m
    north = -math.sin(rad) * offset_m
    lat2 = lat + math.degrees(north / EARTH_RADIUS_M)
    lng2 = lng + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat2, lng2


def distance_to_polyline_m(point: Sequence[float], points: Sequence[Sequence[float]]) -> float:
    """Shortest distance from `point` to the polyline centerline, in meters."""
    if len(points) < 2:
        return haversine_m(point, points[0]) if points else 0.0

    origin = points[0]
    px, py = _local_xy(point, origin)
    best = float("inf")
    for i in range(len(points) - 1):
        ax, ay = _local_xy(points[i], origin)
        bx, by = _local_xy(points[i + 1], origin)
        dist, _ = _project_on_segment(px, py, ax, ay, bx, by)
        best = min(best, dist)
    return best


class RouteGeometry:
    """Pre-computed geometry of one route polyline."""

    def __init__(self, points: Iterable[Sequence[float]]):
        self.points = [(float(p[0]), float(p[1])) for p in points]
        self.cum = cumulative_lengths(self.points)
        self.total_m = self.cum[-1]

    def position_at(self, distance_m: float) -> tuple[float, float, float]:
        return point_at_distance(self.points, self.cum, distance_m)

    def project(self, point: Sequence[float]) -> float:
        """Distance along the route (from its start) of the point's projection."""
        if len(self.points) < 2:
            return 0.0
        origin = self.points[0]
        px, py = _local_xy(point, origin)
        best_dist, best_along = float("inf"), 0.0
        for i in range(len(self.points) - 1):
            ax, ay = _local_xy(self.points[i], origin)
            bx, by = _local_xy(self.points[i + 1], origin)
            dist, t = _project_on_segment(px, py, ax, ay, bx, by)
            if dist < best_dist:
                best_dist = dist
                best_along = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
        return best_along

    def as_dict(self) -> dict:
        return {
            "points": [[round(lat, 6), round(lng, 6)] for lat, lng in self.points],
            "length_m": round(self.total_m, 1),
        }
