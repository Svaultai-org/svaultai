

from __future__ import annotations

import json
import time
import unittest

from vault_deep_answer import (
    DEEP_ANSWER_STATUS_READY,
    DEEP_ANSWER_STATUS_SCANNING,
    DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    DEEP_INTENT_SEARCH_FILES_ABOUT,
    DEEP_INTENT_LIST_BY_TAG,
    DEEP_INTENT_TRAVEL_READINESS,
    DEEP_REQUIRED_INTENTS,
    STAGE_LABELS,
    build_coverage_report,
    get_job,
    is_deep_intent,
    progress_message,
    required_stages_for_intent,
    reset_jobs_for_tests,
    safe_job_snapshot,
    start_or_resume_job,
    step_deep_answer,
)


class IntentGatingTests(unittest.TestCase):
    def test_credential_search_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("search_files_for_credentials"))

    def test_find_files_about_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("search_files_about"))

    def test_list_by_tag_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("list_by_tag"))

    def test_travel_readiness_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("travel_readiness"))

    def test_related_files_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("related_files"))

    def test_vault_clusters_is_a_deep_intent(self):
        self.assertTrue(is_deep_intent("vault_clusters"))

    def test_save_login_is_not_a_deep_intent(self):
                                                                   
                                  
        self.assertFalse(is_deep_intent("save_login"))

    def test_unknown_intent_is_not_a_deep_intent(self):
        self.assertFalse(is_deep_intent("totally_made_up_intent"))
        self.assertFalse(is_deep_intent(""))
        self.assertFalse(is_deep_intent(None))


class RequiredStagesTests(unittest.TestCase):
    def test_credential_search_needs_every_text_producing_stage(self):
        stages = required_stages_for_intent(
            DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        )
        self.assertIn("text_extraction", stages)
        self.assertIn("ocr", stages)
        self.assertIn("archive_indexing", stages)
        self.assertIn("audio_transcription", stages)
        self.assertIn("video_transcription", stages)
                                                                  
                                 
        self.assertNotIn("file_embedding", stages)

    def test_find_files_about_needs_understanding_too(self):
        stages = required_stages_for_intent(DEEP_INTENT_SEARCH_FILES_ABOUT)
        self.assertIn("file_understanding", stages)

    def test_unknown_intent_falls_back_to_full_content_set(self):
        stages = required_stages_for_intent("never_seen_this_before")
                                                                        
                                                                     
        self.assertIn("text_extraction", stages)
        self.assertIn("file_understanding", stages)

    def test_every_required_stage_has_a_human_label(self):
                                                                      
                                                                
        all_required: set[str] = set()
        for intent in DEEP_REQUIRED_INTENTS:
            all_required.update(required_stages_for_intent(intent))
                                                                     
                                          
        missing = all_required - set(STAGE_LABELS.keys())
        self.assertEqual(missing, set(),
            f"required stages with no human label: {missing}")


class CoverageMathTests(unittest.TestCase):
    def test_empty_vault_is_scan_complete(self):
        report = build_coverage_report({"total": 0})
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["scanned"], 0)
        self.assertEqual(report["pending"], 0)

    def test_pending_blocks_scan_complete(self):
        report = build_coverage_report({
            "total": 10, "analyzed": 9, "pending": 1,
        })
        self.assertEqual(report["scanned"], 9)
        self.assertEqual(report["pending"], 1)
        self.assertFalse(report["scan_complete"])

    def test_unsupported_counts_toward_complete(self):
                                                                  
                           
        report = build_coverage_report({
            "total": 10, "analyzed": 8, "unsupported": 2,
        })
        self.assertTrue(report["scan_complete"])

    def test_failed_counts_toward_complete(self):
        report = build_coverage_report({
            "total": 5, "analyzed": 3, "failed": 2,
        })
        self.assertTrue(report["scan_complete"])

    def test_processing_blocks_complete(self):
        report = build_coverage_report({
            "total": 5, "analyzed": 3, "processing": 2,
        })
        self.assertFalse(report["scan_complete"])

    def test_not_started_rolls_into_pending(self):
        report = build_coverage_report({
            "total": 5, "analyzed": 0,
            "not_started": 3, "needs_reanalysis": 2,
        })
        self.assertEqual(report["pending"], 5)
        self.assertFalse(report["scan_complete"])

    def test_invalid_input_does_not_crash(self):
                                                                    
                                   
        report = build_coverage_report("not a dict")                          
        self.assertEqual(report["total"], 0)
        self.assertTrue(report["scan_complete"])


