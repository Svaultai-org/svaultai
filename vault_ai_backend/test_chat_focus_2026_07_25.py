"""Tests for ConversationalFocus storage primitives, TTL, and
clearing semantics.
"""

from __future__ import annotations

import unittest

import vault_chat_focus as vf
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-focus-test"
SESSION = "sess-focus-test"


class FocusValidationTest(unittest.TestCase):

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            vf.ConversationalFocus(
                kind="bogus", id="x",
                assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
                assistant_turn_id="a1",
                vault_id=VAULT, session_id=SESSION,
                at=1.0, expires_at=2.0,
            )

    def test_unknown_assistant_act_rejected(self):
        with self.assertRaises(ValueError):
            vf.ConversationalFocus(
                kind=vf.FOCUS_KIND_DRAFT, id="x",
                assistant_act="bogus",
                assistant_turn_id="a1",
                vault_id=VAULT, session_id=SESSION,
                at=1.0, expires_at=2.0,
            )

    def test_kind_none_forbids_id(self):
        with self.assertRaises(ValueError):
            vf.ConversationalFocus(
                kind=vf.FOCUS_KIND_NONE, id="oops",
                assistant_act=vf.FOCUS_ACT_NONE,
                assistant_turn_id="a1",
                vault_id=VAULT, session_id=SESSION,
                at=1.0, expires_at=2.0,
            )

    def test_kind_draft_requires_id(self):
        with self.assertRaises(ValueError):
            vf.ConversationalFocus(
                kind=vf.FOCUS_KIND_DRAFT, id=None,
                assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
                assistant_turn_id="a1",
                vault_id=VAULT, session_id=SESSION,
                at=1.0, expires_at=2.0,
            )


class FocusTargetsTest(unittest.TestCase):

    def test_targets_true_when_matches(self):
        f = vf.ConversationalFocus(
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
            vault_id=VAULT, session_id=SESSION,
            at=1.0, expires_at=2.0,
        )
        self.assertTrue(f.targets(vf.FOCUS_KIND_DRAFT, "d-1"))

    def test_targets_false_on_different_kind(self):
        f = vf.ConversationalFocus(
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
            vault_id=VAULT, session_id=SESSION,
            at=1.0, expires_at=2.0,
        )
        self.assertFalse(f.targets(vf.FOCUS_KIND_PENDING_ACTION, "d-1"))

    def test_targets_false_on_different_id(self):
        f = vf.ConversationalFocus(
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
            vault_id=VAULT, session_id=SESSION,
            at=1.0, expires_at=2.0,
        )
        self.assertFalse(f.targets(vf.FOCUS_KIND_DRAFT, "d-2"))


class FocusStorageTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_stamp_then_read(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
        )
        f = vf.read_focus(vault_id=VAULT, session_id=SESSION)
        self.assertIsNotNone(f)
        self.assertEqual(f.kind, vf.FOCUS_KIND_DRAFT)
        self.assertEqual(f.id, "d-1")

    def test_read_missing_returns_none(self):
        self.assertIsNone(vf.read_focus(vault_id=VAULT, session_id=SESSION))

    def test_stamp_refreshes(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1", now=1000.0,
        )
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-2",
            assistant_act=vf.FOCUS_ACT_ASKED_CLARIFICATION,
            assistant_turn_id="a2", now=1010.0,
        )
        f = vf.read_focus(vault_id=VAULT, session_id=SESSION, now=1020.0)
        self.assertEqual(f.id, "d-2")
        self.assertEqual(f.assistant_turn_id, "a2")

    def test_clear_focus(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
        )
        removed = vf.clear_focus(vault_id=VAULT, session_id=SESSION)
        self.assertTrue(removed)
        self.assertIsNone(vf.read_focus(vault_id=VAULT, session_id=SESSION))

    def test_clear_focus_missing_returns_false(self):
        self.assertFalse(vf.clear_focus(vault_id=VAULT, session_id=SESSION))

    def test_clear_focus_if_matches_deletes_on_match(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
        )
        self.assertTrue(vf.clear_focus_if_matches(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
        ))
        self.assertIsNone(vf.read_focus(vault_id=VAULT, session_id=SESSION))

    def test_clear_focus_if_matches_preserves_on_mismatch(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
        )
        self.assertFalse(vf.clear_focus_if_matches(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-99",
        ))
        self.assertIsNotNone(vf.read_focus(vault_id=VAULT, session_id=SESSION))


class FocusExpiryTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_expired_focus_not_returned(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
            now=1000.0, ttl_seconds=1,
        )
        self.assertIsNone(
            vf.read_focus(vault_id=VAULT, session_id=SESSION, now=2000.0),
        )


class FocusSessionScopeTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_focus_is_per_session(self):
        vf.stamp_focus(
            vault_id=VAULT, session_id="A",
            kind=vf.FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=vf.FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a1",
        )
        self.assertIsNotNone(vf.read_focus(vault_id=VAULT, session_id="A"))
        self.assertIsNone(vf.read_focus(vault_id=VAULT, session_id="B"))


if __name__ == "__main__":
    unittest.main()
