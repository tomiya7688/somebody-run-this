from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from private_ai_hub.audit import AuditService, AuditSettings, AuditStream
from private_ai_hub.identity import (
    AuthorizationError,
    Permission,
    Principal,
    User,
)
from private_ai_hub.storage import connect, initialize


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "audit.sqlite3"
        initialize(self.path)

    def _principal(
        self,
        *,
        user_id: str,
        permissions: set[Permission],
    ) -> Principal:
        return Principal(
            user=User(
                id=user_id,
                organization_id="acme",
                username=user_id,
                display_name=user_id,
                enabled=True,
            ),
            permissions=frozenset(permission.value for permission in permissions),
        )

    def test_security_audit_redacts_secrets_and_verifies_chain(self) -> None:
        service = AuditService(self.path)
        event_id = service.record_security(
            "auth.login.succeeded",
            organization_id="acme",
            actor_user_id="alice",
            metadata={
                "password": "must-not-appear",
                "nested": {
                    "access_token": "secret-token",
                    "safe": "kept",
                },
            },
            occurred_at=100,
        )
        self.assertIsNotNone(event_id)

        admin = self._principal(
            user_id="admin",
            permissions={Permission.SECURITY_AUDIT_READ},
        )
        events = service.list_security(admin)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].metadata["password"], "[REDACTED]")
        self.assertEqual(
            events[0].metadata["nested"]["access_token"],
            "[REDACTED]",
        )
        self.assertEqual(events[0].metadata["nested"]["safe"], "kept")
        self.assertTrue(service.verify_chain("acme", AuditStream.SECURITY))

    def test_tampered_security_event_breaks_chain_verification(self) -> None:
        service = AuditService(self.path)
        service.record_security(
            "policy.changed",
            organization_id="acme",
            actor_user_id="admin",
            metadata={"target": "web_search", "after": "disabled"},
            occurred_at=100,
        )
        with connect(self.path) as connection:
            connection.execute(
                """
                UPDATE security_audit_events
                SET metadata_json = ?
                WHERE organization_id = ?
                """,
                ('{"changed":true}', "acme"),
            )

        self.assertFalse(service.verify_chain("acme", AuditStream.SECURITY))

    def test_security_audit_can_remain_enabled_when_conversation_is_disabled(self) -> None:
        service = AuditService(
            self.path,
            AuditSettings(
                security_enabled=True,
                conversation_enabled=False,
            ),
        )
        self.assertIsNotNone(
            service.record_security(
                "auth.login.failed",
                organization_id="acme",
                metadata={"username": "alice"},
            )
        )
        self.assertIsNone(
            service.record_conversation(
                "chat.completed",
                organization_id="acme",
                owner_user_id="alice",
                prompt_content="private prompt",
                response_content="private response",
            )
        )
        with connect(self.path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM conversation_audit_events"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_conversation_content_is_off_independently(self) -> None:
        service = AuditService(
            self.path,
            AuditSettings(
                conversation_enabled=True,
                store_prompt_content=False,
                store_response_content=False,
            ),
        )
        service.record_conversation(
            "chat.completed",
            organization_id="acme",
            owner_user_id="alice",
            actor_user_id="alice",
            conversation_id="conversation-1",
            metadata={"model": "luna", "total_tokens": 42},
            prompt_content="do not store this prompt",
            response_content="do not store this response",
            occurred_at=100,
        )

        auditor = self._principal(
            user_id="auditor",
            permissions={Permission.CONVERSATION_AUDIT_READ},
        )
        events = service.list_conversation(auditor)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].prompt_content)
        self.assertIsNone(events[0].response_content)
        self.assertEqual(events[0].metadata["model"], "luna")

    def test_conversation_content_requires_explicit_setting_and_permission(self) -> None:
        service = AuditService(
            self.path,
            AuditSettings(
                conversation_enabled=True,
                store_prompt_content=True,
                store_response_content=True,
            ),
        )
        service.record_conversation(
            "chat.completed",
            organization_id="acme",
            owner_user_id="alice",
            actor_user_id="alice",
            prompt_content="prompt text",
            response_content="response text",
        )

        admin = self._principal(
            user_id="admin",
            permissions={Permission.SECURITY_AUDIT_READ},
        )
        with self.assertRaises(AuthorizationError):
            service.list_conversation(admin)

        auditor = self._principal(
            user_id="auditor",
            permissions={Permission.CONVERSATION_AUDIT_READ},
        )
        event = service.list_conversation(auditor)[0]
        self.assertEqual(event.prompt_content, "prompt text")
        self.assertEqual(event.response_content, "response text")

    def test_retention_purge_preserves_verifiable_chain_anchor(self) -> None:
        service = AuditService(
            self.path,
            AuditSettings(retention_days=1),
        )
        service.record_security(
            "old.one",
            organization_id="acme",
            metadata={},
            occurred_at=10,
        )
        service.record_security(
            "old.two",
            organization_id="acme",
            metadata={},
            occurred_at=20,
        )
        service.record_security(
            "new.one",
            organization_id="acme",
            metadata={},
            occurred_at=200_000,
        )

        self.assertTrue(service.verify_chain("acme", AuditStream.SECURITY))
        deleted = service.purge_expired(now=200_000)
        self.assertEqual(deleted, 2)
        self.assertTrue(service.verify_chain("acme", AuditStream.SECURITY))

        admin = self._principal(
            user_id="admin",
            permissions={Permission.SECURITY_AUDIT_READ},
        )
        events = service.list_security(admin)
        self.assertEqual([event.event_type for event in events], ["new.one"])

    def test_admin_change_is_authorized_and_secret_values_are_redacted(self) -> None:
        service = AuditService(self.path)
        admin = self._principal(
            user_id="admin",
            permissions={
                Permission.ADMIN_MANAGE,
                Permission.SECURITY_AUDIT_READ,
            },
        )
        service.record_admin_change(
            "policy.changed",
            principal=admin,
            target="openai-extension",
            before={"api_key": "old-secret"},
            after={"api_key": "new-secret"},
        )
        event = service.list_security(admin)[0]
        self.assertEqual(
            event.metadata["before"]["api_key"],
            "[REDACTED]",
        )
        self.assertEqual(
            event.metadata["after"]["api_key"],
            "[REDACTED]",
        )

    def test_security_audit_can_be_disabled(self) -> None:
        service = AuditService(
            self.path,
            AuditSettings(security_enabled=False),
        )
        self.assertIsNone(
            service.record_security(
                "security.disabled.example",
                organization_id="acme",
            )
        )


if __name__ == "__main__":
    unittest.main()
