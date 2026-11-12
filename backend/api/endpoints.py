"""REST endpoints.

Each function receives a `Request` and returns a `Response`, raising `ApiError`
on failure. Paths are mapped to functions through `router`. See the API table
in the README for the full list.
"""

from __future__ import annotations

from .. import config
from ..clock import local_day_start_ms, now_ms
from ..routes import VEHICLE_BY_ID, VEHICLES
from .csv_export import positions_to_csv
from .router import ApiError, Request, Response, Router

router = Router()

MAX_MINUTES = 1440  # queries look back at most 24 hours


# ---------------------------------------------------------------------- helpers
def _vehicle_id(req: Request, vid: str | None = None, status: int = 404) -> str:
    vid = vid if vid is not None else req.params.get("vehicle_id", "")
    if vid not in VEHICLE_BY_ID:
        raise ApiError(status, "Vehicle not found")
    return vid


def _time_window(req: Request, default_minutes: int) -> tuple[int, int, int]:
    """(start, end, minutes) from the `?minutes=` query parameter."""
    minutes = req.query_int("minutes", default_minutes, 1, MAX_MINUTES)
    end = now_ms()
    return end - minutes * 60_000, end, minutes


def _json(payload, status: int = 200) -> Response:
    return Response(status=status, json=payload)


# ---------------------------------------------------------------------- general
@router.get("/api/bootstrap")
def bootstrap(req: Request) -> Response:
    """Initial dashboard load: routes, vehicle definitions and the first snapshot."""
    return _json(
        {
            "app": {"name": "FiloTrack", "subtitle": "Live Fleet Monitoring Center", "demo": True},
            "routes": req.app.route_payload,
            "vehicles": VEHICLES,
            "state": req.app.sim.get_snapshot() or {},
            "server_time": now_ms(),
        }
    )


@router.get("/api/health")
def health(req: Request) -> Response:
    return _json(
        {
            "ok": True,
            "server_time": now_ms(),
            "simulation": req.app.sim.running,
            "vehicles": len(VEHICLES),
        }
    )


@router.get("/api/routes")
def routes(req: Request) -> Response:
    return _json({"routes": req.app.route_payload})


@router.get("/api/state")
def state(req: Request) -> Response:
    return _json(req.app.sim.get_snapshot() or {})


@router.get("/api/storage")
def storage(req: Request) -> Response:
    return _json(req.app.db.counts())


# ---------------------------------------------------------------------- vehicles
@router.get("/api/vehicles")
def vehicles(req: Request) -> Response:
    snapshot = req.app.sim.get_snapshot() or {}
    return _json({"vehicles": snapshot.get("vehicles", [])})


@router.get("/api/vehicles/{vehicle_id}")
def vehicle_detail(req: Request) -> Response:
    vid = _vehicle_id(req)
    snapshot = req.app.sim.get_snapshot() or {}
    current = next((v for v in snapshot.get("vehicles", []) if v["vehicle_id"] == vid), None)
    day_start = local_day_start_ms()
    db = req.app.db
    return _json(
        {
            "vehicle": VEHICLE_BY_ID[vid],
            "route": req.app.route_payload[VEHICLE_BY_ID[vid]["route_id"]],
            "current": current,
            "today": {
                **db.positions.vehicle_stats(vid, day_start),
                "alarms": db.alarms.count_since(day_start, vid),
            },
        }
    )


@router.get("/api/vehicles/{vehicle_id}/history")
def vehicle_history(req: Request) -> Response:
    """Route trail drawn on the map (downsampled)."""
    vid = _vehicle_id(req)
    start, end, minutes = _time_window(req, default_minutes=15)
    points = req.app.db.positions.history(vid, start, end, max_points=1200)
    return _json({"vehicle_id": vid, "from": start, "to": end, "minutes": minutes, "points": points})


@router.get("/api/vehicles/{vehicle_id}/series")
def vehicle_speed_series(req: Request) -> Response:
    """Speed chart; `bucket` is the bucket size in seconds (5–300)."""
    vid = _vehicle_id(req)
    start, end, _ = _time_window(req, default_minutes=60)
    bucket = req.query_int("bucket", 30, 5, 300)
    series = req.app.db.positions.speed_series(vid, start, end, bucket * 1000)
    return _json(
        {"vehicle_id": vid, "from": start, "to": end, "bucket_seconds": bucket, "series": series}
    )


