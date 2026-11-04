from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from private_ai_hub.identity import AuthorizationError, Permission
from private_ai_hub.identity_store import IdentityStore
from private_ai_hub.model_registry import (
    ModelAccessDenied,
    ModelCapabilities,
    ModelHealthState,
    ModelPolicyScopeType,
    ModelRegistry,
    ModelRegistryError,
    ModelSourceKind,
)
from private_ai_hub.storage import initialize


class ModelRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        initialize(self.path)

        self.identity = IdentityStore(self.path)
        self.identity.create_organization("acme", "Acme")
        self.roles = self.identity.ensure_builtin_roles("acme")

        self.admin = self.identity.create_user("acme", "admin")
        self.identity.assign_role_to_user(
            self.admin.id,
            self.roles["admin"].id,
        )
        self.admin_principal = self._principal(self.admin.id)

        self.alice = self.identity.create_user("acme", "alice")
        self.identity.assign_role_to_user(
            self.alice.id,
            self.roles["user"].id,
        )
        self.alice_principal = self._principal(self.alice.id)

        self.registry = ModelRegistry(self.path)
        self.model_root = Path(self.temp.name) / "models"
        self.model_root.mkdir()

    def _principal(self, user_id: str):
        user = self.identity.get_user(user_id)
        assert user is not None
        from private_ai_hub.identity import Principal

        return Principal(
            user=user,
            permissions=self.identity.permissions_for_user(user_id),
            group_ids=self.identity.group_ids_for_user(user_id),
            role_ids=self.identity.role_ids_for_user(user_id),
        )

    def _register_ready(
        self,
        model_id: str,
        *,
        backend_model_id: str | None = None,
        capabilities: ModelCapabilities | None = None,
        enabled: bool = True,
    ):
        model_path = self.model_root / model_id
        model_path.mkdir(exist_ok=True)
        record = self.registry.register_model(
            self.admin_principal,
            model_id=model_id,
            display_name=model_id.upper(),
            source_kind=ModelSourceKind.LOCAL,
            backend_id="vllm",
            backend_model_id=backend_model_id or model_id,
            local_path=model_path.resolve(),
            capabilities=capabilities or ModelCapabilities(
                text=True,
                streaming=True,
                context_limit=8192,
            ),
            revision="local-test",
            digest="sha256:" + ("a" * 64),
            enabled=enabled,
        )
        return self.registry.update_health(
            "acme",
            record.model_key,
            state=ModelHealthState.READY,
            occurred_at=100,
        )

    def test_newly_registered_ready_model_is_still_default_denied(self) -> None:
        self._register_ready("luna")

        self.assertEqual(
            self.registry.list_effective_models(self.alice_principal),
            (),
        )
        with self.assertRaises(ModelAccessDenied):
            self.registry.require_allowed_model(
                self.alice_principal,
                "luna",
            )

    def test_one_model_allowlist_is_first_class(self) -> None:
        self._register_ready("luna")
        self._register_ready("sol")

        scope = self.registry.configure_allowlist(
            self.admin_principal,
            scope_type=ModelPolicyScopeType.ORGANIZATION,
            scope_id="acme",
            allowed_model_ids={"luna"},
            default_model_id="luna",
        )
        self.assertEqual(scope.revision, 1)
        self.assertEqual(scope.allowed_model_ids, frozenset({"luna"}))

        visible = self.registry.list_effective_models(self.alice_principal)
        self.assertEqual(
            [model.model_id for model in visible],
            ["luna"],
        )
        self.assertEqual(
            self.registry.require_allowed_model(
                self.alice_principal,
                "luna",
            ).model_key,
            "luna",
        )
        with self.assertRaises(ModelAccessDenied):
            self.registry.require_allowed_model(
                self.alice_principal,
                "sol",
            )

        default = self.registry.resolve_default_model(self.alice_principal)
        self.assertIsNotNone(default)
        assert default is not None
        self.assertEqual(default.model_key, "luna")

    def test_zero_model_allowlist_denies_everything(self) -> None:
        self._register_ready("luna")
        scope = self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids=(),
        )
        self.assertEqual(scope.allowed_model_ids, frozenset())
        self.assertEqual(
            self.registry.list_effective_models(self.alice_principal),
            (),
        )

    def test_group_policy_can_only_narrow_organization_allowlist(self) -> None:
        self._register_ready("luna")
        self._register_ready("sol")
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna", "sol"},
        )

        group = self.identity.create_group("acme", "research")
        self.identity.add_user_to_group(self.alice.id, group.id)
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="group",
            scope_id=group.id,
            allowed_model_ids={"luna"},
        )
        principal = self._principal(self.alice.id)

        self.assertEqual(
            [m.model_id for m in self.registry.list_effective_models(principal)],
            ["luna"],
        )

    def test_project_policy_cannot_widen_organization_allowlist(self) -> None:
        self._register_ready("luna")
        self._register_ready("sol")
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
        )
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="project",
            scope_id="project-a",
            allowed_model_ids={"luna", "sol"},
        )

        visible = self.registry.list_effective_models(
            self.alice_principal,
            project_id="project-a",
        )
        self.assertEqual([model.model_id for model in visible], ["luna"])
        with self.assertRaises(ModelAccessDenied):
            self.registry.require_allowed_model(
                self.alice_principal,
                "sol",
                project_id="project-a",
            )

    def test_project_empty_allowlist_denies_all_for_project(self) -> None:
        self._register_ready("luna")
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
        )
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="project",
            scope_id="project-a",
            allowed_model_ids=(),
        )

        self.assertEqual(
            self.registry.list_effective_models(
                self.alice_principal,
                project_id="project-a",
            ),
            (),
        )

    def test_disabled_or_unhealthy_model_is_not_usable(self) -> None:
        self._register_ready("luna")
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
        )

        self.registry.set_enabled(
            self.admin_principal,
            "luna",
            False,
        )
        self.assertEqual(
            self.registry.list_effective_models(self.alice_principal),
            (),
        )

        self.registry.set_enabled(
            self.admin_principal,
            "luna",
            True,
        )
        self.registry.update_health(
            "acme",
            "luna",
            state="unhealthy",
            detail="worker stopped",
            occurred_at=200,
        )
        with self.assertRaises(ModelAccessDenied):
            self.registry.require_allowed_model(
                self.alice_principal,
                "luna",
            )

    def test_allowlist_revision_increments_on_every_change(self) -> None:
        self._register_ready("luna")
        first = self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
        )
        second = self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids=(),
        )
        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)

    def test_failed_allowlist_update_rolls_back_previous_policy(self) -> None:
        self._register_ready("luna")
        first = self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
            default_model_id="luna",
        )

        with self.assertRaises(ModelRegistryError):
            self.registry.configure_allowlist(
                self.admin_principal,
                scope_type="organization",
                scope_id="acme",
                allowed_model_ids={"luna", "not-registered"},
            )

        after = self.registry.get_policy_scope(
            "acme",
            ModelPolicyScopeType.ORGANIZATION,
            "acme",
        )
        self.assertIsNotNone(after)
        assert after is not None
        self.assertEqual(after.revision, first.revision)
        self.assertEqual(after.allowed_model_ids, frozenset({"luna"}))
        self.assertEqual(after.default_model_id, "luna")

    def test_default_model_must_be_in_same_scope_allowlist(self) -> None:
        self._register_ready("luna")
        self._register_ready("sol")
        with self.assertRaises(ModelRegistryError):
            self.registry.configure_allowlist(
                self.admin_principal,
                scope_type="organization",
                scope_id="acme",
                allowed_model_ids={"luna"},
                default_model_id="sol",
            )

    def test_non_admin_cannot_change_catalog_or_allowlist(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.registry.register_model(
                self.alice_principal,
                model_id="luna",
                display_name="Luna",
                source_kind="local",
                backend_id="vllm",
                backend_model_id="luna",
                local_path=(self.model_root / "luna").resolve(),
                capabilities=ModelCapabilities(),
            )
        with self.assertRaises(AuthorizationError):
            self.registry.configure_allowlist(
                self.alice_principal,
                scope_type="organization",
                scope_id="acme",
                allowed_model_ids=(),
            )

    def test_cross_organization_group_scope_is_rejected(self) -> None:
        self.identity.create_organization("other", "Other")
        other_group = self.identity.create_group("other", "other-group")
        with self.assertRaises(ModelRegistryError):
            self.registry.configure_allowlist(
                self.admin_principal,
                scope_type="group",
                scope_id=other_group.id,
                allowed_model_ids=(),
            )

    def test_capabilities_are_passed_to_policy_engine(self) -> None:
        self._register_ready(
            "luna",
            capabilities=ModelCapabilities(
                text=True,
                streaming=True,
                vision=False,
                tool_calling=False,
                context_limit=32768,
            ),
        )
        self.registry.configure_allowlist(
            self.admin_principal,
            scope_type="organization",
            scope_id="acme",
            allowed_model_ids={"luna"},
        )

        capabilities = self.registry.policy_capabilities_for_model(
            self.alice_principal,
            "luna",
        )
        self.assertTrue(capabilities.features["text"])
        self.assertFalse(capabilities.features["vision"])
        self.assertFalse(capabilities.features["tool_calling"])
        self.assertEqual(
            capabilities.integer_maximums["context_tokens"],
            32768,
        )

    def test_model_and_backend_keys_are_canonicalized(self) -> None:
        model = self._register_ready("LUNA")
        self.assertEqual(model.model_key, "luna")
        self.assertEqual(model.backend_id, "vllm")

    def test_external_model_cannot_have_local_path(self) -> None:
        with self.assertRaises(ModelRegistryError):
            self.registry.register_model(
                self.admin_principal,
                model_id="cloud-model",
                display_name="Cloud Model",
                source_kind="external",
                backend_id="openai",
                backend_model_id="provider-model",
                local_path=Path("/tmp/not-allowed"),
                capabilities=ModelCapabilities(),
            )


if __name__ == "__main__":
    unittest.main()
