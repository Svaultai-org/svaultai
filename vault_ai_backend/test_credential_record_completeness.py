

from __future__ import annotations

import json
import unittest

from vault_inventory import (
    verified_credential_files_report,
    format_credential_files_reply,
    _count_complete_credential_records,
    _count_labelled_pair_credential_records,
    _looks_like_password_value,
    _looks_like_identifier_value,
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


_BLOCKCHAIN_EXPLORER_LIST = """\
Etherscan
BscScan
Solscan
TronScan
CardanoScan
Polkascan
TonViewer
Avalanche Explorer
PolygonScan
Blockchain
Bitcoin Explorer
BTC.com
Blockchain.com Explorer
BitInfoCharts
Zcash Block Explorer
BlockCypher
Stellar Explorer
Cosmos Explorer
"""

_WEBSITE_LIST = """\
GitHub
GitLab
Bitbucket
SourceHut
Codeberg
Gitea
HuggingFace
"""

_COMPANY_NAME_LIST = """\
Apple
Google
Microsoft
Amazon
Meta
Tesla
Adobe
Adobe Inc
Nvidia
"""

_PASSWORD_WORD_ONLY = """\
We require a password of at least 8 characters.
Please choose a strong password and confirm by re-entering it.
You will be asked for your password each time you log in.
Forgot your password? Visit the help centre.
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

_SERVICE_PLUS_EMAIL_ONLY = """\
Gmail
alice@example.com
American Express
bob@example.com
Apple
carol@example.com
"""

_SERVICE_PLUS_PASSWORD_ONLY = """\
Gmail
hunter2!secret9
American Express
SunF1ower!Spring9
Apple
Z9q!Wp$73a99
"""


_SERVICE_USER_PASSWORD_TRIPLE = """\
Gmail
alice@example.com
hunter2!secret9

American Express
bob@example.com
SunF1ower!Spring9

Apple
carol@example.com
Z9q!Wp$73a99
"""

_PWD_MANAGER_EXPORT = """\
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

_ARCHIVE_ACCOUNTS_TXT = """\
[ARCHIVE INDEX: family-backup.zip]

accounts.txt:
Spotify
mom@example.com
SunF1ower!9secret
Netflix
dad@example.com
NoSp01l3rs#2024
Twitch
gamer@example.com
Aim4thest@rs!a
"""

_OCR_LOGIN_SCREENSHOT = """\
[OCR TEXT]
Login to your account
Username: admin@example.com
Password: hunter2!secret9
Forgot password?
Sign in
"""


class CompleteRecordVerifierRejectsTests(unittest.TestCase):
    def _expect_rejected(self, file_name, text, *, content_type="text/plain"):
        rows = [_row(file_name, extracted_text=text,
                     content_type=content_type)]
        report = verified_credential_files_report(rows)
        self.assertEqual(
            len(report["matches"]), 0,
            f"verifier must REJECT {file_name!r}; got "
            f"{[m['file_name'] for m in report['matches']]}",
        )

    def test_blockchain_explorer_keyword_list_is_rejected(self):
        self._expect_rejected(
            "blockchain-explorer-keyword.txt",
            _BLOCKCHAIN_EXPLORER_LIST,
        )

    def test_list_of_websites_only_is_rejected(self):
        self._expect_rejected("websites.txt", _WEBSITE_LIST)

    def test_list_of_company_names_only_is_rejected(self):
        self._expect_rejected("companies.txt", _COMPANY_NAME_LIST)

    def test_text_containing_only_password_word_is_rejected(self):
        self._expect_rejected("policy.txt", _PASSWORD_WORD_ONLY)

    def test_form_with_password_input_is_rejected(self):
        self._expect_rejected(
            "login-form.html", _LOGIN_HTML_FORM, content_type="text/html",
        )

    def test_service_plus_email_without_password_value_is_rejected(self):
        self._expect_rejected(
            "service-email-only.txt", _SERVICE_PLUS_EMAIL_ONLY,
        )

    def test_service_plus_password_without_identifier_is_rejected(self):
        self._expect_rejected(
            "service-password-only.txt", _SERVICE_PLUS_PASSWORD_ONLY,
        )


class CompleteRecordVerifierAcceptsTests(unittest.TestCase):
    def _expect_accepted(self, file_name, text, *, content_type="text/plain",
                          asset_type="file"):
        rows = [_row(file_name, extracted_text=text,
                     content_type=content_type, asset_type=asset_type)]
        report = verified_credential_files_report(rows)
        self.assertEqual(
            len(report["matches"]), 1,
            f"verifier must ACCEPT {file_name!r}; got "
            f"{[m['file_name'] for m in report['matches']]}",
        )
        return report["matches"][0]

    def test_service_plus_identifier_plus_password_is_accepted(self):
        match = self._expect_accepted(
            "saved-logins.txt", _SERVICE_USER_PASSWORD_TRIPLE,
        )
        self.assertGreaterEqual(int(match["record_count"]), 1)
        self.assertTrue(match["password_present"])

    def test_password_manager_export_is_accepted(self):
        match = self._expect_accepted(
            "pwd-manager.txt", _PWD_MANAGER_EXPORT,
        )
                                                                          
        self.assertGreaterEqual(int(match["record_count"]), 3)
                                                               
        self.assertTrue(match["safe_service_names"])

    def test_ocr_login_screenshot_with_labelled_pair_is_accepted(self):
        match = self._expect_accepted(
            "screenshot.png", _OCR_LOGIN_SCREENSHOT,
            content_type="image/png", asset_type="image",
        )
        self.assertEqual(match["evidence_source"], "ocr")
        self.assertEqual(match["evidence_source_label"], "OCR")

    def test_archive_accounts_txt_with_records_is_accepted(self):
        match = self._expect_accepted(
            "family-backup.zip", _ARCHIVE_ACCOUNTS_TXT,
            content_type="application/zip", asset_type="archive",
        )
        self.assertEqual(match["evidence_source"], "archive")


class StrictPasswordValueMatcherTests(unittest.TestCase):
    def test_accepts_real_password_shapes(self):
        for s in [
            "hunter2!secret9",
            "Spr1ng!2024",
            "Z9q!Wp$73a",
            "SunF1ower!fall9",
        ]:
            with self.subTest(s=s):
                self.assertTrue(_looks_like_password_value(s))

    def test_rejects_short_words(self):
        for s in ["hello", "pass", "abc123", "Hi9!"]:
            with self.subTest(s=s):
                self.assertFalse(_looks_like_password_value(s))

    def test_rejects_domain_shapes(self):
        for s in [
            "BTC.com", "blockchain.com", "wells.org",
            "etherscan.io", "polygonscan.net",
        ]:
            with self.subTest(s=s):
                self.assertFalse(_looks_like_password_value(s))

    def test_rejects_emails(self):
        for s in [
            "user@example.com", "alice@gmail.com",
            "bob.smith@corp.io",
        ]:
            with self.subTest(s=s):
                self.assertFalse(_looks_like_password_value(s))

    def test_rejects_pure_letter_brand_names(self):
        for s in ["AmericanExpress", "BlockCypher", "WellsFargo"]:
            with self.subTest(s=s):
                self.assertFalse(_looks_like_password_value(s))

    def test_rejects_pure_digit_runs(self):
        self.assertFalse(_looks_like_password_value("123456789"))

    def test_rejects_strings_with_spaces(self):
        self.assertFalse(_looks_like_password_value("hunter 2 secret"))


class StrictIdentifierValueMatcherTests(unittest.TestCase):
    def test_accepts_email(self):
        self.assertTrue(_looks_like_identifier_value("alice@example.com"))

    def test_rejects_pure_brand_token(self):
        self.assertFalse(_looks_like_identifier_value("Apple"))
        self.assertFalse(_looks_like_identifier_value("AmericanExpress"))

    def test_rejects_domain_shape(self):
        self.assertFalse(_looks_like_identifier_value("BTC.com"))

    def test_accepts_username_with_digits(self):
        self.assertTrue(_looks_like_identifier_value("alice99"))
        self.assertTrue(_looks_like_identifier_value("admin_42"))


class CompleteRecordCounterTests(unittest.TestCase):
    def test_blockchain_explorer_list_yields_zero_records(self):
        self.assertEqual(
            _count_complete_credential_records(
                _BLOCKCHAIN_EXPLORER_LIST,
            )["complete_records"],
            0,
        )

    def test_password_manager_export_yields_multiple_records(self):
        self.assertGreaterEqual(
            _count_complete_credential_records(
                _PWD_MANAGER_EXPORT,
            )["complete_records"],
            3,
        )

    def test_labelled_pair_counter_picks_up_ocr_screenshot(self):
        self.assertGreaterEqual(
            _count_labelled_pair_credential_records(
                _OCR_LOGIN_SCREENSHOT,
            ),
            1,
        )

    def test_labelled_pair_counter_rejects_password_word_prose(self):
        self.assertEqual(
            _count_labelled_pair_credential_records(_PASSWORD_WORD_ONLY),
            0,
        )


class StrictEnvelopeSafetyTests(unittest.TestCase):
    def test_envelope_never_leaks_credential_values(self):
        rows = [
            _row("pwd-manager.txt", extracted_text=_PWD_MANAGER_EXPORT),
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
        for leak in (
            "MKSherm81765", "sunshine6856", "e&t082826",
            "Patrick62109", "Spr1ng!2024", "Z9q!Wp$73a",
            "person@example.com", "loul@example.com",
            "jane@example.com", "alex@example.com",
        ):
            self.assertNotIn(
                leak, envelope_json,
                f"strict envelope leaked credential value: {leak!r}",
            )
                                                                     
        payload = json.loads(envelope_json)
        self.assertGreaterEqual(payload["count"], 1)


if __name__ == "__main__":
    unittest.main()
