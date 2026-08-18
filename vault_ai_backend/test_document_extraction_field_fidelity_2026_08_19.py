from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

import extractor
import main
import vault_chat_card_data
from secure_document_extractor import extract_secure_records


SYNTHETIC_FIDELITY_TEXT = """[[SVAULTAI_PAGE:1]]
[[SVAULTAI_RECORD:p1-r1]]
Ebay
email=test@example.com
password=ExactPass!123
[[SVAULTAI_RECORD:p1-r2]]
Comcast
user_id=test-user-001
password=ExactPass!456
[[SVAULTAI_RECORD:p1-r3]]
Bank
account_number=123456789
pin=2468
password=ExactPass!789
[[SVAULTAI_RECORD:p1-r4]]
Portal
username=userA
email=userA@example.com
password=ExactPass!ABC
url=https://example.invalid
[[SVAULTAI_RECORD:p1-r5]]
Mixed
login_id=member55
secure_value=alpha-beta
pin=9988
password=ExactPass!XYZ"""


EXPECTED_FIELDS = {
    "Ebay": {
        "email": "test@example.com",
        "password": "ExactPass!123",
    },
    "Comcast": {
        "user_id": "test-user-001",
        "password": "ExactPass!456",
    },
    "Bank": {
        "account_number": "123456789",
        "pin": "2468",
        "password": "ExactPass!789",
    },
    "Portal": {
        "username": "userA",
        "email": "userA@example.com",
        "password": "ExactPass!ABC",
        "url": "https://example.invalid",
    },
    "Mixed": {
        "login_id": "member55",
        "secure_value": "alpha-beta",
        "pin": "9988",
        "password": "ExactPass!XYZ",
    },
}


def _records() -> list[dict]:
    return extract_secure_records(SYNTHETIC_FIDELITY_TEXT)


def _review_state() -> tuple[dict, list[dict]]:
    envelope = main._build_credential_extraction_review_envelope(
        file_id="synthetic-fidelity-file",
        file_name="synthetic-field-fidelity.pdf",
        saved_name=None,
        relative_path=None,
        records=_records(),
        message="Review",
        text_available=True,
    )
    memory: dict = {}
    main._remember_credential_extraction_review(memory, envelope)
    return (
        memory[main._PENDING_CREDENTIAL_EXTRACTION_KEY],
        json.loads(envelope)["records"],
    )


def _file_row() -> dict:
    return {
        "id": "synthetic-fidelity-file",
        "file_name": "synthetic-field-fidelity.pdf",
        "saved_name": None,
        "relative_path": None,
        "extracted_text": SYNTHETIC_FIDELITY_TEXT,
    }


