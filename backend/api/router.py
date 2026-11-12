"""Small, dependency-free URL router.

Endpoints are independent of HTTP: they receive a `Request`, return a
`Response` or raise `ApiError`. The server (`server.py`) only writes these
objects to the socket, which lets endpoints be tested without opening one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ApiError(Exception):
    """Error returned to the client as a JSON body (`{"error": ..., "status": ...}`)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Request:
    method: str
    path: str
    params: dict[str, str]          # groups captured by the path pattern, e.g. {"vehicle_id": "V-01"}
    query: dict[str, list[str]]     # output of urllib.parse.parse_qs
    body: dict[str, Any]            # POST JSON body
    app: Any                        # AppContext (db, sim, ...)

    def query_value(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default

    def query_int(self, name: str, default: int, minimum: int, maximum: int) -> int:
        """Integer query parameter; invalid → default, out of range → clamped."""
        try:
            value = int(self.query_value(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))


@dataclass
class Response:
    status: int = 200
    json: Any = None
    body: bytes | None = None
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


Handler = Callable[[Request], Response]

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SEGMENT = "[A-Za-z0-9_-]+"


def compile_pattern(pattern: str) -> re.Pattern:
    """`/api/vehicles/{vehicle_id}/export.csv` → an anchored regex.

    Literal parts are escaped with `re.escape` (so `.` is a real dot);
    `{name}` placeholders match exactly one path segment.
    """
    out = []
    for part in re.split(r"(\{\w+\})", pattern):
        m = _PLACEHOLDER.fullmatch(part)
        out.append(f"(?P<{m.group(1)}>{_SEGMENT})" if m else re.escape(part))
    return re.compile("^" + "".join(out) + "$")


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern, Handler]] = []

    def route(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        """Registers an endpoint for a path pattern containing `{name}` placeholders."""
        regex = compile_pattern(pattern)

        def decorator(func: Handler) -> Handler:
            self._routes.append((method, regex, func))
            return func

        return decorator

    def get(self, pattern: str) -> Callable[[Handler], Handler]:
        return self.route("GET", pattern)

    def post(self, pattern: str) -> Callable[[Handler], Handler]:
        return self.route("POST", pattern)

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str]]:
        """Finds the endpoint for a path; raises 404 if unknown, 405 if the method does not match."""
        path_matched = False
        for route_method, regex, func in self._routes:
            match = regex.match(path)
            if not match:
                continue
            if route_method == method:
                return func, match.groupdict()
            path_matched = True
        if path_matched:
            raise ApiError(405, "Method not allowed for this endpoint")
        raise ApiError(404, "API endpoint not found")
