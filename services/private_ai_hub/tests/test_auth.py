from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from private_ai_hub.auth import (
    AuthService,
    AuthenticationError,
    LocalAuthProvider,
    bootstrap_local_admin,
)
from private_ai_hub.identity import Permission
from private_ai_hub.identity_store import IdentityStore
from private_ai_hub.storage import initialize


PASSWORD = "correct horse battery staple"


class AuthAndRbacTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        initialize(self.path)
        self.store = IdentityStore(self.path)
        self.store.create_organization("acme", "Acme")
        self.roles = self.store.ensure_builtin_roles("acme")

    def _create_user(
        self,
        username: str,
        *,
        role: str = "user",
    ):
        user = self.store.create_user("acme", username)
        provider = LocalAuthProvider(self.store)
        provider.set_password(user.id, PASSWORD)
        self.store.assign_role_to_user(user.id, self.roles[role].id)
        return user, provider

    def test_admin_role_does_not_include_conversation_audit_content(self) -> None:
        user, _provider = self._create_user("admin", role="admin")
        permissions = self.store.permissions_for_user(user.id)

        self.assertIn(Permission.ADMIN_MANAGE.value, permissions)
        self.assertIn(Permission.SECURITY_AUDIT_READ.value, permissions)
        self.assertNotIn(Permission.CONVERSATION_AUDIT_READ.value, permissions)

    def test_disabled_user_cannot_login_and_existing_session_stops_working(self) -> None:
        user, provider = self._create_user("alice")
        service = AuthService(
            self.store,
            {provider.provider_id: provider},
            session_ttl_seconds=3600,
        )
        login = service.login(
            organization_id="acme",
            provider_id="local",
            identifier="alice",
            secret=PASSWORD,
        )
        self.assertIsNotNone(
            service.authenticate_session(login.session.value)
        )

        self.store.set_user_enabled(user.id, False)
        self.assertIsNone(
            service.authenticate_session(login.session.value)
        )
        with self.assertRaises(AuthenticationError):
            service.login(
                organization_id="acme",
                provider_id="local",
                identifier="alice",
                secret=PASSWORD,
            )

    def test_logout_all_revokes_all_existing_sessions(self) -> None:
        _user, provider = self._create_user("alice")
        service = AuthService(
            self.store,
            {provider.provider_id: provider},
            session_ttl_seconds=3600,
        )
        first = service.login(
            organization_id="acme",
            provider_id="local",
            identifier="alice",
            secret=PASSWORD,
        )
        second = service.login(
            organization_id="acme",
            provider_id="local",
            identifier="alice",
            secret=PASSWORD,
        )

        service.logout_all(first.principal)

        self.assertIsNone(
            service.authenticate_session(first.session.value)
        )
        self.assertIsNone(
            service.authenticate_session(second.session.value)
        )

    def test_group_role_change_is_visible_to_existing_session(self) -> None:
        user, provider = self._create_user("alice")
        service = AuthService(
            self.store,
            {provider.provider_id: provider},
            session_ttl_seconds=3600,
        )
        login = service.login(
            organization_id="acme",
            provider_id="local",
            identifier="alice",
            secret=PASSWORD,
        )
        before = service.authenticate_session(login.session.value)
        self.assertIsNotNone(before)
        assert before is not None
        self.assertFalse(before.has_permission(Permission.AGENT_USE))

        group = self.store.create_group("acme", "agents")
        agent_role = self.store.ensure_role("acme", "agent-user")
        self.store.replace_role_permissions(
            agent_role.id,
            {Permission.AGENT_USE},
        )
        self.store.add_user_to_group(user.id, group.id)
        self.store.assign_role_to_group(group.id, agent_role.id)

        after = service.authenticate_session(login.session.value)
        self.assertIsNotNone(after)
        assert after is not None
        self.assertTrue(after.has_permission(Permission.AGENT_USE))

    def test_cross_organization_role_assignment_is_rejected(self) -> None:
        user, _provider = self._create_user("alice")
        self.store.create_organization("other", "Other")
        other_roles = self.store.ensure_builtin_roles("other")

        with self.assertRaises(ValueError):
            self.store.assign_role_to_user(
                user.id,
                other_roles["admin"].id,
            )

    def test_wrong_password_uses_generic_authentication_failure(self) -> None:
        _user, provider = self._create_user("alice")
        service = AuthService(
            self.store,
            {provider.provider_id: provider},
            session_ttl_seconds=3600,
        )
        with self.assertRaisesRegex(
            AuthenticationError,
            "^authentication failed$",
        ):
            service.login(
                organization_id="acme",
                provider_id="local",
                identifier="alice",
                secret="this password is incorrect",
            )

    def test_bootstrap_admin_creates_admin_without_audit_content_permission(self) -> None:
        other_path = Path(self.temp.name) / "bootstrap.sqlite3"
        initialize(other_path)
        user = bootstrap_local_admin(
            other_path,
            organization_id="bootstrap",
            organization_name="Bootstrap Org",
            username="root-admin",
            display_name="Root Admin",
            password=PASSWORD,
        )
        store = IdentityStore(other_path)
        permissions = store.permissions_for_user(user.id)

        self.assertIn(Permission.ADMIN_MANAGE.value, permissions)
        self.assertNotIn(
            Permission.CONVERSATION_AUDIT_READ.value,
            permissions,
        )


if __name__ == "__main__":
    unittest.main()
