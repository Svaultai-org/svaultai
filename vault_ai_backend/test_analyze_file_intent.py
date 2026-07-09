

from __future__ import annotations

import inspect
import unittest

import vault_inventory as vi
import vault_document_purpose as vp
import vault_file_analysis as vfa


def _saved_login_list_text() -> str:
    return "\n".join([
        "AOL", "user1@example.com", "Patrick62109",
        "Apple", "user2@example.com", "MKSherm81765",
        "American Express", "user3@example.com", "e&t082826",
        "Wells Fargo", "user4@example.com", "sunshine6856",
        "Gmail", "user5@example.com", "loul82!Bridge",
        "Netflix", "user6@example.com", "Sky88!morning",
    ])


def _application_form_with_emails_text() -> str:


    return "\n".join([
        "Disaster Assistance Application Form",
        "",
        "Applicant Name: ____________________",
        "Date of Birth: ____________",
        "Address: ____________________",
        "City: ________   State: ___   Zip Code: ______",
        "Phone Number: ____________",
        "Email Address: applicant1@example.com",
        "Spouse Email: applicant2@example.com",
        "Occupation: ____________________",
        "Employer: ____________________",
        "",
        "Reference Number: APP-2024-0001",
        "Application ID: REF-XYZ",
        "Case Number: CASE-99",
        "",
        "Declaration:",
        "I hereby certify under penalty of perjury that the",
        "information provided is true. I authorize the release",
        "of records necessary to process this application.",
        "",
        "Signature: ____________   Date Signed: ____________",
        "Witness: ____________",
    ])


def _insurance_form_text() -> str:
    return "\n".join([
        "ACME LIFE INSURANCE CO.",
        "Policy Number: ACME-POL-12345",
        "Policy Holder: ____________________",
        "Named Insured: ____________________",
        "Claim Number: ACME-CLM-67890",
        "Date of Loss: ____________",
        "Policy Term: 2024-01-01 to 2025-01-01",
        "Premium: $1,250.00",
        "Deductible: $500",
        "Coverage Limit: $250,000",
        "Beneficiary: ____________________",
        "Claims Department contact: ____________",
        "Agent Name: __________   Agent Number: ____________",
        "Underwriter: ____________",
        "Loss Payee: ____________________",
        "Schedule of Benefits attached.",
        "Declaration:",
        "By signing below, I declare under penalty of perjury that",
        "the information provided is accurate.",
        "Signature: ____________   Date Signed: ____________",
    ])


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge", "Sky88!morning",
    "user1@example.com", "user2@example.com",
    "user3@example.com", "user4@example.com",
    "user5@example.com", "user6@example.com",
)


