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

    def test_thresholds_are_only_public_symbols(self):
        # No stray numeric constants sneaking in.
        expected = {
            "CONFIDENCE_EXECUTE_NON_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_DESTRUCTIVE",
            "CONFIDENCE_EXECUTE_HIGH_CONTEXT",
        }
        self.assertEqual(set(ct.__all__), expected)


if __name__ == "__main__":
    unittest.main()
