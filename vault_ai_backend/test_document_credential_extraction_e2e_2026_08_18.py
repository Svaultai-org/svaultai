from __future__ import annotations

import base64
import io
import inspect
import json
import logging
import io as stdlib_io
import unittest
from unittest.mock import patch

import docx
from reportlab.pdfgen import canvas

import extractor
import main
from secure_document_extractor import extract_secure_records, extraction_counts


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


def _synthetic_twelve_page_mixed_pdf() -> tuple[bytes, int]:
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    expected = 0
    for page in range(1, 13):
        y = 750
        for row in range(1, 6):
            expected += 1
            is_duplicate = page == 12 and row == 5
            title = (
                "Synthetic Service P1 R1"
                if is_duplicate else f"Synthetic Service P{page} R{row}"
            )
            pdf.drawString(72, y, title)
            y -= 18
            variant = 1 if is_duplicate else row % 5
            if variant == 1:
                username = "user-p1-r1" if is_duplicate else f"user-p{page}-r{row}"
                password = "P1!R1 #Exact" if is_duplicate else f"P{page}!R{row} #Exact"
                pdf.drawString(72, y, f"username: {username}")
                y -= 18
                pdf.drawString(72, y, f"password: {password}")
            elif variant == 2:
                pdf.drawString(72, y, f"email: p{page}r{row}@example.invalid")
                y -= 18
                pdf.drawString(72, y, f"password: Email-P{page}?R{row}!")
            elif variant == 3:
                pdf.drawString(72, y, f"pin: {page:02d}{row:02d}")
                y -= 18
                pdf.drawString(72, y, f"account number: {page:02d}000000{row}")
            elif variant == 4:
                pdf.drawString(
                    72, y,
                    f"url: https://p{page}-r{row}.example.invalid/login",
                )
                y -= 18
                pdf.drawString(72, y, f"access code: ACCESS-{page}-{row}!")
            else:
                pdf.drawString(72, y, f"secure identifier: MEMBER-{page}-{row}")
                y -= 18
                pdf.drawString(72, y, f"password: Space kept P{page} R{row}!")
            y -= 38
        pdf.showPage()
    pdf.save()
    return output.getvalue(), expected


