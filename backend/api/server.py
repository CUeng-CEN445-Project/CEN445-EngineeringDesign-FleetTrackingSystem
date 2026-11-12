"""HTTP layer: REST + SSE + static files on the standard library's `ThreadingHTTPServer`.

This module only handles transport: it parses the request, calls the matching
endpoint through `router` and writes the returned `Response` to the socket.
Application logic lives in `endpoints.py`.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .. import config
from .context import AppContext
from .endpoints import router
from .router import ApiError, Request, Response

log = logging.getLogger("filotrack.server")

MAX_BODY_BYTES = 1_000_000
SSE_POLL_SECONDS = 0.3
SSE_HEARTBEAT_SECONDS = 12

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class FleetHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, app: AppContext):
        super().__init__(addr, handler)
        self.app = app
        self.stop_event = threading.Event()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], _CLIENT_GONE):
            return  # the client closed the connection; not worth logging
        super().handle_error(request, client_address)


class FleetRequestHandler(BaseHTTPRequestHandler):
    server: FleetHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "FiloTrack/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - BaseHTTPRequestHandler signature
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------------ entry points
    def do_GET(self):  # noqa: N802
        path, query = self._split_path()
        if path == "/api/stream":
            return self._stream()
        if path.startswith("/api/"):
            return self._dispatch("GET", path, query, body={})
        return self._serve_static(path)

    def do_HEAD(self):  # noqa: N802
        return self.do_GET()

    def do_POST(self):  # noqa: N802
        path, query = self._split_path()
        try:
            body = self._read_json()
        except ApiError as exc:
            return self._write(_error_response(exc))
        return self._dispatch("POST", path, query, body)

    # ------------------------------------------------------------------ API
    def _split_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlsplit(self.path)
        return unquote(parsed.path), parse_qs(parsed.query)

    def _dispatch(self, method: str, path: str, query: dict, body: dict) -> None:
        try:
            handler, params = router.resolve(method, path)
            response = handler(Request(method, path, params, query, body, self.server.app))
        except ApiError as exc:
            response = _error_response(exc)
        except _CLIENT_GONE:
            self.close_connection = True
            return
        except Exception as exc:  # pragma: no cover - unexpected errors
            log.exception("%s %s failed", method, path)
            response = _error_response(ApiError(500, f"Server error: {exc}"))
        try:
            self._write(response)
        except _CLIENT_GONE:
            self.close_connection = True

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError(400, "Request body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Invalid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object")
        return data

    def _write(self, response: Response) -> None:
        if response.body is not None:
            body = response.body
            headers = dict(response.headers)
        else:
            body = json.dumps(response.json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers = {
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
                **response.headers,
            }
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ------------------------------------------------------------------ SSE
    def _stream(self) -> None:
        """Server-Sent Events: sends an event whenever the snapshot changes (≈ 1 s)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        sim = self.server.app.sim
        last_seq: int | None = None
        last_write = time.monotonic()
        try:
            while not self.server.stop_event.is_set():
                snap = sim.get_snapshot(last_seq)
                if snap:
                    payload = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"id: {snap['seq']}\ndata: {payload}\n\n".encode())
                    self.wfile.flush()
                    last_seq = snap["seq"]
                    last_write = time.monotonic()
                elif time.monotonic() - last_write > SSE_HEARTBEAT_SECONDS:
                    # Comment line so that proxies do not close an idle connection
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_write = time.monotonic()
                time.sleep(SSE_POLL_SECONDS)
        except (*_CLIENT_GONE, OSError):
            pass

    # ------------------------------------------------------------------ static files
    def _serve_static(self, path: str) -> None:
        web_root = config.WEB_DIR.resolve()
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (web_root / rel).resolve()
        # Block attempts to escape the web root (../)
        if web_root not in target.parents and target != web_root:
            return self._write(_error_response(ApiError(403, "Access denied")))
        if not target.is_file():
            return self._write(_error_response(ApiError(404, "File not found")))
        ext = target.suffix.lower()
        cache = "no-cache" if ext in (".html", ".css", ".js") else "public, max-age=3600"
        self._write(
            Response(
                body=target.read_bytes(),
                content_type=MIME.get(ext, "application/octet-stream"),
                headers={"Cache-Control": cache},
            )
        )


def _error_response(exc: ApiError) -> Response:
    return Response(status=exc.status, json={"error": exc.message, "status": exc.status})


def create_server(host: str, port: int, app: AppContext) -> FleetHTTPServer:
    return FleetHTTPServer((host, port), FleetRequestHandler, app)
