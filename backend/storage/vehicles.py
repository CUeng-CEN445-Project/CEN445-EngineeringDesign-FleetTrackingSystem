"""`vehicles` table: vehicle definitions and odometers."""

from __future__ import annotations

from collections.abc import Sequence

from ..clock import now_ms
from .base import Repository


class VehicleRepository(Repository):
    def seed(self, vehicles: Sequence[dict]) -> None:
        """Inserts vehicle definitions and updates existing ones.

        The odometer (`odometer_m`) is preserved, so it survives restarts.
        """
        ts = now_ms()
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT INTO vehicles (id, plate, driver, model, kind, route_id,
                                      speed_limit, phone, odometer_m, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    plate=excluded.plate, driver=excluded.driver,
                    model=excluded.model, kind=excluded.kind,
                    route_id=excluded.route_id, speed_limit=excluded.speed_limit,
                    phone=excluded.phone
                """,
                [
                    (
                        v["id"], v["plate"], v["driver"], v["model"], v["kind"],
                        v["route_id"], float(v["speed_limit"]), v.get("phone"), ts,
                    )
                    for v in vehicles
                ],
            )

    def all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_odometers(self, values: dict[str, float]) -> None:
        if not values:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE vehicles SET odometer_m = ? WHERE id = ?",
                [(round(v, 1), vid) for vid, v in values.items()],
            )
