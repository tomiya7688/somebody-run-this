from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import http.client
import ipaddress
import logging
import re
import socket
import ssl
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit

from .audit import AuditService


logger = logging.getLogger(__name__)

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)
_FORBIDDEN_CALLER_HEADERS = frozenset(
    {"host", "content-length", "connection", "transfer-encoding"}
)


class NetworkProfile(StrEnum):
    OFFLINE = "offline"
    RESTRICTED_EGRESS = "restricted-egress"


class EgressPurpose(StrEnum):
    MODEL_IMPORT = "model_import"
    EXTENSION = "extension"


class EgressDenied(PermissionError):
    """Raised before a prohibited outbound request is sent."""


class EgressError(RuntimeError):
    """Raised when an allowed outbound request fails safely."""


@dataclass(frozen=True)
class EgressAuditContext:
    organization_id: str
    actor_user_id: str | None = None
    component_id: str | None = None
    purpose: EgressPurpose | str = EgressPurpose.EXTENSION

    def __post_init__(self) -> None:
        if not isinstance(self.organization_id, str) or not self.organization_id.strip():
            raise ValueError("organization_id must be a non-empty string")
        if self.actor_user_id is not None and (
            not isinstance(self.actor_user_id, str)
            or not self.actor_user_id.strip()
        ):
            raise ValueError("actor_user_id must be a non-empty string")
        if self.component_id is not None and (
            not isinstance(self.component_id, str)
            or not self.component_id.strip()
        ):
            raise ValueError("component_id must be a non-empty string")
        object.__setattr__(
            self,
            "purpose",
            EgressPurpose(self.purpose),
        )


@dataclass(frozen=True)
class EgressPolicy:
    enabled: bool = False
    allowed_domains: frozenset[str] | set[str] | tuple[str, ...] = field(
        default_factory=frozenset
    )
    allowed_methods: frozenset[str] | set[str] | tuple[str, ...] = field(
        default_factory=lambda: frozenset({"GET", "HEAD"})
    )
    allowed_ports: frozenset[int] | set[int] | tuple[int, ...] = field(
        default_factory=lambda: frozenset({443})
    )
    allow_subdomains: bool = True
    allow_http: bool = False
    allowed_private_networks: tuple[str, ...] = ()
    timeout_seconds: int = 10
    max_request_bytes: int = 1024 * 1024
    max_response_bytes: int = 4 * 1024 * 1024
    max_redirects: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if not isinstance(self.allow_subdomains, bool):
            raise ValueError("allow_subdomains must be boolean")
        if not isinstance(self.allow_http, bool):
            raise ValueError("allow_http must be boolean")

        domains = frozenset(_normalize_host(value) for value in self.allowed_domains)
        methods = frozenset(_normalize_method(value) for value in self.allowed_methods)

        ports: set[int] = set()
        for port in self.allowed_ports:
            if isinstance(port, bool) or not isinstance(port, int):
                raise ValueError("allowed ports must be integers")
            if not 1 <= port <= 65535:
                raise ValueError("allowed ports must be between 1 and 65535")
            ports.add(port)

        private_networks: list[ipaddress._BaseNetwork] = []
        for raw_network in self.allowed_private_networks:
            if not isinstance(raw_network, str):
                raise ValueError("allowed private networks must be CIDR strings")
            network = ipaddress.ip_network(raw_network, strict=False)
            if network.is_loopback or network.is_link_local or network.is_multicast:
                raise ValueError(
                    "loopback, link-local and multicast networks cannot be allowed"
                )
            private_networks.append(network)

        for name, value, minimum, maximum in (
            ("timeout_seconds", self.timeout_seconds, 1, 300),
            ("max_request_bytes", self.max_request_bytes, 0, 64 * 1024 * 1024),
            ("max_response_bytes", self.max_response_bytes, 1, 64 * 1024 * 1024),
            ("max_redirects", self.max_redirects, 0, 10),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}"
                )

        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(self, "allowed_methods", methods)
        object.__setattr__(self, "allowed_ports", frozenset(ports))
        object.__setattr__(
            self,
            "allowed_private_networks",
            tuple(private_networks),
        )


