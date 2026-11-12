"""Application configuration.

Paths and network settings can be overridden with environment variables
(FT_DATA_DIR, FT_DB_PATH, FT_HOST, FT_PORT).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = Path(os.environ.get("FT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("FT_DB_PATH", DATA_DIR / "filotrack.db"))
# Database file name used by earlier versions; renamed to DB_PATH on startup
LEGACY_DB_PATH = DATA_DIR / "filotakip.db"

HOST = os.environ.get("FT_HOST", "127.0.0.1")
PORT = int(os.environ.get("FT_PORT", "8000"))

# Interval between simulated measurements (seconds)
TICK_SECONDS = 1.0
# Time-series retention (hours); older positions are deleted automatically
RETENTION_HOURS = 24
# How often the retention cleanup runs (seconds)
MAINTENANCE_SECONDS = 60

DEFAULT_SETTINGS = {
    "speed_tolerance_kmh": 5.0,      # allowed overspeed above the limit
    "deviation_threshold_m": 120.0,  # allowed distance from the route centerline
    "retention_hours": float(RETENTION_HOURS),
    "alarm_sound": 1.0,
}

# Allowed (min, max) range of each setting that the dashboard / API may change
SETTINGS_LIMITS = {
    "speed_tolerance_kmh": (0.0, 30.0),
    "deviation_threshold_m": (20.0, 1000.0),
    "retention_hours": (1.0, 168.0),
    "alarm_sound": (0.0, 1.0),
}

# Resolved alarms are kept for this many days
ALARM_RETENTION_DAYS = 7

# Number of consecutive violating samples required before an alarm is raised
SPEED_ALARM_TICKS = 3
DEVIATION_ALARM_TICKS = 2

# Probability (per vehicle, per tick) and duration (s) of spontaneous violations
SPEED_EVENT_CHANCE = 0.0012
SPEED_EVENT_DURATION = 14.0
DEVIATION_EVENT_CHANCE = 0.0006
DEVIATION_EVENT_DURATION = 18.0


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
