

from __future__ import annotations

import json
import unittest

from vault_inventory import (
    search_files_for_credentials_report,
    format_credential_files_reply,
    CREDENTIAL_TIER_CONFIRMED,
    CREDENTIAL_TIER_POSSIBLE,
    CREDENTIAL_TIER_FILENAME_ONLY,
)
from main import (
    _build_credential_files_envelope,
    _build_credential_extraction_review_envelope,
)


def _row(file_name, **overrides):
    base = {
        "id":                 overrides.get("file_id") or f"id-{file_name}",
        "file_name":          file_name,
        "saved_name":         overrides.get("saved_name", ""),
        "relative_path":      overrides.get("relative_path", ""),
        "content_type":       overrides.get("content_type", "text/plain"),
        "mime_type":          overrides.get("content_type", "text/plain"),
        "asset_type":         overrides.get("asset_type", "file"),
        "detected_service":   overrides.get("detected_service", ""),
        "detected_type":      overrides.get("detected_type", ""),
        "extracted_text":     overrides.get("extracted_text"),
        "content_sha256":     overrides.get("content_sha256", f"sha-{file_name}"),
        "file_size":          overrides.get("file_size", 100),
        "created_at":         None,
        "needs_naming":       False,
    }
    return base


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

_APPLICATION_FORM = """\
Application for residency renewal — Department of State

Applicant name: Maureen Smith
Email address: applicant@example.com
Phone:         555-0102
Date of birth: 1989-04-12
Passport number:  see attached copy

If you wish to set up an online account, choose a password
of at least 8 characters. Submit this form within 30 days.
Signature:____________________  Date:____________________
"""

_ARCHIVE_INDEX_WITH_CREDENTIALS = """\
[ARCHIVE INDEX: family-backup.zip]

accounts.txt:
Spotify
mom@example.com
SunF1ower!9
Netflix
dad@example.com
NoSp01l3rs#2024
Twitch
gamer@example.com
Aim4thest@rs!

photos/dscf0001.jpg
photos/dscf0002.jpg
"""

_OCR_SCREENSHOT = """\
[OCR TEXT]
Login to your account
Username: admin@example.com
Password: hunter2!
Forgot password?
Sign in
"""


