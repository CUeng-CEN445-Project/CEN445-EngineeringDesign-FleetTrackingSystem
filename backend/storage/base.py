"""Common base class of the table repositories."""

from __future__ import annotations

import sqlite3
import threading


class Repository:
    """Groups the queries of a single table.

    All repositories share one SQLite connection and one lock. The connection is
    used from several threads (simulator + HTTP requests), so every query runs
    under `self._lock`; writes use `with self._conn:` so each one is a single
    transaction.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self._conn = conn
        self._lock = lock
