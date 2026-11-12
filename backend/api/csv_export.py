"""CSV export of the position time series."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

CSV_HEADER = [
    "timestamp_utc", "ts_ms", "lat", "lng", "speed_kmh", "heading", "offset_m", "odometer_m",
]


def positions_to_csv(rows: list[dict]) -> bytes:
    """Converts raw position rows to CSV.

    Starts with a UTF-8 BOM so that Excel opens the file with the right encoding.
    """
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        iso = datetime.fromtimestamp(r["ts"] / 1000, tz=timezone.utc).isoformat()
        writer.writerow(
            [
                iso, r["ts"], f"{r['lat']:.6f}", f"{r['lng']:.6f}",
                f"{r['speed']:.1f}", f"{r['heading']:.1f}",
                f"{r['offset_m']:.1f}", f"{r['odometer_m']:.1f}",
            ]
        )
    return buf.getvalue().encode("utf-8")
