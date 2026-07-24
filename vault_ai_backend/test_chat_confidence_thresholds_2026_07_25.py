"""Tests for the centralised confidence thresholds module."""

from __future__ import annotations

import unittest

import vault_chat_confidence_thresholds as ct


class ThresholdsTest(unittest.TestCase):

    def test_non_destructive_threshold_value(self):
        self.assertEqual(ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE, 0.85)

    def test_destructive_threshold_value(self):
        self.assertEqual(ct.CONFIDENCE_EXECUTE_DESTRUCTIVE, 0.95)

    def test_high_context_threshold_value(self):
        self.assertEqual(ct.CONFIDENCE_EXECUTE_HIGH_CONTEXT, 0.95)

    def test_destructive_at_least_non_destructive(self):
        self.assertGreaterEqual(
            ct.CONFIDENCE_EXECUTE_DESTRUCTIVE,
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE,
        )

    def test_thresholds_in_unit_interval(self):
        for name in (
            "CONFIDENCE_EXECUTE_NON_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_HIGH_CONTEXT",
        ):
            with self.subTest(name=name):
                v = getattr(ct, name)
                self.assertIsInstance(v, float)
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)

    def test_public_symbols_include_predicates(self):
        expected = {
            "CONFIDENCE_EXECUTE_NON_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_HIGH_CONTEXT",
            "is_valid_confidence",
            "may_execute_non_destructive",
            "may_execute_destructive",
            "may_execute_high_context",
            "requires_clarification",
        }
        self.assertEqual(set(ct.__all__), expected)


class ConfidencePredicatesTest(unittest.TestCase):
    """Predicate helpers (design memo rev 4 constraint 7)."""

    # -- is_valid_confidence --

    def test_is_valid_confidence_accepts_endpoints_and_midpoints(self):
        for v in (0.0, 0.001, 0.5, 0.849, 0.85, 0.95, 1.0):
            with self.subTest(value=v):
                self.assertTrue(ct.is_valid_confidence(v))

    def test_is_valid_confidence_rejects_out_of_range(self):
        for v in (-0.1, 1.1, 2.0, -1.0):
            with self.subTest(value=v):
                self.assertFalse(ct.is_valid_confidence(v))

    def test_is_valid_confidence_rejects_non_numeric(self):
        for v in ("0.9", None, [], {}):
            with self.subTest(value=v):
                self.assertFalse(ct.is_valid_confidence(v))

    def test_is_valid_confidence_rejects_bool(self):
        # bool is a numeric subtype in Python — must be rejected
        # explicitly so a truthy/falsy value can't smuggle through.
        for v in (True, False):
            with self.subTest(value=v):
                self.assertFalse(ct.is_valid_confidence(v))

    # -- may_execute_non_destructive --

    def test_may_execute_non_destructive_at_threshold(self):
        self.assertTrue(ct.may_execute_non_destructive(
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE))

    def test_may_execute_non_destructive_just_below(self):
        eps = 1e-6
        self.assertFalse(ct.may_execute_non_destructive(
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE - eps))

    # -- may_execute_destructive --

    def test_may_execute_destructive_at_threshold(self):
        self.assertTrue(ct.may_execute_destructive(
            ct.CONFIDENCE_EXECUTE_DESTRUCTIVE))

    def test_may_execute_destructive_below_non_destructive_gate_is_false(self):
        self.assertFalse(ct.may_execute_destructive(
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE))

    # -- may_execute_high_context --

    def test_may_execute_high_context_at_threshold(self):
        self.assertTrue(ct.may_execute_high_context(
            ct.CONFIDENCE_EXECUTE_HIGH_CONTEXT))

    # -- requires_clarification --

    def test_requires_clarification_non_destructive_below_threshold(self):
        self.assertTrue(ct.requires_clarification(0.7, destructive=False))

    def test_requires_clarification_non_destructive_at_threshold(self):
        self.assertFalse(ct.requires_clarification(
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE, destructive=False))

    def test_requires_clarification_destructive_at_non_destructive_threshold(self):
        # 0.85 is enough for non-destructive but NOT for destructive.
        self.assertTrue(ct.requires_clarification(
            ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE, destructive=True))

    def test_requires_clarification_destructive_at_destructive_threshold(self):
        self.assertFalse(ct.requires_clarification(
            ct.CONFIDENCE_EXECUTE_DESTRUCTIVE, destructive=True))


if __name__ == "__main__":
    unittest.main()
