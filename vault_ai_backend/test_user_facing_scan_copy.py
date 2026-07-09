

from __future__ import annotations

import json
import unittest
from unittest import mock

from vault_deep_answer import (
    STAGE_LABELS,
    progress_message,
    build_coverage_report,
    reset_jobs_for_tests,
)


_FORBIDDEN_INTERNAL = (
    "Deep Answer Mode",
    "deep answer",
    "Deep Answer",
)


def _assert_no_internal_names(text: str, ctx: str) -> None:


    lowered = text.lower()
    for forbidden in _FORBIDDEN_INTERNAL:
        if forbidden.lower() in lowered:
            raise AssertionError(
                f"{ctx} carried internal name {forbidden!r}: {text!r}"
            )


class StageLabelCopyTests(unittest.TestCase):


    def test_text_extraction_label_is_friendly(self):
                                                             
                          
        self.assertEqual(STAGE_LABELS["text_extraction"], "Reading files")

    def test_ocr_label_is_friendly(self):
        self.assertEqual(STAGE_LABELS["ocr"], "Checking images")

    def test_archive_indexing_label_is_friendly(self):
        self.assertEqual(
            STAGE_LABELS["archive_indexing"], "Inspecting archives",
        )

    def test_understanding_label_is_friendly(self):
                                                                 
                                           
        self.assertEqual(
            STAGE_LABELS["file_understanding"],
            "Reviewing scanned content",
        )

    def test_embedding_label_is_friendly(self):
                                                              
                                             
        self.assertEqual(
            STAGE_LABELS["file_embedding"], "Preparing results",
        )

    def test_no_raw_enum_keys_leak_to_label_values(self):
                                                                    
                                                             
        for stage, label in STAGE_LABELS.items():
            self.assertNotIn(
                "_", label,
                f"stage {stage!r} surfaced a tech key in label "
                f"{label!r}",
            )

    def test_no_stage_label_carries_internal_names(self):
        for stage, label in STAGE_LABELS.items():
            _assert_no_internal_names(label, f"STAGE_LABELS[{stage!r}]")


class ProgressMessageHonestyTests(unittest.TestCase):


    def test_zero_scanned_with_pending_says_preparing(self):
        msg = progress_message(
            build_coverage_report({
                "total": 425, "analyzed": 0, "pending": 425,
            }),
            intent="search_files_for_credentials",
        )
        self.assertIn("Preparing scan", msg)
                                           
        self.assertNotIn("0 of 425", msg)
        self.assertNotIn("Scan complete", msg)
        _assert_no_internal_names(msg, "progress_message zero")

    def test_mid_scan_says_n_of_total_read(self):
        msg = progress_message(
            build_coverage_report({
                "total": 425, "analyzed": 12, "pending": 410,
                "processing": 3,
            }),
            intent="search_files_for_credentials",
            stage_label="Reading files",
        )
        self.assertIn("12 of 425", msg)
        self.assertIn("Reading files", msg)
        _assert_no_internal_names(msg, "progress_message mid")

    def test_scan_complete_says_preparing_results(self):
        msg = progress_message(
            build_coverage_report({"total": 425, "analyzed": 425}),
            intent="search_files_for_credentials",
        )
        self.assertIn("I scanned 425 files", msg)
        self.assertIn("Preparing results", msg)
        _assert_no_internal_names(msg, "progress_message complete")


