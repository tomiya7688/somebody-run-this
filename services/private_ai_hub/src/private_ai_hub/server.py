from __future__ import annotations

from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
from pathlib import Path
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .audit import (
    AuditService,
    AuditSettings,
    ConversationAuditEvent,
    SecurityAuditEvent,
)
from .auth import (
    AuthService,
    AuthenticationError,
    LOCAL_PROVIDER_ID,
    build_local_auth_service,
)
from .identity import AuthorizationError, Permission, Principal, require_permission
from .storage import is_ready


logger = logging.getLogger(__name__)

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
        self._last_cleanup = 0.0
        self._lock = threading.Lock()

    def _cleanup_locked(self, now: float) -> None:
        if now - self._last_cleanup < 60.0:
            return
        cutoff = now - 60.0
        for key in tuple(self._attempts):
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                self._attempts.pop(key, None)
        self._last_cleanup = now

    def allow(self, client_key: str) -> bool:
        now = float(self._clock())
        cutoff = now - 60.0
        with self._lock:
            self._cleanup_locked(now)
            attempts = self._attempts[client_key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.attempts_per_minute:
                return False
            attempts.append(now)
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


def _security_event_payload(event: SecurityAuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "actor_user_id": event.actor_user_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "metadata": dict(event.metadata),
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
    }


def _conversation_event_payload(
    event: ConversationAuditEvent,
) -> dict[str, object]:
    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "owner_user_id": event.owner_user_id,
        "actor_user_id": event.actor_user_id,
        "project_id": event.project_id,
        "conversation_id": event.conversation_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "metadata": dict(event.metadata),
        "prompt_content": event.prompt_content,
        "response_content": event.response_content,
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
    }


