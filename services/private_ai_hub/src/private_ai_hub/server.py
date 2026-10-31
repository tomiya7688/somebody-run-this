from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import threading

from . import __version__
from .storage import is_ready


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        max_connections: int,
        request_timeout_seconds: int,
        address_family: int,
    ) -> None:
        self.address_family = address_family
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._request_timeout_seconds = request_timeout_seconds
        super().__init__(server_address, handler_class)

    def get_request(self) -> tuple[socket.socket, object]:
        request, client_address = super().get_request()
        request.settimeout(self._request_timeout_seconds)
        return request, client_address

    def process_request(self, request: socket.socket, client_address: object) -> None:
        if not self._connection_slots.acquire(blocking=False):
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(
        self,
        request: socket.socket,
        client_address: object,
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


def _address_family_for_host(host: str) -> int:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return socket.AF_INET
    return socket.AF_INET6 if address.version == 6 else socket.AF_INET


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


def build_server(
    host: str,
    port: int,
    storage_path: Path,
    *,
    max_connections: int = 64,
    request_timeout_seconds: int = 10,
) -> BoundedThreadingHTTPServer:
    return BoundedThreadingHTTPServer(
        (host, port),
        make_handler(storage_path),
        max_connections=max_connections,
        request_timeout_seconds=request_timeout_seconds,
        address_family=_address_family_for_host(host),
    )
