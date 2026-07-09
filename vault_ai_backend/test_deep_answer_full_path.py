

from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from vault_deep_answer import (
    DEEP_ANSWER_STATUS_READY,
    DEEP_ANSWER_STATUS_SCANNING,
    DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    debug_job_snapshot,
    reset_jobs_for_tests,
    start_or_resume_job,
    step_deep_answer,
)


class _FakeVaultState:


    def __init__(self, *, total: int):
        self.total = total
                                                               
                                          
        self.files = {f"f{i}": "not_started" for i in range(total)}
                                                                
        self.jobs: dict[str, str] = {}

                                
    def coverage(self) -> dict:
        analyzed = sum(1 for s in self.files.values() if s == "analyzed")
        pending = sum(1 for s in self.files.values() if s == "pending")
        processing = sum(1 for s in self.files.values() if s == "processing")
        failed = sum(1 for s in self.files.values() if s == "failed")
        not_started = sum(
            1 for s in self.files.values() if s == "not_started"
        )
        unsupported = sum(
            1 for s in self.files.values() if s == "unsupported"
        )
        return {
            "total": self.total,
            "analyzed": analyzed,
            "pending": pending,
            "processing": processing,
            "failed": failed,
            "unsupported": unsupported,
            "not_started": not_started,
            "needs_reanalysis": 0,
            "skipped": 0,
        }

                                     
    def enqueue_missing(self, vault_id: str) -> dict:
        enqueued = 0
        for fid, status in list(self.files.items()):
            if status not in ("not_started", "needs_reanalysis"):
                continue
            if fid in self.jobs:
                continue
            self.jobs[fid] = "text_extraction"
            self.files[fid] = "pending"
            enqueued += 1
        return {
            "enqueued": enqueued, "considered": enqueued,
            "by_stage": {"text_extraction": enqueued},
            "error": None,
        }

                            
    def drain_text_extraction(self, *, vault_id, key, max_jobs):
        succeeded = 0
        for _ in range(max_jobs):
                                                
            for fid, status in self.files.items():
                if status == "pending" and fid in self.jobs:
                    self.files[fid] = "analyzed"
                    del self.jobs[fid]
                    succeeded += 1
                    break
            else:
                break
        return {
            "processed": succeeded, "succeeded": succeeded, "failed": 0,
        }


def _make_engine_collaborators(state: _FakeVaultState, *,
                                drain_fn=None):


    def _loader():
        return state.coverage()

    def _final(*, vault_id, key, intent, query):
        return {"envelope": {"type": "credential_files", "files": []}}

    drains = {"text_extraction": drain_fn or state.drain_text_extraction}
    return {
        "coverage_loader":    _loader,
        "drain_fns":          drains,
        "final_results_fn":   _final,
        "enqueue_missing_fn": state.enqueue_missing,
    }


class EnqueueFromNotStartedTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_ten_not_started_files_become_ten_queue_rows(self):
        state = _FakeVaultState(total=10)
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        collab = _make_engine_collaborators(state)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            **collab,
        )
                                                           
                                                                 
        self.assertEqual(job.progress["jobs_enqueued"], 10)
        self.assertGreater(job.progress["jobs_claimed"], 0)
        self.assertGreater(state.coverage()["analyzed"], 0,
            "analyzed coverage must advance once the drain runs")


class PollClaimsAndAdvancesCoverageTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_poll_claims_at_least_one_job(self):
        state = _FakeVaultState(total=5)
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        collab = _make_engine_collaborators(state)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32, **collab,
        )
        self.assertGreater(
            job.progress["jobs_claimed"], 0,
            "at least one queue row must be claimed per poll",
        )

    def test_after_poll_jobs_completed_increases(self):
        state = _FakeVaultState(total=5)
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        before = job.progress.get("jobs_completed", 0)
        collab = _make_engine_collaborators(state)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32, **collab,
        )
        self.assertGreater(
            job.progress["jobs_completed"], before,
            "jobs_completed must advance after a successful drain",
        )

    def test_after_poll_coverage_analyzed_count_advances(self):
        state = _FakeVaultState(total=5)
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        before = state.coverage()["analyzed"]
        collab = _make_engine_collaborators(state)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32, **collab,
        )
        after = state.coverage()["analyzed"]
        self.assertGreater(
            after, before, "analyzed coverage MUST move after a drain",
        )


class JobsEnqueuedButNotClaimedTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_no_worker_registered_blocker(self):
        state = _FakeVaultState(total=3)
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                               
                                            
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=state.coverage,
            drain_fns={},
            final_results_fn=lambda **_: {"envelope": {"type": "x"}},
            enqueue_missing_fn=state.enqueue_missing,
        )
        reason = job.progress.get("blocker_reason") or ""
        self.assertTrue(
            reason.startswith("no_worker_registered:"),
            f"expected no_worker_registered:* blocker, got {reason!r}",
        )

    def test_drain_returns_zero_blocker(self):
                                                                      
                                                                    
        state = _FakeVaultState(total=3)
                                                                
                                               
        state.files = {fid: "pending" for fid in state.files}

        def _stuck_drain(*, vault_id, key, max_jobs):
            return {"processed": 0, "succeeded": 0, "failed": 0}

                                                             
        def _enq(vault_id):
            return {"enqueued": 0, "by_stage": {}, "error": None}

        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=state.coverage,
            drain_fns={"text_extraction": _stuck_drain},
            final_results_fn=lambda **_: {"envelope": {"type": "x"}},
            enqueue_missing_fn=_enq,
        )
        self.assertEqual(
            job.progress.get("blocker_reason"),
            "files_pending_but_drains_returned_zero",
        )


class ClaimedButFailedTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_failed_drain_surfaces_jobs_failed_on_debug_snapshot(self):
        state = _FakeVaultState(total=2)

        def _failing_drain(*, vault_id, key, max_jobs):
            return {"processed": 2, "succeeded": 0, "failed": 2}

        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        collab = _make_engine_collaborators(state, drain_fn=_failing_drain)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32, **collab,
        )
        snap = debug_job_snapshot(job)
        self.assertEqual(snap["jobs_failed"], 2)
        self.assertEqual(snap["jobs_completed"], 0)
        self.assertEqual(snap["jobs_claimed"], 2)


class EnqueueSqlColumnsGuardTests(unittest.TestCase):


    def test_enqueue_helper_uses_uf_id_not_uf_file_id(self):
        import vault_analysis
        src = inspect_module_source(vault_analysis)
                                                                      
                                                            
        self.assertIn("uf.id", src)

    def test_enqueue_helper_uses_uf_file_name(self):
        import vault_analysis
        src = inspect_module_source(vault_analysis)
        self.assertIn("uf.file_name", src)

    def test_enqueue_helper_does_NOT_reference_encrypted_file_name(self):
                                                                  
                                                       
        import vault_analysis
        src = inspect_module_source(vault_analysis)
        self.assertNotIn("encrypted_file_name", src)

    def test_enqueue_helper_does_NOT_reference_file_extension(self):
                                                         
        import vault_analysis
        src = inspect_module_source(vault_analysis)
        self.assertNotIn("uf.file_extension", src)

    def test_enqueue_helper_filters_for_pending_orphans(self):
                                                                 
                                                               
        import vault_analysis
        src = inspect_module_source(vault_analysis)
                                                                 
        self.assertIn("ANALYSIS_STATUS_PENDING", src)


class MultiStageDrainTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_engine_attempts_ocr_when_text_drain_returns_zero(self):
                                                                  
                                                                
        text_calls = []
        ocr_calls = []

        def _text_drain(*, vault_id, key, max_jobs):
            text_calls.append(1)
            return {"processed": 0, "succeeded": 0, "failed": 0}

        def _ocr_drain(*, vault_id, key, max_jobs):
            ocr_calls.append(1)
            return {"processed": 3, "succeeded": 3, "failed": 0}

        def _loader():
            return {"total": 5, "analyzed": 0, "pending": 5}

        def _enq(vault_id):
            return {"enqueued": 0, "by_stage": {}, "error": None}

        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=_loader,
            drain_fns={
                "text_extraction": _text_drain,
                "ocr":             _ocr_drain,
            },
            final_results_fn=lambda **_: {"envelope": {"type": "x"}},
            enqueue_missing_fn=_enq,
        )
        self.assertEqual(len(text_calls), 1)
        self.assertEqual(len(ocr_calls), 1,
            "engine MUST attempt OCR when text returned zero — the "
            "single-drain bug stalled OCR-only queues")


