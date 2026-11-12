"""Motion model of a single vehicle on its route.

The vehicle moves along its assigned route polyline with limited acceleration
and braking, random traffic stops, and optional speeding / off-route
scenarios. This class is pure computation: no database, thread or network.
"""

from __future__ import annotations

import math
import random
import time

from .. import config
from ..geo import RouteGeometry, distance_to_polyline_m, offset_point

# Maximum speed change per second, in km/h
ACCEL_KMH_PER_S = 5.0   # ≈ 1.4 m/s²
DECEL_KMH_PER_S = 11.0  # ≈ 3 m/s²

# Chance of a random traffic stop (light / bus stop) per vehicle per tick
TRAFFIC_STOP_CHANCE = 0.0035


class VehicleSim:
    def __init__(self, cfg: dict, route: dict, odometer_m: float = 0.0, start_fraction: float = 0.0):
        self.cfg = cfg
        self.vehicle_id: str = cfg["id"]
        self.route = route
        self.route_id: str = cfg["route_id"]
        self.speed_limit: float = float(cfg["speed_limit"])
        self.geom = RouteGeometry(route["points"])
        self.distance_m = self.geom.total_m * start_fraction
        self.direction = 1
        self.odometer_m = odometer_m
        self.stopped_until = 0.0
        self.boost_until = 0.0
        self.dev_start = 0.0
        self.dev_until = 0.0
        self.dev_peak = 0.0
        self.dev_sign = 1
        self._cruise = random.uniform(0.65, 0.88)  # cruising speed as a fraction of the limit
        self._next_jitter = 0.0
        # The fleet starts already cruising (not from 0 km/h), so a speeding
        # scenario triggered right after startup raises an alarm within seconds.
        self.speed = self.speed_limit * self._cruise
        self.lat = 0.0
        self.lng = 0.0
        self.heading = 0.0
        self.offset_m = 0.0
        self._update_position(time.monotonic())

    # ------------------------------------------------------------------ scenarios
    def trigger_speed(self, now: float, duration: float = 15.0) -> None:
        """Drives 15–28 km/h above the limit for `duration` seconds."""
        self.boost_until = max(self.boost_until, now + duration)
        # If the vehicle is waiting at a light / stop, start the scenario immediately
        self.stopped_until = 0.0

    def trigger_deviation(self, now: float, duration: float = 18.0) -> None:
        """Drifts up to 200–280 m away from the route for `duration` seconds."""
        self.dev_start = now
        self.dev_until = now + duration
        self.dev_peak = random.uniform(200.0, 280.0)
        self.dev_sign = random.choice((-1, 1))

    # ------------------------------------------------------------------ motion
    def _target_speed(self, now: float) -> float:
        # A speeding scenario takes precedence over stops (e.g. turning at a route end)
        if now < self.boost_until:
            return self.speed_limit + random.uniform(15.0, 28.0)
        if now < self.stopped_until:
            return 0.0
        if now >= self._next_jitter:
            self._cruise = random.uniform(0.62, 0.9)
            self._next_jitter = now + random.uniform(10.0, 25.0)
        return self.speed_limit * self._cruise

    def _update_position(self, now: float) -> None:
        base_lat, base_lng, tangent = self.geom.position_at(self.distance_m)
        heading = (tangent + (180.0 if self.direction < 0 else 0.0)) % 360.0

        # Off-route scenario: the offset follows a sine curve 0 → peak → 0
        amplitude = 0.0
        if self.dev_start and now < self.dev_until:
            span = max(1e-6, self.dev_until - self.dev_start)
            t = min(1.0, max(0.0, (now - self.dev_start) / span))
            amplitude = self.dev_sign * self.dev_peak * math.sin(math.pi * t)

        if abs(amplitude) > 0.5:
            self.lat, self.lng = offset_point(base_lat, base_lng, heading, amplitude)
            # Measure the real distance of the shifted point from the route
            self.offset_m = distance_to_polyline_m((self.lat, self.lng), self.geom.points)
        else:
            self.lat, self.lng = base_lat, base_lng
            self.offset_m = 0.0
        self.heading = heading

    def _apply_speed(self, target: float, dt: float) -> None:
        """Moves the speed towards `target` within physical acceleration limits."""
        if target > self.speed:
            self.speed = min(target, self.speed + ACCEL_KMH_PER_S * dt)
        else:
            self.speed = max(target, self.speed - DECEL_KMH_PER_S * dt)
        self.speed = max(0.0, self.speed)

    def _roll_natural_events(self, now: float) -> None:
        if random.random() < TRAFFIC_STOP_CHANCE and self.speed > 5 and now >= self.boost_until:
            self.stopped_until = now + random.uniform(3.0, 9.0)
        if random.random() < config.SPEED_EVENT_CHANCE:
            self.trigger_speed(now, config.SPEED_EVENT_DURATION)
        if random.random() < config.DEVIATION_EVENT_CHANCE:
            self.trigger_deviation(now, config.DEVIATION_EVENT_DURATION)

    def _advance(self, movement: float, now: float) -> None:
        """Moves `movement` meters along the route and handles the route ends."""
        total = self.geom.total_m
        self.odometer_m += movement
        self.distance_m += movement * self.direction

        if self.route["mode"] == "loop":
            # Closed loop: wrap around to the start
            self.distance_m %= total
            return

        # Out-and-back (pingpong): reflect the overshoot, turn around and wait
        # briefly. Strict comparisons (> / <) are deliberate: a vehicle resting
        # exactly at an end (0 or total) must not flip direction every tick.
        if self.distance_m > total:
            self.distance_m = max(0.0, total - (self.distance_m - total))
        elif self.distance_m < 0:
            self.distance_m = min(total, -self.distance_m)
        else:
            return
        self.direction *= -1
        self.stopped_until = now + random.uniform(1.5, 3.5)
        self.speed = 0.0

    def step(self, dt: float, now: float, *, natural_events: bool = True) -> None:
        """Advances the simulation by `dt` seconds."""
        self._apply_speed(self._target_speed(now), dt)
        if natural_events:
            self._roll_natural_events(now)
        self._advance((self.speed / 3.6) * dt, now)
        self._update_position(now)

    # ------------------------------------------------------------------ output
    def state(self, ts: int) -> dict:
        """Current measurement: stored in `positions` and sent to the dashboard."""
        progress = self.distance_m / self.geom.total_m if self.geom.total_m else 0.0
        return {
            "vehicle_id": self.vehicle_id,
            "plate": self.cfg["plate"],
            "driver": self.cfg["driver"],
            "model": self.cfg["model"],
            "kind": self.cfg["kind"],
            "phone": self.cfg.get("phone"),
            "route_id": self.route_id,
            "route_name": self.route["name"],
            "route_area": self.route["area"],
            "route_color": self.route["color"],
            "lat": round(self.lat, 6),
            "lng": round(self.lng, 6),
            "speed": round(self.speed, 1),
            "heading": round(self.heading, 1),
            "offset_m": round(self.offset_m, 1),
            "progress": round(progress, 4),
            "direction": self.direction,
            "ignition": 1,
            "speed_limit": self.speed_limit,
            "odometer_m": round(self.odometer_m, 1),
            "ts": ts,
        }
