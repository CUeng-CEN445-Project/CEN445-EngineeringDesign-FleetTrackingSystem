"""Builds the fleet state sent to the dashboard (SSE / REST).

Pure functions: they take measurements, alarms and statistics and return a
JSON-serializable dict, so they can be tested without a database or thread.
"""

from __future__ import annotations

MOVING_SPEED_KMH = 1.0


def vehicle_status(speed: float, alarm_types: set[str]) -> str:
    """Status that decides the marker color.

    Priority: off route > speeding > moving > stopped.
    """
    if "DEVIATION" in alarm_types:
        return "deviation"
    if "SPEED" in alarm_types:
        return "speed"
    if speed > MOVING_SPEED_KMH:
        return "moving"
    return "stopped"


def build_snapshot(
    *,
    seq: int,
    ts: int,
    states: list[dict],
    open_alarms: list[dict],
    recent_alarms: list[dict],
    today_stats: dict,
    settings: dict,
    simulation: dict,
    storage: dict,
) -> dict:
    open_types: dict[str, set[str]] = {}
    for alarm in open_alarms:
        open_types.setdefault(alarm["vehicle_id"], set()).add(alarm["type"])

    vehicles = []
    for st in states:
        alarm_types = open_types.get(st["vehicle_id"], set())
        vehicles.append(
            {
                **st,
                "status": vehicle_status(st["speed"], alarm_types),
                "active_alarm_types": sorted(alarm_types),
            }
        )

    count = len(vehicles)
    return {
        "seq": seq,
        "server_time": ts,
        "simulation": simulation,
        "settings": dict(settings),
        "vehicles": vehicles,
        "alarms": open_alarms,
        "recent_alarms": recent_alarms,
        "stats": {
            **today_stats,
            "total": count,
            "moving": sum(1 for v in vehicles if v["speed"] > MOVING_SPEED_KMH),
            "avg_speed": round(sum(v["speed"] for v in vehicles) / max(1, count), 1),
            "open_alarms": len(open_alarms),
            "distance_km": round(sum(v["odometer_m"] for v in vehicles) / 1000.0, 1),
        },
        "storage": storage,
    }
