from __future__ import annotations

import unittest

from private_ai_hub.policy import FeatureMode, IntegerLimit
from private_ai_hub.policy_engine import (
    LimitBehavior,
    PolicyCapabilities,
    PolicyEngine,
    PolicyErrorCode,
    PolicyLayer,
    PolicyRequest,
)


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PolicyEngine()

    def test_admin_disabled_cannot_be_enabled_by_user(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                features={"web_search": FeatureMode.DISABLED},
            ),
        )
        decision = self.engine.resolve_feature(
            "web_search", True, layers
        )
        self.assertTrue(decision.permitted)
        self.assertFalse(decision.effective)

    def test_admin_required_cannot_be_disabled_by_user(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                features={"audit_security": FeatureMode.REQUIRED},
            ),
        )
        decision = self.engine.resolve_feature(
            "audit_security", False, layers
        )
        self.assertTrue(decision.permitted)
        self.assertTrue(decision.effective)

    def test_lower_layer_cannot_widen_disabled_feature(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                features={"web_search": FeatureMode.DISABLED},
            ),
            PolicyLayer(
                name="project",
                revision=3,
                features={"web_search": FeatureMode.OPTIONAL},
            ),
        )
        decision = self.engine.resolve_feature(
            "web_search", True, layers
        )
        self.assertTrue(decision.permitted)
        self.assertFalse(decision.effective)

    def test_project_cannot_enable_feature_missing_from_root_policy(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
            ),
            PolicyLayer(
                name="project",
                revision=2,
                features={"web_search": FeatureMode.OPTIONAL},
            ),
        )
        decision = self.engine.resolve_feature(
            "web_search", True, layers
        )
        self.assertTrue(decision.permitted)
        self.assertFalse(decision.effective)

    def test_conflicting_forced_feature_modes_fail_closed(self) -> None:
        layers = (
            PolicyLayer(
                name="group",
                revision=1,
                features={"memory": FeatureMode.REQUIRED},
            ),
            PolicyLayer(
                name="project",
                revision=2,
                features={"memory": FeatureMode.DISABLED},
            ),
        )
        decision = self.engine.resolve_feature("memory", True, layers)
        self.assertFalse(decision.permitted)
        self.assertFalse(decision.effective)
        self.assertEqual(
            decision.denial_code,
            PolicyErrorCode.POLICY_CONFLICT,
        )

    def test_unconfigured_feature_is_default_denied(self) -> None:
        decision = self.engine.resolve_feature("new_feature", True, ())
        self.assertTrue(decision.permitted)
        self.assertFalse(decision.effective)

    def test_required_feature_fails_if_runtime_capability_missing(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                features={"vision": FeatureMode.REQUIRED},
            ),
        )
        decision = self.engine.resolve_feature(
            "vision",
            True,
            layers,
            capability_available=False,
        )
        self.assertFalse(decision.permitted)
        self.assertEqual(
            decision.denial_code,
            PolicyErrorCode.CAPABILITY_UNAVAILABLE,
        )

    def test_integer_limits_use_strictest_range(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                integer_limits={
                    "max_files": IntegerLimit(minimum=0, maximum=100)
                },
            ),
            PolicyLayer(
                name="group",
                revision=2,
                integer_limits={
                    "max_files": IntegerLimit(minimum=10, maximum=50)
                },
            ),
        )
        decision = self.engine.resolve_integer(
            "max_files",
            80,
            layers,
            behavior=LimitBehavior.CLAMP,
        )
        self.assertTrue(decision.permitted)
        self.assertEqual(decision.minimum, 10)
        self.assertEqual(decision.maximum, 50)
        self.assertEqual(decision.effective, 50)

    def test_integer_limit_rejects_out_of_range(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                integer_limits={
                    "context_tokens": IntegerLimit(maximum=8192)
                },
            ),
        )
        decision = self.engine.resolve_integer(
            "context_tokens",
            16384,
            layers,
            behavior=LimitBehavior.REJECT,
        )
        self.assertFalse(decision.permitted)
        self.assertIsNone(decision.effective)
        self.assertEqual(
            decision.denial_code,
            PolicyErrorCode.VALUE_OUT_OF_RANGE,
        )

    def test_model_allowlists_are_intersected_with_provider_catalog(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                allowed_values={"model": {"luna", "sol"}},
            ),
            PolicyLayer(
                name="project",
                revision=4,
                allowed_values={"model": {"luna"}},
            ),
        )
        decision = self.engine.resolve_choice(
            "model",
            "luna",
            layers,
            available_values={"luna", "sol", "astra"},
        )
        self.assertTrue(decision.permitted)
        self.assertEqual(decision.effective, "luna")
        self.assertEqual(decision.allowed_values, ("luna",))

    def test_project_cannot_widen_model_allowlist(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
                allowed_values={"model": {"luna"}},
            ),
            PolicyLayer(
                name="project",
                revision=2,
                allowed_values={"model": {"luna", "sol"}},
            ),
        )
        decision = self.engine.resolve_choice(
            "model",
            "sol",
            layers,
            available_values={"luna", "sol"},
        )
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.allowed_values, ("luna",))

    def test_project_allowlist_cannot_replace_missing_root_allowlist(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=1,
            ),
            PolicyLayer(
                name="project",
                revision=2,
                allowed_values={"model": {"luna"}},
            ),
        )
        decision = self.engine.resolve_choice(
            "model",
            "luna",
            layers,
            available_values={"luna"},
        )
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.allowed_values, ())

    def test_choice_is_default_denied_without_admin_allowlist(self) -> None:
        decision = self.engine.resolve_choice(
            "model",
            "luna",
            (),
            available_values={"luna"},
        )
        self.assertFalse(decision.permitted)
        self.assertEqual(
            decision.denial_code,
            PolicyErrorCode.VALUE_NOT_ALLOWED,
        )

    def test_full_snapshot_is_serializable_and_tracks_revisions(self) -> None:
        layers = (
            PolicyLayer(
                name="organization",
                revision=7,
                features={"web_search": FeatureMode.OPTIONAL},
                integer_limits={
                    "max_upload_bytes": IntegerLimit(maximum=1024)
                },
                allowed_values={"model": {"luna"}},
            ),
        )
        request = PolicyRequest(
            features={"web_search": True},
            integers={"max_upload_bytes": 900},
            choices={"model": "luna"},
        )
        capabilities = PolicyCapabilities(
            features={"web_search": True},
            integer_maximums={"max_upload_bytes": 2048},
            choices={"model": {"luna", "sol"}},
        )
        snapshot = self.engine.evaluate(
            request,
            layers,
            capabilities=capabilities,
        )
        payload = snapshot.to_dict()

        self.assertTrue(snapshot.permitted)
        self.assertEqual(payload["engine_version"], 1)
        self.assertEqual(
            payload["source_revisions"],
            [{"source": "organization", "revision": 7}],
        )
        self.assertEqual(
            payload["choices"]["model"]["allowed_values"],
            ["luna"],
        )


if __name__ == "__main__":
    unittest.main()
