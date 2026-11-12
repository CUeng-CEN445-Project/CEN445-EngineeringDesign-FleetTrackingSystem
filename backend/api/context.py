"""Application context shared by all endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..routes import ROUTES, VEHICLES
from ..simulation import Simulator
from ..storage import Database


def build_route_payload() -> dict[str, dict]:
    """Route definitions in the shape sent to the dashboard (computed once)."""
    return {
        rid: {
            "id": rid,
            "name": r["name"],
            "area": r["area"],
            "color": r["color"],
            "speed_limit": r["speed_limit"],
            "mode": r["mode"],
            "points": [[round(p[0], 6), round(p[1], 6)] for p in r["points"]],
            "vehicles": [v["id"] for v in VEHICLES if v["route_id"] == rid],
        }
        for rid, r in ROUTES.items()
    }


@dataclass
class AppContext:
    db: Database
    sim: Simulator
    route_payload: dict[str, dict] = field(default_factory=build_route_payload)
