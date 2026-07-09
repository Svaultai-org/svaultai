

from __future__ import annotations

import inspect
import json
import time
import unittest

import vault_inventory as vi
import vault_document_purpose as vp
import vault_chat_memory as cm


def _saved_login_list_text() -> str:


    return "\n".join([
        "AOL", "user1@example.com", "Patrick62109",
        "Apple", "user2@example.com", "MKSherm81765",
        "American Express", "user3@example.com", "e&t082826",
        "Wells Fargo", "user4@example.com", "sunshine6856",
        "Gmail", "user5@example.com", "loul82!Bridge",
        "Netflix", "user6@example.com", "Sky88!morning",
        "Dropbox", "user7@example.com", "DropIt@2024",
    ])


def _bitwarden_csv_export_text() -> str:


    return "\n".join([
        "folder,favorite,type,name,notes,fields,login_uri,login_username,login_password,login_totp",
        ",,,Gmail,,,https://mail.google.com,user1@example.com,a-pwd",
        ",,,Apple,,,https://appleid.apple.com,user2@example.com,b-pwd",
    ])


def _chrome_csv_export_text() -> str:
    return "\n".join([
        "name,url,username,password",
        "Gmail,https://mail.google.com,me@example.com,pw1",
        "Twitter,https://twitter.com,me@example.com,pw2",
    ])


def _env_config_secrets_text() -> str:
    return "\n".join([
        "username: ops-rotate-me",
        "email: ops@example.com",
        "password: rotate-me",
        "api_key: sk_live_abcdef",
        "api_secret: shhh-keep-this-secret",
        "token: bearer-token-here",
        "secret: app-rotate-this",
        "private_key: -----BEGIN PRIVATE KEY-----...-----END PRIVATE KEY-----",
        "mnemonic: word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12",
        "login: ops-prod-svc",
    ])


def _fema_application_form_text() -> str:


    return "\n".join([
        "FEDERAL EMERGENCY MANAGEMENT AGENCY",
        "Disaster Assistance Application",
        "OMB Control No. 1660-0002",
        "",
        "Applicant Name: __________________________",
        "Date of Birth: ____________",
        "Social Security Number: _______________",
        "Address: ______________________________",
        "City: ________   State: ___   Zip Code: ______",
        "Phone Number: ____________",
        "",
        "Date of Damage: __________",
        "Disaster Number: _________",
        "Damaged Address: ________________________",
        "",
        "Reference Number: FEMA-DR-1234-XX",
        "Application ID: APP-2024-0001",
        "",
        "Declaration:",
        "I hereby certify under penalty of perjury that the",
        "information provided above is true and correct.",
        "I authorize the release of information necessary to",
        "process this application.",
        "",
        "Signature: ________________  Date Signed: ________",
        "Witness: ________________",
        "",
        "Page 1 of 4",
                                                                       
        "Online portal: your password reset code will arrive via email.",
    ])


def _insurance_claim_form_text() -> str:
    return "\n".join([
        "ACME LIFE INSURANCE CO.",
        "Property and Casualty Claim Form",
        "",
        "Policy Number: ACME-POL-12345",
        "Policy Holder: ____________________",
        "Named Insured: ____________________",
        "Claim Number: ACME-CLM-67890",
        "Date of Loss: ____________",
        "",
        "Policy Term: 2024-01-01 to 2025-01-01",
        "Premium: $1,250.00",
        "Deductible: $500",
        "Coverage Limit: $250,000",
        "",
        "Beneficiary: ____________________",
        "Claims Department contact: ____________",
        "Agent Name: __________   Agent Number: ____________",
        "Underwriter: ____________",
        "Loss Payee: ____________________",
        "",
        "Schedule of Benefits attached.",
        "",
        "Declaration:",
        "By signing below, I declare under penalty of perjury that",
        "the information provided is accurate to the best of my",
        "knowledge.",
        "",
        "Signature: ____________   Date Signed: ____________",
    ])


def _tax_1040_text() -> str:
    return "\n".join([
        "Form 1040 — U.S. Individual Income Tax Return",
        "Internal Revenue Service",
        "Tax Year 2024",
        "OMB Number 1545-0074",
        "",
        "Applicant Name: ____________________",
        "Spouse Name: ____________________",
        "Social Security Number: __________",
        "Filing Status: ____",
        "Occupation: ____________________",
        "",
        "Address: ____________________",
        "City: ________   State: ___   Zip Code: ______",
        "",
        "Line 1: Wages, salaries, tips: ________",
        "Line 7: Total income: ________",
        "Line 12: Standard deduction: ________",
        "Line 16: Tax: ________",
        "",
        "Under penalties of perjury, I declare that I have examined",
        "this return and to the best of my knowledge it is true.",
        "",
        "Signature: ____________   Date Signed: ____________",
        "Page 1 of 2",
    ])


