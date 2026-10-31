from __future__ import annotations

import unittest

from private_ai_hub.policy import FeatureMode, IntegerLimit, PolicyViolation, resolve_feature


class PolicyTests(unittest.TestCase):
    def test_admin_disabled_wins(self) -> None:
        decision = resolve_feature(FeatureMode.DISABLED, requested=True)
        self.assertFalse(decision.effective)

    def test_admin_required_wins(self) -> None:
        decision = resolve_feature(FeatureMode.REQUIRED, requested=False)
        self.assertTrue(decision.effective)

    def test_optional_follows_user_request(self) -> None:
        self.assertTrue(resolve_feature(FeatureMode.OPTIONAL, True).effective)
        self.assertFalse(resolve_feature(FeatureMode.OPTIONAL, False).effective)

    def test_integer_limit_clamps(self) -> None:
        limit = IntegerLimit(minimum=1, maximum=8)
        self.assertEqual(limit.clamp(99), 8)
        self.assertEqual(limit.clamp(0), 1)

    def test_integer_limit_can_reject(self) -> None:
        limit = IntegerLimit(minimum=1, maximum=8)
        with self.assertRaises(PolicyViolation):
            limit.require(9)


if __name__ == "__main__":
    unittest.main()
