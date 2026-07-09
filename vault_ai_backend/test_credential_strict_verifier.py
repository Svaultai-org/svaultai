

from __future__ import annotations

import json
import unittest

from vault_inventory import (
    verified_credential_files_report,
    format_credential_files_reply,
)
from main import _build_credential_files_envelope


def _row(file_name, *, extracted_text=None, **overrides):
    return {
        "id":                 overrides.get("file_id") or f"id-{file_name}",
        "file_name":          file_name,
        "saved_name":         overrides.get("saved_name", ""),
        "relative_path":      overrides.get("relative_path", ""),
        "content_type":       overrides.get("content_type", "text/plain"),
        "mime_type":          overrides.get("content_type", "text/plain"),
        "asset_type":         overrides.get("asset_type", "file"),
        "detected_service":   overrides.get("detected_service", ""),
        "detected_type":      overrides.get("detected_type", ""),
        "extracted_text":     extracted_text,
        "content_sha256":     overrides.get("content_sha256", f"sha-{file_name}"),
        "file_size":          overrides.get("file_size", 100),
        "created_at":         None,
        "needs_naming":       False,
    }


_LOGIN_JS_CODE = """\
import {useState} from 'react';
export function LoginForm() {
  const [user, setUser] = useState('');
  const [pwd, setPwd]   = useState('');
  return (
    <form>
      <input type="text" name="username" />
      <input type="password" name="password" />
      <button>Sign in</button>
    </form>
  );
}
"""

_LOGIN_HTML_FORM = """\
<!doctype html>
<html><body>
  <form action="/login" method="post">
    <input type="text" name="username" placeholder="Username">
    <input type="password" name="password" placeholder="Password">
    <button>Sign in</button>
  </form>
</body></html>
"""

_CREDIT_CARD_AUTH_FORM = """\
CREDIT CARD AUTHORIZATION

I hereby authorize the merchant named below to charge my credit
card account for the amount specified in this agreement.

Cardholder name: ______________________________
Email address: cardholder@example.com
Card number:  see attached image
Expiration:   __/__/____
Authorized amount: $ ______
Signature: __________________  Date: __________
"""

_APPLICATION_FORM_WITH_PASSWORD = """\
Application for residency renewal — Department of State

Applicant name: Maureen Smith
Email address: applicant@example.com
Phone:         555-0102
Date of birth: 1989-04-12

If you wish to set up an online account, choose a password
of at least 8 characters. Submit this form within 30 days.
Signature:____________________  Date:____________________
"""

_INSURANCE_FORM_WITH_PWD = """\
HEALTH INSURANCE CLAIM FORM

Policy number: HX-882819
Insured name: ___________________
Email address: insured@example.com
Phone: 555-0190

We will issue a temporary online account password by mail. Do
not write a password on this form. Sign below to attest accuracy.
"""

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

_OCR_LOGIN_SCREENSHOT = """\
[OCR TEXT]
Login to your account
Username: admin@example.com
Password: hunter2!
Forgot password?
Sign in
"""

_TEXT_LABELED_CREDS = """\
Spotify
username: mom@example.com
password: hunter2!fall

Netflix
username: dad@example.com
password: NoSp01l3rs#2024
"""