class DebugScriptTests(unittest.TestCase):


    def test_script_imports_clean(self):
        from scripts import debug_deep_scan        
        self.assertTrue(hasattr(debug_deep_scan, "main"))
        self.assertTrue(hasattr(debug_deep_scan, "_verdict"))
        self.assertTrue(hasattr(debug_deep_scan, "CLOSED_SET_REASONS"))

    def test_verdict_closed_set(self):
        from scripts.debug_deep_scan import CLOSED_SET_REASONS
        for code in [
            "ok_engine_can_process",
            "empty_vault_no_files_to_scan",
            "all_files_terminal",
            "no_worker_registered",
            "files_pending_but_no_queue_rows",
            "queue_rows_for_unregistered_stage",
            "all_files_in_not_started",
            "all_files_missing_extracted_text",
            "db_unavailable",
            "unknown",
        ]:
            self.assertIn(code, CLOSED_SET_REASONS)

    def test_verdict_empty_vault(self):
        from scripts.debug_deep_scan import _verdict
        v = _verdict(
            coverage={"total": 0},
            jobs_by_status={}, jobs_by_stage={},
            registered=["text_extraction"], required=["text_extraction"],
        )
        self.assertEqual(v, "empty_vault_no_files_to_scan")

    def test_verdict_no_worker_registered(self):
        from scripts.debug_deep_scan import _verdict
        v = _verdict(
            coverage={"total": 5, "pending": 5},
            jobs_by_status={"pending": 5},
            jobs_by_stage={"text_extraction": 5},
            registered=[], required=["text_extraction"],
        )
        self.assertEqual(v, "no_worker_registered")

    def test_verdict_files_pending_but_no_queue_rows(self):
        from scripts.debug_deep_scan import _verdict
        v = _verdict(
            coverage={"total": 5, "pending": 5},
            jobs_by_status={},                 
            jobs_by_stage={},
            registered=["text_extraction"], required=["text_extraction"],
        )
        self.assertEqual(v, "files_pending_but_no_queue_rows")

    def test_verdict_queue_rows_for_unregistered_stage(self):
        from scripts.debug_deep_scan import _verdict
        v = _verdict(
            coverage={"total": 5, "pending": 5},
            jobs_by_status={"pending": 5},
            jobs_by_stage={"ocr": 5},                        
            registered=["text_extraction"], required=["text_extraction", "ocr"],
        )
                                                                             
        self.assertEqual(v, "queue_rows_for_unregistered_stage")

    def test_verdict_ok_when_everything_aligned(self):
        from scripts.debug_deep_scan import _verdict
        v = _verdict(
            coverage={"total": 10, "analyzed": 5, "pending": 5},
            jobs_by_status={"pending": 5},
            jobs_by_stage={"text_extraction": 5},
            registered=["text_extraction"], required=["text_extraction"],
        )
        self.assertEqual(v, "ok_engine_can_process")

    def test_script_json_output_carries_no_credential_values(self):
                                                               
                                                  
        sentinels = ["hunter2leak", "tok-leak-99", "pin-leak-1234"]

        with patch("vault_analysis.analysis_coverage_for_vault") as cov, \
             patch("scripts.debug_deep_scan._query_job_breakdown") as jb, \
             patch("scripts.debug_deep_scan._query_extracted_text_counts") as etc, \
             patch("scripts.debug_deep_scan._query_recent_failed_jobs") as rfj:
            cov.return_value = {"total": 5, "analyzed": 5}
            jb.return_value  = ({"succeeded": 5}, {"text_extraction": 5},
                                {"text_extraction": {"succeeded": 5}}, 5)
            etc.return_value = {
                "files_with_extracted_text": 5,
                "pdfs_with_extracted_text": 2,
                "pdfs_total": 2,
                "images_total": 0,
                "scanned_pdf_candidates_for_ocr": 0,
            }
            rfj.return_value = [{
                                                                  
                                                                
                "job_id": "abc", "stage": "text_extraction",
                "attempts": 1, "max_attempts": 3,
                "last_error":
                    "decrypt failed: " + " ".join(sentinels),
                "completed_at": "2026-06-10T00:00:00",
            }]

            buf = io.StringIO()
            from scripts.debug_deep_scan import main
            with redirect_stdout(buf):
                rc = main(["--vault-id", "v1", "--json"])
            self.assertEqual(rc, 0)
            payload = buf.getvalue()

                                                                  
            data = json.loads(payload)
                                                               
                                                      
            for k in data:
                self.assertNotIn("password", k.lower())
                self.assertNotIn("token", k.lower())

    def test_script_text_output_keys_never_include_secrets(self):
                                                               
                                                                 
        with patch("vault_analysis.analysis_coverage_for_vault") as cov, \
             patch("scripts.debug_deep_scan._query_job_breakdown") as jb, \
             patch("scripts.debug_deep_scan._query_extracted_text_counts") as etc, \
             patch("scripts.debug_deep_scan._query_recent_failed_jobs") as rfj:
            cov.return_value = {"total": 5, "analyzed": 5}
            jb.return_value  = ({"succeeded": 5}, {"text_extraction": 5}, {}, 5)
            etc.return_value = {
                "files_with_extracted_text": 5,
                "pdfs_with_extracted_text": 2,
                "pdfs_total": 2, "images_total": 0,
                "scanned_pdf_candidates_for_ocr": 0,
            }
            rfj.return_value = []

            buf = io.StringIO()
            from scripts.debug_deep_scan import main
            with redirect_stdout(buf):
                rc = main(["--vault-id", "v1"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()

                                                                  
            for forbidden in ("Password:", "Token:", "Secret:"):
                self.assertNotIn(forbidden, out)


def inspect_module_source(mod) -> str:
    import inspect
    return inspect.getsource(mod)


if __name__ == "__main__":
    unittest.main()
