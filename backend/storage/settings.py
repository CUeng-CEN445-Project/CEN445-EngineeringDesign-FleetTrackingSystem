"""`settings` table: numeric settings editable from the dashboard (key → value)."""

from __future__ import annotations

from .base import Repository


class SettingsRepository(Repository):
    def seed_defaults(self, defaults: dict[str, float]) -> None:
        """Adds missing settings with their defaults; never overwrites user changes."""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                [(k, float(v)) for k, v in defaults.items()],
            )

    def get_all(self) -> dict[str, float]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def update(self, values: dict[str, float]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                [(k, float(v)) for k, v in values.items()],
            )
