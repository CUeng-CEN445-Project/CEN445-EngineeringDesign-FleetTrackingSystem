"""HTTP API: REST endpoints, SSE live stream and the dashboard's static files."""

from .context import AppContext
from .server import FleetHTTPServer, create_server

__all__ = ["AppContext", "FleetHTTPServer", "create_server"]