def make_handler(
    storage_path: Path,
    auth_service: AuthService,
    login_limiter: LoginRateLimiter,
    audit_service: AuditService,
) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        server_version = "PrivateAIHubBootstrap/0.3"

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

        def _parsed_url(self):
            return urlsplit(self.path)

        def _path(self) -> str:
            return self._parsed_url().path

        def _client_key(self) -> str:
            if isinstance(self.client_address, tuple) and self.client_address:
                return str(self.client_address[0])
            return "unknown"

        def _read_json_object(self) -> dict[str, object] | None:
            content_type = self.headers.get("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().casefold()
            if media_type != "application/json":
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

        def _audit_security(
            self,
            event_type: str,
            *,
            organization_id: str,
            actor_user_id: str | None = None,
            metadata: dict[str, object] | None = None,
            fail_closed: bool = True,
        ) -> bool:
            try:
                audit_service.record_security(
                    event_type,
                    organization_id=organization_id,
                    actor_user_id=actor_user_id,
                    metadata=metadata,
                )
                return True
            except Exception:
                logger.exception("failed to record security audit event")
                if fail_closed:
                    self._send_error_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "audit_unavailable",
                        "Security audit is temporarily unavailable",
                    )
                return False

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
                    if not self._audit_security(
                        "authorization.denied",
                        organization_id=principal.user.organization_id,
                        actor_user_id=principal.user.id,
                        metadata={
                            "permission": permission.value,
                            "path": self._path(),
                        },
                    ):
                        return None
                    self._send_error_json(
                        HTTPStatus.FORBIDDEN,
                        "permission_denied",
                        "Permission denied",
                    )
                    return None
            return principal, token

        def _query_limit(self, *, default: int = 100) -> int | None:
            values = parse_qs(self._parsed_url().query).get("limit")
            if not values:
                return default
            if len(values) != 1:
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_limit",
                    "limit must be supplied once",
                )
                return None
            try:
                limit = int(values[0], 10)
            except ValueError:
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_limit",
                    "limit must be an integer",
                )
                return None
            if not 1 <= limit <= 1000:
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_limit",
                    "limit must be between 1 and 1000",
                )
                return None
            return limit

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
            if path == "/v1/admin/audit/security":
                authenticated = self._require_principal(
                    Permission.SECURITY_AUDIT_READ
                )
                if authenticated is None:
                    return
                principal, _token = authenticated
                limit = self._query_limit()
                if limit is None:
                    return
                try:
                    events = audit_service.list_security(
                        principal,
                        limit=limit,
                    )
                except (AuthorizationError, ValueError):
                    self._send_error_json(
                        HTTPStatus.FORBIDDEN,
                        "permission_denied",
                        "Permission denied",
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "events": [
                            _security_event_payload(event)
                            for event in events
                        ]
                    },
                )
                return
            if path == "/v1/admin/audit/conversation":
                authenticated = self._require_principal(
                    Permission.CONVERSATION_AUDIT_READ
                )
                if authenticated is None:
                    return
                principal, _token = authenticated
                limit = self._query_limit()
                if limit is None:
                    return
                try:
                    events = audit_service.list_conversation(
                        principal,
                        limit=limit,
                    )
                except (AuthorizationError, ValueError):
                    self._send_error_json(
                        HTTPStatus.FORBIDDEN,
                        "permission_denied",
                        "Permission denied",
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "events": [
                            _conversation_event_payload(event)
                            for event in events
                        ]
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
                payload = self._read_json_object()
                if payload is None:
                    return
                organization_id = payload.get("organization_id")
                username = payload.get("username")
                password = payload.get("password")
                provider_id = payload.get("provider", LOCAL_PROVIDER_ID)
                if not (
                    isinstance(organization_id, str)
                    and 1 <= len(organization_id.strip()) <= 128
                    and isinstance(username, str)
                    and 1 <= len(username.strip()) <= 128
                    and isinstance(password, str)
                    and 1 <= len(password.encode("utf-8")) <= 1024
                    and isinstance(provider_id, str)
                    and 1 <= len(provider_id.strip()) <= 64
                ):
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        "invalid_login_request",
                        "Required login fields are invalid",
                    )
                    return

                organization_id = organization_id.strip()
                username = username.strip()
                provider_id = provider_id.strip()

                if not login_limiter.allow(self._client_key()):
                    if not self._audit_security(
                        "auth.login.rate_limited",
                        organization_id=organization_id,
                        metadata={
                            "provider": provider_id,
                            "username": username,
                            "client_ip": self._client_key(),
                        },
                    ):
                        return
                    self._send_error_json(
                        HTTPStatus.TOO_MANY_REQUESTS,
                        "login_rate_limited",
                        "Too many login attempts",
                        extra_headers={"Retry-After": "60"},
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
                    if not self._audit_security(
                        "auth.login.failed",
                        organization_id=organization_id,
                        metadata={
                            "provider": provider_id,
                            "username": username,
                            "client_ip": self._client_key(),
                        },
                    ):
                        return
                    self._send_error_json(
                        HTTPStatus.UNAUTHORIZED,
                        "authentication_failed",
                        "Authentication failed",
                    )
                    return

                if not self._audit_security(
                    "auth.login.succeeded",
                    organization_id=result.principal.user.organization_id,
                    actor_user_id=result.principal.user.id,
                    metadata={
                        "provider": provider_id,
                        "client_ip": self._client_key(),
                    },
                ):
                    auth_service.logout(result.session.value)
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
                principal, token = authenticated
                auth_service.logout(token)
                self._audit_security(
                    "auth.logout",
                    organization_id=principal.user.organization_id,
                    actor_user_id=principal.user.id,
                    metadata={"scope": "current_session"},
                    fail_closed=False,
                )
                self._send_json(HTTPStatus.OK, {"status": "logged_out"})
                return

            if path == "/v1/auth/logout-all":
                authenticated = self._require_principal()
                if authenticated is None:
                    return
                principal, _token = authenticated
                auth_service.logout_all(principal)
                self._audit_security(
                    "auth.logout_all",
                    organization_id=principal.user.organization_id,
                    actor_user_id=principal.user.id,
                    metadata={"scope": "all_sessions"},
                    fail_closed=False,
                )
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
    audit_service: AuditService | None = None,
    audit_settings: AuditSettings | None = None,
) -> BoundedThreadingHTTPServer:
    service = auth_service
    if service is None:
        service, _provider = build_local_auth_service(
            storage_path,
            session_ttl_seconds=session_ttl_seconds,
        )

    resolved_audit = audit_service or AuditService(
        storage_path,
        audit_settings or AuditSettings(),
    )
    resolved_audit.purge_expired()

    limiter = LoginRateLimiter(
        attempts_per_minute=login_attempts_per_minute
    )
    return BoundedThreadingHTTPServer(
        (host, port),
        make_handler(
            storage_path,
            service,
            limiter,
            resolved_audit,
        ),
        max_connections=max_connections,
        request_timeout_seconds=request_timeout_seconds,
        address_family=_address_family_for_host(host),
    )