def _records() -> list[dict]:
    return extract_secure_records(SYNTHETIC_TEXT)


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
    def test_all_supported_secure_record_types_are_normalized(self):
        cases = (
            ("username: user\npassword: pass", "LOGIN"),
            ("account number: 123456789\nusername: owner", "ACCOUNT"),
            ("pin: 1234", "PIN"),
            ("account number: 123456789", "ACCOUNT_NUMBER"),
            ("secure identifier: MEMBER-1", "SECURE_IDENTIFIER"),
            ("url: https://example.invalid", "URL"),
            ("access code: RECOVERY-1", "RECOVERY_OR_ACCESS_CODE"),
            ("note: private synthetic note", "OTHER_SECURE_RECORD"),
        )
        text_parts = ["[[SVAULTAI_PAGE:1]]"]
        for index, (body, _expected) in enumerate(cases, 1):
            text_parts.extend((f"[[SVAULTAI_RECORD:p1-r{index}]]", body))
        records = extract_secure_records("\n".join(text_parts))
        self.assertEqual(
            [record["record_type"] for record in records],
            [expected for _body, expected in cases],
        )

    def test_extracted_values_are_not_written_to_logs(self):
        stream = stdlib_io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            main._build_credential_extraction_review_envelope(
                file_id="file-synthetic",
                file_name="synthetic.pdf",
                saved_name=None,
                relative_path=None,
                records=_records(),
                message="Review",
                text_available=True,
            )
        finally:
            root.removeHandler(handler)
        logged = stream.getvalue()
        self.assertNotIn("Alpha-Secret-1", logged)
        self.assertNotIn("alpha-user", logged)

    def test_twelve_page_mixed_document_preserves_every_page_and_record(self):
        pdf_bytes, expected = _synthetic_twelve_page_mixed_pdf()
        text = main._extract_text_from_bytes(
            "synthetic-twelve-page-mixed.pdf", pdf_bytes,
        )
        records = extract_secure_records(text or "")
        counts = extraction_counts(text or "", records)

        self.assertEqual(expected, 60)
        self.assertEqual(len(records), expected)
        self.assertEqual(counts["pdf_page_count"], 12)
        self.assertEqual(counts["text_extraction_page_count"], 12)
        self.assertEqual(counts["raw_secret_candidate_count"], expected)
        self.assertEqual(counts["normalized_record_count"], expected)
        self.assertEqual(counts["ui_rendered_record_count"], expected)
        pages = {
            page
            for record in records
            for page in record["provenance"]["page_numbers"]
        }
        self.assertIn(1, pages)
        self.assertIn(6, pages)
        self.assertIn(12, pages)
        self.assertTrue(any(r["record_type"] == "ACCOUNT" for r in records))
        self.assertTrue(any(
            r["record_type"] == "RECOVERY_OR_ACCESS_CODE" for r in records
        ))
        exact = next(
            r for r in records
            if r["service"] == "Synthetic Service P11 R5"
        )
        self.assertEqual(exact["fields"]["password"], "Space kept P11 R5!")
        duplicate_rows = [
            r for r in records
            if r["service"] == "Synthetic Service P1 R1"
            and r["fields"].get("password") == "P1!R1 #Exact"
        ]
        self.assertEqual(len(duplicate_rows), 2)

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

    def test_txt_and_docx_use_the_same_three_candidate_extractor(self):
        txt = main._extract_text_from_bytes(
            "synthetic-three-logins.txt", SYNTHETIC_TEXT.encode("utf-8")
        )
        self.assertEqual(len(extractor.extract_multiple_credentials(txt or "")), 3)

        document = docx.Document()
        for line in SYNTHETIC_TEXT.splitlines():
            document.add_paragraph(line)
        output = io.BytesIO()
        document.save(output)
        docx_text = main._extract_text_from_bytes(
            "synthetic-three-logins.docx", output.getvalue()
        )
        self.assertEqual(
            len(extractor.extract_multiple_credentials(docx_text or "")), 3
        )

    def test_ocr_populated_image_text_uses_owner_review(self):
        with patch.object(
            main,
            "_load_one_file_for_analysis",
            return_value={
                "id": "image-synthetic",
                "file_name": "synthetic-three-logins.png",
                "saved_name": None,
                "relative_path": None,
                "extracted_text": SYNTHETIC_TEXT,
            },
        ):
            envelope = main._handle_extract_logins_from_file(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                asset_name=None,
                file_id="image-synthetic",
            )
        payload = json.loads(envelope)
        self.assertEqual(payload["count"], 3)
        self.assertTrue(
            all(record["password_present"] for record in payload["records"])
        )
        self.assertEqual(
            payload["records"][0]["fields"]["password"],
            "Alpha-Secret-1",
        )

    def test_review_envelope_exposes_exact_values_only_in_encrypted_payload(self):
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
        payload = json.loads(envelope)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len({row["candidate_id"] for row in payload["records"]}), 3)
        self.assertTrue(all(row["password_present"] for row in payload["records"]))
        self.assertEqual(
            payload["records"][0]["fields"]["password"],
            "Alpha-Secret-1",
        )
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
        ), patch.object(
            main,
            "_save_extracted_secret_batch",
            side_effect=lambda vault_id, payloads, key: (
                saved.extend(payloads) or (len(payloads), 0, 0, 0)
            ),
        ) as batch_mock:
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
        batch_mock.assert_called_once_with(
            "vault-synthetic", [records[0], records[2]], b"k" * 32,
        )
        self.assertIn("Saved 2 selected", reply)
        self.assertIn("No unselected candidates were saved", reply)

    def test_bulk_save_uses_one_transaction_and_defers_metadata_enrichment(self):
        source = inspect.getsource(main._save_extracted_secret_batch)
        self.assertEqual(source.count("conn = get_db()"), 1)
        self.assertEqual(source.count("conn.commit()"), 1)
        self.assertIn("cursor.executemany", source)
        self.assertIn("_schedule_bulk_secure_postprocessing", source)
        self.assertNotIn("save_secret_tool(", source)

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
        ), patch.object(main, "_peek_existing_secret_fields", return_value={}), patch.object(
            main,
            "save_secret_tool",
            side_effect=lambda vault_id, payload, key, **_kwargs: saved.append(payload),
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
            "_peek_existing_secret_fields",
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
            "I couldn't identify any supported secure records in this file. "
            "Nothing was saved.",
        )


if __name__ == "__main__":
    unittest.main()
