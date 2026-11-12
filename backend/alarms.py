"""Rule-based alarm engine: speeding and off-route detection."""

from __future__ import annotations

import threading
from collections.abc import Callable

from . import config
from .storage.alarms import AlarmRepository

# An overspeed of at least this many km/h above the limit is "critical"
SPEED_CRITICAL_OVER_KMH = 20.0
# An offset greater than threshold × this factor is "critical"
DEVIATION_CRITICAL_FACTOR = 1.8

SPEED = "SPEED"
DEVIATION = "DEVIATION"


class AlarmEngine:
    """Tracks how long each vehicle has been violating a rule.

    A rule fires only after several consecutive violating samples, so a single
    noisy GPS fix does not raise a false alarm. While an alarm is open no
    duplicate is created; when the condition clears the alarm is resolved
    automatically (`resolved_ts` is set).

    The stored `message` is English; dashboards build their own localized text
    from the structured fields (speed, speed_limit, offset_m, threshold_m).
    """

    def __init__(self, store: AlarmRepository, settings: dict[str, float]):
        self.store = store
        self.settings = dict(settings)
        self.on_alarm: Callable[[dict], None] | None = None  # optional, called for each new alarm
        self._lock = threading.RLock()
        self._open: dict[tuple[str, str], int] = {}  # (vehicle_id, type) -> alarm id
        self._speed_streak: dict[str, int] = {}
        self._deviation_streak: dict[str, int] = {}

    def update_settings(self, settings: dict[str, float]) -> None:
        with self._lock:
            self.settings.update(settings)

    @property
    def tolerance(self) -> float:
        return float(self.settings.get("speed_tolerance_kmh", 5.0))

    @property
    def deviation_threshold(self) -> float:
        return float(self.settings.get("deviation_threshold_m", 120.0))

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, states: list[dict], ts: int) -> list[dict]:
        """Checks one tick of measurements; returns the alarms created in this tick."""
        created: list[dict] = []
        with self._lock:
            for state in states:
                created += self._check_speed(state, ts)
                created += self._check_deviation(state, ts)

        if self.on_alarm:
            for alarm in created:
                self.on_alarm(alarm)
        return created

    def _check_speed(self, state: dict, ts: int) -> list[dict]:
        vid = state["vehicle_id"]
        over = state["speed"] - state["speed_limit"]
        if over <= self.tolerance:
            self._speed_streak[vid] = 0
            self._resolve(vid, SPEED, ts)
            return []

        self._speed_streak[vid] = self._speed_streak.get(vid, 0) + 1
        if self._speed_streak[vid] < config.SPEED_ALARM_TICKS or (vid, SPEED) in self._open:
            return []

        return [
            self._raise(
                vid, SPEED, ts,
                severity="critical" if over >= SPEED_CRITICAL_OVER_KMH else "warning",
                message=(
                    f"Speeding: {state['speed']:.0f} km/h "
                    f"(limit {state['speed_limit']:.0f} km/h, +{over:.0f} km/h)"
                ),
                speed=round(state["speed"], 1),
                speed_limit=float(state["speed_limit"]),
            )
        ]

    def _check_deviation(self, state: dict, ts: int) -> list[dict]:
        vid = state["vehicle_id"]
        offset = state["offset_m"]
        threshold = self.deviation_threshold
        if offset <= threshold:
            self._deviation_streak[vid] = 0
            self._resolve(vid, DEVIATION, ts)
            return []

        self._deviation_streak[vid] = self._deviation_streak.get(vid, 0) + 1
        if self._deviation_streak[vid] < config.DEVIATION_ALARM_TICKS or (vid, DEVIATION) in self._open:
            return []

        return [
            self._raise(
                vid, DEVIATION, ts,
                severity="critical" if offset > threshold * DEVIATION_CRITICAL_FACTOR else "warning",
                message=(
                    f"Off route: {offset:.0f} m from the route centerline "
                    f"(threshold {threshold:.0f} m)"
                ),
                offset_m=round(offset, 1),
                threshold_m=threshold,
            )
        ]

    # ------------------------------------------------------------------ persistence
    def _raise(
        self,
        vehicle_id: str,
        alarm_type: str,
        ts: int,
        *,
        severity: str,
        message: str,
        speed: float | None = None,
        speed_limit: float | None = None,
        offset_m: float | None = None,
        threshold_m: float | None = None,
    ) -> dict:
        alarm = {
            "vehicle_id": vehicle_id,
            "type": alarm_type,
            "severity": severity,
            "ts": ts,
            "speed": speed,
            "speed_limit": speed_limit,
            "offset_m": offset_m,
            "threshold_m": threshold_m,
            "message": message,
        }
        alarm["id"] = self.store.create(alarm)
        alarm["status"] = "active"
        alarm["resolved_ts"] = None
        self._open[(vehicle_id, alarm_type)] = alarm["id"]
        return alarm

    def _resolve(self, vehicle_id: str, alarm_type: str, ts: int) -> None:
        alarm_id = self._open.pop((vehicle_id, alarm_type), None)
        if alarm_id is not None:
            self.store.resolve(alarm_id, ts)
