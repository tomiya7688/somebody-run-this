from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from . import __version__
from .storage import is_ready


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def make_handler(storage_path: Path) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        server_version = "PrivateAIHubBootstrap/0.1"

        def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/healthz":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/readyz":
                ready = is_ready(storage_path)
                self._send_json(
                    HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "ready" if ready else "not_ready"},
                )
                return
            if self.path == "/v1/info":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "service": "private-ai-hub",
                        "version": __version__,
                        "bootstrap": True,
                    },
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def log_message(self, format: str, *args: object) -> None:
            # The bootstrap server deliberately avoids request-body logging.
            super().log_message(format, *args)

    return HealthHandler


def build_server(host: str, port: int, storage_path: Path) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(storage_path))