class IntentClassifierWiringTests(unittest.TestCase):
    def test_detect_vault_intent_prompt_names_analyze_file(self):
        import main
        src = inspect.getsource(main.detect_vault_intent)
        self.assertIn("analyze_file", src,
            "the LLM intent prompt must include analyze_file so the "
            "classifier knows how to route 'analyze X' phrasings")
                                                               
                                                                 
        for phrase in (
            "analyze passedwordtex.pdf",
            "what is in",
            "tell me about this file",
            "what kind of file is this",
        ):
            self.assertIn(phrase, src, phrase)

    def test_chat_handler_has_analyze_file_branch(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn('intent == "analyze_file"', src)
                                                             
                                            
        idx = src.find('intent == "analyze_file"')
                                                           
        branch_body = src[idx:idx + 1500]
        self.assertIn("build_safe_file_analysis", branch_body,
            "analyze_file MUST go through the safe summariser")
        self.assertNotIn("list_logins_tool(", branch_body,
            "analyze_file must NEVER route to saved-login listing")

    def test_chat_handler_analyze_file_runs_before_travel_readiness(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        a_idx = src.find('intent == "analyze_file"')
        t_idx = src.find('intent == "travel_readiness"')
        self.assertGreater(a_idx, -1)
        self.assertGreater(t_idx, -1)
        self.assertLess(a_idx, t_idx,
            "analyze_file branch should come before "
            "travel_readiness so a tied intent doesn't fall through "
            "to a different feature")


class SavedLoginSummariserTests(unittest.TestCase):
    def _build(self, text, *, file_name="passedwordtex.pdf",
               show_secret_values=False):
        metrics = vi._compute_credential_density_metrics(text)
        purpose = vp.classify_document_purpose(text, metrics=metrics)
        return vfa.build_safe_file_analysis(
            text,
            file_name=file_name,
            metrics=metrics,
            purpose_decision=purpose,
            show_secret_values=show_secret_values,
        )

    def test_saved_login_list_reply_leads_with_purpose(self):
        reply = self._build(_saved_login_list_text())
        self.assertIn("appears to be a saved-login list", reply.lower())

    def test_saved_login_list_reply_states_record_count(self):
        reply = self._build(_saved_login_list_text())
                                                               
                                                                
        self.assertRegex(
            reply,
            r"\d+\s+repeated\s+website/app\s+credential\s+records?",
        )

    def test_saved_login_list_reply_offers_safe_consent_line(self):
        reply = self._build(_saved_login_list_text())
        low = reply.lower()
        self.assertIn("won't show", low)
                                                                
                                                       
        self.assertIn("saved-logins", low)

    def test_saved_login_reply_does_NOT_leak_any_passwords(self):
        reply = self._build(_saved_login_list_text())
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, reply,
                f"the safe summariser MUST NEVER include the "
                f"literal value {sentinel!r} in its reply",
            )

    def test_service_preview_lists_brand_names_only(self):
        reply = self._build(_saved_login_list_text())
                                                        
                                                              
        self.assertTrue(
            any(name in reply for name in (
                "AOL", "Apple", "Wells Fargo", "Gmail", "Netflix"
            )),
            "the safe summariser should list service brand names "
            "as a preview so the user can sanity-check what's in "
            "the file",
        )
                                                                   
                              
        for sentinel in (
            "user1@example.com", "user2@example.com",
        ):
            self.assertNotIn(sentinel, reply)


class CredentialExportSummariserTests(unittest.TestCase):
    def test_bitwarden_csv_reply_calls_it_a_password_manager_export(self):
        csv_text = (
            "folder,favorite,type,name,notes,fields,login_uri,login_username,login_password,login_totp\n"
            ",,,Gmail,,,https://mail.google.com,user1@example.com,SUPERSECRET-XYZ-123,\n"
            ",,,Apple,,,https://appleid.apple.com,user2@example.com,hunter2,\n"
        )
        metrics = vi._compute_credential_density_metrics(csv_text)
        purpose = vp.classify_document_purpose(csv_text, metrics=metrics)
        reply = vfa.build_safe_file_analysis(
            csv_text,
            file_name="bitwarden_export.csv",
            metrics=metrics,
            purpose_decision=purpose,
        )
        self.assertIn(
            "appears to be a password-manager export",
            reply,
        )
                                  
        for sentinel in ("SUPERSECRET-XYZ-123", "hunter2"):
            self.assertNotIn(sentinel, reply)


class FormSummariserTests(unittest.TestCase):
    def _build(self, text, *, file_name="form.pdf"):
        metrics = vi._compute_credential_density_metrics(text)
        purpose = vp.classify_document_purpose(text, metrics=metrics)
        return vfa.build_safe_file_analysis(
            text,
            file_name=file_name,
            metrics=metrics,
            purpose_decision=purpose,
        )

    def test_application_form_reply_says_not_a_saved_login_list(self):
        reply = self._build(_application_form_with_emails_text())
        low = reply.lower()
        self.assertIn("application form", low)
        self.assertIn("does not look like a saved-login list", low)

    def test_insurance_form_reply_says_not_a_saved_login_list(self):
        reply = self._build(_insurance_form_text())
        low = reply.lower()
        self.assertIn("insurance form", low)
        self.assertIn("does not look like a saved-login list", low)

    def test_form_summariser_does_not_leak_emails_in_form_body(self):
                                                                     
                                                                    
        reply = self._build(_application_form_with_emails_text())
        self.assertNotIn("applicant1@example.com", reply)
        self.assertNotIn("applicant2@example.com", reply)


class GenericTextSummariserTests(unittest.TestCase):
    def test_generic_prose_reply_is_honest(self):
        text = "Project handover doc. " * 50
        metrics = vi._compute_credential_density_metrics(text)
        purpose = vp.classify_document_purpose(text, metrics=metrics)
        reply = vfa.build_safe_file_analysis(
            text,
            file_name="handover.pdf",
            metrics=metrics,
            purpose_decision=purpose,
        )
        self.assertIn(
            "don't see strong evidence",
            reply.lower(),
        )


class NoExtractedTextTests(unittest.TestCase):
    def test_empty_text_returns_honest_fallback(self):
        reply = vfa.build_safe_file_analysis(
            None,
            file_name="foo.pdf",
            metrics={},
            purpose_decision={"purpose": "unknown"},
        )
        self.assertIn("don't have extracted text", reply.lower())
        self.assertIn("foo.pdf", reply)


class ExplicitValueRequestTests(unittest.TestCase):
    def test_analyse_phrases_do_NOT_trigger_explicit_consent(self):
        for phrase in (
            "analyze passedwordtex.pdf",
            "what is in passedwordtex.pdf",
            "what is inside this file",
            "tell me about this file",
            "what kind of file is this",
            "summarize this file",
        ):
            self.assertFalse(
                vfa.user_explicitly_requested_values(phrase),
                f"the phrase {phrase!r} is an analyse request, "
                "NOT a consent to dump passwords",
            )

    def test_explicit_phrases_DO_trigger_consent(self):
        for phrase in (
            "show me the passwords inside",
            "reveal the secrets",
            "extract all passwords from this file",
            "dump the tokens",
            "print every password",
        ):
            self.assertTrue(
                vfa.user_explicitly_requested_values(phrase),
                f"the phrase {phrase!r} is an EXPLICIT "
                "dump-credentials request",
            )


def _row(file_id, *, name, text, sha=""):
    return {
        "id":             file_id,
        "file_name":      name,
        "saved_name":     "",
        "relative_path":  "",
        "content_type":   "application/pdf",
        "asset_type":     "file",
        "extracted_text": text,
        "content_sha256": sha,
    }


class RankingDowngradeTests(unittest.TestCase):
    def test_application_form_with_emails_is_NOT_ranked_as_saved_login(self):
        rows = [
            _row("dump", name="passedwordtex.pdf",
                 text=_saved_login_list_text(), sha="dump-1"),
            _row("appform", name="application.pdf",
                 text=_application_form_with_emails_text(), sha="app-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        ids = [m["file_id"] for m in report["matches"]]
                                                                 
                        
        self.assertIn("dump", ids)
        self.assertEqual(ids[0], "dump",
            "the real saved-login list must rank above an "
            "application form even when the form has email fields")

    def test_insurance_form_is_NOT_ranked_above_real_password_list(self):
        rows = [
            _row("ins", name="claim.pdf",
                 text=_insurance_form_text(), sha="ins-1"),
            _row("dump", name="passedwordtex.pdf",
                 text=_saved_login_list_text(), sha="dump-1"),
        ]
        report = vi.search_files_for_credentials_report(rows)
                                                              
                                               
        ids = [m["file_id"] for m in report["matches"]]
        self.assertEqual(ids[0], "dump")
        self.assertNotIn(
            "ins", ids,
            "an insurance form must not appear in the credential "
            "surface — the user asked for files WITH credentials, "
            "not files about insurance",
        )


class PurposeDecisionExposesSignalsTests(unittest.TestCase):
    def test_form_signal_counts_are_on_every_decision(self):
        text = _application_form_with_emails_text()
        metrics = vi._compute_credential_density_metrics(text)
        verdict = vp.classify_document_purpose(text, metrics=metrics)
                                                                 
                                                          
        for key in (
            "form_field_hits",
            "form_declaration_hit",
            "gov_hit",
            "insurance_hits",
        ):
            self.assertIn(key, verdict, key)

    def test_application_form_threshold_fires_at_3_plus_declaration(self):
                                                                
                                                                 
        short_form = "\n".join([
            "Applicant Name: ____________________",
            "Address: ____________________",
            "Signature: ____________",
            "",
            "I hereby certify under penalty of perjury that the",
            "information above is correct.",
        ])
        metrics = vi._compute_credential_density_metrics(short_form)
        verdict = vp.classify_document_purpose(short_form, metrics=metrics)
        self.assertEqual(
            verdict["purpose"],
            vp.PURPOSE_APPLICATION_FORM,
            "3 form fields + a declaration clause should fire the "
            "application_form verdict",
        )


if __name__ == "__main__":
    unittest.main()
