"""Fleet simulator: background thread.

Every tick (1 Hz):
    1. every vehicle advances one step,
    2. the measurements are written to the `positions` time series in one transaction,
    3. the alarm engine evaluates the measurements,
    4. the dashboard snapshot is rebuilt (SSE connections broadcast it).
"""

from __future__ import annotations

import logging
import threading
import time

from .. import config
from ..alarms import AlarmEngine
from ..clock import local_day_start_ms, now_ms
from ..routes import ROUTES, VEHICLES
from ..storage import Database
from .snapshot import build_snapshot
from .vehicle import VehicleSim

log = logging.getLogger("filotrack.sim")

MIN_SPEED_MULTIPLIER = 0.25
MAX_SPEED_MULTIPLIER = 20.0
STORAGE_SYNC_EVERY_TICKS = 10
TODAY_STATS_CACHE_MS = 10_000


class Simulator(threading.Thread):
    def __init__(self, db: Database, settings: dict[str, float]):
        super().__init__(name="vehicle-simulator", daemon=True)
        self.db = db
        self.settings = dict(settings)
        self.alarm_engine = AlarmEngine(db.alarms, settings)
        self.alarm_engine.on_alarm = self._log_alarm
        self.stop_event = threading.Event()
        self.running = True
        self.speed_multiplier = 1.0
        self.started_at = now_ms()
        self.vehicles: list[VehicleSim] = self._build_fleet()
        self._lock = threading.RLock()
        self._snapshot: dict = {}
        self._states: list[dict] = []
        self._version = 0
        self._last_prune = 0.0
        self._storage = self.db.counts()
        self._today_cache: tuple[int, dict] = (0, {})

    # ------------------------------------------------------------------ setup
    def _build_fleet(self) -> list[VehicleSim]:
        odometers = {v["id"]: float(v.get("odometer_m") or 0.0) for v in self.db.vehicles.all()}
        return [
            VehicleSim(
                cfg,
                ROUTES[cfg["route_id"]],
                odometer_m=odometers.get(cfg["id"], 0.0),
                start_fraction=idx / len(VEHICLES),  # spread the vehicles along their routes
            )
            for idx, cfg in enumerate(VEHICLES)
        ]

    @staticmethod
    def _log_alarm(alarm: dict) -> None:
        log.warning("ALARM %s | %s | %s", alarm["vehicle_id"], alarm["type"], alarm["message"])

    # ------------------------------------------------------------------ controls
    def pause(self) -> None:
        with self._lock:
            self.running = False
            self._version += 1

    def resume(self) -> None:
        with self._lock:
            self.running = True
            self._version += 1

    def set_speed(self, multiplier: float) -> None:
        multiplier = max(MIN_SPEED_MULTIPLIER, min(MAX_SPEED_MULTIPLIER, float(multiplier)))
        with self._lock:
            self.speed_multiplier = multiplier
            self._version += 1

    def trigger(self, vehicle_id: str, kind: str) -> bool:
        """Starts a test scenario (`speed` / `deviation`); False for an unknown vehicle or kind."""
        vehicle = next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)
        if vehicle is None:
            return False
        now = time.monotonic()
        if kind == "speed":
            vehicle.trigger_speed(now, 18.0)
        elif kind == "deviation":
            vehicle.trigger_deviation(now, 20.0)
        else:
            return False
        with self._lock:
            self._version += 1
        return True

    def update_settings(self, values: dict[str, float]) -> None:
        with self._lock:
            self.settings.update(values)
            self.alarm_engine.update_settings(values)
            self._version += 1

    def stop(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        log.info("Simulator started (%d vehicles)", len(self.vehicles))
        next_tick = time.monotonic()
        tick = 0
        while not self.stop_event.is_set():
            with self._lock:
                running = self.running
                multiplier = self.speed_multiplier
            now = time.monotonic()
            if running:
                self.step(config.TICK_SECONDS * multiplier, now)
                tick += 1
                if tick % STORAGE_SYNC_EVERY_TICKS == 0:
                    self._sync_storage()
                if now - self._last_prune > config.MAINTENANCE_SECONDS:
                    self._last_prune = now
                    self._prune()
            self.publish()

            next_tick += config.TICK_SECONDS
            sleep_for = next_tick - time.monotonic()
            if sleep_for < 0:  # fell behind: do not try to catch up
                next_tick = time.monotonic()
                sleep_for = 0
            self.stop_event.wait(sleep_for)

        self.db.vehicles.update_odometers(self._odometers())
        log.info("Simulator stopped")

    def step(self, dt: float, now: float) -> list[dict]:
        """Advances the whole fleet one step, stores the measurements and evaluates alarms."""
        ts = now_ms()
        states = []
        for vehicle in self.vehicles:
            vehicle.step(dt, now)
            states.append(vehicle.state(ts))
        self.db.positions.add(states)
        created = self.alarm_engine.evaluate(states, ts)
        with self._lock:
            self._states = states
            # Increment the counters every tick; an exact COUNT(*) sync runs periodically
            self._storage = {
                **self._storage,
                "positions": self._storage.get("positions", 0) + len(states),
                "alarms": self._storage.get("alarms", 0) + len(created),
            }
        return created

    def _odometers(self) -> dict[str, float]:
        return {v.vehicle_id: v.odometer_m for v in self.vehicles}

    def _sync_storage(self) -> None:
        self._storage = self.db.counts()
        self.db.vehicles.update_odometers(self._odometers())

    def _prune(self) -> None:
        retention = float(self.settings.get("retention_hours", config.RETENTION_HOURS))
        deleted = self.db.prune(retention, config.ALARM_RETENTION_DAYS)
        if deleted:
            log.info("Retention policy: deleted %d old position rows", deleted)

    # ------------------------------------------------------------------ publishing
    def _today_stats(self, ts: int) -> dict:
        """Daily statistics are expensive queries, so they are cached for 10 s."""
        cached_at, stats = self._today_cache
        if ts - cached_at > TODAY_STATS_CACHE_MS:
            day_start = local_day_start_ms(ts)
            stats = {
                **self.db.positions.fleet_stats(day_start),
                "alarms_today": self.db.alarms.count_since(day_start),
            }
            self._today_cache = (ts, stats)
        return stats

    def publish(self) -> None:
        ts = now_ms()
        with self._lock:
            states = self._states or [v.state(ts) for v in self.vehicles]
            self._version += 1
            seq = self._version
            simulation = {
                "running": self.running,
                "speed": self.speed_multiplier,
                "started_at": self.started_at,
            }
            settings = dict(self.settings)
            storage = dict(self._storage)

        snapshot = build_snapshot(
            seq=seq,
            ts=ts,
            states=states,
            open_alarms=self.db.alarms.open(60),
            recent_alarms=self.db.alarms.history(40),
            today_stats=self._today_stats(ts),
            settings=settings,
            simulation=simulation,
            storage=storage,
        )
        with self._lock:
            self._snapshot = snapshot

    def get_snapshot(self, since_version: int | None = None) -> dict | None:
        """Latest snapshot; None if nothing changed since `since_version` (used by SSE)."""
        with self._lock:
            if since_version is not None and self._version <= since_version and self._snapshot:
                return None
            return self._snapshot
