"""Time helpers.

All timestamps in the system are epoch milliseconds (int).
"""

from __future__ import annotations

import time

DAY_MS = 86_400_000


def now_ms() -> int:
    """Current time in epoch milliseconds."""
    return int(time.time() * 1000)


def local_day_start_ms(ts_ms: int | None = None) -> int:
    """Start of the local calendar day containing `ts_ms` (default: now), epoch ms.

    `ts % 86_400_000` would give UTC midnight; in Türkiye (UTC+3) the "day"
    would then start at 03:00. Daily statistics therefore use the local day.
    """
    if ts_ms is None:
        ts_ms = now_ms()
    lt = time.localtime(ts_ms / 1000)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return int(midnight * 1000)
