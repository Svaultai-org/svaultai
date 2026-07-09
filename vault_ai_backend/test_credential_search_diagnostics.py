

from __future__ import annotations

import json
import unittest

from vault_inventory import (
    verified_credential_files_report,
    format_credential_files_reply,
    credential_search_diagnostics,
    search_files_for_credentials_report,
    VERIFIER_REJECT_REASONS,
    _classify_credential_reject_reason,
)
from main import _build_credential_files_envelope


def _row(file_name, *, extracted_text=None, content_sha256=None,
         relative_path="", **k):
    return {
        "id":                k.get("file_id") or f"id-{file_name}",
        "file_name":         file_name,
        "saved_name":        k.get("saved_name", ""),
        "relative_path":     relative_path,
        "content_type":      k.get("content_type", "text/plain"),
        "mime_type":         k.get("content_type", "text/plain"),
        "asset_type":        k.get("asset_type", "file"),
        "detected_service":  k.get("detected_service", ""),
        "detected_type":     k.get("detected_type", ""),
        "extracted_text":    extracted_text,
        "content_sha256":    content_sha256 or f"sha-{file_name}",
        "file_size":         100,
        "created_at":        None,
        "needs_naming":      False,
    }


_PWD_MANAGER_DUMP = """\
AOL
person@example.com
MKSherm81765
American Express
sunshine6856
e&t082826
Apple
loul@example.com
Patrick62109
Wells Fargo
jane@example.com
Spr1ng!2024
Gmail
alex@example.com
Z9q!Wp$73a
"""


_BLOCKCHAIN_EXPLORER_LIST = """\
Etherscan
BscScan
Solscan
TronScan
CardanoScan
"""


_FORM_TEXT = """\
Application for residency renewal — Department of State

Applicant name: Maureen Smith
Email address: applicant@example.com

Choose a password of at least 8 characters and submit this form.
"""


class RejectReasonsTests(unittest.TestCase):
    def test_form_like_is_classified_as_rejected_form_like(self):
        rows = [_row("application.pdf", extracted_text=_FORM_TEXT,
                     content_type="application/pdf")]
        loose = search_files_for_credentials_report(rows)["matches"]
        if loose:
            self.assertEqual(
                _classify_credential_reject_reason(loose[0]),
                "rejected_form_like",
            )

    def test_keyword_list_is_classified_as_rejected_keyword_list(self):
        rows = [_row("blockchain.txt", extracted_text=_BLOCKCHAIN_EXPLORER_LIST)]
        loose = search_files_for_credentials_report(rows)["matches"]
        if loose:
            self.assertEqual(
                _classify_credential_reject_reason(loose[0]),
                "rejected_keyword_list",
            )

    def test_password_manager_dump_is_accepted(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        loose = search_files_for_credentials_report(rows)["matches"]
        self.assertEqual(len(loose), 1)
        self.assertIsNone(_classify_credential_reject_reason(loose[0]))

    def test_reject_reasons_are_a_closed_set(self):
                                                                 
                                                           
        for r in VERIFIER_REJECT_REASONS:
            self.assertTrue(r.startswith("rejected_"))
            self.assertIn("_", r)
        expected_subset = {
            "rejected_form_like",
            "rejected_no_extracted_text",
            "rejected_no_secret_value",
            "rejected_no_identifier",
            "rejected_no_service_context",
            "rejected_keyword_list",
            "rejected_filename_only",
            "rejected_no_complete_record",
        }
        self.assertTrue(
            expected_subset.issubset(set(VERIFIER_REJECT_REASONS)),
            "every reason called out by the user spec must be in "
            "the closed set; missing: "
            f"{expected_subset - set(VERIFIER_REJECT_REASONS)}",
        )


class CoverageConsistencyTests(unittest.TestCase):
    def test_threaded_coverage_overrides_loose_counts(self):
                                                                 
                                                                    
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        coverage = {
            "total": 425, "scanned": 194,
            "pending": 200, "processing": 31,
            "unsupported": 0, "failed": 0,
            "scan_complete": False,
        }
        report = verified_credential_files_report(rows, coverage=coverage)
        self.assertEqual(report["scanned_count"], 194)
        self.assertGreaterEqual(report["not_scanned_count"], 231)
        self.assertTrue(report["is_partial"])

    def test_no_coverage_falls_back_to_loose_counts(self):
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
            _row("locked.bin", extracted_text=None),
        ]
        report = verified_credential_files_report(rows)
        self.assertEqual(report["scanned_count"], 1)
        self.assertEqual(report["not_scanned_count"], 1)
        self.assertTrue(report["is_partial"])

    def test_not_scanned_count_is_dynamic(self):
                                                            
                                                                  
        rows_a = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
            _row("a.bin", extracted_text=None),
            _row("b.bin", extracted_text=None),
        ]
        rows_b = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
        ]
        r_a = verified_credential_files_report(rows_a)
        r_b = verified_credential_files_report(rows_b)
        self.assertEqual(r_a["not_scanned_count"], 2)
        self.assertEqual(r_b["not_scanned_count"], 0)


