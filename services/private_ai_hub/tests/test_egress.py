from __future__ import annotations

from collections import deque
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest

from private_ai_hub.audit import AuditService
from private_ai_hub.egress import (
    EgressAuditContext,
    EgressBroker,
    EgressDenied,
    EgressPolicy,
    NetworkProfile,
)
from private_ai_hub.identity import Permission, Principal, User
from private_ai_hub.storage import initialize


_PUBLIC_IP = "93.184.216.34"


def public_resolver(host: str, port: int, **_kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (_PUBLIC_IP, port),
        )
    ]


class PeerSocket:
    def __init__(self, sock: socket.socket, peer_ip: str, peer_port: int) -> None:
        self._sock = sock
        self._peer = (peer_ip, peer_port)

    def getpeername(self):
        return self._peer

    def __getattr__(self, name: str):
        return getattr(self._sock, name)


class PassthroughTLSContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def wrap_socket(self, sock, *, server_hostname: str):
        if not server_hostname:
            raise AssertionError("server_hostname is required")
        return sock


class ScriptedConnector:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = deque(responses)
        self.requests: list[bytes] = []
        self.addresses: list[tuple[str, int]] = []

    def __call__(self, address: tuple[str, int], timeout: float):
        if not self.responses:
            raise AssertionError("unexpected connector call")
        response = self.responses.popleft()
        client, server = socket.socketpair()
        client.settimeout(timeout)
        server.settimeout(timeout)
        self.addresses.append(address)

        def serve() -> None:
            try:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                self.requests.append(request)
                server.sendall(response)
            finally:
                server.close()

        threading.Thread(target=serve, daemon=True).start()
        return PeerSocket(client, address[0], address[1])


def response(
    status: str = "200 OK",
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"OK",
) -> bytes:
    resolved = {
        "Content-Length": str(len(body)),
        "Connection": "close",
        **(headers or {}),
    }
    rendered = "".join(f"{name}: {value}\r\n" for name, value in resolved.items())
    return (
        f"HTTP/1.1 {status}\r\n{rendered}\r\n".encode("ascii")
        + body
    )