@dataclass(frozen=True)
class EgressResponse:
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    final_url: str


def _normalize_method(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("HTTP method must be a non-empty string")
    method = value.strip().upper()
    if not method.isalpha() or len(method) > 16:
        raise ValueError("HTTP method is invalid")
    return method


def _normalize_host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("domain must be a non-empty string")
    raw = value.strip().rstrip(".")
    try:
        return raw.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError("domain is invalid") from exc


def _host_matches(host: str, policy: EgressPolicy) -> bool:
    if host in policy.allowed_domains:
        return True
    if not policy.allow_subdomains:
        return False
    return any(
        host.endswith("." + allowed)
        for allowed in policy.allowed_domains
        if not _is_ip_literal(allowed)
    )


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _private_network_allowed(
    address: ipaddress._BaseAddress,
    policy: EgressPolicy,
) -> bool:
    return any(
        address.version == network.version and address in network
        for network in policy.allowed_private_networks
    )


def _validate_address(
    address: ipaddress._BaseAddress,
    policy: EgressPolicy,
) -> None:
    if address.is_loopback:
        raise EgressDenied("loopback destinations are prohibited")
    if address.is_link_local:
        raise EgressDenied("link-local and metadata destinations are prohibited")
    if address.is_multicast:
        raise EgressDenied("multicast destinations are prohibited")
    if address.is_unspecified:
        raise EgressDenied("unspecified destinations are prohibited")
    if address.is_reserved:
        raise EgressDenied("reserved destinations are prohibited")

    if address.is_global:
        return
    if _private_network_allowed(address, policy):
        return
    raise EgressDenied(
        f"non-global destination {address.compressed} is not explicitly allowed"
    )


def _validate_header(name: object, value: object) -> tuple[str, str]:
    if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
        raise EgressDenied("request contains an invalid HTTP header name")
    normalized_name = name.casefold()
    if normalized_name in _FORBIDDEN_CALLER_HEADERS:
        raise EgressDenied(f"caller cannot override HTTP header {name!r}")
    if not isinstance(value, str):
        raise EgressDenied("HTTP header values must be strings")
    if "\r" in value or "\n" in value:
        raise EgressDenied("HTTP header values cannot contain line breaks")
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise EgressDenied("HTTP header value is not representable") from exc
    return name, value


def _host_header(host: str, port: int, scheme: str) -> str:
    rendered = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return rendered if port == default_port else f"{rendered}:{port}"


Resolver = Callable[..., list[tuple[object, object, object, object, object]]]
Connector = Callable[[tuple[str, int], float], socket.socket]


class EgressBroker:
    def __init__(
        self,
        *,
        profile: NetworkProfile | str,
        policy: EgressPolicy,
        resolver: Resolver = socket.getaddrinfo,
        connector: Connector = socket.create_connection,
        ssl_context: ssl.SSLContext | None = None,
        audit_service: AuditService | None = None,
        audit_context: EgressAuditContext | None = None,
    ) -> None:
        self.profile = NetworkProfile(profile)
        self.policy = policy
        self._resolver = resolver
        self._connector = connector
        self._ssl_context = ssl_context or ssl.create_default_context()
        self.audit_service = audit_service
        self.audit_context = audit_context

    def _audit(
        self,
        event_type: str,
        *,
        metadata: Mapping[str, object],
        fail_closed: bool,
    ) -> None:
        if self.audit_service is None or self.audit_context is None:
            return
        try:
            self.audit_service.record_security(
                event_type,
                organization_id=self.audit_context.organization_id,
                actor_user_id=self.audit_context.actor_user_id,
                metadata={
                    "component_id": self.audit_context.component_id,
                    "purpose": self.audit_context.purpose.value,
                    **dict(metadata),
                },
            )
        except Exception as exc:
            logger.exception("failed to record egress security audit event")
            if fail_closed:
                raise EgressDenied(
                    "egress blocked because security audit is unavailable"
                ) from exc

    def _deny(
        self,
        reason: str,
        *,
        method: str | None = None,
        host: str | None = None,
        port: int | None = None,
        scheme: str | None = None,
    ) -> None:
        self._audit(
            "egress.request.denied",
            metadata={
                "reason": reason,
                "method": method,
                "host": host,
                "port": port,
                "scheme": scheme,
            },
            fail_closed=False,
        )
        raise EgressDenied(reason)

    def _validate_target(
        self,
        url: str,
        *,
        method: str,
    ) -> tuple[str, str, int, str, tuple[str, ...]]:
        if self.profile is NetworkProfile.OFFLINE:
            self._deny("network profile is offline", method=method)
        if not self.policy.enabled:
            self._deny("egress policy is disabled", method=method)

        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        if scheme not in {"https", "http"}:
            self._deny("only HTTP(S) egress is supported", method=method)
        if scheme == "http" and not self.policy.allow_http:
            self._deny("plain HTTP egress is disabled", method=method, scheme=scheme)
        if parsed.username is not None or parsed.password is not None:
            self._deny("credentials in URLs are prohibited", method=method, scheme=scheme)
        if parsed.fragment:
            self._deny("URL fragments are not permitted for egress", method=method)

        host = parsed.hostname
        if host is None:
            self._deny("egress URL has no hostname", method=method, scheme=scheme)
        host = _normalize_host(host)

        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80

        if method not in self.policy.allowed_methods:
            self._deny(
                f"HTTP method {method} is not allowed",
                method=method,
                host=host,
                port=port,
                scheme=scheme,
            )
        if port not in self.policy.allowed_ports:
            self._deny(
                f"destination port {port} is not allowed",
                method=method,
                host=host,
                port=port,
                scheme=scheme,
            )
        if not _host_matches(host, self.policy):
            self._deny(
                "destination hostname is not allowlisted",
                method=method,
                host=host,
                port=port,
                scheme=scheme,
            )

        addresses: list[str] = []
        if _is_ip_literal(host):
            addresses.append(host)
        else:
            try:
                results = self._resolver(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
            except OSError as exc:
                raise EgressError("DNS resolution failed") from exc
            for result in results:
                sockaddr = result[4]
                if not isinstance(sockaddr, tuple) or not sockaddr:
                    continue
                address = str(sockaddr[0])
                if address not in addresses:
                    addresses.append(address)

        if not addresses:
            raise EgressError("DNS resolution returned no usable addresses")

        for raw_address in addresses:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                self._deny(
                    "DNS returned an invalid IP address",
                    method=method,
                    host=host,
                    port=port,
                    scheme=scheme,
                )
                raise AssertionError("unreachable") from exc
            try:
                _validate_address(address, self.policy)
            except EgressDenied as exc:
                self._deny(
                    str(exc),
                    method=method,
                    host=host,
                    port=port,
                    scheme=scheme,
                )

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return scheme, host, port, path, tuple(addresses)

    def _connect(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        addresses: tuple[str, ...],
    ) -> socket.socket:
        last_error: OSError | None = None
        for address in addresses:
            try:
                raw = self._connector(
                    (address, port),
                    float(self.policy.timeout_seconds),
                )
                raw.settimeout(float(self.policy.timeout_seconds))
                peer = raw.getpeername()
                if isinstance(peer, tuple) and peer:
                    peer_address = ipaddress.ip_address(str(peer[0]))
                    _validate_address(peer_address, self.policy)
                    if peer_address != ipaddress.ip_address(address):
                        raw.close()
                        raise EgressDenied(
                            "connected peer does not match validated DNS address"
                        )
                if scheme == "https":
                    try:
                        return self._ssl_context.wrap_socket(
                            raw,
                            server_hostname=host,
                        )
                    except Exception:
                        raw.close()
                        raise
                return raw
            except EgressDenied:
                raise
            except OSError as exc:
                last_error = exc
        raise EgressError("unable to connect to any validated address") from last_error

    def _send_once(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> EgressResponse:
        scheme, host, port, path, addresses = self._validate_target(
            url,
            method=method,
        )

        self._audit(
            "egress.request.allowed",
            metadata={
                "method": method,
                "host": host,
                "port": port,
                "scheme": scheme,
            },
            fail_closed=True,
        )

        request_headers: list[tuple[str, str]] = [
            ("Host", _host_header(host, port, scheme)),
            ("Connection", "close"),
            ("User-Agent", "PrivateAIHub-Egress/0.1"),
        ]
        for name, value in headers.items():
            request_headers.append(_validate_header(name, value))
        if body:
            request_headers.append(("Content-Length", str(len(body))))

        try:
            encoded_headers = "".join(
                f"{name}: {value}\r\n" for name, value in request_headers
            ).encode("latin-1")
            request = (
                f"{method} {path} HTTP/1.1\r\n".encode("ascii")
                + encoded_headers
                + b"\r\n"
                + body
            )
        except UnicodeEncodeError as exc:
            raise EgressDenied("request headers are not safely encodable") from exc

        sock = self._connect(
            scheme=scheme,
            host=host,
            port=port,
            addresses=addresses,
        )
        response: http.client.HTTPResponse | None = None
        try:
            sock.sendall(request)
            response = http.client.HTTPResponse(sock)
            response.begin()

            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length, 10)
                except ValueError as exc:
                    raise EgressError("invalid response Content-Length") from exc
                if declared < 0 or declared > self.policy.max_response_bytes:
                    raise EgressDenied("response exceeds configured size limit")

            response_body = response.read(self.policy.max_response_bytes + 1)
            if len(response_body) > self.policy.max_response_bytes:
                raise EgressDenied("response exceeds configured size limit")

            return EgressResponse(
                status=int(response.status),
                reason=str(response.reason or ""),
                headers=tuple((str(k), str(v)) for k, v in response.getheaders()),
                body=response_body,
                final_url=url,
            )
        except socket.timeout as exc:
            raise EgressError("egress request timed out") from exc
        except http.client.HTTPException as exc:
            raise EgressError("invalid HTTP response") from exc
        finally:
            if response is not None:
                response.close()
            sock.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> EgressResponse:
        resolved_method = _normalize_method(method)
        request_body = body or b""
        if not isinstance(request_body, bytes):
            raise EgressDenied("request body must be bytes")
        if len(request_body) > self.policy.max_request_bytes:
            self._deny(
                "request body exceeds configured size limit",
                method=resolved_method,
            )

        current_url = url
        current_headers = dict(headers or {})
        previous_origin: tuple[str, str, int] | None = None

        for redirect_count in range(self.policy.max_redirects + 1):
            response = self._send_once(
                method=resolved_method,
                url=current_url,
                headers=current_headers,
                body=request_body,
            )
            if (
                response.status not in _REDIRECT_STATUSES
                or resolved_method not in {"GET", "HEAD"}
            ):
                return response

            location = next(
                (
                    value
                    for name, value in response.headers
                    if name.casefold() == "location"
                ),
                None,
            )
            if location is None:
                return response
            if redirect_count >= self.policy.max_redirects:
                raise EgressDenied("maximum redirect count exceeded")

            old = urlsplit(current_url)
            new_url = urljoin(current_url, location)
            new = urlsplit(new_url)
            old_port = old.port or (443 if old.scheme.casefold() == "https" else 80)
            new_port = new.port or (443 if new.scheme.casefold() == "https" else 80)
            old_origin = (
                old.scheme.casefold(),
                _normalize_host(old.hostname or ""),
                old_port,
            )
            new_origin = (
                new.scheme.casefold(),
                _normalize_host(new.hostname or ""),
                new_port,
            )

            if previous_origin is None:
                previous_origin = old_origin
            if new_origin != old_origin:
                current_headers = {
                    name: value
                    for name, value in current_headers.items()
                    if name.casefold() not in _SENSITIVE_REDIRECT_HEADERS
                }
            current_url = new_url

        raise AssertionError("redirect loop should have returned or raised")
