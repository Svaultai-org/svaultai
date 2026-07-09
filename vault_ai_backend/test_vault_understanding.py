

from __future__ import annotations

import inspect
import json
import os
import unittest

import vault_analysis as va
import vault_document_purpose as vp
import vault_understanding as vu


def _migration_0007_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0007_vault_file_understanding.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _saved_login_list_text() -> str:
    return "\n".join([
        "AOL", "alice@example.com", "Patrick62109",
        "Apple", "bob@example.com", "MKSherm81765",
        "American Express", "carol@example.com", "e&t082826",
        "Wells Fargo", "dan@example.com", "sunshine6856",
        "Gmail", "erin@example.com", "loul82!Bridge",
        "Netflix", "frank@example.com", "Sky88!morning",
    ])


def _wells_fargo_finance_doc() -> str:
    return "\n".join([
        "Wells Fargo Bank Statement",
        "Account ending 1234",
        "Statement Period: 2024-01-01 to 2024-01-31",
        "",
        "Beginning balance: $1,234.56",
        "Deposit on 2024-01-05: $500.00",
        "Withdrawal on 2024-01-15: $250.00",
        "Ending balance: $1,484.56",
        "",
        "If you have questions, contact us at help@wellsfargo.com.",
    ])


def _maureen_recipe_doc() -> str:
    return "\n".join([
        "Maureen's pumpkin pie recipe",
        "",
        "Ingredients:",
        "  - 1 cup pumpkin puree",
        "  - 1/2 cup cream",
        "",
        "Dictated by Maureen on December 15, 2023.",
        "Notes from the kitchen, continued.",
    ])


def _application_form_text() -> str:
    return "\n".join([
        "Application for Federal Assistance",
        "",
        "Applicant Name: ____________________",
        "Address: ____________________",
        "Phone Number: ____________",
        "Date of Birth: ____________",
        "Email Address: applicant@example.com",
        "Reference Number: REF-1234",
        "Application ID: APP-2024-0001",
        "",
        "Declaration:",
        "I hereby certify under penalty of perjury that the",
        "information above is true.",
        "",
        "Signature: ____________   Date Signed: ____________",
    ])


def _insurance_form_text() -> str:
    return "\n".join([
        "ACME Insurance — Claim Form",
        "Policy Number: ACME-POL-12345",
        "Policy Holder: ____________________",
        "Named Insured: ____________________",
        "Premium: $1,250.00",
        "Deductible: $500",
        "Coverage Limit: $250,000",
        "Beneficiary: ____________________",
        "Underwriter: ____________________",
        "Loss Payee: ____________________",
        "Declaration:",
        "By signing below, I certify under penalty of perjury that",
        "the above is true.",
        "Signature: ____________   Date Signed: ____________",
    ])


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge", "Sky88!morning",
)


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0007_source()

    def test_table_exists(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS vault_file_understanding",
            self.src,
        )

    def test_required_columns_present(self):
        for col in (
            "understanding_id",
            "vault_id",
            "file_id",
            "source_text_version",
            "analysis_version",
            "status",
            "document_purpose",
            "purpose_label",
            "purpose_confidence",
            "summary_encrypted",
            "safe_preview_encrypted",
            "topics_jsonb",
            "entities_jsonb",
            "dates_jsonb",
            "detected_categories_jsonb",
            "credential_signals_jsonb",
            "travel_signals_jsonb",
            "financial_signals_jsonb",
            "legal_signals_jsonb",
            "identity_signals_jsonb",
            "relationship_signals_jsonb",
            "searchable_terms_jsonb",
            "confidence_jsonb",
            "last_error",
            "created_at",
            "updated_at",
        ):
            self.assertIn(col, self.src, f"missing column: {col}")

    def test_status_enum_includes_all_python_constants(self):
        for status in vu.UNDERSTANDING_STATUSES:
            self.assertTrue(
                f'"{status}"' in self.src or f"'{status}'" in self.src,
                f"migration must declare status {status!r}",
            )

    def test_no_plaintext_summary_check_constraint(self):
        self.assertIn(
            "vault_file_understanding_no_plaintext_summary_chk",
            self.src,
            "the constraint that refuses plaintext summary MUST "
            "exist — it's the schema-level floor",
        )
        self.assertIn(
            "vault_file_understanding_no_plaintext_preview_chk",
            self.src,
        )

    def test_ready_has_purpose_check_constraint(self):
        self.assertIn(
            "vault_file_understanding_ready_has_purpose_chk",
            self.src,
            "ready rows must have a document_purpose — a ready "
            "row without a verdict is incoherent",
        )

    def test_unique_vault_file_index(self):
        self.assertIn(
            "vault_file_understanding_file_idx",
            self.src,
        )

    def test_vault_status_index(self):
        self.assertIn(
            "vault_file_understanding_vault_status_idx",
            self.src,
        )

    def test_vault_purpose_index(self):
        self.assertIn(
            "vault_file_understanding_vault_purpose_idx",
            self.src,
        )

    def test_source_text_version_index_for_stale_detection(self):
        self.assertIn(
            "vault_file_understanding_source_text_version_idx",
            self.src,
            "stale detection needs a vault + version index so a "
            "housekeeping query can find understanding rows "
            "whose source has been re-extracted",
        )

    def test_migration_adds_file_understanding_stage_to_check(self):
                                                                  
                                                                     
        self.assertTrue(
            '"file_understanding"' in self.src
            or "'file_understanding'" in self.src,
            "migration must declare the file_understanding stage",
        )
        self.assertIn(
            "vault_analysis_jobs_stage_chk",
            self.src,
        )

    def test_migration_is_reversible(self):
        for needle in (
            "DROP TABLE IF EXISTS vault_file_understanding",
            "DROP INDEX IF EXISTS vault_file_understanding_file_idx",
        ):
            self.assertIn(needle, self.src)


