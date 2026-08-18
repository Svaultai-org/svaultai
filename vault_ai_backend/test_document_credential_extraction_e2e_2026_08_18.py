from __future__ import annotations

import base64
import io
import inspect
import json
import unittest
from unittest.mock import patch

from reportlab.pdfgen import canvas

import extractor
import main


SYNTHETIC_TEXT = """Synthetic Alpha
username: alpha-user
password: Alpha-Secret-1
website: https://alpha.example.invalid

Synthetic Beta
email: beta@example.invalid
password: Beta-Secret-2
website: beta.example.invalid

Synthetic Gamma
username: gamma-user
password: Gamma-Secret-3
website: https://gamma.example.invalid/login
"""


def _synthetic_pdf_bytes() -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    y = 800
    for line in SYNTHETIC_TEXT.splitlines():
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()
    return output.getvalue()


def _records() -> list[dict]:
    return extractor.extract_multiple_credentials(SYNTHETIC_TEXT)


def _pending(records: list[dict]) -> tuple[dict, list[dict]]:
    envelope = main._build_credential_extraction_review_envelope(
        file_id="file-synthetic",
        file_name="synthetic-three-logins.pdf",
        saved_name=None,
        relative_path=None,
        records=records,
        message="Review",
        text_available=True,
    )
    memory: dict = {}
    main._remember_credential_extraction_review(memory, envelope)
    safe = json.loads(envelope)["records"]
    return memory[main._PENDING_CREDENTIAL_EXTRACTION_KEY], safe


