from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from private_ai_hub.auth import (
    LocalAuthProvider,
    bootstrap_local_admin,
    build_local_auth_service,
)
from private_ai_hub.identity import Permission
from private_ai_hub.identity_store import IdentityStore
from private_ai_hub.server import (
    LoginRateLimiter,
    _address_family_for_host,
    build_server,
)
from private_ai_hub.storage import initialize


PASSWORD = "correct horse battery staple"


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, object], object]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc), exc.headers
    with response:
        return response.status, json.load(response), response.headers


class ServerTests(unittest.TestCase):
    def test_health_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "state.sqlite3"
            initialize(storage_path)
            server = build_server(
                "127.0.0.1",
                0,
                storage_path,
                max_connections=8,
                request_timeout_seconds=2,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {"status": "ok"})
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/readyz", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {"status": "ready"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_authenticated_endpoints_and_admin_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "state.sqlite3"
            initialize(storage_path)
            bootstrap_local_admin(
                storage_path,
                organization_id="acme",
                organization_name="Acme",
                username="admin",
                display_name="Administrator",
                password=PASSWORD,
            )

            store = IdentityStore(storage_path)
            roles = store.ensure_builtin_roles("acme")
            regular = store.create_user("acme", "alice")
            provider = LocalAuthProvider(store)
            provider.set_password(regular.id, PASSWORD)
            store.assign_role_to_user(regular.id, roles["user"].id)

            auth_service, _local = build_local_auth_service(
                storage_path,
                session_ttl_seconds=3600,
            )
            server = build_server(
                "127.0.0.1",
                0,
                storage_path,
                auth_service=auth_service,
                max_connections=8,
                request_timeout_seconds=2,
                login_attempts_per_minute=20,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"

                admin_status, admin_login, _headers = request_json(
                    base,
                    "/v1/auth/login",
                    method="POST",
                    payload={
                        "organization_id": "acme",
                        "username": "admin",
                        "password": PASSWORD,
                    },
                )
                self.assertEqual(admin_status, 200)
                admin_token = str(admin_login["access_token"])

                me_status, me, _headers = request_json(
                    base,
                    "/v1/me",
                    token=admin_token,
                )
                self.assertEqual(me_status, 200)
                self.assertIn(
                    Permission.ADMIN_MANAGE.value,
                    me["permissions"],
                )
                self.assertNotIn(
                    Permission.CONVERSATION_AUDIT_READ.value,
                    me["permissions"],
                )

                admin_ping_status, _payload, _headers = request_json(
                    base,
                    "/v1/admin/ping",
                    token=admin_token,
                )
                self.assertEqual(admin_ping_status, 200)

                conversation_audit_status, _payload, _headers = request_json(
                    base,
                    "/v1/admin/audit/conversation",
                    token=admin_token,
                )
                self.assertEqual(conversation_audit_status, 403)

                failed_status, _failed, _headers = request_json(
                    base,
                    "/v1/auth/login",
                    method="POST",
                    payload={
                        "organization_id": "acme",
                        "username": "alice",
                        "password": "wrong password long enough",
                    },
                )
                self.assertEqual(failed_status, 401)

                user_status, user_login, _headers = request_json(
                    base,
                    "/v1/auth/login",
                    method="POST",
                    payload={
                        "organization_id": "acme",
                        "username": "alice",
                        "password": PASSWORD,
                    },
                )
                self.assertEqual(user_status, 200)
                user_token = str(user_login["access_token"])

                denied_status, denied, _headers = request_json(
                    base,
                    "/v1/admin/ping",
                    token=user_token,
                )
                self.assertEqual(denied_status, 403)
                self.assertEqual(
                    denied["error"]["code"],
                    "permission_denied",
                )

                logout_status, _payload, _headers = request_json(
                    base,
                    "/v1/auth/logout",
                    method="POST",
                    payload={},
                    token=user_token,
                )
                self.assertEqual(logout_status, 200)

                after_logout_status, _payload, _headers = request_json(
                    base,
                    "/v1/me",
                    token=user_token,
                )
                self.assertEqual(after_logout_status, 401)

                audit_status, audit_payload, _headers = request_json(
                    base,
                    "/v1/admin/audit/security?limit=100",
                    token=admin_token,
                )
                self.assertEqual(audit_status, 200)
                event_types = {
                    event["event_type"]
                    for event in audit_payload["events"]
                }
                self.assertIn("auth.login.succeeded", event_types)
                self.assertIn("auth.login.failed", event_types)
                self.assertIn("authorization.denied", event_types)
                self.assertIn("auth.logout", event_types)

                serialized_audit = json.dumps(audit_payload)
                self.assertNotIn(PASSWORD, serialized_audit)
                self.assertNotIn(admin_token, serialized_audit)
                self.assertNotIn(user_token, serialized_audit)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_login_rate_limiter(self) -> None:
        now = [1000.0]
        limiter = LoginRateLimiter(
            attempts_per_minute=2,
            clock=lambda: now[0],
        )
        self.assertTrue(limiter.allow("client"))
        self.assertTrue(limiter.allow("client"))
        self.assertFalse(limiter.allow("client"))
        now[0] += 61
        self.assertTrue(limiter.allow("client"))

    def test_ipv6_literal_selects_ipv6_server_family(self) -> None:
        self.assertEqual(_address_family_for_host("::1"), socket.AF_INET6)

    def test_ipv4_literal_selects_ipv4_server_family(self) -> None:
        self.assertEqual(_address_family_for_host("127.0.0.1"), socket.AF_INET)


if __name__ == "__main__":
    unittest.main()
