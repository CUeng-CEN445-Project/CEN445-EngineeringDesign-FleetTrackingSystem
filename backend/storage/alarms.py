"""`alarms` table: speeding and off-route alarm records.

Lifecycle:
    active  --(user acknowledges)-->  acked
    active / acked  --(condition clears)-->  resolved_ts is set

Alarms with `resolved_ts IS NULL` are "open". An acknowledged alarm keeps the
status `acked` after it is resolved, so the history shows which alarms the
operator had seen.
"""

from __future__ import annotations

from .base import Repository

_SELECT_WITH_VEHICLE = """
    SELECT a.*, v.plate, v.driver, v.kind
    FROM alarms a LEFT JOIN vehicles v ON v.id = a.vehicle_id
"""


class AlarmRepository(Repository):
    # ------------------------------------------------------------------ reads
    def open(self, limit: int = 100) -> list[dict]:
        """Open (unresolved) alarms, newest first."""
        with self._lock:
            rows = self._conn.execute(
                _SELECT_WITH_VEHICLE + " WHERE a.resolved_ts IS NULL ORDER BY a.ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def history(self, limit: int = 100, vehicle_id: str | None = None) -> list[dict]:
        """All alarms (open and resolved), newest first; optionally for one vehicle."""
        sql = _SELECT_WITH_VEHICLE
        params: list = []
        if vehicle_id:
            sql += " WHERE a.vehicle_id = ?"
            params.append(vehicle_id)
        sql += " ORDER BY a.ts DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get(self, alarm_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(_SELECT_WITH_VEHICLE + " WHERE a.id = ?", (alarm_id,)).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM alarms").fetchone()[0]

    def count_open(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM alarms WHERE resolved_ts IS NULL"
            ).fetchone()[0]

    def count_since(self, since_ts: int, vehicle_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM alarms WHERE ts >= ?"
        params: list = [since_ts]
        if vehicle_id:
            sql += " AND vehicle_id = ?"
            params.append(vehicle_id)
        with self._lock:
            return self._conn.execute(sql, params).fetchone()[0]

    # ------------------------------------------------------------------ writes
    def create(self, alarm: dict) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO alarms
                    (vehicle_id, type, severity, ts, speed, speed_limit,
                     offset_m, threshold_m, message, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    alarm["vehicle_id"], alarm["type"], alarm["severity"],
                    alarm["ts"], alarm.get("speed"), alarm.get("speed_limit"),
                    alarm.get("offset_m"), alarm.get("threshold_m"),
                    alarm["message"],
                ),
            )
        return int(cur.lastrowid)

    def resolve(self, alarm_id: int, ts: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE alarms
                SET resolved_ts = ?,
                    status = CASE WHEN status = 'acked' THEN 'acked' ELSE 'resolved' END
                WHERE id = ? AND resolved_ts IS NULL
                """,
                (ts, alarm_id),
            )

    def resolve_all_open(self, ts: int) -> None:
        """Closes alarms left open by a previous run (their condition is unknown now)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE alarms SET resolved_ts = ?, status = 'resolved' WHERE resolved_ts IS NULL",
                (ts,),
            )

    def acknowledge(self, alarm_id: int) -> bool:
        """Acknowledges an open, not yet acknowledged alarm; True on success."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                UPDATE alarms SET status = 'acked'
                WHERE id = ? AND status = 'active' AND resolved_ts IS NULL
                """,
                (alarm_id,),
            )
        return cur.rowcount > 0

    def acknowledge_all(self) -> int:
        """Acknowledges every open alarm; returns how many were acknowledged."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE alarms SET status = 'acked' WHERE status = 'active' AND resolved_ts IS NULL"
            )
        return cur.rowcount

    def delete_resolved_before(self, cutoff_ts: int) -> int:
        """Retention policy: deletes *resolved* alarms older than `cutoff_ts`."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM alarms WHERE resolved_ts IS NOT NULL AND ts < ?", (cutoff_ts,)
            )
        return max(0, cur.rowcount)
