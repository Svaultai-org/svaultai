

from __future__ import annotations

import json
import unittest

from vault_inventory import (
    verified_credential_files_report,
    credential_search_diagnostics,
)


def _row(file_name, *, extracted_text=None, content_sha256=None,
         relative_path="", **k):
    return {
        "id":               k.get("file_id") or f"id-{file_name}",
        "file_name":        file_name,
        "saved_name":       k.get("saved_name", ""),
        "relative_path":    relative_path or f"_root/{file_name}",
        "content_type":     k.get("content_type", "text/plain"),
        "mime_type":        k.get("content_type", "text/plain"),
        "asset_type":       k.get("asset_type", "file"),
        "detected_service": k.get("detected_service", ""),
        "detected_type":    k.get("detected_type", ""),
        "extracted_text":   extracted_text,
        "content_sha256":   content_sha256 or f"sha-{file_name}",
        "file_size":        100,
        "created_at":       None,
        "needs_naming":     False,
    }


_FIXTURE_TEXT = """\
Gmail
alice@example.com
hunter2!secret9

American Express
bob@example.com
SunF1ower!Spring9
"""

                                                                     
_FIXTURE_PDF_TEXT = """\
Family Passwords

Gmail
alice@example.com
hunter2!secret9

Wells Fargo
charles@example.com
NorthSt@r!autumn9

Apple ID
dana@example.com
Z9q!Wp$73a99
"""

                                                                  
_FIXTURE_PDF_OCR = """\
SAVED LOGINS — printout, scanned 2023

Service     Netflix
Username    family@example.com
Password    Cr1mson!autumn9

Service     Spotify
Username    music@example.com
Password    LoUdR!ock9plays
"""

                                                                 
_FIXTURE_ARCHIVE = """\
[ARCHIVE INDEX: family-backup.zip]

accounts.txt:
Twitch
gamer@example.com
Aim4thest@rs!9

Discord
chat@example.com
DragonH3ad!s9rv
"""

                                                                    
_FIXTURE_PDF_DUP = _FIXTURE_PDF_TEXT


def _accuracy_rows() -> list[dict]:
    return [
        _row(
            "family-passwords.txt",
            extracted_text=_FIXTURE_TEXT,
            relative_path="Family/Logins/family-passwords.txt",
        ),
        _row(
            "family-passwords.pdf",
            extracted_text=_FIXTURE_PDF_TEXT,
            relative_path="Family/Logins/family-passwords.pdf",
            content_type="application/pdf",
            content_sha256="sha-family-pdf-primary",
        ),
        _row(
            "scanned-logins.pdf",
            extracted_text=_FIXTURE_PDF_OCR,
            relative_path="Family/Logins/Scanned/scanned-logins.pdf",
            content_type="application/pdf",
            asset_type="image",
        ),
        _row(
            "family-backup.zip",
            extracted_text=_FIXTURE_ARCHIVE,
            relative_path="Backups/2023/family-backup.zip",
            content_type="application/zip",
            asset_type="archive",
        ),
                                                              
                                                               
        _row(
            "family-passwords.pdf",
            extracted_text=_FIXTURE_PDF_DUP,
            relative_path="Archive/Old/family-passwords.pdf",
            content_type="application/pdf",
            content_sha256="sha-family-pdf-primary",
            file_id="id-pdf-dup",
        ),
    ]


class AccuracyAuditTests(unittest.TestCase):
    def test_all_five_distinct_credential_files_are_found(self):
        report = verified_credential_files_report(_accuracy_rows())
        names = sorted(m["file_name"] for m in report["matches"])
                                                                
                                                              
        self.assertGreaterEqual(
            len(report["matches"]), 4,
            f"verifier must surface every distinct credential file. "
            f"Got: {names!r}",
        )
        for required in (
            "family-passwords.txt",
            "family-passwords.pdf",
            "scanned-logins.pdf",
            "family-backup.zip",
        ):
            self.assertIn(
                required, names,
                f"required credential file {required!r} missing from "
                f"verified results — accuracy regression. Got: {names!r}",
            )

    def test_pdf_with_selectable_text_is_found(self):
        rows = [_row("family-passwords.pdf",
                     extracted_text=_FIXTURE_PDF_TEXT,
                     content_type="application/pdf",
                     relative_path="Family/family-passwords.pdf")]
        names = [m["file_name"] for m in
                 verified_credential_files_report(rows)["matches"]]
        self.assertIn(
            "family-passwords.pdf", names,
            "PDF with selectable-text credentials must be found",
        )

    def test_scanned_pdf_via_ocr_text_is_found(self):
        rows = [_row("scanned-logins.pdf",
                     extracted_text=_FIXTURE_PDF_OCR,
                     content_type="application/pdf",
                     asset_type="image",
                     relative_path="Family/scanned-logins.pdf")]
        names = [m["file_name"] for m in
                 verified_credential_files_report(rows)["matches"]]
        self.assertIn(
            "scanned-logins.pdf", names,
            "Scanned PDF (OCR-extracted labelled-pair text) must be found",
        )

    def test_archive_accounts_txt_is_found(self):
        rows = [_row("family-backup.zip",
                     extracted_text=_FIXTURE_ARCHIVE,
                     content_type="application/zip",
                     asset_type="archive",
                     relative_path="Backups/family-backup.zip")]
        names = [m["file_name"] for m in
                 verified_credential_files_report(rows)["matches"]]
        self.assertIn(
            "family-backup.zip", names,
            "Archive whose inner accounts.txt holds records must be found",
        )

    def test_duplicate_in_another_folder_is_surfaced_not_silently_dropped(self):
                                                             
                                                                 
        report = verified_credential_files_report(_accuracy_rows())
        pdf_rows = [m for m in report["matches"]
                    if m["file_name"] == "family-passwords.pdf"]
        self.assertEqual(
            len(pdf_rows), 1,
            "byte-identical duplicates collapse to one row + the "
            "duplicate is surfaced via duplicate_paths",
        )
        survivor = pdf_rows[0]
                                                                  
                                          
        self.assertTrue(
            survivor["duplicate_paths"],
            "duplicate copy must NOT be silently collapsed — "
            "duplicate_paths must surface the second folder",
        )
        joined = " ".join(survivor["duplicate_paths"])
        self.assertIn("Archive/Old", joined)