class DeepAnswerGatingMessageCopyTests(unittest.TestCase):


    def setUp(self):
        reset_jobs_for_tests()

    def _stub_coverage(self, raw: dict):
        return mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value=raw,
        )

    def _stub_drains(self):
        return mock.patch(
            "routes.deep_answer_routes._drain_fns",
            return_value={},
        )

    def _stub_final(self):
        return mock.patch(
            "routes.deep_answer_routes._final_results_fn",
            return_value={
                "envelope": {"type": "credential_files",
                             "files": [],
                             "sections": {"confirmed": [],
                                          "possible": [],
                                          "filename_only": []},
                             "has_content_matches": False},
                "intent": "search_files_for_credentials",
            },
        )

    def test_envelope_message_is_user_friendly(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage(
            {"total": 256, "analyzed": 42, "pending": 200,
             "processing": 14},
        ), self._stub_drains(), self._stub_final():
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-copy",
                intent="search_files_for_credentials",
                query="show me files that have credentials saved in it",
                key=b"k" * 32,
            )
        self.assertIsNotNone(out)
        payload = json.loads(out)
        message = payload["message"]
                                                    
        _assert_no_internal_names(message, "gating envelope message")
                                        
        self.assertIn(
            "Scanning your vault for files that contain saved credentials",
            message,
        )
                                                                
                               
        self.assertNotIn(payload["job_id"], message)

    def test_envelope_message_for_zero_scanned_says_preparing(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage(
            {"total": 425, "analyzed": 0, "pending": 425},
        ), self._stub_drains(), self._stub_final():
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-zero",
                intent="search_files_for_credentials",
                query="",
                key=b"k" * 32,
            )
        self.assertIsNotNone(out)
        payload = json.loads(out)
        self.assertIn("Preparing scan", payload["message"])
        self.assertNotIn("0 of 425", payload["message"])

    def test_envelope_per_intent_headline(self):
                                                                   
                                                                  
        from main import _maybe_build_deep_answer_envelope
        cases = {
            "search_files_for_credentials":
                "files that contain saved credentials",
            "search_files_about": "files about this topic",
            "list_by_tag": "files matching this category",
            "travel_readiness": "travel documents",
        }
        for intent, expected_fragment in cases.items():
            reset_jobs_for_tests()
            with self.subTest(intent=intent), self._stub_coverage(
                {"total": 100, "analyzed": 10, "pending": 90},
            ), self._stub_drains(), self._stub_final():
                out = _maybe_build_deep_answer_envelope(
                    vault_id="v-headline",
                    intent=intent, query="",
                    key=b"k" * 32,
                )
            self.assertIsNotNone(out, f"intent {intent!r}")
            payload = json.loads(out)
            self.assertIn(expected_fragment, payload["message"])


class CredentialReplyHeadlineTests(unittest.TestCase):


    def test_with_scanned_count_prepends_spec_headline(self):
                                                              
                                                            
        from vault_inventory import format_credential_files_reply
        matches = [
            {
                "file_id": "f1", "file_name": "dump1.txt",
                "saved_name": "", "record_count": 5,
                "evidence_source": "file_text",
                "evidence_source_label": "file text",
                "password_present": True,
            },
            {
                "file_id": "f2", "file_name": "dump2.txt",
                "saved_name": "", "record_count": 3,
                "evidence_source": "file_text",
                "evidence_source_label": "file text",
                "password_present": True,
            },
            {
                "file_id": "f3", "file_name": "dump3.txt",
                "saved_name": "", "record_count": 7,
                "evidence_source": "ocr",
                "evidence_source_label": "OCR",
                "password_present": True,
            },
        ]
        text = format_credential_files_reply(
            matches,
            scanned_count=425,
            not_scanned_count=0,
        )
        self.assertIn(
            "I checked 425 files and found 3 files with saved "
            "credential records.",
            text,
        )
                                                                
        self.assertIn("Files with saved credentials:", text)
                                         
        self.assertNotIn("may contain", text.lower())

    def test_singular_match_uses_file_not_files(self):
        from vault_inventory import format_credential_files_reply
        matches = [
            {
                "file_id": "f1", "file_name": "dump.txt",
                "saved_name": "", "record_count": 2,
                "evidence_source": "file_text",
                "evidence_source_label": "file text",
                "password_present": True,
            },
        ]
        text = format_credential_files_reply(
            matches,
            scanned_count=425,
            not_scanned_count=0,
        )
        self.assertIn(
            "I checked 425 files and found 1 file with saved "
            "credential records.",
            text,
        )

    def test_without_scanned_count_uses_softer_headline(self):
                                                                    
                                                               
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1", "file_name": "dump.txt",
                    "saved_name": "", "record_count": 2,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                },
            ],
        )
        self.assertIn(
            "I found 1 file with saved credential records.",
            text,
        )
        self.assertNotIn("I scanned ", text)

    def test_empty_matches_with_scan_uses_strict_empty_copy(self):
                                                                
                                                                 
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply(
            matches=[],
            scanned_count=425,
            not_scanned_count=0,
        )
        self.assertIn(
            "I scanned the readable files and did not find saved "
            "credential records.",
            text,
        )
        self.assertNotIn("may contain", text.lower())
        self.assertNotIn("filename match", text.lower())


if __name__ == "__main__":
    unittest.main()
