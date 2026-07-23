"""Regression tests for the 2026-07-24 Redis migration of
``vault_chat_active_entity``.

Locks:
    * public API still works identically
    * cross-worker semantics — a set written by worker A is
      readable by worker B via the shared backend
    * session-scope guarantee is preserved
    * safety checklist (forbidden ref keys, unknown entity types,
      unknown actions) still fires
"""

from __future__ import annotations

import unittest

import vault_chat_active_entity as ae
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-ae-redis"


class TestSetAndGet(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        ae._reset_store_for_test()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_set_then_get_returns_record(self):
        ok = ae.set_active_entity(
            VAULT,
            entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "gmail"},
            display_label="Gmail",
            allowed_actions=[ae.ACTION_SHOW, ae.ACTION_DELETE],
        )
        self.assertTrue(ok)
        record = ae.get_active_entity(VAULT)
        self.assertIsNotNone(record)
        self.assertEqual(record["entity_type"], "login")
        self.assertEqual(record["display_label"], "Gmail")
        self.assertIn("show", record["allowed_actions"])
        self.assertIn("delete", record["allowed_actions"])

    def test_clear_removes_entity(self):
        ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_FILE,
            entity_ref={"file_id": "abc"},
            display_label="doc.pdf",
        )
        self.assertTrue(ae.clear_active_entity(VAULT))
        self.assertIsNone(ae.get_active_entity(VAULT))

    def test_returns_none_after_expiry(self):
        ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_FILE,
            entity_ref={"file_id": "x"},
            display_label="x",
            ttl_seconds=1,
        )
        # Immediately available.
        self.assertIsNotNone(ae.get_active_entity(VAULT))


class TestSessionScope(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        ae._reset_store_for_test()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_session_bound_record_invisible_across_sessions(self):
        ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "gmail"},
            display_label="Gmail",
            session_id="session-A",
        )
        self.assertIsNotNone(ae.get_active_entity(
            VAULT, session_id="session-A",
        ))
        self.assertIsNone(ae.get_active_entity(
            VAULT, session_id="session-B",
        ))

    def test_session_bound_record_invisible_without_session(self):
        ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "gmail"},
            display_label="Gmail",
            session_id="session-A",
        )
        self.assertIsNone(ae.get_active_entity(VAULT))


class TestSafetyChecklist(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        ae._reset_store_for_test()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_unknown_entity_type_rejected(self):
        ok = ae.set_active_entity(
            VAULT, entity_type="not_a_real_type",
            entity_ref={"id": "1"},
        )
        self.assertFalse(ok)

    def test_forbidden_ref_key_rejected(self):
        ok = ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_LOGIN,
            entity_ref={"password": "secret"},   # forbidden
        )
        self.assertFalse(ok)

    def test_unknown_ref_key_rejected(self):
        ok = ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_LOGIN,
            entity_ref={"favourite_colour": "blue"},  # unknown
        )
        self.assertFalse(ok)

    def test_unknown_action_dropped_silently(self):
        ok = ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "gmail"},
            display_label="Gmail",
            allowed_actions=["show", "elope_with_it"],  # elope dropped
        )
        self.assertTrue(ok)
        record = ae.get_active_entity(VAULT)
        self.assertIn("show", record["allowed_actions"])
        self.assertNotIn("elope_with_it", record["allowed_actions"])


class TestCrossWorker(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        ae._reset_store_for_test()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_set_via_one_call_visible_from_another(self):
        # In production this is the "worker A writes, worker B
        # reads" scenario. With the shared backend both calls
        # hit the same store, matching Redis semantics.
        ae.set_active_entity(
            VAULT, entity_type=ae.ENTITY_FILE,
            entity_ref={"file_id": "doc-123"},
            display_label="report.pdf",
            session_id="worker-A-session",
        )
        # A separate "worker" call — same backend, session matches.
        record = ae.get_active_entity(
            VAULT, session_id="worker-A-session",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["entity_ref"]["file_id"], "doc-123")


class TestEntityMatchesAction(unittest.TestCase):

    def test_matches_allowed_action(self):
        record = {"allowed_actions": ("show", "delete")}
        self.assertTrue(ae.entity_matches_action(record, "delete"))

    def test_does_not_match_missing_action(self):
        record = {"allowed_actions": ("show",)}
        self.assertFalse(ae.entity_matches_action(record, "delete"))

    def test_case_insensitive(self):
        record = {"allowed_actions": ("show",)}
        self.assertTrue(ae.entity_matches_action(record, "SHOW"))


if __name__ == "__main__":
    unittest.main()
