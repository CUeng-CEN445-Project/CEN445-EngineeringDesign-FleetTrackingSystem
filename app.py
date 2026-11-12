#!/usr/bin/env python3
"""FiloTrack - Live Fleet Monitoring and Alarm System.

Usage:
    python app.py
    python app.py --port 8080 --no-open
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Keep non-ASCII characters (e.g. Turkish street names) intact in redirected output on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):  # pragma: no cover
    pass

from backend import config
from backend.api import AppContext, create_server
from backend.clock import now_ms
from backend.routes import VEHICLES
from backend.simulation import Simulator
from backend.storage import Database, database_files, migrate_legacy_file


def banner(host: str, port: int) -> None:
    url = f"http://{host}:{port}"
    print()
    print("  ============================================================")
    print("   FILOTRACK  |  Live Fleet Monitoring and Alarm System")
    print("  ============================================================")
    print(f"   Dashboard    : {url}")
    print(f"   API          : {url}/api/state")
    print(f"   SSE stream   : {url}/api/stream")
    print(f"   Database     : {config.DB_PATH}")
    print("   Press Ctrl+C to stop")
    print("  ============================================================")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="FiloTrack fleet tracking system")
    parser.add_argument("--host", default=config.HOST, help="address to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.PORT, help="port to listen on (default 8000)")
    parser.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier (default 1.0)")
    parser.add_argument("--reset", action="store_true", help="delete the database and start fresh")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--verbose", action="store_true", help="verbose HTTP logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("http.server").setLevel(logging.WARNING)

    config.ensure_dirs()

    if migrate_legacy_file(config.LEGACY_DB_PATH, config.DB_PATH):
        print(f"Renamed database {config.LEGACY_DB_PATH.name} -> {config.DB_PATH.name} (history kept).")

    if args.reset:
        for path in database_files(config.DB_PATH):
            if path.exists():
                path.unlink()
        print("Database reset.")

    db = Database(config.DB_PATH)
    db.vehicles.seed(VEHICLES)
    db.settings.seed_defaults(config.DEFAULT_SETTINGS)
    # Alarms left open by a previous run: their condition is no longer known
    db.alarms.resolve_all_open(now_ms())
    settings = db.settings.get_all()

    sim = Simulator(db, settings)
    if args.speed != 1.0:
        sim.set_speed(args.speed)

    try:
        server = create_server(args.host, args.port, AppContext(db=db, sim=sim))
    except OSError as exc:
        print(f"ERROR: could not listen on {args.host}:{args.port} -> {exc}")
        print("The port may be in use. Try another one, e.g. --port 8080.")
        db.close()
        return 1

    sim.start()
    banner(args.host, args.port)

    if not args.no_open:
        display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
        url = f"http://{display_host}:{args.port}"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.stop_event.set()
        sim.stop()
        sim.join(timeout=3)
        try:
            server.server_close()
        finally:
            db.close()
    print("FiloTrack stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