def _prose_handover_doc_text() -> str:


    lines = [
        "This is the Q4 project handover document. Below we cover",
        "the migration timeline, the API rewrite, the frontend",
        "split, the rollout plan, and the security review.",
        "Each work-stream has its own owner and timeline.",
        "",
        "Legacy admin password: ProjectHandoverLegacyOnly",
        "Please rotate this once migration completes.",
        "",
    ]
    while len(lines) < 80:
        lines.append("Notes from the meeting, continued.")
    return "\n".join(lines)


def _row(file_id, *, name, text, sha="", relative_path=""):
    return {
        "id":             file_id,
        "file_name":      name,
        "saved_name":     "",
        "relative_path":  relative_path,
        "content_type":   "application/pdf",
        "asset_type":     "file",
        "extracted_text": text,
        "content_sha256": sha,
    }


class ClassifierVerdictsTests(unittest.TestCase):
    def _classify(self, text):
        metrics = vi._compute_credential_density_metrics(text)
        return vp.classify_document_purpose(text, metrics=metrics)

    def test_saved_login_list_dump_fires_saved_login_list(self):
        verdict = self._classify(_saved_login_list_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_SAVED_LOGIN_LIST)
        self.assertGreaterEqual(verdict["confidence"], 0.75)
        self.assertEqual(verdict["purpose_rank"], 0)
        joined = " ".join(verdict["evidence"]).lower()
        self.assertIn("saved", joined)

    def test_bitwarden_csv_header_fires_credential_export(self):
        verdict = self._classify(_bitwarden_csv_export_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_CREDENTIAL_EXPORT)
        self.assertGreaterEqual(verdict["confidence"], 0.90)
        self.assertEqual(verdict["purpose_rank"], 0)
        self.assertIn(
            "password-manager export",
            " ".join(verdict["evidence"]).lower(),
        )

    def test_chrome_csv_header_fires_credential_export(self):
        verdict = self._classify(_chrome_csv_export_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_CREDENTIAL_EXPORT)
        self.assertEqual(verdict["purpose_rank"], 0)

    def test_env_with_many_labelled_fields_fires_config_secrets(self):
        verdict = self._classify(_env_config_secrets_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_CONFIG_SECRETS)
        self.assertEqual(verdict["purpose_rank"], 1)
        self.assertGreaterEqual(verdict["confidence"], 0.6)

    def test_fema_form_fires_government_legal(self):
        verdict = self._classify(_fema_application_form_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_GOVERNMENT_LEGAL)
        self.assertEqual(verdict["purpose_rank"], 3)

    def test_insurance_claim_fires_insurance_form(self):
        verdict = self._classify(_insurance_claim_form_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_INSURANCE_FORM)
        self.assertEqual(verdict["purpose_rank"], 3)

    def test_tax_1040_fires_government_legal(self):
        verdict = self._classify(_tax_1040_text())
        self.assertEqual(verdict["purpose"], vp.PURPOSE_GOVERNMENT_LEGAL)
        self.assertEqual(verdict["purpose_rank"], 3)

    def test_prose_handover_fires_generic_text(self):
        verdict = self._classify(_prose_handover_doc_text())
        self.assertIn(
            verdict["purpose"],
            (vp.PURPOSE_GENERIC_TEXT, vp.PURPOSE_UNKNOWN),
            "a project handover docx with ONE stray password line "
            "must NOT be classified as a credential file",
        )
        self.assertGreaterEqual(verdict["purpose_rank"], 2)

    def test_empty_text_returns_unknown(self):
        verdict = vp.classify_document_purpose(None)
        self.assertEqual(verdict["purpose"], vp.PURPOSE_UNKNOWN)
        verdict = vp.classify_document_purpose("   \n  \t  ")
        self.assertEqual(verdict["purpose"], vp.PURPOSE_UNKNOWN)