class ProgressMessageTests(unittest.TestCase):
    def test_credential_search_has_required_headline(self):
        msg = progress_message(
            build_coverage_report({
                "total": 256, "analyzed": 42, "pending": 200, "processing": 14,
            }),
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            stage_label="Reading files",
        )
                                                                
        self.assertIn(
            "Scanning your vault for files that contain saved credentials",
            msg,
        )
                                 
        self.assertIn("42 of 256", msg)
        self.assertIn("Reading files", msg)
                                                        
        self.assertNotIn("Deep Answer Mode", msg)
        self.assertNotIn("live", msg.lower().split())

    def test_remaining_fragment_shows_when_no_stage_label(self):
                                                                
                                                  
        msg = progress_message(
            build_coverage_report({
                "total": 256, "analyzed": 42, "pending": 200, "processing": 14,
            }),
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        )
        self.assertIn("214 files left to check", msg)

    def test_zero_scanned_shows_preparing(self):
                                                                
                                                                
        msg = progress_message(
            build_coverage_report({
                "total": 425, "analyzed": 0, "pending": 425,
            }),
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        )
        self.assertIn("Preparing scan", msg)
                                                                   
                                                  
        self.assertNotIn("0 of 425", msg)

    def test_scan_complete_uses_friendly_finalize_copy(self):
        msg = progress_message(
            build_coverage_report({"total": 10, "analyzed": 10}),
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        )
        self.assertIn("I scanned 10 files", msg)
        self.assertIn("Preparing results", msg)

    def test_other_intents_have_their_own_headline(self):
        msg = progress_message(
            build_coverage_report({"total": 10, "analyzed": 5, "pending": 5}),
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
        )
        self.assertIn("Scanning your vault for files about this topic", msg)

    def test_progress_never_carries_credential_values(self):
                                                                 
                                                                   
        msg = progress_message(
            build_coverage_report({
                "total": 10, "analyzed": 5, "pending": 5,
                "password": "hunter2-leak",
            }),
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        )
        self.assertNotIn("hunter2", msg)
        self.assertNotIn("hunter2-leak", msg)


class StepRunnerTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def _fake_coverage_sequence(self, *sequence):


        idx = [0]

        def _loader():
            i = idx[0]
            if i < len(sequence) - 1:
                idx[0] = i + 1
            return sequence[i]

        return _loader

    def _stub_drain(self, *, processed=2, succeeded=2, failed=0):
        calls = []

        def _drain(*, vault_id, key, max_jobs):
            calls.append({
                "vault_id": vault_id, "key_len": len(key), "max_jobs": max_jobs,
            })
            return {
                "processed": processed,
                "succeeded": succeeded,
                "failed":    failed,
                "drained_at": "stub",
            }
        _drain.calls = calls
        return _drain

    def _final_results_stub(self, payload):
        def _final(*, vault_id, key, intent, query):
            return payload
        return _final

    def test_step_drains_text_extraction_when_pending(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="show me files that have credentials saved in it",
        )
        drain_text = self._stub_drain(processed=4)
        loader = self._fake_coverage_sequence(
            {"total": 10, "analyzed": 6, "pending": 4},
            {"total": 10, "analyzed": 10},
        )
        final = self._final_results_stub({"envelope": {"type": "stub"}})

        result = step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain_text},
            final_results_fn=final,
        )

        self.assertEqual(len(drain_text.calls), 1)
                                                                      
                                                        
        self.assertEqual(job.status, DEEP_ANSWER_STATUS_READY)
        self.assertEqual(job.results, {"envelope": {"type": "stub"}})
        self.assertTrue(result.coverage["scan_complete"])

    def test_step_does_not_drain_when_already_scan_complete(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        drain_text = self._stub_drain(processed=0)
        loader = self._fake_coverage_sequence(
            {"total": 10, "analyzed": 10},
        )
        final = self._final_results_stub({"envelope": {"type": "stub"}})

        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain_text},
            final_results_fn=final,
        )

        self.assertEqual(len(drain_text.calls), 0,
            "drain must not run when scan is already complete")
        self.assertEqual(job.status, DEEP_ANSWER_STATUS_READY)

    def test_step_finalizes_at_wallclock_cap(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                                 
        job.started_at = time.time() - 200.0
        drain_text = self._stub_drain(processed=0)
        loader = self._fake_coverage_sequence(
            {"total": 10, "analyzed": 4, "pending": 6},
        )
        final = self._final_results_stub({"envelope": {"type": "stub"}})

        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain_text},
            final_results_fn=final,
            max_wallclock_seconds=90.0,
        )

        self.assertEqual(job.status, DEEP_ANSWER_STATUS_READY,
            "wallclock cap must transition to ready")

    def test_step_continues_when_drain_crashes(self):
                                                                
                                                                 
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )

        def _exploding_drain(*, vault_id, key, max_jobs):
            raise RuntimeError("boom")

        loader = self._fake_coverage_sequence(
            {"total": 10, "analyzed": 4, "pending": 6},
                                                                   
                                
            {"total": 10, "analyzed": 4, "pending": 6},
        )
        final = self._final_results_stub({"envelope": {"type": "stub"}})

        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _exploding_drain},
            final_results_fn=final,
        )
        self.assertEqual(job.status, DEEP_ANSWER_STATUS_SCANNING)

    def test_get_job_is_vault_scoped(self):
                                                                   
                                   
        job_a = start_or_resume_job(
            vault_id="vault-a", intent="search_files_for_credentials",
            query="",
        )
        self.assertIsNotNone(get_job("vault-a", job_a.job_id))
        self.assertIsNone(get_job("vault-b", job_a.job_id),
            "cross-vault lookup must miss")


class SnapshotSafetyTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_snapshot_hides_results_until_ready(self):
        job = start_or_resume_job(
            vault_id="v1", intent="search_files_for_credentials",
            query="",
        )
        job.results = {"envelope": {"sensitive": "ignored"}}
                                                      
        self.assertEqual(job.status, DEEP_ANSWER_STATUS_SCANNING)
        snap = safe_job_snapshot(job)
        self.assertIsNone(snap["results"])

    def test_snapshot_returns_closed_set_keys_only(self):
        job = start_or_resume_job(
            vault_id="v1", intent="search_files_for_credentials",
            query="show me files with credentials",
        )
        snap = safe_job_snapshot(job)
        self.assertEqual(
            set(snap.keys()),
            {
                "job_id", "vault_id", "intent", "query", "status",
                "progress", "results", "error", "elapsed_seconds",
            },
        )

    def test_snapshot_can_be_json_serialised(self):
        job = start_or_resume_job(
            vault_id="v1", intent="search_files_for_credentials",
            query="",
        )
                               
        json.dumps(safe_job_snapshot(job))


class FinalResultsSectionsTests(unittest.TestCase):


    def test_login_js_alone_is_filename_only_via_real_ranker(self):
        from vault_inventory import search_files_for_credentials_report

        rows = [
            {
                "id": "f-loginjs",
                "file_name": "login.js",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/javascript",
                "mime_type": "text/javascript",
                "asset_type": "file",
                "detected_service": "",
                "detected_type": "",
                                                     
                "extracted_text": (
                    "import React from 'react';\n"
                    "export function LoginForm() {\n"
                    "  return <form>...</form>;\n"
                    "}\n"
                ),
                "content_sha256": "sha-loginjs",
                "file_size": 100,
                "created_at": None,
                "needs_naming": False,
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertFalse(report["has_content_matches"])
        sections = report["sections"]
        self.assertEqual(sections["confirmed"], [])
        self.assertEqual(sections["possible"], [])
        self.assertEqual(len(sections["filename_only"]), 1)
        self.assertEqual(
            sections["filename_only"][0]["file_name"], "login.js",
        )

    def test_password_dump_is_confirmed_via_real_ranker(self):
        from vault_inventory import search_files_for_credentials_report

        rows = [
            {
                "id": "f-dump",
                "file_name": "passwords.txt",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/plain",
                "mime_type": "text/plain",
                "asset_type": "file",
                "detected_service": "",
                "detected_type": "",
                "extracted_text": (
                    "AOL\nalice@example.com\nMKSherm81765\n"
                    "American Express\nbob@example.com\nSpr1ng!2024\n"
                    "Apple\ncarol@example.com\nZ9q!Wp$73a\n"
                    "Gmail\ndan@example.com\nNoSp01l3rs#2024\n"
                ),
                "content_sha256": "sha-dump",
                "file_size": 200,
                "created_at": None,
                "needs_naming": False,
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertTrue(report["has_content_matches"])
        sections = report["sections"]
        self.assertEqual(len(sections["confirmed"]), 1)
        self.assertEqual(
            sections["confirmed"][0]["file_name"], "passwords.txt",
        )

    def test_html_password_form_is_not_confirmed(self):
        from vault_inventory import search_files_for_credentials_report

                                                                    
        rows = [
            {
                "id": "f-signup",
                "file_name": "signup-form.html",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/html",
                "mime_type": "text/html",
                "asset_type": "file",
                "detected_service": "",
                "detected_type": "",
                "extracted_text": (
                    "<form>\n"
                    "  <label>Email:</label><input type='email'>\n"
                    "  <label>Choose a password:</label>"
                    "<input type='password'>\n"
                    "  <button>Create account</button>\n"
                    "</form>\n"
                ),
                "content_sha256": "sha-signup",
                "file_size": 200,
                "created_at": None,
                "needs_naming": False,
            },
        ]
        report = search_files_for_credentials_report(rows)
        confirmed_names = [
            m["file_name"] for m in report["sections"]["confirmed"]
        ]
        self.assertNotIn("signup-form.html", confirmed_names)


if __name__ == "__main__":
    unittest.main()