class DocumentCredentialExtractionE2ETests(unittest.TestCase):
    def test_synthetic_pdf_extracts_three_exact_source_candidates(self):
        text = main._extract_text_from_bytes(
            "synthetic-three-logins.pdf", _synthetic_pdf_bytes()
        )
        self.assertTrue(text)
        records = extractor.extract_multiple_credentials(text or "")
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record["service"] for record in records],
            ["synthetic alpha", "synthetic beta", "synthetic gamma"],
        )
        self.assertEqual(
            [record["fields"].get("password") for record in records],
            ["Alpha-Secret-1", "Beta-Secret-2", "Gamma-Secret-3"],
        )
        self.assertEqual(
            records[2]["fields"].get("url"),
            "https://gamma.example.invalid/login",
        )

    def test_review_envelope_masks_secrets_and_normalizes_source_fields(self):
        records = _records()
        envelope = main._build_credential_extraction_review_envelope(
            file_id="file-synthetic",
            file_name="synthetic-three-logins.pdf",
            saved_name=None,
            relative_path=None,
            records=records,
            message="Review",
            text_available=True,
        )
        self.assertNotIn("Alpha-Secret-1", envelope)
        self.assertNotIn("Beta-Secret-2", envelope)
        self.assertNotIn("Gamma-Secret-3", envelope)
        payload = json.loads(envelope)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len({row["candidate_id"] for row in payload["records"]}), 3)
        self.assertTrue(all(row["password_present"] for row in payload["records"]))
        self.assertEqual(
            payload["records"][0]["website"],
            "https://alpha.example.invalid",
        )
        self.assertTrue(all(row["source_context"] for row in payload["records"]))

    def test_all_attachment_extraction_phrases_route_to_review(self):
        phrases = (
            "analyze this file and save the credentials",
            "read this document and find all logins",
            "extract the passwords from this file",
            "show me all credentials in this document",
            "find all usernames and passwords in this PDF",
            "analyze this attached PDF and save credentials",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(main._user_requested_login_extraction(phrase))
        self.assertFalse(
            main._user_requested_login_extraction("show my Facebook login")
        )

    def test_attachment_review_guard_precedes_all_planner_routing(self):
        source = inspect.getsource(main.chat_endpoint)
        guard_index = source.index("_current_attachment_extraction = bool")
        planner_index = source.index("site=route_to_ai_planner_stream")
        self.assertLess(guard_index, planner_index)
        self.assertIn("generation_suppressed=true", source)

    def test_encrypted_review_action_parser_accepts_only_bounded_actions(self):
        payload = {
            "action": "save",
            "candidate_ids": ["a" * 24],
            "overrides": {},
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload).encode("utf-8")
        ).decode("ascii").rstrip("=")
        parsed = main._parse_credential_extraction_action(
            main._CREDENTIAL_EXTRACTION_ACTION_PREFIX + encoded
        )
        self.assertEqual(parsed["candidate_ids"], ["a" * 24])
        self.assertIsNone(main._parse_credential_extraction_action("save it"))
        self.assertEqual(
            main._parse_credential_extraction_action(
                main._CREDENTIAL_EXTRACTION_ACTION_PREFIX + "invalid"
            ),
            {},
        )

    def test_save_one_and_save_selected_persist_only_source_candidates(self):
        records = _records()
        pending, safe = _pending(records)
        saved: list[dict] = []
        file_row = {
            "id": "file-synthetic",
            "file_name": "synthetic-three-logins.pdf",
            "saved_name": None,
            "relative_path": None,
            "extracted_text": SYNTHETIC_TEXT,
        }
        with patch.object(main, "_load_one_file_for_analysis", return_value=file_row), patch.object(
            main, "extract_multiple_credentials", return_value=records
        ), patch.object(main, "_peek_existing_login_fields", return_value={}), patch.object(
            main,
            "save_secret_tool",
            side_effect=lambda vault_id, payload, key: saved.append(payload),
        ):
            reply = main._handle_credential_extraction_action(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
                action={
                    "action": "save_selected",
                    "candidate_ids": [
                        safe[0]["candidate_id"],
                        safe[2]["candidate_id"],
                    ],
                    "overrides": {},
                },
            )
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0], records[0])
        self.assertEqual(saved[1], records[2])
        self.assertIn("Saved 2 selected", reply)
        self.assertIn("No unselected candidates were saved", reply)

    def test_edit_before_save_and_duplicate_detection_fail_closed(self):
        records = _records()
        pending, safe = _pending(records)
        selected_id = safe[0]["candidate_id"]
        saved: list[dict] = []
        file_row = {
            "id": "file-synthetic",
            "file_name": "synthetic-three-logins.pdf",
            "saved_name": None,
            "relative_path": None,
            "extracted_text": SYNTHETIC_TEXT,
        }
        with patch.object(main, "_load_one_file_for_analysis", return_value=file_row), patch.object(
            main, "extract_multiple_credentials", return_value=records
        ), patch.object(main, "_peek_existing_login_fields", return_value={}), patch.object(
            main,
            "save_secret_tool",
            side_effect=lambda vault_id, payload, key: saved.append(payload),
        ):
            main._handle_credential_extraction_action(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
                action={
                    "action": "edit_and_save",
                    "candidate_ids": [selected_id],
                    "overrides": {
                        selected_id: {
                            "service": "Synthetic Alpha Edited",
                            "username": "edited-user",
                            "password": "Edited-Synthetic-Secret",
                            "website": "https://edited.example.invalid",
                            "notes": "synthetic edit",
                        }
                    },
                },
            )
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["service"], "Synthetic Alpha Edited")
        self.assertEqual(saved[0]["fields"]["username"], "edited-user")
        self.assertEqual(
            saved[0]["fields"]["password"], "Edited-Synthetic-Secret"
        )

        with patch.object(main, "_load_one_file_for_analysis", return_value=file_row), patch.object(
            main, "extract_multiple_credentials", return_value=records
        ), patch.object(
            main,
            "_peek_existing_login_fields",
            return_value=dict(records[0]["fields"]),
        ), patch.object(main, "save_secret_tool") as save_mock:
            reply = main._handle_credential_extraction_action(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
                action={
                    "action": "save",
                    "candidate_ids": [selected_id],
                    "overrides": {},
                },
            )
        save_mock.assert_not_called()
        self.assertIn("Skipped 1 exact duplicate", reply)

    def test_no_credentials_document_is_honest_and_never_generates(self):
        with patch.object(
            main,
            "_load_one_file_for_analysis",
            return_value={
                "id": "file-empty",
                "file_name": "ordinary.pdf",
                "saved_name": None,
                "relative_path": None,
                "extracted_text": "This is an ordinary synthetic memo.",
            },
        ):
            envelope = main._handle_extract_logins_from_file(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                asset_name=None,
                file_id="file-empty",
            )
        payload = json.loads(envelope)
        self.assertEqual(payload["records"], [])
        self.assertEqual(
            payload["message"],
            "I couldn't identify any credentials in this file. Nothing was saved.",
        )


if __name__ == "__main__":
    unittest.main()