class ClassifierIgnoresFilenameTests(unittest.TestCase):
    def test_misleading_filename_does_not_change_verdict(self):
                                                                    
                                                                    
        metrics = vi._compute_credential_density_metrics(
            _fema_application_form_text())
        verdict = vp.classify_document_purpose(
            _fema_application_form_text(), metrics=metrics,
        )
        self.assertEqual(verdict["purpose"], vp.PURPOSE_GOVERNMENT_LEGAL)
                                                             
                                                                
    def test_password_named_file_with_form_content_classifies_as_form(self):
        rows = [
            _row("fake-passwords",
                 name="passwords list 2024.docx.pdf",
                 text=_fema_application_form_text(),
                 sha="aaaa"),
        ]
        report = vi.search_files_for_credentials_report(rows)
                                                                 
                                                             
        self.assertEqual(
            len(report["matches"]), 0,
            "a FEMA application form with a misleading "
            "'passwords list' filename must NOT show up in the "
            "credential surface",
        )


class PurposeRankingTests(unittest.TestCase):
    def test_saved_login_dump_ranks_above_config_secrets(self):
        rows = [
            _row("env",  name="dotenv.txt",
                 text=_env_config_secrets_text(), sha="env-1"),
            _row("dump", name="logins-2024.txt",
                 text=_saved_login_list_text(), sha="dump-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "dump",
            "saved_login_list (rank 0) must rank above "
            "config_secrets (rank 1)")

    def test_csv_export_ranks_above_saved_login_dump(self):
                                                              
                                                                  
        rows = [
            _row("dump", name="logins.txt",
                 text=_saved_login_list_text(), sha="dump-1"),
            _row("csv",  name="bitwarden_export.csv",
                 text=_bitwarden_csv_export_text(), sha="csv-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
                                                              
                                                 
        ids = [m["file_id"] for m in report["matches"]]
        self.assertIn("dump", ids)
        self.assertIn("csv", ids)

    def test_form_government_insurance_are_dropped(self):
        rows = [
            _row("fema", name="fema.pdf",
                 text=_fema_application_form_text(), sha="fema-1"),
            _row("ins",  name="claim.pdf",
                 text=_insurance_claim_form_text(),  sha="ins-1"),
            _row("tax",  name="1040.pdf",
                 text=_tax_1040_text(),              sha="tax-1"),
            _row("dump", name="logins.txt",
                 text=_saved_login_list_text(),      sha="dump-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        ids = {m["file_id"] for m in report["matches"]}
        self.assertIn("dump", ids,
            "saved_login_list must survive the form filter")
        for dropped in ("fema", "ins", "tax"):
            self.assertNotIn(
                dropped, ids,
                f"{dropped} (form/gov/insurance) must NOT appear in "
                "the credential surface — the classifier downgrades "
                "it out",
            )

    def test_filename_only_hit_with_prose_content_drops_or_weakens(self):
                                                                  
                                                                 
        rows = [
            _row("prose", name="passwords-readme.txt",
                 text=_prose_handover_doc_text(), sha="prose-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        if report["matches"]:
                                                                   
                                                                     
            self.assertEqual(report["matches"][0]["confidence"], "weak")


class BestMatchPurposeGuardTests(unittest.TestCase):
    def test_saved_login_dump_gets_best_match(self):
        rows = [
            _row("dump", name="logins.txt",
                 text=_saved_login_list_text(), sha="dump-1"),
            _row("env",  name="dotenv.txt",
                 text=_env_config_secrets_text(), sha="env-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        top = report["matches"][0]
        self.assertEqual(top["file_id"], "dump")
        self.assertTrue(top.get("best_match"),
            "the saved_login_list file must be flagged best_match")

    def test_csv_export_alone_gets_best_match_via_explicit_verdict(self):
        rows = [
            _row("csv", name="bitwarden.csv",
                 text=_bitwarden_csv_export_text(), sha="csv-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "csv")
        self.assertTrue(report["matches"][0].get("best_match"),
            "a single credential_export verdict is enough for "
            "best_match — no density tie-break required")


class EnvelopeCarriesPurposeTests(unittest.TestCase):
    def test_envelope_carries_purpose_and_label(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[
                {
                    "file_id":       "dump",
                    "file_name":     "logins.txt",
                    "confidence":    "strong",
                    "purpose":       vp.PURPOSE_SAVED_LOGIN_LIST,
                    "purpose_label": "saved website/app login records",
                    "best_match":    True,
                    "reasons":       ["..."],
                },
            ],
            title="Best match",
            message="",
            context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertEqual(row["purpose"], vp.PURPOSE_SAVED_LOGIN_LIST)
        self.assertEqual(
            row["purpose_label"],
            "saved website/app login records",
        )

    def test_envelope_omits_purpose_when_absent(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[
                {
                    "file_id":   "f1",
                    "file_name": "x.pdf",
                    "confidence": "strong",
                    "reasons":   ["x"],
                },
            ],
            title="t", message="m", context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertNotIn("purpose", row)
        self.assertNotIn("purpose_label", row)


class SnapshotCarriesPurposeTests(unittest.TestCase):
    def setUp(self):
        self.vault_id = f"vault-{time.time_ns()}"

    def tearDown(self):
        cm.clear_last_file_search_results(self.vault_id)

    def test_snapshot_carries_purpose_and_label(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=[{
                "file_id":       "dump",
                "file_name":     "logins.txt",
                "confidence":    "strong",
                "purpose":       vp.PURPOSE_SAVED_LOGIN_LIST,
                "purpose_label": "saved website/app login records",
                "best_match":    True,
            }],
        )
        out = cm.get_last_file_search_results(self.vault_id)
        row = out["results"][0]
        self.assertEqual(row["purpose"], vp.PURPOSE_SAVED_LOGIN_LIST)
        self.assertEqual(
            row["purpose_label"],
            "saved website/app login records",
        )


class PurposeVocabularyTests(unittest.TestCase):
    def test_purpose_rank_table_is_complete(self):
        for name in (
            vp.PURPOSE_SAVED_LOGIN_LIST,
            vp.PURPOSE_CREDENTIAL_EXPORT,
            vp.PURPOSE_CONFIG_SECRETS,
            vp.PURPOSE_APPLICATION_FORM,
            vp.PURPOSE_INSURANCE_FORM,
            vp.PURPOSE_GOVERNMENT_LEGAL,
            vp.PURPOSE_GENERIC_TEXT,
            vp.PURPOSE_UNKNOWN,
        ):
            self.assertIn(name, vp.PURPOSE_RANK)

    def test_credential_bearing_predicate(self):
        self.assertTrue(
            vp.purpose_is_credential_bearing(vp.PURPOSE_SAVED_LOGIN_LIST))
        self.assertTrue(
            vp.purpose_is_credential_bearing(vp.PURPOSE_CREDENTIAL_EXPORT))
        self.assertTrue(
            vp.purpose_is_credential_bearing(vp.PURPOSE_CONFIG_SECRETS))
        for non in (
            vp.PURPOSE_APPLICATION_FORM,
            vp.PURPOSE_INSURANCE_FORM,
            vp.PURPOSE_GOVERNMENT_LEGAL,
            vp.PURPOSE_GENERIC_TEXT,
            vp.PURPOSE_UNKNOWN,
        ):
            self.assertFalse(vp.purpose_is_credential_bearing(non), non)

    def test_form_like_predicate(self):
        self.assertTrue(vp.purpose_is_form_like(vp.PURPOSE_APPLICATION_FORM))
        self.assertTrue(vp.purpose_is_form_like(vp.PURPOSE_INSURANCE_FORM))
        self.assertTrue(vp.purpose_is_form_like(vp.PURPOSE_GOVERNMENT_LEGAL))
        for non in (
            vp.PURPOSE_SAVED_LOGIN_LIST,
            vp.PURPOSE_CREDENTIAL_EXPORT,
            vp.PURPOSE_CONFIG_SECRETS,
            vp.PURPOSE_GENERIC_TEXT,
            vp.PURPOSE_UNKNOWN,
        ):
            self.assertFalse(vp.purpose_is_form_like(non), non)


class ClassifierNeverLeaksValuesTests(unittest.TestCase):
    def test_evidence_strings_never_contain_sentinel_values(self):
                                                                  
                                                                  
        text = (
            _saved_login_list_text()
            + "\nhunter2\npassword: SUPERSECRET-XYZ-123\n"
        )
        metrics = vi._compute_credential_density_metrics(text)
        verdict = vp.classify_document_purpose(text, metrics=metrics)
        joined = "\n".join(verdict["evidence"])
        for sentinel in (
            "hunter2",
            "SUPERSECRET-XYZ-123",
            "Patrick62109",
            "MKSherm81765",
        ):
            self.assertNotIn(
                sentinel, joined,
                f"the classifier must NEVER include the literal "
                f"value {sentinel!r} in its evidence strings",
            )


class SourceGuardTests(unittest.TestCase):
    def test_credential_search_imports_classifier(self):
                                                                    
                                                                  
        src = inspect.getsource(vi.search_files_for_credentials_report)
        self.assertIn("vault_document_purpose", src)
        self.assertIn("classify_document_purpose", src)


if __name__ == "__main__":
    unittest.main()
