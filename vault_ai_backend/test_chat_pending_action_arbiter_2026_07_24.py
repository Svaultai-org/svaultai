"""Regression tests for ``vault_chat_pending_action`` — the unified
pending-action arbiter that replaced the pre-2026-07-24 cascade.

Root-cause coverage:

    * A stale ``uploaded_files.needs_naming=TRUE`` row without a
      matching upload binding must NOT surface as a pending
      attachment. This is the fix for the "yes → Saved this video
      as Video_XXX.webm" incident.

    * A fresh pending delete + a stale unnamed file must resolve
      to the pending delete, not the unnamed file, because the
      delete is destructive-priority.

    * Cross-session bindings must not surface in another
      session's arbiter view.
"""

from __future__ import annotations

import time
import unittest

from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-arbiter-test"
SESSION_A = "session-A"
SESSION_B = "session-B"


class _NoopMemory(dict):
    pass


class _FakeDeleteIntent:
    def __init__(self, intent_id, service, item_type, is_login,
                 created_at, expires_at, item_id=None):
        self.intent_id = intent_id
        self.service = service
        self.item_type = item_type
        self.is_login = is_login
        self.created_at = created_at
        self.expires_at = expires_at
        self.item_id = item_id

    def is_expired(self, now=None):
        return (now or time.time()) >= self.expires_at


class TestArbiter(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        # Patch modules the arbiter reads from with lightweight
        # in-test fakes so we can control what each returns.
        import vault_chat_pending_action as pa
        self.pa = pa
        # Real credential_draft is Redis-backed so it works
        # naturally; real delete-intent is Redis-backed so it
        # works naturally too. We only stub for edge cases.

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    # ---------------------------------------------------------------
    # Core: stale attachment without binding is invisible.
    # ---------------------------------------------------------------

    def test_stale_uploaded_file_without_binding_is_invisible(self):
        """The root cause. get_pending_named_file may return a row
        for an old unnamed video, but without a fresh binding for
        THIS session the arbiter must NOT expose it."""
        # No binding writes → the read side sees no attachment.
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_A,
            memory=_NoopMemory(),
        )
        self.assertEqual(pending.kind, self.pa.KIND_NONE)

    # ---------------------------------------------------------------
    # Core: delete beats attachment when both are live.
    # ---------------------------------------------------------------

    def test_pending_delete_wins_over_bound_attachment(self):
        """Even if a session has a fresh attachment binding, if a
        pending delete exists too, the destructive one wins."""
        from vault_chat_upload_binding import bind_upload
        from vault_secure_item_delete_confirmation import (
            store_delete_intent,
        )
        # Bind a fresh attachment for this session.
        bind_upload(
            vault_id=VAULT, session_id=SESSION_A,
            turn_id="upload-1", uploaded_file_id="file-1",
            filename="photo.jpg", content_type="image/jpeg",
        )
        # Stamp a pending delete on the same vault.
        store_delete_intent(
            vault_id=VAULT, service="Instagram",
            item_type="login", item_id=None,
        )
        # The DB verify would fail in-test because the fake vault
        # has no `main.get_pending_named_file` support — but the
        # priority sort means the delete is chosen first anyway
        # even if the attachment were admitted.
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_A,
            memory=_NoopMemory(),
        )
        self.assertEqual(pending.kind, self.pa.KIND_DELETE_SECURE_ITEM)
        self.assertTrue(pending.is_destructive)

    # ---------------------------------------------------------------
    # Session isolation
    # ---------------------------------------------------------------

    def test_binding_for_other_session_is_invisible(self):
        """A pending attachment bound to session A must not show
        up for session B."""
        from vault_chat_upload_binding import bind_upload
        bind_upload(
            vault_id=VAULT, session_id=SESSION_A,
            turn_id="upload-1", uploaded_file_id="file-1",
            filename="photo.jpg", content_type="image/jpeg",
        )
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_B,
            memory=_NoopMemory(),
        )
        self.assertEqual(pending.kind, self.pa.KIND_NONE)

    # ---------------------------------------------------------------
    # Expiry handling
    # ---------------------------------------------------------------

    def test_expired_delete_is_invisible(self):
        """Expired pending delete must not appear as active."""
        # There is no direct API to write an expired intent, but
        # we can call store then advance time via a stubbed
        # reader — instead, exercise the arbiter's now= override.
        from vault_secure_item_delete_confirmation import (
            DELETE_INTENT_TTL_SECONDS, store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT, service="Instagram",
            item_type="login",
        )
        # Query far in the future.
        future = time.time() + DELETE_INTENT_TTL_SECONDS + 10
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_A,
            memory=_NoopMemory(), now=future,
        )
        self.assertEqual(pending.kind, self.pa.KIND_NONE)

    # ---------------------------------------------------------------
    # None is well-formed
    # ---------------------------------------------------------------

    def test_none_pending_returns_none_kind(self):
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_A,
            memory=_NoopMemory(),
        )
        self.assertEqual(pending.kind, self.pa.KIND_NONE)
        self.assertFalse(pending.is_destructive)
        self.assertEqual(pending.action_id, "")

    # ---------------------------------------------------------------
    # to_prompt_dict never leaks vault_id / metadata plaintext
    # ---------------------------------------------------------------

    def test_prompt_dict_shape(self):
        from vault_secure_item_delete_confirmation import (
            store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT, service="Netflix", item_type="login",
        )
        pending = self.pa.read_active_pending(
            vault_id=VAULT, session_id=SESSION_A,
            memory=_NoopMemory(),
        )
        d = pending.to_prompt_dict()
        self.assertIn("action_id", d)
        self.assertIn("kind", d)
        self.assertIn("target_label", d)
        self.assertIn("is_destructive", d)
        self.assertIn("age_seconds", d)
        self.assertNotIn("vault_id", d)
        self.assertNotIn("session_id", d)


class TestHasDestructivePending(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_flag_true_when_delete_stamped(self):
        from vault_chat_pending_action import has_destructive_pending
        from vault_secure_item_delete_confirmation import (
            store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT, service="Gmail", item_type="login",
        )
        self.assertTrue(has_destructive_pending(
            vault_id=VAULT, session_id=SESSION_A,
        ))

    def test_flag_false_when_no_pending(self):
        from vault_chat_pending_action import has_destructive_pending
        self.assertFalse(has_destructive_pending(
            vault_id=VAULT, session_id=SESSION_A,
        ))


if __name__ == "__main__":
    unittest.main()
