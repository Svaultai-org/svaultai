from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from vault_brain_intent import (
    ANSWER_FROM_FILE_CONTENT,
    CREDENTIAL_LOOKUP,
    classify_brain_intent,
)
from vault_chat_router import build_vault_chat_envelope


class CurrentAttachmentPrecedenceTests(unittest.TestCase):
    def test_reported_credential_document_prompt_binds_to_attachment(self):
        message = "analyze and save all credentials added"
        decision = classify_brain_intent(
            message,
            has_uploaded_files_in_turn=True,
        )
        self.assertEqual(decision.intent, ANSWER_FROM_FILE_CONTENT)
        self.assertEqual(decision.scope_hint, "this_file")
        self.assertIsNone(
            build_vault_chat_envelope(
                message,
                has_current_attachments=True,
            )
        )

    def test_same_words_without_attachment_keep_historical_lookup_semantics(self):
        message = "analyze and save all credentials added"
        self.assertEqual(
            classify_brain_intent(message).intent,
            CREDENTIAL_LOOKUP,
        )
        envelope = build_vault_chat_envelope(message)
        self.assertEqual(envelope["intent"], "vault_login_search")

    def test_current_file_credential_question_never_becomes_login_card(self):
        for message in (
            "what credentials are in this file?",
            "extract the logins from this PDF",
            "review this document for usernames and passwords",
            "scan the attached file for account records",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    classify_brain_intent(
                        message,
                        has_uploaded_files_in_turn=True,
                    ).intent,
                    ANSWER_FROM_FILE_CONTENT,
                )
                self.assertIsNone(
                    build_vault_chat_envelope(
                        message,
                        has_current_attachments=True,
                    )
                )

    def test_explicit_historical_vault_scope_can_override_attachment(self):
        message = "search my vault for saved credentials"
        self.assertNotEqual(
            classify_brain_intent(
                message,
                has_uploaded_files_in_turn=True,
            ).intent,
            ANSWER_FROM_FILE_CONTENT,
        )


class CredentialExtractionConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    @staticmethod
    def _records():
        return [
            {
                "secret_type": "login",
                "service": "Synthetic Alpha",
                "fields": {
                    "username": "alpha-user",
                    "password": "synthetic-alpha-secret",
                },
            },
            {
                "secret_type": "login",
                "service": "Synthetic Beta",
                "fields": {
                    "email": "beta@example.invalid",
                    "password": "synthetic-beta-secret",
                },
            },
        ]

    def _pending(self, records):
        envelope = self.main._build_credential_extraction_review_envelope(
            file_id="file-current",
            file_name="synthetic.csv",
            saved_name=None,
            relative_path=None,
            records=records,
            message="review",
            text_available=True,
        )
        memory = {}
        self.main._remember_credential_extraction_review(memory, envelope)
        return memory[self.main._PENDING_CREDENTIAL_EXTRACTION_KEY]

    def test_review_decision_phrases_are_narrow_and_fast_path_guarded(self):
        self.assertIsNotNone(
            self.main._CONFIRM_CREDENTIAL_EXTRACTION_RE.match(
                "approve all extracted credentials"
            )
        )
        self.assertIsNotNone(
            self.main._CANCEL_CREDENTIAL_EXTRACTION_RE.match(
                "discard the extracted credentials"
            )
        )
        self.assertIsNone(
            self.main._CONFIRM_CREDENTIAL_EXTRACTION_RE.match(
                "save my Facebook login"
            )
        )
        import inspect
        chat_source = inspect.getsource(self.main.chat_endpoint)
        self.assertIn(
            "_CONFIRM_CREDENTIAL_EXTRACTION_RE.match",
            chat_source,
        )
        self.assertIn(
            "_CANCEL_CREDENTIAL_EXTRACTION_RE.match",
            chat_source,
        )

    def test_review_state_contains_no_secret_values(self):
        records = self._records()
        pending = self._pending(records)
        serialized = json.dumps(pending)
        self.assertNotIn("synthetic-alpha-secret", serialized)
        self.assertNotIn("synthetic-beta-secret", serialized)
        self.assertEqual(pending["record_count"], 2)

    def test_separate_confirmation_saves_exact_reviewed_records(self):
        records = self._records()
        pending = self._pending(records)
        saved = []
        file_row = {
            "id": "file-current",
            "file_name": "synthetic.csv",
            "saved_name": None,
            "relative_path": None,
            "extracted_text": "synthetic source",
        }
        with patch.object(
            self.main,
            "_load_one_file_for_analysis",
            return_value=file_row,
        ), patch.object(
            self.main,
            "extract_secure_records",
            return_value=records,
        ), patch.object(
            self.main,
            "save_secret_tool",
            side_effect=lambda vault_id, payload, key, **_kwargs: saved.append(payload),
        ):
            reply = self.main._confirm_credential_extraction_review(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
            )
        self.assertEqual(len(saved), 2)
        self.assertIn("Saved 2 approved", reply)

    def test_changed_record_set_fails_closed_without_saving(self):
        records = self._records()
        pending = self._pending(records)
        changed = [dict(records[0], service="Different Service")]
        with patch.object(
            self.main,
            "_load_one_file_for_analysis",
            return_value={
                "id": "file-current",
                "file_name": "synthetic.csv",
                "saved_name": None,
                "relative_path": None,
                "extracted_text": "synthetic source",
            },
        ), patch.object(
            self.main,
            "extract_secure_records",
            return_value=changed,
        ), patch.object(self.main, "save_secret_tool") as save_mock:
            reply = self.main._confirm_credential_extraction_review(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
            )
        save_mock.assert_not_called()
        self.assertIn("changed since review", reply)


if __name__ == "__main__":
    unittest.main()