class StageConstantTests(unittest.TestCase):
    def test_stage_file_understanding_in_python_stages(self):
        self.assertIn(va.STAGE_FILE_UNDERSTANDING, va.STAGES)

    def test_stage_name_matches_string(self):
        self.assertEqual(va.STAGE_FILE_UNDERSTANDING, "file_understanding")


class BuilderPurposeTests(unittest.TestCase):
    def test_saved_login_list_text_builds_ready_record(self):
        record = vu.build_understanding(
            _saved_login_list_text(), file_name="logins.txt",
        )
        self.assertEqual(record["status"], "ready")
        self.assertEqual(
            record["document_purpose"], vp.PURPOSE_SAVED_LOGIN_LIST,
        )
        self.assertGreaterEqual(record["purpose_confidence"], 0.75)

    def test_application_form_text_builds_application_form(self):
        record = vu.build_understanding(
            _application_form_text(), file_name="application.pdf",
        )
        self.assertEqual(record["status"], "ready")
        self.assertEqual(
            record["document_purpose"], vp.PURPOSE_APPLICATION_FORM,
        )

    def test_insurance_form_text_builds_insurance_form(self):
        record = vu.build_understanding(
            _insurance_form_text(), file_name="claim.pdf",
        )
        self.assertEqual(
            record["document_purpose"], vp.PURPOSE_INSURANCE_FORM,
        )

    def test_government_text_builds_government_legal(self):
        text = (
            "Internal Revenue Service\n"
            "Form 1040 — U.S. Individual Income Tax Return\n"
            "Tax Year 2024\nOMB Number 1545-0074\n"
            "Under penalties of perjury, I declare ...\n"
            "Applicant Name: ___\nAddress: ___"
        )
        record = vu.build_understanding(text, file_name="1040.pdf")
        self.assertEqual(
            record["document_purpose"],
            vp.PURPOSE_GOVERNMENT_LEGAL,
        )

    def test_generic_text_builds_generic(self):
        record = vu.build_understanding(
            "This is a project handover note. " * 30,
            file_name="handover.txt",
        )
        self.assertEqual(record["status"], "ready")
        self.assertIn(
            record["document_purpose"],
            (vp.PURPOSE_GENERIC_TEXT, vp.PURPOSE_UNKNOWN),
        )

    def test_empty_text_marks_unsupported(self):
        record = vu.build_understanding(None, file_name="x.pdf")
        self.assertEqual(record["status"], "unsupported")

        record2 = vu.build_understanding("", file_name="x.pdf")
        self.assertEqual(record2["status"], "unsupported")


