from __future__ import annotations

from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

from . import __version__
from .auth import (
    AuthService,
    AuthenticationError,
    LOCAL_PROVIDER_ID,
    build_local_auth_service,
)
from .identity import AuthorizationError, Permission, Principal, require_permission
from .storage import is_ready


_MAX_AUTH_BODY_BYTES = 16 * 1024
_MAX_AUTHORIZATION_HEADER_BYTES = 4096


class LoginRateLimiter:
    def __init__(
        self,
        *,
        attempts_per_minute: int,
        clock=time.monotonic,
    ) -> None:
        if isinstance(attempts_per_minute, bool) or not isinstance(
            attempts_per_minute, int
        ):
            raise ValueError("attempts_per_minute must be an integer")
        if attempts_per_minute < 1:
            raise ValueError("attempts_per_minute must be >= 1")
        self.attempts_per_minute = attempts_per_minute
        self._clock = clock
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client_key: str) -> bool:
        now = float(self._clock())
        cutoff = now - 60.0
        with self._lock:
            attempts = self._attempts[client_key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.attempts_per_minute:
                return False
            attempts.append(now)
            if not attempts:
                self._attempts.pop(client_key, None)
            return True


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


def _principal_payload(principal: Principal) -> dict[str, object]:
    return {
        "user": {
            "id": principal.user.id,
            "organization_id": principal.user.organization_id,
            "username": principal.user.username,
            "display_name": principal.user.display_name,
        },
        "permissions": sorted(principal.permissions),
        "group_ids": sorted(principal.group_ids),
        "role_ids": sorted(principal.role_ids),
    }


def make_handler(
    storage_path: Path,
    auth_service: AuthService,
    login_limiter: LoginRateLimiter,
) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        server_version = "PrivateAIHubBootstrap/0.2"

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, object],
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(
            self,
            status: HTTPStatus,
            code: str,
            message: str,
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self._send_json(
                status,
                {
                    "error": {
                        "code": code,
                        "message": message,
                    }
                },
                extra_headers=extra_headers,
            )

        def _path(self) -> str:
            return urlsplit(self.path).path

        def _client_key(self) -> str:
            if isinstance(self.client_address, tuple) and self.client_address:
                return str(self.client_address[0])
            return "unknown"

        def _read_json_object(self) -> dict[str, object] | None:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                self._send_error_json(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "content_type_required",
                    "Content-Type must be application/json",
                )
                return None

            length_header = self.headers.get("Content-Length")
            if length_header is None:
                self._send_error_json(
                    HTTPStatus.LENGTH_REQUIRED,
                    "content_length_required",
                    "Content-Length is required",
                )
                return None
            try:
                length = int(length_header, 10)
            except ValueError:
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_content_length",
                    "Content-Length is invalid",
                )
                return None
            if length < 0 or length > _MAX_AUTH_BODY_BYTES:
                self._send_error_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "request_too_large",
                    "Request body is too large",
                )
                return None

            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_json",
                    "Request body must be valid JSON",
                )
                return None
            if not isinstance(payload, dict):
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_json_object",
                    "Request body must be a JSON object",
                )
                return None
            return payload

        def _bearer_token(self) -> str | None:
            header = self.headers.get("Authorization")
            if header is None:
                return None
            if len(header.encode("utf-8")) > _MAX_AUTHORIZATION_HEADER_BYTES:
                return None
            scheme, separator, token = header.partition(" ")
            if not separator or scheme.casefold() != "bearer":
                return None
            token = token.strip()
            return token or None

        def _require_principal(
            self,
            permission: Permission | None = None,
        ) -> tuple[Principal, str] | None:
            token = self._bearer_token()
            if token is None:
                self._send_error_json(
                    HTTPStatus.UNAUTHORIZED,
                    "authentication_required",
                    "Authentication is required",
                )
                return None
            principal = auth_service.authenticate_session(token)
            if principal is None:
                self._send_error_json(
                    HTTPStatus.UNAUTHORIZED,
                    "invalid_session",
                    "Session is invalid or expired",
                )
                return None
            if permission is not None:
                try:
                    require_permission(principal, permission)
                except AuthorizationError:
                    self._send_error_json(
                        HTTPStatus.FORBIDDEN,
                        "permission_denied",
                        "Permission denied",
                    )
                    return None
            return principal, token

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            path = self._path()
            if path == "/healthz":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/readyz":
                ready = is_ready(storage_path)
                self._send_json(
                    HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "ready" if ready else "not_ready"},
                )
                return
            if path == "/v1/info":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "service": "private-ai-hub",
                        "version": __version__,
                        "bootstrap": True,
                    },
                )
                return
            if path == "/v1/me":
                authenticated = self._require_principal()
                if authenticated is None:
                    return
                principal, _token = authenticated
                self._send_json(
                    HTTPStatus.OK,
                    _principal_payload(principal),
                )
                return
            if path == "/v1/admin/ping":
                authenticated = self._require_principal(
                    Permission.ADMIN_MANAGE
                )
                if authenticated is None:
                    return
                principal, _token = authenticated
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "user_id": principal.user.id,
                    },
                )
                return
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                "not_found",
                "Resource not found",
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            path = self._path()

            if path == "/v1/auth/login":
                if not login_limiter.allow(self._client_key()):
                    self._send_error_json(
                        HTTPStatus.TOO_MANY_REQUESTS,
                        "login_rate_limited",
                        "Too many login attempts",
                        extra_headers={"Retry-After": "60"},
                    )
                    return

                payload = self._read_json_object()
                if payload is None:
                    return
                organization_id = payload.get("organization_id")
                username = payload.get("username")
                password = payload.get("password")
                provider_id = payload.get("provider", LOCAL_PROVIDER_ID)
                if not all(
                    isinstance(value, str) and value
                    for value in (
                        organization_id,
                        username,
                        password,
                        provider_id,
                    )
                ):
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        "invalid_login_request",
                        "Required login fields are missing",
                    )
                    return
                try:
                    result = auth_service.login(
                        organization_id=organization_id,
                        provider_id=provider_id,
                        identifier=username,
                        secret=password,
                    )
                except AuthenticationError:
                    self._send_error_json(
                        HTTPStatus.UNAUTHORIZED,
                        "authentication_failed",
                        "Authentication failed",
                    )
                    return

                response = _principal_payload(result.principal)
                response.update(
                    {
                        "access_token": result.session.value,
                        "token_type": "Bearer",
                        "expires_at": result.session.expires_at,
                    }
                )
                self._send_json(HTTPStatus.OK, response)
                return

            if path == "/v1/auth/logout":
                authenticated = self._require_principal()
                if authenticated is None:
                    return
                _principal, token = authenticated
                auth_service.logout(token)
                self._send_json(HTTPStatus.OK, {"status": "logged_out"})
                return

            if path == "/v1/auth/logout-all":
                authenticated = self._require_principal()
                if authenticated is None:
                    return
                principal, _token = authenticated
                auth_service.logout_all(principal)
                self._send_json(
                    HTTPStatus.OK,
                    {"status": "all_sessions_revoked"},
                )
                return

            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                "not_found",
                "Resource not found",
            )

        def log_message(self, format: str, *args: object) -> None:
            # Request bodies and bearer tokens are never logged.
            super().log_message(format, *args)

    return ApiHandler


def build_server(
    host: str,
    port: int,
    storage_path: Path,
    *,
    max_connections: int = 64,
    request_timeout_seconds: int = 10,
    session_ttl_seconds: int = 12 * 60 * 60,
    login_attempts_per_minute: int = 10,
    auth_service: AuthService | None = None,
) -> BoundedThreadingHTTPServer:
    service = auth_service
    if service is None:
        service, _provider = build_local_auth_service(
            storage_path,
            session_ttl_seconds=session_ttl_seconds,
        )
    limiter = LoginRateLimiter(
        attempts_per_minute=login_attempts_per_minute
    )
    return BoundedThreadingHTTPServer(
        (host, port),
        make_handler(storage_path, service, limiter),
        max_connections=max_connections,
        request_timeout_seconds=request_timeout_seconds,
        address_family=_address_family_for_host(host),
    )