class DocumentExtractionFieldFidelityTests(unittest.TestCase):
    def test_plain_text_aliases_keep_semantic_types_and_exact_case(self):
        extracted = extractor.extract_credentials(
            "Service\n"
            "Email=CaseSensitive.User@Example.COM\n"
            "User_ID=test-user-001\n"
            "Login-ID=member55\n"
            "Account_ID=account-77\n"
            "Account_Number=123456789\n"
            "Secure_Value=alpha-beta\n"
            "Password=ExactPass!123"
        )
        self.assertEqual(extracted["email"], "CaseSensitive.User@Example.COM")
        self.assertEqual(extracted["user_id"], "test-user-001")
        self.assertEqual(extracted["login_id"], "member55")
        self.assertEqual(extracted["account_id"], "account-77")
        self.assertEqual(extracted["account_number"], "123456789")
        self.assertEqual(extracted["secure_value"], "alpha-beta")
        self.assertEqual(extracted["password"], "ExactPass!123")

    def test_extraction_review_preserves_every_typed_field_exactly(self):
        records = _records()
        self.assertEqual(len(records), 5)
        self.assertTrue(all(row["secret_type"] == "login" for row in records))
        self.assertEqual(
            {row["service"]: row["fields"] for row in records},
            EXPECTED_FIELDS,
        )

        _pending, safe_records = _review_state()
        self.assertEqual(
            {row["service"]: row["fields"] for row in safe_records},
            EXPECTED_FIELDS,
        )
        identifier_types = {
            row["service"]: row["login_identifier_type"]
            for row in safe_records
        }
        self.assertEqual(identifier_types["Ebay"], "email")
        self.assertEqual(identifier_types["Comcast"], "user_id")
        self.assertEqual(identifier_types["Portal"], "username")
        self.assertEqual(identifier_types["Mixed"], "login_id")

    def test_save_one_and_save_selected_keep_the_same_complete_records(self):
        records = _records()
        pending, safe_records = _review_state()
        captured_one: list[dict] = []

        with patch.object(
            main, "_load_one_file_for_analysis", return_value=_file_row()
        ), patch.object(
            main, "_peek_existing_secret_fields", return_value={}
        ), patch.object(
            main,
            "save_secret_tool",
            side_effect=lambda _vault, payload, _key, **_kwargs: (
                captured_one.append(payload)
            ),
        ):
            for safe in safe_records:
                reply = main._handle_credential_extraction_action(
                    vault_id="vault-synthetic",
                    key=b"k" * 32,
                    pending=pending,
                    action={
                        "action": "save",
                        "candidate_ids": [safe["candidate_id"]],
                        "overrides": {},
                    },
                )
                self.assertIn("Saved 1 selected", reply)

        captured_selected: list[dict] = []
        with patch.object(
            main, "_load_one_file_for_analysis", return_value=_file_row()
        ), patch.object(
            main,
            "_save_extracted_secret_batch",
            side_effect=lambda _vault, payloads, _key: (
                captured_selected.extend(payloads)
                or (len(payloads), 0, 0, 0)
            ),
        ):
            reply = main._handle_credential_extraction_action(
                vault_id="vault-synthetic",
                key=b"k" * 32,
                pending=pending,
                action={
                    "action": "save_selected",
                    "candidate_ids": [
                        row["candidate_id"] for row in safe_records
                    ],
                    "overrides": {},
                },
            )
        self.assertIn("Saved 5 selected", reply)
        self.assertEqual(captured_one, records)
        self.assertEqual(captured_selected, records)

    def test_single_and_bulk_storage_share_full_fidelity_envelope(self):
        single_source = inspect.getsource(main.save_secret_tool)
        bulk_source = inspect.getsource(main._save_extracted_secret_batch)
        self.assertIn("_build_secure_record_storage_envelope", single_source)
        self.assertIn("_build_secure_record_storage_envelope", bulk_source)

        key = b"f" * 32
        for record in _records():
            envelope = main._build_secure_record_storage_envelope(
                secret_type=record["secret_type"],
                record_type=record["record_type"],
                service=record["service"],
                fields=record["fields"],
                provenance=record["provenance"],
            )
            encrypted = main.encrypt_message(
                json.dumps(envelope, ensure_ascii=False), key
            )
            self.assertEqual(
                main._decode_encrypted_secret_fields(encrypted, key),
                EXPECTED_FIELDS[record["service"]],
            )
            decrypted = json.loads(main.decrypt_message(encrypted, key))
            self.assertEqual(decrypted["schema"], "secure_record_v1")
            self.assertEqual(decrypted["record_type"], "LOGIN")
            self.assertEqual(
                decrypted["fields"], EXPECTED_FIELDS[record["service"]]
            )
            self.assertEqual(
                decrypted["provenance"]["source_ref"],
                record["provenance"]["source_ref"],
            )

    def test_chat_retrieval_projects_alias_and_custom_fields_without_loss(self):
        expected_labels = {
            "Ebay": {"Email", "Password"},
            "Comcast": {"User ID", "Password"},
            "Bank": {"Account number", "pin", "Password"},
            "Portal": {"Username", "Email", "Password", "Website or URL"},
            "Mixed": {"Login ID", "Secure value", "pin", "Password"},
        }
        expected_identifier_types = {
            "Ebay": "email",
            "Comcast": "user_id",
            "Bank": "",
            "Portal": "username",
            "Mixed": "login_id",
        }
        key = b"r" * 32
        for index, record in enumerate(_records(), 1):
            envelope = main._build_secure_record_storage_envelope(
                secret_type=record["secret_type"],
                record_type=record["record_type"],
                service=record["service"],
                fields=record["fields"],
                provenance=record["provenance"],
            )
            encrypted = main.encrypt_message(json.dumps(envelope), key)
            detail = vault_chat_card_data._project_login_row_detail(
                {
                    "id": index,
                    "service": record["service"],
                    "encrypted_data": encrypted,
                },
                key,
            )
            self.assertEqual(
                detail["identifier_type"],
                expected_identifier_types[record["service"]],
            )
            rendered_fields = {
                item["label"]: item["value"] for item in detail["fields"]
            }
            self.assertEqual(
                set(rendered_fields), expected_labels[record["service"]]
            )
            self.assertEqual(
                set(rendered_fields.values()),
                set(EXPECTED_FIELDS[record["service"]].values()),
            )


if __name__ == "__main__":
    unittest.main()