class BuilderSignalsTests(unittest.TestCase):
    def test_wells_fargo_doc_extracts_finance_signals_and_entity(self):
        record = vu.build_understanding(
            _wells_fargo_finance_doc(), file_name="statement.pdf",
        )
               
        self.assertIn("finance", record["topics"])
                  
        self.assertIn("finance", record["detected_categories"])
                
        self.assertIn("Wells Fargo", record["entities"]["names"])
                        
        self.assertIn("2024-01-01", record["dates"])
                                                 
        joined = " ".join(record["searchable_terms"])
        self.assertIn("wells fargo", joined)
        self.assertIn("finance", joined)

    def test_maureen_recipe_extracts_name_and_date_entities(self):
        record = vu.build_understanding(
            _maureen_recipe_doc(), file_name="pumpkin.txt",
        )
                                   
        self.assertIn("Maureen", record["entities"]["names"])
                                            
        self.assertIn("2023-12-15", record["dates"])
                                             
        self.assertIn("maureen", record["searchable_terms"])

    def test_saved_login_text_fires_credential_signals(self):
        record = vu.build_understanding(
            _saved_login_list_text(), file_name="logins.txt",
        )
        cs = record["credential_signals"]
        self.assertTrue(cs["is_credential_bearing"])
        self.assertTrue(cs["mostly_credentials"])
        self.assertGreaterEqual(cs["credential_block_count"], 3)
        self.assertGreaterEqual(cs["service_count"], 3)
                                     
        self.assertIn("security", record["detected_categories"])

    def test_insurance_form_fires_insurance_topic(self):
        record = vu.build_understanding(
            _insurance_form_text(), file_name="claim.pdf",
        )
        self.assertIn("insurance", record["topics"])
        self.assertIn("insurance", record["detected_categories"])

    def test_travel_text_fires_travel_signals(self):
        text = (
            "Passport details and boarding pass. Hotel itinerary "
            "follows for your flight to Tokyo via Narita Airport."
        )
        record = vu.build_understanding(text, file_name="trip.pdf")
        self.assertIn("travel", record["topics"])
        ts = record["travel_signals"]
        self.assertTrue(ts["any_present"])
        self.assertIn("passport", ts["doc_types"])
        self.assertIn("boarding_pass", ts["doc_types"])

    def test_identity_doc_fires_identity_signals(self):
        text = (
            "Driver's License Number: DL-1234-5678\n"
            "Date of Birth: 1990-05-15\n"
            "Place of Birth: California\n"
        )
        record = vu.build_understanding(text, file_name="dl.pdf")
        ids = record["identity_signals"]
        self.assertTrue(ids["any_present"])
        self.assertIn("driver_license", ids["doc_types"])

    def test_relationship_terms_detected(self):
        text = (
            "My spouse and beneficiary information is below. "
            "Next of kin: Jane Smith."
        )
        record = vu.build_understanding(text, file_name="form.pdf")
        rs = record["relationship_signals"]
        self.assertTrue(rs["any_present"])
        self.assertIn("spouse", rs["kinship_terms"])
        self.assertIn("beneficiary", rs["kinship_terms"])


class BuilderNeverLeaksSecretsTests(unittest.TestCase):
    def test_saved_login_summary_does_not_leak_passwords(self):
        record = vu.build_understanding(
            _saved_login_list_text(), file_name="logins.txt",
        )
                 
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, record["summary"])
                                                       
        self.assertNotIn("Patrick62109", record["safe_preview"])
        self.assertEqual(
            record["safe_preview"],
            "[credential records — values withheld]",
            "credential-bearing purposes get a withheld preview "
            "regardless of source text",
        )

    def test_searchable_terms_have_no_password_tokens(self):
        record = vu.build_understanding(
            _saved_login_list_text(), file_name="logins.txt",
        )
        for term in record["searchable_terms"]:
            for sentinel in SENTINELS:
                self.assertNotIn(
                    sentinel.lower(), term,
                    f"searchable_terms must not contain "
                    f"sentinel {sentinel!r}",
                )

    def test_entities_have_no_password_tokens(self):
        record = vu.build_understanding(
            _saved_login_list_text(), file_name="logins.txt",
        )
                                                               
                                                               
        names = record["entities"]["names"]
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, names)