class VerifierRejectsNonCredentialFilesTests(unittest.TestCase):
    def _expect_dropped(self, row):
        report = verified_credential_files_report([row])
        names = [m["file_name"] for m in report["matches"]]
        self.assertNotIn(
            row["file_name"], names,
            f"verifier must NOT surface {row['file_name']!r} — "
            "no real credential records inside",
        )
        return report

    def test_login_js_with_login_ui_code_is_not_shown(self):
                                                                      
        self._expect_dropped(
            _row("login.js", extracted_text=_LOGIN_JS_CODE),
        )

    def test_loginatt_html_with_password_form_is_not_shown(self):
        self._expect_dropped(
            _row(
                "loginatt.html", extracted_text=_LOGIN_HTML_FORM,
                content_type="text/html",
            ),
        )

    def test_credit_card_authorization_form_is_not_shown(self):
        self._expect_dropped(
            _row(
                "credit-card-authorization.pdf",
                extracted_text=_CREDIT_CARD_AUTH_FORM,
                content_type="application/pdf",
            ),
        )

    def test_application_form_with_password_field_is_not_shown(self):
        self._expect_dropped(
            _row(
                "residency-application.pdf",
                extracted_text=_APPLICATION_FORM_WITH_PASSWORD,
                content_type="application/pdf",
            ),
        )

    def test_insurance_form_with_password_mention_is_not_shown(self):
        self._expect_dropped(
            _row(
                "health-insurance-claim.pdf",
                extracted_text=_INSURANCE_FORM_WITH_PWD,
                content_type="application/pdf",
            ),
        )

    def test_filename_only_match_is_not_shown(self):
                                                                      
                                                            
        self._expect_dropped(
            _row("passwords.txt", extracted_text=""),
        )

    def test_tagger_only_match_is_not_shown(self):
                                                                       
                                                                  
        self._expect_dropped(
            _row(
                "random-doc.pdf",
                extracted_text="",
                detected_service="login",
                content_type="application/pdf",
            ),
        )

    def test_random_words_that_look_like_company_names_are_not_shown(self):
                                                                 
                                                                  
        self._expect_dropped(
            _row(
                "marketing-brief.txt",
                extracted_text=(
                    "Apple has released the latest device.\n"
                    "Google added a new feature last month.\n"
                    "Microsoft will announce something in May.\n"
                    "Amazon shipped a quarterly update on Tuesday.\n"
                ),
            ),
        )


    def test_tenant_application_with_email_and_account_numbers_is_not_shown(self):
        self._expect_dropped(
            _row(
                "TENANT's PROFILE FORM UPDATED.pdf",
                extracted_text=(
                    "PROPERTY\n"
                    "Would you mind if we contact your last landlord "
                    "or agent?\n"
                    "Applicant email: tenant@example.com\n"
                    "Account number: 5501 0187 064\n"
                    "Bank: Ally Bank\n"
                    "Office reference: MKS herm 81765\n"
                    "Signature: __________________\n"
                ),
                content_type="application/pdf",
            ),
        )

    def test_email_only_list_is_not_shown(self):
        self._expect_dropped(
            _row(
                "swiftemail.txt",
                extracted_text=(
                    "edward.jackson@uwclub.net\n"
                    "nelondonrsp@yahoo.co.uk\n"
                    "example@gmail.com\n"
                ),
            ),
        )

    def test_prose_with_secret_word_and_bank_reference_is_not_shown(self):
        self._expect_dropped(
            _row(
                "792946415-IWE-OGUNN-1.pdf",
                extracted_text=(
                    "Asiri yi da fun eniyan ni ofiisi. "
                    "Bank account number 55010187064 appears on the form, "
                    "but there is no login username and no password value."
                ),
                content_type="application/pdf",
            ),
        )


class VerifierAcceptsRealCredentialFilesTests(unittest.TestCase):
    def _expect_kept(self, row):
        report = verified_credential_files_report([row])
        names = [m["file_name"] for m in report["matches"]]
        self.assertIn(
            row["file_name"], names,
            f"verifier must surface {row['file_name']!r} — file contains "
            "verified credential records",
        )
        return report

    def test_password_manager_export_is_shown(self):
        report = self._expect_kept(
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
        )
        match = report["matches"][0]
        self.assertGreaterEqual(int(match["record_count"]), 3)
        self.assertTrue(match["password_present"])
                                                                    
        self.assertTrue(match["safe_service_names"])

    def test_text_file_with_labelled_credential_records_is_shown(self):
        self._expect_kept(
            _row("accounts.txt", extracted_text=_TEXT_LABELED_CREDS),
        )

    def test_archive_accounts_txt_with_credentials_is_shown(self):
        report = self._expect_kept(
            _row(
                "family-backup.zip",
                extracted_text=_ARCHIVE_INDEX_WITH_CREDENTIALS,
                content_type="application/zip",
                asset_type="archive",
            ),
        )
        match = report["matches"][0]
        self.assertEqual(match["evidence_source"], "archive")
        self.assertEqual(match["evidence_source_label"], "archive")

    def test_ocr_login_screenshot_is_shown(self):
        report = self._expect_kept(
            _row(
                "screenshot.png",
                extracted_text=_OCR_LOGIN_SCREENSHOT,
                content_type="image/png",
                asset_type="image",
            ),
        )
        match = report["matches"][0]
        self.assertEqual(match["evidence_source"], "ocr")
        self.assertEqual(match["evidence_source_label"], "OCR")
        self.assertTrue(match["password_present"])