class FilenameDoesNotOutrankContentTests(unittest.TestCase):
    def test_strong_content_beats_weak_filename_in_sections(self):
        rows = [
            _row("login.js", extracted_text="console.log('hello world');"),
            _row(
                "harmless-name.pdf",
                extracted_text=_PWD_MANAGER_DUMP,
                content_type="application/pdf",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        sections = report["sections"]
                                                             
                        
        confirmed_names = [m["file_name"] for m in sections[CREDENTIAL_TIER_CONFIRMED]]
        filename_only_names = [m["file_name"] for m in sections[CREDENTIAL_TIER_FILENAME_ONLY]]
        self.assertIn("harmless-name.pdf", confirmed_names)
        self.assertIn("login.js", filename_only_names)
                                                                
                              
        self.assertEqual(
            report["matches"][0]["file_name"], "harmless-name.pdf",
            "content-confirmed row must rank above filename-only row",
        )

    def test_only_filename_matches_set_has_content_matches_false(self):
        rows = [
            _row("login.js", extracted_text="console.log('hello');"),
            _row("loginatt.html", extracted_text="<html>hi</html>"),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertFalse(report["has_content_matches"])
                                                     
        self.assertEqual(report["sections"][CREDENTIAL_TIER_CONFIRMED], [])
        self.assertEqual(report["sections"][CREDENTIAL_TIER_POSSIBLE], [])
        self.assertGreaterEqual(
            len(report["sections"][CREDENTIAL_TIER_FILENAME_ONLY]), 1,
        )


class TierClassificationTests(unittest.TestCase):
    def test_login_js_with_no_credential_content_is_filename_only(self):
        rows = [_row("login.js", extracted_text="export function foo() {}")]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(
            report["matches"][0]["tier"], CREDENTIAL_TIER_FILENAME_ONLY,
        )
        self.assertEqual(report["matches"][0]["confidence"], "weak")

    def test_password_manager_dump_is_confirmed(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(report["matches"][0]["tier"], CREDENTIAL_TIER_CONFIRMED)
        self.assertEqual(report["matches"][0]["confidence"], "strong")
                                        
        self.assertTrue(report["matches"][0]["password_present"])

    def test_application_form_with_password_field_is_not_confirmed(self):
                                                                   
                                                                    
        rows = [
            _row(
                "residency-application.pdf",
                extracted_text=_APPLICATION_FORM,
                content_type="application/pdf",
            ),
        ]
        report = search_files_for_credentials_report(rows)
                                                                 
                                                                    
        confirmed = report["sections"][CREDENTIAL_TIER_CONFIRMED]
        self.assertEqual(
            confirmed, [],
            "application form must not appear under Confirmed — "
            "it has a single password mention buried in form prose",
        )

    def test_archive_index_text_with_credentials_is_confirmed(self):
                                                      
                                                                 
        rows = [
            _row(
                "family-backup.zip",
                extracted_text=_ARCHIVE_INDEX_WITH_CREDENTIALS,
                content_type="application/zip",
                asset_type="archive",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        confirmed_names = [
            m["file_name"] for m in report["sections"][CREDENTIAL_TIER_CONFIRMED]
        ]
        self.assertIn("family-backup.zip", confirmed_names)

    def test_ocr_screenshot_with_credentials_is_at_least_possible(self):
                                                                 
                                           
        rows = [
            _row(
                "screenshot.png",
                extracted_text=_OCR_SCREENSHOT,
                content_type="image/png",
                asset_type="image",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        match = report["matches"][0] if report["matches"] else None
        self.assertIsNotNone(match, "OCR'd login screen must produce a match")
                                                                
                                                                
        self.assertIn(
            match["tier"],
            (CREDENTIAL_TIER_CONFIRMED, CREDENTIAL_TIER_POSSIBLE),
        )
        self.assertTrue(match["password_present"])


class UnscannedHintTests(unittest.TestCase):
    def test_not_scanned_count_surfaces_for_unextracted_rows(self):
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
                                                          
            _row("big-archive.zip", extracted_text=None),
            _row("another.zip", extracted_text=None),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["not_scanned_count"], 2)
        self.assertEqual(report["scanned_count"], 1)

    def test_envelope_includes_scan_remaining_action_when_unscanned(self):
        envelope_json = _build_credential_files_envelope(
            matches=[],
            message="x",
            scanned_count=10,
            not_scanned_count=231,
            sections={
                "confirmed": [], "possible": [], "filename_only": [],
            },
            has_content_matches=False,
        )
        payload = json.loads(envelope_json)
        actions = payload.get("actions") or []
        scan_action = next(
            (a for a in actions if a.get("type") == "scan_remaining"),
            None,
        )
        self.assertIsNotNone(
            scan_action,
            "envelope must include a scan_remaining action when "
            "files are unscanned",
        )
        self.assertEqual(scan_action["file_count"], 231)
        self.assertIn("Scan remaining files", scan_action["label"])

    def test_envelope_omits_scan_remaining_action_when_all_scanned(self):
        envelope_json = _build_credential_files_envelope(
            matches=[],
            message="x",
            scanned_count=10,
            not_scanned_count=0,
            sections={
                "confirmed": [], "possible": [], "filename_only": [],
            },
            has_content_matches=False,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload.get("actions") or [], [])

    def test_format_reply_unscanned_hint_is_rendered_separately(self):
                                                                    
                                                                    
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1",
                    "file_name": "dump.txt",
                    "saved_name": "",
                    "record_count": 5,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                }
            ],
            not_scanned_count=42,
        )
        self.assertIn("42 still need extraction/OCR", text)
        self.assertIn("These results are incomplete", text)


class SafeSurfaceTests(unittest.TestCase):
    def test_password_present_boolean_in_payload(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = search_files_for_credentials_report(rows)
        match = report["matches"][0]
        self.assertIn("password_present", match)
        self.assertTrue(match["password_present"])

    def test_no_password_values_in_envelope(self):
                                                                       
                                                                     
        from vault_inventory import verified_credential_files_report
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = verified_credential_files_report(rows)
        envelope = _build_credential_files_envelope(
            matches=report["matches"],
            message=format_credential_files_reply(
                report["matches"],
                not_scanned_count=report["not_scanned_count"],
                scanned_count=report["scanned_count"],
            ),
            scanned_count=report["scanned_count"],
            not_scanned_count=report["not_scanned_count"],
        )
                                                                  
                                                                     
        for leaked in (
            "MKSherm81765", "sunshine6856", "e&t082826",
            "Patrick62109", "Spr1ng!2024", "Z9q!Wp$73a",
            "person@example.com", "loul@example.com",
            "jane@example.com", "alex@example.com",
        ):
            self.assertNotIn(
                leaked, envelope,
                f"envelope leaked literal value: {leaked!r}",
            )

    def test_safe_service_names_render_in_payload(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = search_files_for_credentials_report(rows)
        match = report["matches"][0]
        self.assertIn("safe_service_names", match)
                                                                
                                                                
        self.assertTrue(
            any(s in match["safe_service_names"]
                for s in ("AOL", "American Express", "Apple", "Wells Fargo", "Gmail")),
            f"expected brand-like service names; got "
            f"{match['safe_service_names']!r}",
        )

    def test_safe_identifier_count_is_a_bounded_scalar(self):
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = search_files_for_credentials_report(rows)
        match = report["matches"][0]
        self.assertIn("safe_identifier_count", match)
        self.assertIsInstance(match["safe_identifier_count"], int)
        self.assertGreaterEqual(match["safe_identifier_count"], 0)


class EnvelopeShapeTests(unittest.TestCase):
    def test_envelope_drops_sections_and_has_content_matches(self):
                                                                   
                                                                     
        envelope_json = _build_credential_files_envelope(
            matches=[
                {
                    "file_id": "a", "file_name": "dump.txt",
                    "record_count": 3,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                },
            ],
            message="x",
            scanned_count=10,
            not_scanned_count=0,
        )
        payload = json.loads(envelope_json)
        self.assertNotIn(
            "sections", payload,
            "envelope must not carry sections (no weak/medium/"
            "filename_only on the user-facing surface)",
        )
        self.assertNotIn(
            "has_content_matches", payload,
            "envelope must not carry has_content_matches (verified ⟹ "
            "content matched)",
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["files"][0]["record_count"], 3)


class CredentialExtractionReviewTests(unittest.TestCase):
    def test_review_envelope_strips_password_values(self):
                                                                    
                                                                 
        envelope_json = _build_credential_extraction_review_envelope(
            file_id="f1",
            file_name="bitwarden.json",
            saved_name="",
            relative_path="Secrets/",
            records=[
                {
                    "service":     "Gmail",
                    "secret_type": "login",
                    "fields": {
                        "username": "alice@example.com",
                        "password": "hunter2!secret",
                    },
                },
                {
                    "service":     "Wells Fargo",
                    "secret_type": "login",
                    "fields": {
                        "username": "alice@example.com",
                        "password": "Spr1ng!2024",
                        "pin":      "1234",
                    },
                },
            ],
            message="ok",
            text_available=True,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["type"], "credential_extraction_review")
        self.assertEqual(payload["count"], 2)
                                                   
        for rec in payload["records"]:
            self.assertIn("password_present", rec)
            self.assertNotIn("password", rec,
                "review payload must never carry password VALUES")
            self.assertNotIn("pin", rec,
                "review payload must never carry pin VALUES")
                                                                     
        for leaked in ("hunter2!secret", "Spr1ng!2024", "1234"):
            self.assertNotIn(leaked, envelope_json)
                                                           
        self.assertIn("alice@example.com", envelope_json)
                                                                  
        self.assertTrue(payload["records"][0]["password_present"])
        self.assertTrue(payload["records"][1]["password_present"])
        self.assertTrue(payload["records"][1]["pin_present"])

    def test_review_envelope_records_capped_at_50(self):
                                                              
                                                                   
        records = [
            {"service": f"svc{i}",
             "secret_type": "login",
             "fields": {"username": f"u{i}", "password": "x"}}
            for i in range(60)
        ]
        envelope_json = _build_credential_extraction_review_envelope(
            file_id="f1",
            file_name="big-export.csv",
            saved_name="",
            relative_path="",
            records=records,
            message="ok",
            text_available=True,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["count"], 50)

    def test_review_envelope_handles_no_text_available(self):
        envelope_json = _build_credential_extraction_review_envelope(
            file_id="f1",
            file_name="locked.bin",
            saved_name="",
            relative_path="",
            records=[],
            message="no text yet",
            text_available=False,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["text_available"], False)


class IntentRoutingTests(unittest.TestCase):
    def test_extract_logins_intent_listed_in_detect_prompt(self):
                                                                     
                                                                
        import inspect, main
        prompt_src = inspect.getsource(main.detect_vault_intent)
        self.assertIn("extract_logins_from_file", prompt_src)

    def test_extract_logins_handler_branch_exists(self):
                                                                
                                                                   
        import inspect, main
        chat_src = inspect.getsource(main)
        self.assertIn(
            'intent == "extract_logins_from_file"',
            chat_src,
        )
        self.assertIn(
            "_handle_extract_logins_from_file(",
            chat_src,
        )

    def test_search_files_for_credentials_never_calls_save(self):
                                                               
                                                              
        import inspect, main
        src = inspect.getsource(main)
        branch_start = src.find('if intent == "search_files_for_credentials":')
        self.assertGreater(branch_start, -1)
        branch_end = src.find('if intent == "extract_logins_from_file"', branch_start)
        self.assertGreater(branch_end, branch_start)
        branch_body = src[branch_start:branch_end]
                                                       
                                                 
        for forbidden in (
            "save_login(",
            "INSERT INTO vault_items",
            "extract_multiple_credentials(",
            "extract_credentials(",
        ):
            self.assertNotIn(
                forbidden, branch_body,
                f"search_files_for_credentials branch must NOT "
                f"reference {forbidden!r} — that intent is find-only",
            )


if __name__ == "__main__":
    unittest.main()