class StatusHelpersTests(unittest.TestCase):
    def test_normalize_unknown_falls_back_to_pending(self):
        self.assertEqual(
            vu.normalize_understanding_status(None), "pending",
        )
        self.assertEqual(
            vu.normalize_understanding_status("xxx"), "pending",
        )

    def test_normalize_passthrough_for_known(self):
        for s in vu.UNDERSTANDING_STATUSES:
            self.assertEqual(vu.normalize_understanding_status(s), s)

    def test_is_terminal(self):
        self.assertTrue(vu.is_terminal_understanding_status("ready"))
        self.assertTrue(vu.is_terminal_understanding_status("failed"))
        self.assertTrue(vu.is_terminal_understanding_status("unsupported"))
        self.assertFalse(vu.is_terminal_understanding_status("pending"))
        self.assertFalse(vu.is_terminal_understanding_status("stale"))


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_exists_and_drains_via_claim(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw.drain_file_understanding)
        self.assertIn("claim_next_analysis_job", src)
                                                                   
                                                                 
        mod_src = inspect.getsource(vuw)
        self.assertIn("STAGE_FILE_UNDERSTANDING", mod_src)
        self.assertIn("_HANDLED_STAGE", src)

    def test_worker_calls_classifier_and_builder(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
        self.assertIn("classify_document_purpose", src)
        self.assertIn("build_understanding", src)
        self.assertIn("upsert_understanding", src)

    def test_worker_encrypts_summary_before_persist(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
                                                              
                                                               
        encrypt_idx = src.find("encrypt_message")
        last_upsert_idx = src.rfind("upsert_understanding")
        self.assertGreater(encrypt_idx, -1)
        self.assertGreater(last_upsert_idx, -1)
        self.assertLess(
            encrypt_idx, last_upsert_idx,
            "summary MUST be encrypted before being upserted on "
            "the success path — the CHECK constraint refuses "
            "plaintext, but defence-in-depth still requires the "
            "order in source",
        )

    def test_worker_drops_plaintext_after_use(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
                                                              
                                                            
        self.assertIn(
            'plaintext = None',
            src,
            "the worker must drop the decrypted plaintext "
            "reference once the in-memory record is built — "
            "minimises the secret-in-memory window",
        )


class TextExtractionEnqueuesUnderstandingTests(unittest.TestCase):
    def test_text_extraction_worker_enqueues_understanding_after_success(self):
        import vault_analysis_worker as vaw
        src = inspect.getsource(vaw._process_one_text_extraction_job)
                                                        
                                                             
        analyzed_idx = src.find("mark_file_analysis_analyzed")
        enqueue_idx = src.find("enqueue_understanding_after_text_extraction")
        self.assertGreater(analyzed_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(
            analyzed_idx, enqueue_idx,
            "text-extraction success must come BEFORE the "
            "understanding enqueue — otherwise a failed "
            "extraction could spawn an understanding job with "
            "no text to read",
        )


class CoverageFormatterTests(unittest.TestCase):
    def test_format_zero_files(self):
        text = vu.format_coverage_for_chat({"total_files": 0})
        self.assertIn("haven't analyzed any files", text)

    def test_format_partial_coverage(self):
        text = vu.format_coverage_for_chat({
            "total_files": 425,
            "files_understood": 194,
            "files_pending": 0,
            "files_text_only": 0,
            "files_needing_ocr": 100,
            "files_needing_transcription": 131,
            "files_unsupported": 0,
        })
        self.assertIn("194 of 425", text)
        self.assertIn("OCR/transcription", text)

    def test_format_full_coverage_no_bits(self):
        text = vu.format_coverage_for_chat({
            "total_files": 10,
            "files_understood": 10,
            "files_pending": 0,
            "files_text_only": 0,
            "files_needing_ocr": 0,
            "files_needing_transcription": 0,
            "files_unsupported": 0,
        })
        self.assertIn("10 of 10", text)

    def test_format_pending_surfaces_pending(self):
        text = vu.format_coverage_for_chat({
            "total_files": 5,
            "files_understood": 2,
            "files_pending": 3,
            "files_text_only": 0,
            "files_needing_ocr": 0,
            "files_needing_transcription": 0,
            "files_unsupported": 0,
        })
        self.assertIn("3 pending", text)


class AnalyzeFileReadsUnderstandingTests(unittest.TestCase):
    def test_chat_analyze_file_branch_reads_understanding_first(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        analyze_idx = src.find('intent == "analyze_file"')
        self.assertGreater(analyze_idx, -1)
                                                               
                 
        branch_src = src[analyze_idx:analyze_idx + 4000]
        self.assertIn(
            "get_understanding_for_file",
            branch_src,
            "analyze_file MUST read the persisted understanding "
            "row before falling back to on-demand classification",
        )

    def test_chat_drain_runs_understanding_after_text_extraction(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        text_drain_idx = src.find("drain_text_extraction")
        understanding_drain_idx = src.find("drain_file_understanding")
        self.assertGreater(text_drain_idx, -1)
        self.assertGreater(understanding_drain_idx, -1)
        self.assertLess(
            text_drain_idx, understanding_drain_idx,
            "the understanding drain must run AFTER text "
            "extraction so freshly-extracted text produces an "
            "understanding row in the SAME chat turn",
        )


class SearchInputsTests(unittest.TestCase):
    def test_searchable_terms_carry_topics_and_categories(self):
        record = vu.build_understanding(
            _wells_fargo_finance_doc(), file_name="statement.pdf",
        )
        terms = record["searchable_terms"]
                                                        
        self.assertIn("finance", terms)

    def test_filename_only_match_is_a_weak_signal(self):
                                                                 
                                                             
        record = vu.build_understanding(
            "Random unrelated content " * 20,
            file_name="passwords.txt",
        )
                                                
        self.assertNotIn("credentials", record["topics"])
                             
        self.assertIn(
            record["document_purpose"],
            (vp.PURPOSE_GENERIC_TEXT, vp.PURPOSE_UNKNOWN),
        )


class SafetyTests(unittest.TestCase):
    def test_worker_does_not_touch_vault_items_table(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw)
                                                              
                                                 
        for forbidden in (
            "INSERT INTO vault_items",
            "vault_items",
        ):
            self.assertNotIn(
                forbidden, src,
                f"worker MUST NOT touch {forbidden} — "
                "understanding analysis must never auto-create "
                "saved logins",
            )

    def test_builder_never_executes_user_content(self):
        import vault_understanding as vu_mod
        src = inspect.getsource(vu_mod)
                                                                
                                                               
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(
                forbidden, src,
                f"builder MUST NOT use {forbidden} on user "
                "content — uploaded scripts must be read as "
                "text only",
            )

    def test_worker_logs_do_not_include_plaintext(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw)
                                                         
                                                          
        for forbidden in ('logger.info("%s", plaintext',
                          'logger.info("%s", record',
                          'logger.info("%s", record["summary"]'):
            self.assertNotIn(forbidden, src)

    def test_mark_understanding_failed_scrubs_passwords(self):
                                                               
                                                               
        scrubbed = va._truncate_error(
            "DB write failed: password: hunter2 token=SECRET_VALUE"
        )
        self.assertIn("password=<redacted>", scrubbed)
        self.assertNotIn("hunter2", scrubbed)
        self.assertNotIn("SECRET_VALUE", scrubbed)


class StatusEnumAgreesWithMigrationTests(unittest.TestCase):
    def test_python_enum_matches_migration_check(self):
        src = _migration_0007_source()
        for status in vu.UNDERSTANDING_STATUSES:
            self.assertTrue(
                f'"{status}"' in src or f"'{status}'" in src,
                f"migration must declare status {status!r}",
            )


if __name__ == "__main__":
    unittest.main()