class VerifiedEnvelopeShapeTests(unittest.TestCase):
    def test_envelope_carries_only_verified_files(self):
        rows = [
            _row("dump.txt", extracted_text=_PWD_MANAGER_DUMP),
            _row("login.js", extracted_text=_LOGIN_JS_CODE),
            _row(
                "credit-card-auth.pdf",
                extracted_text=_CREDIT_CARD_AUTH_FORM,
                content_type="application/pdf",
            ),
            _row("passwords.txt", extracted_text=""),
        ]
        report = verified_credential_files_report(rows)
        envelope_json = _build_credential_files_envelope(
            matches=report["matches"],
            message=format_credential_files_reply(
                report["matches"],
                scanned_count=report["scanned_count"],
                not_scanned_count=report["not_scanned_count"],
            ),
            scanned_count=report["scanned_count"],
            not_scanned_count=report["not_scanned_count"],
        )
        payload = json.loads(envelope_json)
                                 
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["files"][0]["file_name"], "dump.txt")

    def test_envelope_drops_legacy_tier_keys(self):
                                                    
                                                                   
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = verified_credential_files_report(rows)
        envelope_json = _build_credential_files_envelope(
            matches=report["matches"],
            message="x",
            scanned_count=report["scanned_count"],
            not_scanned_count=report["not_scanned_count"],
        )
        payload = json.loads(envelope_json)
        self.assertNotIn("sections", payload)
        self.assertNotIn("has_content_matches", payload)
        for f in payload["files"]:
            for forbidden in (
                "tier", "confidence", "reasons", "purpose",
                "purpose_label", "purpose_rank", "credential_density",
                "credential_block_count", "service_count",
                "mostly_credentials", "credential_like_lines",
                "meaningful_lines", "safe_identifier_count",
            ):
                self.assertNotIn(
                    forbidden, f,
                    f"verified row leaked internal field {forbidden!r}",
                )

    def test_envelope_never_carries_credential_values(self):
                                                                 
                                                                    
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        report = verified_credential_files_report(rows)
        envelope_json = _build_credential_files_envelope(
            matches=report["matches"],
            message=format_credential_files_reply(
                report["matches"],
                scanned_count=report["scanned_count"],
                not_scanned_count=report["not_scanned_count"],
            ),
            scanned_count=report["scanned_count"],
            not_scanned_count=report["not_scanned_count"],
        )
        for leak in (
            "MKSherm81765", "sunshine6856", "e&t082826",
            "Patrick62109", "Spr1ng!2024", "Z9q!Wp$73a",
            "person@example.com", "loul@example.com",
            "jane@example.com", "alex@example.com",
        ):
            self.assertNotIn(
                leak, envelope_json,
                f"envelope leaked credential value: {leak!r}",
            )


class VerifiedEmptyAndUnscannedTests(unittest.TestCase):
    def test_empty_after_scan_uses_strict_copy(self):
        rows = [
            _row("login.js", extracted_text=_LOGIN_JS_CODE),
            _row("passwords.txt", extracted_text=""),
        ]
        report = verified_credential_files_report(rows)
                       
        self.assertEqual(len(report["matches"]), 0)
        text = format_credential_files_reply(
            report["matches"],
            scanned_count=2,
            not_scanned_count=0,
        )
        self.assertIn(
            "I scanned the readable files and did not find saved "
            "credential records.",
            text,
        )
                                               
        self.assertNotIn("may contain", text.lower())
        self.assertNotIn("filename match", text.lower())

    def test_unscanned_count_renders_separately_not_as_results(self):
                                                                   
                                                                     
        rows = [_row("dump.txt", extracted_text=_PWD_MANAGER_DUMP)]
        text = format_credential_files_reply(
            verified_credential_files_report(rows)["matches"],
            scanned_count=425,
            not_scanned_count=231,
        )
        self.assertIn(
            "I checked 425 of 656 files. 231 still need "
            "extraction/OCR. These results are incomplete.",
            text,
        )
                                                                 
        self.assertIn(
            "Partial results from already scanned files:",
            text,
        )

    def test_scan_remaining_action_attached_when_unscanned_gt_zero(self):
                                                             
                                                                
        envelope_json = _build_credential_files_envelope(
            matches=[],
            message="x",
            scanned_count=0,
            not_scanned_count=231,
        )
        payload = json.loads(envelope_json)
        actions = payload.get("actions") or []
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "scan_remaining")
        self.assertEqual(actions[0]["file_count"], 231)


if __name__ == "__main__":
    unittest.main()
