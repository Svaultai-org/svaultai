"""Synthetic endpoint regression for upload naming follow-ups.

The real encrypted /chat route is exercised under the default direct-AI
configuration. No real vault, file contents, PIN, or AI service is used.
"""

from __future__ import annotations

import time
from unittest import mock

from test_chat_endpoint_deterministic_2026_08_01 import (
    _ChatEndpointHarness,
    _TEST_SESSION_ID,
    _TEST_VAULT_ID,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_upload_binding import bind_upload, resolve_active_upload
from vault_chat_general_router import route_general_chat

import unittest


_FILE_ID = "synthetic-pending-file-1"


class PendingFileNameEndpointTests(unittest.TestCase):
    def setUp(self):
        self.h = _ChatEndpointHarness(files_fixture=[])
        self.h.setUp()
        install_backend_for_tests(InMemoryChatStateBackend())
        self.pending = True
        self.save_calls = []
        self.pending_row = {
            "id": _FILE_ID,
            "file_name": "synthetic-example.txt",
            "content_type": "text/plain",
            "needs_naming": True,
            "upload_status": "complete",
        }
        self.db_lookup = self.h._patch(
            "main.get_pending_named_file",
            side_effect=lambda vault_id: (
                self.pending_row if self.pending else None
            ),
        )

        def _save(*, vault_id, file_id, saved_name, key,
                  require_pending_name=False):
            self.assertEqual(vault_id, _TEST_VAULT_ID)
            self.assertEqual(file_id, _FILE_ID)
            self.assertTrue(require_pending_name)
            if not self.pending:
                raise ValueError("already named")
            self.pending = False
            self.save_calls.append(saved_name)
            return {"saved_name": saved_name, "file_name": "synthetic-example.txt"}

        self.h._patch("main.save_named_uploaded_asset", side_effect=_save)

    def tearDown(self):
        self.h.tearDown()
        reset_chat_state_backend_for_tests()

    def _bind(self, *, session_id=_TEST_SESSION_ID, created_at=None):
        def _write():
            bind_upload(
                vault_id=_TEST_VAULT_ID,
                session_id=session_id,
                turn_id="synthetic-upload-turn",
                uploaded_file_id=_FILE_ID,
                filename="synthetic-example.txt",
                content_type="text/plain",
            )
        if created_at is None:
            _write()
        else:
            with mock.patch("vault_chat_upload_binding._now", return_value=created_at):
                _write()

    def test_bare_label_after_upload_names_file_without_ai(self):
        label = "project github recovery"
        general = route_general_chat(label, "en")
        self.assertTrue(general and general.model_response_required)
        self._bind()
        self.h.arm_planner_sentinel()

        reply = self.h.post_message(label)

        self.assertEqual(reply.http_status, 200, reply.summary())
        self.assertEqual(reply.x_chat_path, "pending_file_named", reply.summary())
        self.assertEqual(reply.envelope_json, "Saved this file as Project Github Recovery.")
        self.assertFalse(reply.planner_invoked, reply.summary())
        self.assertEqual(self.save_calls, [label])
        self.assertFalse(self.pending)
        self.assertIsNone(resolve_active_upload(
            vault_id=_TEST_VAULT_ID, session_id=_TEST_SESSION_ID,
        ))

    def test_explicit_unrelated_request_does_not_consume_pending_file(self):
        self._bind()
        self.h.disarm_planner_sentinel()

        reply = self.h.post_message("recover account")

        self.assertEqual(reply.http_status, 200, reply.summary())
        self.assertEqual(self.save_calls, [])
        self.assertTrue(self.pending)

    def test_missing_binding_does_not_query_pending_row_or_rename(self):
        self.h.disarm_planner_sentinel()

        reply = self.h.post_message("project github recovery")

        self.assertEqual(reply.http_status, 200, reply.summary())
        self.assertEqual(self.save_calls, [])
        self.assertEqual(self.db_lookup.call_count, 0)

    def test_different_session_binding_does_not_rename(self):
        self._bind(session_id="a-different-session")
        self.h.disarm_planner_sentinel()

        reply = self.h.post_message("project github recovery")

        self.assertEqual(reply.http_status, 200, reply.summary())
        self.assertEqual(self.save_calls, [])
        self.assertEqual(self.db_lookup.call_count, 0)

    def test_expired_binding_does_not_rename(self):
        self._bind(created_at=time.time() - 600)
        self.h.disarm_planner_sentinel()

        reply = self.h.post_message("project github recovery")

        self.assertEqual(reply.http_status, 200, reply.summary())
        self.assertEqual(self.save_calls, [])
        self.assertEqual(self.db_lookup.call_count, 0)

    def test_duplicate_submit_only_names_file_once(self):
        self._bind()
        self.h.arm_planner_sentinel()
        first = self.h.post_message("project github recovery")
        self.assertEqual(first.http_status, 200, first.summary())
        self.h.disarm_planner_sentinel()

        second = self.h.post_message("project github recovery")

        self.assertEqual(second.http_status, 200, second.summary())
        self.assertNotEqual(second.x_chat_path, "pending_file_named")
        self.assertEqual(self.save_calls, ["project github recovery"])

    def test_short_chat_after_naming_is_not_trapped_by_old_binding(self):
        self._bind()
        self.h.arm_planner_sentinel()
        first = self.h.post_message("project github recovery")
        self.assertEqual(first.http_status, 200, first.summary())
        self.h.disarm_planner_sentinel()

        followup = self.h.post_message("thanks")

        self.assertEqual(followup.http_status, 200, followup.summary())
        self.assertNotEqual(followup.x_chat_path, "pending_file_name_stale")
        self.assertEqual(self.save_calls, ["project github recovery"])


class PendingFileNameCandidateTests(unittest.TestCase):
    def test_short_label_and_explicit_name_are_accepted(self):
        import main
        self.assertEqual(
            main.pending_file_name_candidate("project github recovery"),
            "project github recovery",
        )
        self.assertEqual(
            main.pending_file_name_candidate("please call it archive notes"),
            "archive notes",
        )

    def test_new_requests_and_cancellation_are_not_names(self):
        import main
        for message in (
            "reset password", "recover account", "sign in", "log in",
            "please stop", "cancel", "thanks", "hello",
            "show my saved logins",
            "tell me how to recover my account", "what is this?",
        ):
            with self.subTest(message=message):
                self.assertIsNone(main.pending_file_name_candidate(message))


class PendingFileAtomicSaveTests(unittest.TestCase):
    def test_concurrent_name_winner_prevents_second_update(self):
        """A second request that read the row before a rival commit loses CAS."""
        import main

        class Cursor:
            rowcount = 0
            statements = []

            def execute(self, sql, params=()):
                self.statements.append((sql, params))
                # Simulate another request winning just before our UPDATE.
                self.rowcount = 0

            def fetchone(self):
                return {
                    "id": _FILE_ID,
                    "file_name": "synthetic-example.txt",
                    "content_type": "text/plain",
                    "detected_service": None,
                    "needs_naming": True,
                    "extracted_text": None,
                    "extracted_text_encrypted": False,
                }

        class Connection:
            committed = False
            closed = False
            cursor_obj = Cursor()

            def cursor(self, cursor_factory=None):
                return self.cursor_obj

            def commit(self):
                self.committed = True

            def close(self):
                self.closed = True

        conn = Connection()
        with mock.patch("main.get_db", return_value=conn), mock.patch(
            "main._infer_asset_type", return_value="file"
        ):
            with self.assertRaisesRegex(ValueError, "already named"):
                main.save_named_uploaded_asset(
                    vault_id=_TEST_VAULT_ID,
                    file_id=_FILE_ID,
                    saved_name="project github recovery",
                    key=None,
                    require_pending_name=True,
                )
        self.assertFalse(conn.committed)
        self.assertTrue(conn.closed)
        update_sql, update_params = conn.cursor_obj.statements[-1]
        self.assertIn("needs_naming = TRUE", update_sql)
        self.assertIn("vault_id = %s", update_sql)
        self.assertEqual(update_params[-1], _TEST_VAULT_ID)


if __name__ == "__main__":
    unittest.main()