def _csv_response(req: Request, vid: str) -> Response:
    start, end, _ = _time_window(req, default_minutes=60)
    rows = req.app.db.positions.raw(vid, start, end)
    return Response(
        body=positions_to_csv(rows),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="filotrack_{vid}_{now_ms()}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/vehicles/{vehicle_id}/export.csv")
def vehicle_export_csv(req: Request) -> Response:
    return _csv_response(req, _vehicle_id(req))


@router.get("/api/export.csv")
def export_csv_legacy(req: Request) -> Response:
    """Legacy form `/api/export.csv?vehicle_id=V-01`, kept for backward compatibility."""
    return _csv_response(req, _vehicle_id(req, req.query_value("vehicle_id", ""), status=400))


@router.post("/api/vehicles/{vehicle_id}/trigger")
def vehicle_trigger(req: Request) -> Response:
    """Test scenario: `{"type": "speed"}` or `{"type": "deviation"}`."""
    vid = _vehicle_id(req)
    kind = req.body.get("type", "speed")
    if kind not in ("speed", "deviation"):
        raise ApiError(400, "Invalid scenario type")
    ok = req.app.sim.trigger(vid, kind)
    return _json({"ok": ok, "vehicle_id": vid, "type": kind})


# ---------------------------------------------------------------------- alarms
@router.get("/api/alarms")
def alarms(req: Request) -> Response:
    """`?status=open` (default) → open alarms; any other value → history."""
    limit = req.query_int("limit", 100, 1, 500)
    if req.query_value("status", "open") == "open":
        result = req.app.db.alarms.open(limit)
    else:
        result = req.app.db.alarms.history(limit, req.query_value("vehicle_id"))
    return _json({"alarms": result})


@router.post("/api/alarms/{alarm_id}/ack")
def alarm_ack(req: Request) -> Response:
    raw_id = req.params["alarm_id"]
    if not raw_id.isdigit():
        raise ApiError(404, "Alarm not found")
    alarm_id = int(raw_id)
    return _json({"ok": req.app.db.alarms.acknowledge(alarm_id), "alarm_id": alarm_id})


@router.post("/api/alarms/ack-all")
def alarm_ack_all(req: Request) -> Response:
    return _json({"ok": True, "acknowledged": req.app.db.alarms.acknowledge_all()})


# ---------------------------------------------------------------------- simulation
@router.post("/api/simulation")
def simulation_control(req: Request) -> Response:
    """`{"action": "pause" | "resume"}` or `{"action": "speed", "value": 2}`."""
    sim = req.app.sim
    action = req.body.get("action")
    if action == "pause":
        sim.pause()
    elif action == "resume":
        sim.resume()
    elif action == "speed":
        try:
            value = float(req.body.get("value", 1))
        except (TypeError, ValueError):
            raise ApiError(400, "Invalid speed multiplier") from None
        sim.set_speed(value)
    else:
        raise ApiError(400, "Invalid action")
    return _json({"ok": True, "simulation": {"running": sim.running, "speed": sim.speed_multiplier}})


# ---------------------------------------------------------------------- settings
@router.get("/api/settings")
def settings_get(req: Request) -> Response:
    return _json({"settings": req.app.db.settings.get_all()})


def validate_settings(body: dict) -> dict[str, float]:
    """Validates the known settings in the body; unknown keys are ignored."""
    updates: dict[str, float] = {}
    for key, (lo, hi) in config.SETTINGS_LIMITS.items():
        if key not in body:
            continue
        try:
            value = float(body[key])
        except (TypeError, ValueError):
            raise ApiError(400, f"{key} must be a number") from None
        if not lo <= value <= hi:
            raise ApiError(400, f"{key} must be between {lo} and {hi}")
        updates[key] = value
    if not updates:
        raise ApiError(400, "No setting to update")
    return updates


@router.post("/api/settings")
def settings_update(req: Request) -> Response:
    updates = validate_settings(req.body)
    req.app.db.settings.update(updates)
    req.app.sim.update_settings(updates)
    return _json({"ok": True, "settings": req.app.db.settings.get_all()})