class PartialResultsReplyTests(unittest.TestCase):
    def test_partial_headline_is_spec_verbatim(self):
                                                                    
                                                        
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1", "file_name": "dump.txt",
                    "saved_name": "", "record_count": 4,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                }
            ],
            scanned_count=194,
            not_scanned_count=231,
            is_partial=True,
        )
        self.assertIn(
            "I checked 194 of 425 files. 231 still need extraction/OCR. "
            "These results are incomplete.",
            text,
        )
        self.assertIn(
            "Partial results from already scanned files:",
            text,
        )

    def test_full_scan_uses_complete_headline(self):
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1", "file_name": "dump.txt",
                    "saved_name": "", "record_count": 4,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                }
            ],
            scanned_count=425,
            not_scanned_count=0,
            is_partial=False,
        )
        self.assertIn(
            "I checked 425 files and found 1 file with saved "
            "credential records.",
            text,
        )
        self.assertIn("Files with saved credentials:", text)
        self.assertNotIn("incomplete", text)


class EnvelopeIsPartialTests(unittest.TestCase):
    def test_envelope_carries_is_partial_true(self):
        env = json.loads(_build_credential_files_envelope(
            matches=[],
            message="x",
            scanned_count=194,
            not_scanned_count=231,
            is_partial=True,
        ))
        self.assertTrue(env["is_partial"])

    def test_envelope_carries_is_partial_false_when_full(self):
        env = json.loads(_build_credential_files_envelope(
            matches=[],
            message="x",
            scanned_count=425,
            not_scanned_count=0,
            is_partial=False,
        ))
        self.assertFalse(env["is_partial"])


class DuplicateHandlingTests(unittest.TestCase):
    def test_duplicate_paths_are_surfaced_on_surviving_row(self):
                                                                  
                                                                
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Family/2023/dump.txt",
                 content_sha256="sha-shared"),
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Backups/Old/dump.txt",
                 content_sha256="sha-shared",
                 file_id="id-dump-2"),
        ]
        report = verified_credential_files_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        survivor = report["matches"][0]
        self.assertEqual(
            sorted(survivor["duplicate_paths"]),
            sorted(["Backups/Old/dump.txt"]),
        )

    def test_duplicate_paths_empty_when_no_duplicates(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = verified_credential_files_report(rows)
        self.assertEqual(report["matches"][0]["duplicate_paths"], [])

    def test_different_content_in_same_name_is_not_collapsed(self):
                                                                   
                                                                   
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Family",
                 content_sha256="sha-a"),
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Backups",
                 content_sha256="sha-b",
                 file_id="id-dump-2"),
        ]
        report = verified_credential_files_report(rows)
        self.assertEqual(len(report["matches"]), 2)


class CredentialSearchDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_envelope_has_required_top_level_keys(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        diag = credential_search_diagnostics(rows)
        self.assertIn("totals", diag)
        self.assertIn("by_folder", diag)
        self.assertIn("duplicate_groups", diag)
        for k in (
            "input_files", "loose_candidates", "verified",
            "rejected", "rejected_by_reason",
            "missing_extracted_text", "duplicate_groups",
        ):
            self.assertIn(k, diag["totals"])

    def test_diagnostics_breaks_down_per_folder(self):
                                                                    
                                                                     
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Family/Logins/2023/dump.txt"),
            _row("blockchain.txt",
                 extracted_text=_BLOCKCHAIN_EXPLORER_LIST,
                 relative_path="Family/Crypto/blockchain.txt"),
            _row("login.js",
                 extracted_text="export function f(){}",
                 relative_path="Code/Web/login.js"),
            _row("locked.bin",
                 extracted_text=None,
                 relative_path="Code/Web/locked.bin"),
        ]
        diag = credential_search_diagnostics(rows)
        folders = {b["folder"]: b for b in diag["by_folder"]}
        self.assertIn("Family/Logins/2023", folders)
        self.assertIn("Family/Crypto", folders)
        self.assertIn("Code/Web", folders)
                                                                   
        self.assertEqual(folders["Family/Logins/2023"]["verified"], 1)
                                                                   
                             
        code_reasons = folders["Code/Web"]["rejected_by_reason"]
        self.assertIn("rejected_no_extracted_text", code_reasons)

    def test_diagnostics_identifies_keyword_list_rejection(self):
        rows = [_row("blockchain.txt",
                     extracted_text=_BLOCKCHAIN_EXPLORER_LIST,
                     relative_path="A/B/blockchain.txt")]
        diag = credential_search_diagnostics(rows)
        reasons = diag["totals"]["rejected_by_reason"]
                                                                    
                                                                  
        self.assertTrue(
            "rejected_keyword_list" in reasons
            or "rejected_filename_only" in reasons,
            f"diagnostics must explain the rejection: {reasons!r}",
        )

    def test_diagnostics_surfaces_duplicate_groups(self):
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Family/dump.txt",
                 content_sha256="sha-shared"),
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Backups/dump.txt",
                 content_sha256="sha-shared",
                 file_id="id-dump-2"),
        ]
        diag = credential_search_diagnostics(rows)
        self.assertEqual(diag["totals"]["duplicate_groups"], 1)
        group = diag["duplicate_groups"][0]
        self.assertEqual(group["file_name"], "dump.txt")
        self.assertIn("Family/dump.txt", group["paths"])
        self.assertIn("Backups/dump.txt", group["paths"])

    def test_diagnostics_never_carries_credential_values(self):
                                                              
                                                                    
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                 relative_path="Family/Logins/dump.txt"),
        ]
        diag = credential_search_diagnostics(rows)
        encoded = json.dumps(diag)
        for leaked in (
            "MKSherm81765", "sunshine6856", "e&t082826",
            "Patrick62109", "Spr1ng!2024", "Z9q!Wp$73a",
            "person@example.com", "loul@example.com",
            "jane@example.com", "alex@example.com",
        ):
            self.assertNotIn(
                leaked, encoded,
                f"diagnostics leaked credential value: {leaked!r}",
            )

    def test_diagnostics_per_candidate_carries_safe_surface(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP,
                     relative_path="Family/Logins/dump.txt")]
        diag = credential_search_diagnostics(rows)
        folder = next(b for b in diag["by_folder"]
                      if b["folder"] == "Family/Logins")
        cand = folder["candidates"][0]
        for k in (
            "file_id", "file_name", "saved_name", "relative_path",
            "verdict", "complete_record_count", "labelled_pair_count",
            "has_credential_value", "purpose", "duplicate_paths",
        ):
            self.assertIn(k, cand)
        self.assertNotIn("extracted_text", cand)
        self.assertNotIn("password", cand)
        self.assertEqual(cand["verdict"], "accepted")


if __name__ == "__main__":
    unittest.main()