class EgressTests(unittest.TestCase):
    def _http_policy(self, **kwargs) -> EgressPolicy:
        values = {
            "enabled": True,
            "allowed_domains": {"example.com"},
            "allowed_methods": {"GET"},
            "allowed_ports": {80},
            "allow_http": True,
            "max_redirects": 3,
        }
        values.update(kwargs)
        return EgressPolicy(**values)

    def test_offline_profile_denies_before_dns(self) -> None:
        calls: list[str] = []

        def resolver(host: str, port: int, **_kwargs):
            calls.append(host)
            return public_resolver(host, port)

        broker = EgressBroker(
            profile=NetworkProfile.OFFLINE,
            policy=self._http_policy(),
            resolver=resolver,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/")
        self.assertEqual(calls, [])

    def test_disabled_policy_denies_before_dns(self) -> None:
        calls: list[str] = []

        def resolver(host: str, port: int, **_kwargs):
            calls.append(host)
            return public_resolver(host, port)

        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=EgressPolicy(
                enabled=False,
                allowed_domains={"example.com"},
                allowed_ports={80},
                allow_http=True,
            ),
            resolver=resolver,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/")
        self.assertEqual(calls, [])

    def test_loopback_and_metadata_destinations_are_always_denied(self) -> None:
        for host in ("127.0.0.1", "169.254.169.254", "::1"):
            with self.subTest(host=host):
                broker = EgressBroker(
                    profile=NetworkProfile.RESTRICTED_EGRESS,
                    policy=EgressPolicy(
                        enabled=True,
                        allowed_domains={host},
                        allowed_methods={"GET"},
                        allowed_ports={80},
                        allow_http=True,
                    ),
                )
                rendered = f"[{host}]" if ":" in host else host
                with self.assertRaises(EgressDenied):
                    broker.request("GET", f"http://{rendered}/")

    def test_ipv4_mapped_ipv6_loopback_is_denied(self) -> None:
        host = "::ffff:127.0.0.1"
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=EgressPolicy(
                enabled=True,
                allowed_domains={host},
                allowed_methods={"GET"},
                allowed_ports={80},
                allow_http=True,
            ),
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", f"http://[{host}]/")

    def test_mixed_public_private_dns_answer_is_denied(self) -> None:
        connector = ScriptedConnector([response()])

        def mixed_resolver(host: str, port: int, **_kwargs):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (_PUBLIC_IP, port),
                ),
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("10.0.0.5", port),
                ),
            ]

        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(),
            resolver=mixed_resolver,
            connector=connector,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/")
        self.assertEqual(connector.addresses, [])

    def test_explicit_private_network_can_be_allowed_but_not_loopback(self) -> None:
        connector = ScriptedConnector([response(body=b"internal")])

        def private_resolver(host: str, port: int, **_kwargs):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("10.0.0.5", port),
                )
            ]

        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(
                allowed_domains={"internal.example"},
                allowed_private_networks=("10.0.0.0/8",),
            ),
            resolver=private_resolver,
            connector=connector,
        )
        result = broker.request("GET", "http://internal.example/")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b"internal")

    def test_allowed_public_request_uses_validated_numeric_address(self) -> None:
        connector = ScriptedConnector([response(body=b"hello")])
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(),
            resolver=public_resolver,
            connector=connector,
        )
        result = broker.request(
            "GET",
            "http://example.com/path?q=1",
            headers={"X-Test": "yes"},
        )
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b"hello")
        self.assertEqual(connector.addresses, [(_PUBLIC_IP, 80)])
        self.assertIn(b"GET /path?q=1 HTTP/1.1", connector.requests[0])
        self.assertIn(b"Host: example.com", connector.requests[0])

    def test_redirect_to_private_destination_is_revalidated_and_denied(self) -> None:
        connector = ScriptedConnector(
            [
                response(
                    "302 Found",
                    headers={"Location": "http://127.0.0.1/private"},
                    body=b"",
                )
            ]
        )
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(
                allowed_domains={"example.com", "127.0.0.1"},
            ),
            resolver=public_resolver,
            connector=connector,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/start")
        self.assertEqual(len(connector.addresses), 1)

    def test_https_to_http_redirect_downgrade_is_denied_by_default(self) -> None:
        connector = ScriptedConnector(
            [
                response(
                    "302 Found",
                    headers={"Location": "http://plain.example/final"},
                    body=b"",
                )
            ]
        )
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=EgressPolicy(
                enabled=True,
                allowed_domains={"secure.example", "plain.example"},
                allowed_methods={"GET"},
                allowed_ports={443, 80},
                allow_http=True,
            ),
            resolver=public_resolver,
            connector=connector,
            ssl_context=PassthroughTLSContext(),  # type: ignore[arg-type]
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "https://secure.example/start")
        self.assertEqual(len(connector.addresses), 1)

    def test_insecure_tls_context_is_rejected(self) -> None:
        insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        with self.assertRaises(ValueError):
            EgressBroker(
                profile=NetworkProfile.RESTRICTED_EGRESS,
                policy=self._http_policy(),
                ssl_context=insecure,
            )

    def test_sensitive_headers_are_not_forwarded_across_redirect_origins(self) -> None:
        connector = ScriptedConnector(
            [
                response(
                    "302 Found",
                    headers={"Location": "http://api.example.net/final"},
                    body=b"",
                ),
                response(body=b"done"),
            ]
        )
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(
                allowed_domains={"example.com", "api.example.net"},
            ),
            resolver=public_resolver,
            connector=connector,
        )
        result = broker.request(
            "GET",
            "http://example.com/start",
            headers={
                "Authorization": "Bearer secret",
                "X-Safe": "kept",
            },
        )
        self.assertEqual(result.body, b"done")
        self.assertIn(b"Authorization: Bearer secret", connector.requests[0])
        self.assertNotIn(b"Authorization:", connector.requests[1])
        self.assertIn(b"X-Safe: kept", connector.requests[1])

    def test_excessive_dns_answers_are_denied(self) -> None:
        connector = ScriptedConnector([response()])

        def resolver(host: str, port: int, **_kwargs):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (f"8.8.8.{index % 200 + 1}", port),
                )
                for index in range(33)
            ]

        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(),
            resolver=resolver,
            connector=connector,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/")
        self.assertEqual(connector.addresses, [])

    def test_response_size_limit_is_enforced_before_large_read(self) -> None:
        connector = ScriptedConnector(
            [
                response(
                    headers={"Content-Length": "100"},
                    body=b"",
                )
            ]
        )
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(max_response_bytes=10),
            resolver=public_resolver,
            connector=connector,
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://example.com/")

    def test_url_credentials_and_host_override_are_denied(self) -> None:
        broker = EgressBroker(
            profile=NetworkProfile.RESTRICTED_EGRESS,
            policy=self._http_policy(),
            resolver=public_resolver,
            connector=ScriptedConnector([response()]),
        )
        with self.assertRaises(EgressDenied):
            broker.request("GET", "http://user:pass@example.com/")
        with self.assertRaises(EgressDenied):
            broker.request(
                "GET",
                "http://example.com/",
                headers={"Host": "evil.example"},
            )

    def test_egress_audit_does_not_store_url_path_or_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            initialize(database)
            audit = AuditService(database)
            connector = ScriptedConnector([response()])
            broker = EgressBroker(
                profile=NetworkProfile.RESTRICTED_EGRESS,
                policy=self._http_policy(),
                resolver=public_resolver,
                connector=connector,
                audit_service=audit,
                audit_context=EgressAuditContext(
                    organization_id="acme",
                    actor_user_id="alice",
                    component_id="web-search",
                ),
            )
            broker.request(
                "GET",
                "http://example.com/private/path?api_key=must-not-log",
            )

            principal = Principal(
                user=User(
                    id="admin",
                    organization_id="acme",
                    username="admin",
                    display_name="Admin",
                    enabled=True,
                ),
                permissions=frozenset(
                    {Permission.SECURITY_AUDIT_READ.value}
                ),
            )
            event = audit.list_security(principal)[0]
            self.assertEqual(event.event_type, "egress.request.allowed")
            self.assertEqual(event.metadata["host"], "example.com")
            rendered = str(event.metadata)
            self.assertNotIn("private/path", rendered)
            self.assertNotIn("must-not-log", rendered)


if __name__ == "__main__":
    unittest.main()
