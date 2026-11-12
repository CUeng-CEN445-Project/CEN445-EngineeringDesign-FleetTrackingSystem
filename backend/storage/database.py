"""SQLite connection and composition of the table repositories."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..clock import DAY_MS, now_ms
from .alarms import AlarmRepository
from .positions import PositionRepository
from .schema import SCHEMA
from .settings import SettingsRepository
from .vehicles import VehicleRepository

# A SQLite database in WAL mode consists of up to three files
SQLITE_SUFFIXES = ("", "-wal", "-shm")


def database_files(path: Path) -> list[Path]:
    """The database file and its WAL / shared-memory companions (existing or not)."""
    return [Path(str(path) + suffix) for suffix in SQLITE_SUFFIXES]


def migrate_legacy_file(legacy: Path, current: Path) -> bool:
    """Renames a database left by an earlier version so its history is kept.

    Does nothing if `current` already exists or `legacy` does not. All companion
    files are renamed together so the WAL stays paired with its database.
    Must be called before the database is opened. Returns True if renamed.
    """
    if current.exists() or not legacy.exists():
        return False
    for src, dst in zip(database_files(legacy), database_files(current), strict=True):
        if src.exists():
            src.rename(dst)
    return True


class Database:
    """Owns the application's single SQLite connection.

    Table-specific queries live in the repositories:

        db.vehicles   vehicle definitions, odometers
        db.positions  position time series
        db.alarms     alarm records
        db.settings   user settings

    Operations spanning several tables (retention cleanup, counters) live here.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

        self.vehicles = VehicleRepository(self._conn, self._lock)
        self.positions = PositionRepository(self._conn, self._lock)
        self.alarms = AlarmRepository(self._conn, self._lock)
        self.settings = SettingsRepository(self._conn, self._lock)

    def prune(self, retention_hours: float, alarm_retention_days: float = 7) -> int:
        """Applies the retention policy; returns the number of positions deleted.

        - Positions older than `retention_hours` are deleted.
        - *Resolved* alarms older than `alarm_retention_days` are deleted;
          open alarms are kept regardless of age.
        """
        now = now_ms()
        deleted = self.positions.delete_older_than(now - int(retention_hours * 3_600_000))
        self.alarms.delete_resolved_before(now - int(alarm_retention_days * DAY_MS))
        return deleted

    def counts(self) -> dict:
        """Storage indicators shown on the dashboard."""
        try:
            size_mb = round(self.path.stat().st_size / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0
        return {
            "positions": self.positions.count(),
            "alarms": self.alarms.count(),
            "db_size_mb": size_mb,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
