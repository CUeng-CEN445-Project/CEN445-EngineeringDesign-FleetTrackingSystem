"""SQLite schema.

`positions` is an append-only time series: one row per vehicle per second,
indexed on (vehicle_id, ts), with old rows removed by the retention policy.
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS vehicles (
    id           TEXT PRIMARY KEY,
    plate        TEXT NOT NULL,
    driver       TEXT NOT NULL,
    model        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    route_id     TEXT NOT NULL,
    speed_limit  REAL NOT NULL,
    phone        TEXT,
    odometer_m   REAL NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id   TEXT NOT NULL,
    ts           INTEGER NOT NULL,      -- epoch milliseconds
    lat          REAL NOT NULL,
    lng          REAL NOT NULL,
    speed        REAL NOT NULL,         -- km/h
    heading      REAL NOT NULL,         -- degrees, 0 = north
    route_id     TEXT NOT NULL,
    progress     REAL NOT NULL,         -- 0..1 along the route
    offset_m     REAL NOT NULL,         -- distance from the route centerline
    ignition     INTEGER NOT NULL DEFAULT 1,
    odometer_m   REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_positions_vehicle_ts
    ON positions (vehicle_id, ts);
CREATE INDEX IF NOT EXISTS idx_positions_ts
    ON positions (ts);

CREATE TABLE IF NOT EXISTS alarms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id   TEXT NOT NULL,
    type         TEXT NOT NULL,                     -- SPEED | DEVIATION
    severity     TEXT NOT NULL DEFAULT 'warning',   -- warning | critical
    ts           INTEGER NOT NULL,
    resolved_ts  INTEGER,                           -- NULL while the alarm is open
    speed        REAL,
    speed_limit  REAL,
    offset_m     REAL,
    threshold_m  REAL,
    message      TEXT NOT NULL,                     -- English summary
    status       TEXT NOT NULL DEFAULT 'active'     -- active | acked | resolved
);

CREATE INDEX IF NOT EXISTS idx_alarms_vehicle_ts
    ON alarms (vehicle_id, ts);
CREATE INDEX IF NOT EXISTS idx_alarms_ts
    ON alarms (ts);
CREATE INDEX IF NOT EXISTS idx_alarms_open
    ON alarms (resolved_ts);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value REAL NOT NULL
);
"""
