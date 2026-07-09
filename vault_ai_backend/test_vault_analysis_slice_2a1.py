

from __future__ import annotations

import inspect
import json
import unittest


_REGRESSION_FIXTURE_TEXT = (
    "AOL\n"
    "person@example.com\n"
    "MKSherm81765\n"
    "American Express\n"
    "sunshine6856\n"
    "e&t082826\n"
    "Apple\n"
    "loul@example.com\n"
    "Patrick62109\n"
)


class RepeatedCredentialRecordsDetectorTests(unittest.TestCase):
    def test_harmless_filename_with_repeated_records_is_strong(self):
        from vault_inventory import (
            search_files_for_credentials_report,
            CREDENTIAL_CONFIDENCE_STRONG,
        )
        rows = [
            {
                "id": "f1",
                "file_name": "harmless-name.pdf",
                "saved_name": "",
                "relative_path": "",
                "content_type": "application/pdf",
                "file_size": 1024,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": _REGRESSION_FIXTURE_TEXT,
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(
            report["matches"][0]["confidence"],
            CREDENTIAL_CONFIDENCE_STRONG,
            "a harmless-named file containing repeated "
            "service/email/password-like blocks MUST surface as STRONG",
        )

    def test_repeated_records_reason_is_spec_verbatim(self):
        from vault_inventory import search_files_for_credentials_report
        rows = [
            {
                "id": "f1",
                "file_name": "harmless-name.pdf",
                "saved_name": "",
                "relative_path": "",
                "content_type": "application/pdf",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": _REGRESSION_FIXTURE_TEXT,
            },
        ]
        report = search_files_for_credentials_report(rows)
        reasons = " · ".join(report["matches"][0]["reasons"])
                               
        self.assertIn(
            "content contains repeated service/email/password-like "
            "credential records",
            reasons,
        )

    def test_no_password_values_in_response(self):
                                                                
                                                            
        from vault_inventory import search_files_for_credentials_report
        rows = [
            {
                "id": "f1",
                "file_name": "harmless-name.pdf",
                "saved_name": "",
                "relative_path": "",
                "content_type": "application/pdf",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": _REGRESSION_FIXTURE_TEXT,
            },
        ]
        report = search_files_for_credentials_report(rows)
        wire = json.dumps(report)
        for secret in (
            "MKSherm81765", "sunshine6856", "e&t082826", "Patrick62109",
            "person@example.com", "loul@example.com",
        ):
            self.assertNotIn(
                secret, wire,
                f"credential search response MUST NOT echo {secret!r}",
            )

    def test_two_blocks_only_yields_medium_not_strong(self):
                                                                
                                                        
        from vault_inventory import (
            search_files_for_credentials_report,
            CREDENTIAL_CONFIDENCE_MEDIUM,
            CREDENTIAL_CONFIDENCE_STRONG,
        )
        rows = [
            {
                "id": "f1",
                "file_name": "notes.txt",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/plain",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": (
                    "AOL\n"
                    "person@example.com\n"
                    "MKSherm81765\n"
                    "Apple\n"
                    "loul@example.com\n"
                    "Patrick62109\n"
                ),
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertIn(
            report["matches"][0]["confidence"],
            (CREDENTIAL_CONFIDENCE_MEDIUM, CREDENTIAL_CONFIDENCE_STRONG),
        )

    def test_prose_with_words_is_not_a_repeated_block(self):
                                                                
                                                                
        from vault_inventory import _count_repeated_credential_blocks
        prose = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n"
            "Sed do eiusmod tempor incididunt ut labore et dolore "
            "magna aliqua.\n"
            "Ut enim ad minim veniam, quis nostrud exercitation "
            "ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
        )
        blocks = _count_repeated_credential_blocks(prose)
        self.assertEqual(blocks, 0)

    def test_empty_extracted_text_yields_zero_blocks(self):
        from vault_inventory import _count_repeated_credential_blocks
        self.assertEqual(_count_repeated_credential_blocks(""), 0)
        self.assertEqual(_count_repeated_credential_blocks(None), 0)


class FormatterStrictVerifierTests(unittest.TestCase):


    def test_only_filename_matches_now_renders_strict_empty_state(self):
                                                                  
                                                                 
        from vault_inventory import (
            format_credential_files_reply,
            verified_credential_files_report,
        )
        rows = [
            {
                "id":              "f1",
                "file_name":       "loginatt.html",
                "saved_name":      "",
                "relative_path":   "",
                "content_type":    "text/html",
                "mime_type":       "text/html",
                "asset_type":      "file",
                "extracted_text":  "<html>hi</html>",
                "content_sha256":  "sha-1",
                "file_size":       100,
                "created_at":      None,
                "needs_naming":    False,
            },
        ]
        report = verified_credential_files_report(rows)
                                                 
        self.assertEqual(len(report["matches"]), 0)
        text = format_credential_files_reply(
            [],
            scanned_count=report["scanned_count"],
            not_scanned_count=231,
        )
        self.assertIn(
            "I scanned the readable files and did not find saved "
            "credential records.",
            text,
        )
        self.assertIn("231 file", text)
                                                          
        self.assertNotIn("I only found filename matches", text)

    def test_strict_verifier_drops_filename_only_keeps_verified(self):
                                                                     
                                                                  
        from vault_inventory import verified_credential_files_report
        rows = [
                                                                 
            {
                "id":              "verified",
                "file_name":       "harmless-name.pdf",
                "saved_name":      "",
                "relative_path":   "",
                "content_type":    "application/pdf",
                "mime_type":       "application/pdf",
                "asset_type":      "file",
                "detected_service": "",
                "extracted_text":  _REGRESSION_FIXTURE_TEXT,
                "content_sha256":  "sha-verified",
                "file_size":       1,
                "created_at":      None,
                "needs_naming":    False,
            },
                                             
            {
                "id":              "fname",
                "file_name":       "loginatt.html",
                "saved_name":      "",
                "relative_path":   "",
                "content_type":    "text/html",
                "mime_type":       "text/html",
                "asset_type":      "file",
                "detected_service": "",
                "extracted_text":  "<html>hi</html>",
                "content_sha256":  "sha-fname",
                "file_size":       1,
                "created_at":      None,
                "needs_naming":    False,
            },
        ]
        report = verified_credential_files_report(rows)
        names = [m["file_name"] for m in report["matches"]]
        self.assertIn("harmless-name.pdf", names)
        self.assertNotIn("loginatt.html", names)


class StrongRanksAboveWeakTests(unittest.TestCase):
    def test_strong_content_appears_before_weak_filename(self):
        from vault_inventory import search_files_for_credentials_report
        rows = [
                                                                  
                                       
            {
                "id": "weak1",
                "file_name": "loginatt.html",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/html",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": None,
            },
                                                                   
            {
                "id": "strong1",
                "file_name": "harmless-name.pdf",
                "saved_name": "",
                "relative_path": "",
                "content_type": "application/pdf",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": _REGRESSION_FIXTURE_TEXT,
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "strong1")
        self.assertEqual(report["matches"][1]["file_id"], "weak1")


class ChunkedDecryptPathTests(unittest.TestCase):
    def test_drain_no_longer_marks_chunked_as_unsupported(self):
                                                                
                                                                    
        import vault_analysis_worker as worker
        src = inspect.getsource(worker)
        self.assertNotIn(
            'chunked storage not supported by this drain', src,
            "drain must no longer reject chunked rows — slice 2A.1 "
            "added the streaming decrypt path",
        )

    def test_drain_streams_chunks_via_chunked_aead(self):
        import vault_analysis_worker as worker
        src = inspect.getsource(worker)
        self.assertIn(
            "from chunked_aead import decrypt_chunk", src,
            "chunked decrypt path must use the per-chunk AEAD "
            "helper (not the legacy AES-GCM single-blob helper)",
        )
                                                        
        self.assertIn(
            "ORDER BY chunk_index ASC", src,
            "chunked bytes MUST be re-assembled in chunk-index order",
        )

    def test_drain_handles_both_chunks_and_chunked_storage_modes(self):
                                                                
                                                       
        import vault_analysis_worker as worker
        src = inspect.getsource(worker)
        self.assertIn('"chunks", "chunked"', src)

    def test_drain_caps_chunked_plaintext_total_bytes(self):
                                                                   
                                                          
        import vault_analysis_worker as worker
        self.assertGreater(
            worker._CHUNKED_FILE_PLAINTEXT_CAP, 0,
        )
                                                               
        self.assertLessEqual(
            worker._CHUNKED_FILE_PLAINTEXT_CAP, 10_000_000,
        )


class VaultAnalysisAdminRoutesTests(unittest.TestCase):
    def test_routes_are_registered_in_main(self):
                                                                 
                                                             
        path = "main.py"
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn(
            "from routes.vault_analysis_admin_routes import", src,
        )
        self.assertIn(
            "app.include_router(vault_analysis_admin_router)", src,
        )

    def test_coverage_endpoint_exists_and_is_pin_protected(self):
        from routes import vault_analysis_admin_routes as admin
        src = inspect.getsource(admin)
        self.assertIn('"/vault-analysis/coverage"', src)
                                                                 
                      
        self.assertIn("verify_trusted_device", src)
        self.assertIn("get_verified_vault_key", src)

    def test_drain_endpoint_exists_and_is_pin_protected(self):
        from routes import vault_analysis_admin_routes as admin
        src = inspect.getsource(admin)
        self.assertIn(
            '"/vault-analysis/drain-text-extraction"', src,
        )
        self.assertIn("get_verified_vault_key", src)

    def test_drain_endpoint_caps_max_jobs(self):
                                                              
        from routes import vault_analysis_admin_routes as admin
        src = inspect.getsource(admin.vault_analysis_drain_text_extraction)
        self.assertIn("if max_jobs > 1000", src)

    def test_coverage_response_does_not_leak_extracted_text(self):
                                                                 
                                                                
        from routes import vault_analysis_admin_routes as admin
        src = inspect.getsource(admin._list_recent_files_with_analysis_state)
                                                                
                 
        self.assertNotIn("extracted_text ", src.replace("extracted_text_", ""))


class EndToEndSliceRegressionTests(unittest.TestCase):
    def test_screenshot_scenario_finds_real_credential_file(self):


        from vault_inventory import (
            search_files_for_credentials_report,
            CREDENTIAL_CONFIDENCE_STRONG,
            CREDENTIAL_CONFIDENCE_WEAK,
        )
        weak_rows = [
            {
                "id": f"weak{i}",
                "file_name": fn,
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/html",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": None,                   
            }
            for i, fn in enumerate([
                "loginatt.html",
                "wellsfargologinhtml.html",
                "nortonpasswordmanager_recoverykey.pdf",
            ])
        ]
        strong_row = {
            "id": "harmless-real-file",
            "file_name": "harmless-name.pdf",
            "saved_name": "",
            "relative_path": "",
            "content_type": "application/pdf",
            "file_size": 1,
            "asset_type": "file",
            "detected_service": "",
            "created_at": None,
            "extracted_text": _REGRESSION_FIXTURE_TEXT,
        }
        rows = weak_rows + [strong_row]

        report = search_files_for_credentials_report(rows)

                                                  
        strong_matches = [
            m for m in report["matches"]
            if m["confidence"] == CREDENTIAL_CONFIDENCE_STRONG
        ]
        self.assertGreaterEqual(len(strong_matches), 1)
        self.assertTrue(
            any(m["file_id"] == "harmless-real-file" for m in strong_matches),
            "harmless-named file with repeated records MUST surface",
        )

                                                       
        self.assertEqual(
            report["matches"][0]["confidence"],
            CREDENTIAL_CONFIDENCE_STRONG,
        )
        weak_position = next(
            (i for i, m in enumerate(report["matches"])
             if m["confidence"] == CREDENTIAL_CONFIDENCE_WEAK),
            None,
        )
        strong_position = next(
            (i for i, m in enumerate(report["matches"])
             if m["confidence"] == CREDENTIAL_CONFIDENCE_STRONG),
            None,
        )
        self.assertIsNotNone(weak_position)
        self.assertIsNotNone(strong_position)
        self.assertLess(strong_position, weak_position)


if __name__ == "__main__":
    unittest.main()