class NoFilenameOnlyResultsTests(unittest.TestCase):
    def test_filename_only_match_is_NOT_shown(self):
                                                                  
                                                                   
        rows = _accuracy_rows() + [
            _row(
                "passwords.txt",
                extracted_text="",
                relative_path="Misc/passwords.txt",
            ),
            _row(
                "login.js",
                extracted_text="export function loginForm(){}",
                relative_path="Code/login.js",
            ),
        ]
        names = [m["file_name"] for m in
                 verified_credential_files_report(rows)["matches"]]
        self.assertNotIn(
            "passwords.txt", names,
            "filename-only match must NOT appear in verified results",
        )
        self.assertNotIn(
            "login.js", names,
            "code source must NOT appear in verified results",
        )


class FinalAnswerCountConsistencyTests(unittest.TestCase):
    def test_final_count_matches_verified_files_when_coverage_complete(self):
                                                               
                                                             
        rows = _accuracy_rows()
        coverage = {
            "total": len(rows), "scanned": len(rows),
            "pending": 0, "processing": 0,
            "unsupported": 0, "failed": 0,
            "scan_complete": True,
        }
        report = verified_credential_files_report(
            rows, coverage=coverage,
        )
        n = len(report["matches"])
                                         
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply(
            report["matches"],
            scanned_count=report["scanned_count"],
            not_scanned_count=report["not_scanned_count"],
            is_partial=report["is_partial"],
        )
                                                                  
        self.assertIn(
            f"and found {n} file"
            f"{'s' if n != 1 else ''} with saved credential records.",
            text,
            "headline count must equal verified count when coverage "
            "is complete",
        )
        self.assertFalse(report["is_partial"])


class AccuracyAuditEnvelopeShapeTests(unittest.TestCase):
    def test_envelope_carries_required_sections(self):
        diag = credential_search_diagnostics(_accuracy_rows())
                                                    
        for k in (
            "totals",
            "excluded_by_reason",
            "per_folder",
            "per_file",
            "duplicate_groups",
        ):
            self.assertIn(k, diag, f"missing section: {k!r}")
                                           
        self.assertEqual(diag["totals"]["input_files"], 5)
                                                                  
                                                                  
        legal_keys = {
            "no_text", "filename_only", "form_like",
            "no_secret_value", "no_identifier",
            "no_service_context", "verifier_rejected",
            "duplicate_collapsed", "unsupported",
            "ocr_needed", "failed_extraction",
            "folder_not_scanned",
        }
        for k in diag["excluded_by_reason"]:
            self.assertIn(
                k, legal_keys,
                f"unexpected exclusion key: {k!r}",
            )

    def test_per_folder_has_folder_total_scanned_candidates_verified(self):
        diag = credential_search_diagnostics(_accuracy_rows())
        for entry in diag["per_folder"]:
            for k in (
                "folder",
                "total_files",
                "scanned_files",
                "credential_candidates",
                "verified_credential_files",
            ):
                self.assertIn(k, entry, f"per_folder row missing: {k!r}")

    def test_per_file_has_full_verdict_surface(self):
        diag = credential_search_diagnostics(_accuracy_rows())
                                                          
        names = [f["file_name"] for f in diag["per_file"]]
        for required in (
            "family-passwords.txt",
            "family-passwords.pdf",
            "scanned-logins.pdf",
            "family-backup.zip",
        ):
            self.assertIn(required, names)
                                                   
        for f in diag["per_file"]:
            for k in (
                "file_id", "file_name", "relative_path",
                "extraction_source", "text_available",
                "record_count", "verifier_passed",
                "reject_reason", "duplicate_of",
            ):
                self.assertIn(k, f, f"per_file row missing: {k!r}")

    def test_per_file_records_duplicate_of_for_collapsed_copy(self):
        diag = credential_search_diagnostics(_accuracy_rows())
                                                               
                                                                
        dup_paths = []
        for f in diag["per_file"]:
            if f["file_name"] == "family-passwords.pdf":
                if f["duplicate_of"]:
                    dup_paths.append(f["duplicate_of"])
        self.assertTrue(
            dup_paths,
            "per_file must record duplicate_of for the collapsed "
            "credential PDF copy",
        )

    def test_envelope_never_carries_credential_values(self):
        diag = credential_search_diagnostics(_accuracy_rows())
        encoded = json.dumps(diag)
        for leak in (
            "hunter2!secret9", "SunF1ower!Spring9",
            "NorthSt@r!autumn9", "Z9q!Wp$73a99",
            "Cr1mson!autumn9", "LoUdR!ock9plays",
            "Aim4thest@rs!9", "DragonH3ad!s9rv",
            "alice@example.com", "bob@example.com",
            "charles@example.com", "dana@example.com",
            "family@example.com", "music@example.com",
            "gamer@example.com", "chat@example.com",
        ):
            self.assertNotIn(
                leak, encoded,
                f"accuracy-audit envelope leaked credential value: "
                f"{leak!r}",
            )


if __name__ == "__main__":
    unittest.main()
