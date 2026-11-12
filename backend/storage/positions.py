"""`positions` table: the vehicle position time series.

Writes: one `executemany` per tick for the whole fleet, in a single transaction.
Reads: time-range queries on the (vehicle_id, ts) index; map trails and charts
are downsampled into time buckets.
"""

from __future__ import annotations

from collections.abc import Iterable

from .base import Repository

_INSERT = """
    INSERT INTO positions
        (vehicle_id, ts, lat, lng, speed, heading, route_id,
         progress, offset_m, ignition, odometer_m)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class PositionRepository(Repository):
    # ------------------------------------------------------------------ writes
    def add(self, rows: Iterable[dict]) -> int:
        """Appends measurements; returns the number of rows inserted."""
        payload = [
            (
                r["vehicle_id"], r["ts"], r["lat"], r["lng"], r["speed"],
                r["heading"], r["route_id"], r["progress"], r["offset_m"],
                r.get("ignition", 1), r.get("odometer_m", 0.0),
            )
            for r in rows
        ]
        if payload:
            with self._lock, self._conn:
                self._conn.executemany(_INSERT, payload)
        return len(payload)

    def delete_older_than(self, cutoff_ts: int) -> int:
        """Retention policy: deletes measurements older than `cutoff_ts`."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM positions WHERE ts < ?", (cutoff_ts,))
        return max(0, cur.rowcount)

    # ------------------------------------------------------------------ reads
    def history(self, vehicle_id: str, start_ts: int, end_ts: int, max_points: int = 900) -> list[dict]:
        """Downsampled position history for the map trail (about `max_points` points).

        The range is split into equal time buckets (at least 500 ms) and the
        positions in each bucket are averaged.
        """
        span = max(1, end_ts - start_ts)
        bucket = max(500, span // max_points)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT (ts / ?) * ? AS bucket_ts,
                       MIN(ts) AS ts,
                       AVG(lat) AS lat,
                       AVG(lng) AS lng,
                       AVG(speed) AS speed,
                       AVG(offset_m) AS offset_m
                FROM positions
                WHERE vehicle_id = ? AND ts BETWEEN ? AND ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (bucket, bucket, vehicle_id, start_ts, end_ts),
            ).fetchall()
        return [
            {
                "ts": r["ts"],
                "lat": round(r["lat"], 6),
                "lng": round(r["lng"], 6),
                "speed": round(r["speed"], 1),
                "offset_m": round(r["offset_m"], 1),
            }
            for r in rows
        ]

    def raw(self, vehicle_id: str, start_ts: int, end_ts: int, limit: int = 20000) -> list[dict]:
        """Raw measurements ordered by time (used for CSV export)."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT ts, lat, lng, speed, heading, route_id, progress, offset_m,
                       ignition, odometer_m
                FROM positions
                WHERE vehicle_id = ? AND ts BETWEEN ? AND ?
                ORDER BY ts LIMIT ?
                """,
                (vehicle_id, start_ts, end_ts, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def speed_series(self, vehicle_id: str, start_ts: int, end_ts: int, bucket_ms: int = 30_000) -> list[dict]:
        """Speed chart: average / maximum / minimum speed per time bucket."""
        bucket_ms = max(1000, bucket_ms)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT (ts / ?) * ? AS bucket_ts,
                       AVG(speed) AS avg_speed,
                       MAX(speed) AS max_speed,
                       MIN(speed) AS min_speed
                FROM positions
                WHERE vehicle_id = ? AND ts BETWEEN ? AND ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (bucket_ms, bucket_ms, vehicle_id, start_ts, end_ts),
            ).fetchall()
        return [
            {
                "ts": r["bucket_ts"],
                "avg": round(r["avg_speed"], 1),
                "max": round(r["max_speed"], 1),
                "min": round(r["min_speed"], 1),
            }
            for r in rows
        ]

    def vehicle_stats(self, vehicle_id: str, since_ts: int) -> dict:
        """Sample count, average and maximum speed of one vehicle since `since_ts`."""
        with self._lock:
            r = self._conn.execute(
                """
                SELECT COUNT(*) AS samples, AVG(speed) AS avg_speed, MAX(speed) AS max_speed
                FROM positions WHERE vehicle_id = ? AND ts >= ?
                """,
                (vehicle_id, since_ts),
            ).fetchone()
        return {
            "samples": r["samples"] or 0,
            "avg_speed": round(r["avg_speed"] or 0, 1),
            "max_speed": round(r["max_speed"] or 0, 1),
        }

    def fleet_stats(self, since_ts: int) -> dict:
        """Sample count and average speed of the whole fleet since `since_ts`."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) AS samples, AVG(speed) AS avg_speed FROM positions WHERE ts >= ?",
                (since_ts,),
            ).fetchone()
        return {
            "samples_today": r["samples"] or 0,
            "avg_speed": round(r["avg_speed"] or 0, 1),
        }

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
