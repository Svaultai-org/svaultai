"""Regression tests for ``vault_chat_upload_binding``.

Attachment isolation is the structural fix for the "yes → Saved
this video as Video_XXX.webm" incident. These tests lock the
binding lifetime, per-session scope, and cross-worker safety.
"""

from __future__ import annotations

import time
import unittest

from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_upload_binding import (
    ATTACHMENT_BINDING_TTL_SECONDS,
    bind_upload,
    clear_binding,
    resolve_active_upload,
)


VAULT_A = "vault-A"
VAULT_B = "vault-B"
SESSION_A = "sess-A"
SESSION_B = "sess-B"


class TestBindingLifecycle(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    # ---------------------------------------------------------------
    # Freshness
    # ---------------------------------------------------------------

    def test_fresh_binding_is_resolvable(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="photo.jpg", content_type="image/jpeg",
        )
        b = resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
        )
        self.assertIsNotNone(b)
        self.assertEqual(b.uploaded_file_id, "file-1")
        self.assertEqual(b.filename, "photo.jpg")

    def test_stale_binding_beyond_max_age_is_invisible(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="video.webm", content_type="video/webm",
        )
        b = resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            max_age_seconds=0,     # every binding is older than 0s
            now=time.time() + 5,
        )
        self.assertIsNone(b)

    def test_clear_binding_removes_it(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="x.png", content_type="image/png",
        )
        self.assertTrue(clear_binding(
            vault_id=VAULT_A, uploaded_file_id="file-1",
        ))
        self.assertIsNone(resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
        ))

    # ---------------------------------------------------------------
    # Session isolation
    # ---------------------------------------------------------------

    def test_binding_is_per_session(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="p.jpg", content_type="image/jpeg",
        )
        # Same vault, different session — invisible.
        b_other = resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_B,
        )
        self.assertIsNone(b_other)

    def test_binding_is_per_vault(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="p.jpg", content_type="image/jpeg",
        )
        b_other = resolve_active_upload(
            vault_id=VAULT_B, session_id=SESSION_A,
        )
        self.assertIsNone(b_other)

    # ---------------------------------------------------------------
    # Newest wins
    # ---------------------------------------------------------------

    def test_newest_binding_wins(self):
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="old.jpg", content_type="image/jpeg",
        )
        # Sleep briefly so created_at differs.
        time.sleep(0.01)
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t2", uploaded_file_id="file-2",
            filename="new.jpg", content_type="image/jpeg",
        )
        b = resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
        )
        self.assertIsNotNone(b)
        self.assertEqual(b.uploaded_file_id, "file-2")

    # ---------------------------------------------------------------
    # Cross-worker: two workers, one backend
    # ---------------------------------------------------------------

    def test_cross_worker_binding(self):
        """A binding written by worker A is readable by worker B
        because both share the same backend."""
        # Simulate worker A writing.
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="t1", uploaded_file_id="file-1",
            filename="p.jpg", content_type="image/jpeg",
        )
        # Simulate worker B reading (same backend singleton in
        # our test — mirrors what Redis does in production).
        b = resolve_active_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
        )
        self.assertIsNotNone(b)

    # ---------------------------------------------------------------
    # TTL default
    # ---------------------------------------------------------------

    def test_ttl_default_is_five_minutes(self):
        self.assertEqual(ATTACHMENT_BINDING_TTL_SECONDS, 300)


if __name__ == "__main__":
    unittest.main()
