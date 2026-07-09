

from __future__ import annotations

import json
import unittest

from vault_deep_answer import (
    DEEP_ANSWER_STATUS_FAILED,
    DEEP_ANSWER_STATUS_READY,
    DEEP_ANSWER_STATUS_SCANNING,
    DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    DEFAULT_MAX_WALLCLOCK_SECONDS,
    _is_honestly_complete,
    build_coverage_report,
    debug_job_snapshot,
    reset_jobs_for_tests,
    safe_job_snapshot,
    start_or_resume_job,
    step_deep_answer,
)


def _coverage_zero_of_425_not_started():


    return {
        "total":            425,
        "analyzed":         0,
        "pending":          0,
        "processing":       0,
        "failed":           0,
        "unsupported":      0,
        "not_started":      425,
        "needs_reanalysis": 0,
        "skipped":          0,
    }


def _coverage_with_pending(scanned=0, pending=425):
    return {
        "total":            scanned + pending,
        "analyzed":         scanned,
        "pending":          pending,
        "processing":       0,
        "failed":           0,
        "unsupported":      0,
        "not_started":      0,
        "needs_reanalysis": 0,
        "skipped":          0,
    }


def _coverage_loader(*payloads):


    state = {"i": 0}

    def _loader():
        if state["i"] < len(payloads):
            v = payloads[state["i"]]
            state["i"] += 1
            return v
        return payloads[-1]

    return _loader


def _stub_drain(processed=0, succeeded=0, failed=0):
    calls = []

    def _drain(*, vault_id, key, max_jobs):
        calls.append({
            "vault_id": vault_id, "max_jobs": max_jobs,
        })
        return {
            "processed": processed,
            "succeeded": succeeded,
            "failed":    failed,
        }
    _drain.calls = calls
    return _drain


def _stub_final(payload):
    def _final(*, vault_id, key, intent, query):
        return payload
    return _final


def _stub_enqueue_missing(enqueued=425, error=None):
    calls = []

    def _enq(vault_id):
        calls.append({"vault_id": vault_id})
        return {
            "enqueued":   enqueued,
            "considered": enqueued,
            "by_stage":   {"text_extraction": enqueued},
            "error":      error,
        }
    _enq.calls = calls
    return _enq


class SilentFinalizeRegressionTests(unittest.TestCase):


    def setUp(self):
        reset_jobs_for_tests()

    def test_is_honestly_complete_is_false_at_zero_of_425(self):
                                                                    
        coverage = build_coverage_report(
            _coverage_with_pending(scanned=0, pending=425),
        )
        self.assertFalse(_is_honestly_complete(coverage))

    def test_is_honestly_complete_is_false_when_not_started_only(self):
        coverage = build_coverage_report(
            _coverage_zero_of_425_not_started(),
        )
        self.assertFalse(
            _is_honestly_complete(coverage),
            "not_started rolls into pending — scan is NOT complete",
        )

    def test_is_honestly_complete_is_true_for_empty_vault(self):
        coverage = build_coverage_report({"total": 0})
        self.assertTrue(_is_honestly_complete(coverage))

    def test_is_honestly_complete_is_true_when_all_files_terminal(self):
        coverage = build_coverage_report({
            "total": 10, "analyzed": 7, "unsupported": 2, "failed": 1,
        })
        self.assertTrue(_is_honestly_complete(coverage))

    def test_build_coverage_report_scan_complete_is_false_at_0_of_425(self):
        coverage = build_coverage_report(
            _coverage_with_pending(scanned=0, pending=425),
        )
        self.assertFalse(
            coverage["scan_complete"],
            "scan_complete MUST be False when scanned=0 + pending>0",
        )

    def test_step_at_0_of_425_does_NOT_flip_to_ready(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                                 
                                                                
        loader = _coverage_loader(
            _coverage_zero_of_425_not_started(),
            _coverage_zero_of_425_not_started(),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={},                                              
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
                                                                     
                                       
        )
        self.assertEqual(
            job.status, DEEP_ANSWER_STATUS_SCANNING,
            "engine must NOT flip to ready when scanned=0 + total>0",
        )

    def test_step_at_0_of_425_records_blocker_reason(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                               
                                               
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=425),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
                                                                   
                                    
        reason = job.progress.get("blocker_reason")
        self.assertIsNotNone(reason)
        self.assertTrue(
            reason.startswith("no_worker_registered:")
            or reason == "queue_empty_but_coverage_pending"
            or reason in {
                "scan_not_started_no_files_processed_yet",
                "scan_stalled_no_progress",
            },
            f"unexpected blocker_reason={reason!r}",
        )


class EnqueueMissingTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_step_calls_enqueue_missing_fn_when_not_started_present(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_zero_of_425_not_started(),
                                                                
            _coverage_with_pending(scanned=0, pending=425),
            _coverage_with_pending(scanned=0, pending=425),
        )
        drain = _stub_drain(processed=6, succeeded=6, failed=0)
        enq = _stub_enqueue_missing(enqueued=425)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            enqueue_missing_fn=enq,
        )
        self.assertEqual(len(enq.calls), 1)
        self.assertEqual(job.progress["jobs_enqueued"], 425)

    def test_step_calls_enqueue_when_pending_present_for_orphan_check(self):
                                                                   
                                                                
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=100),
            _coverage_with_pending(scanned=0, pending=100),
        )
        drain = _stub_drain(processed=6, succeeded=6)
                                                                     
        enq = _stub_enqueue_missing(enqueued=0)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            enqueue_missing_fn=enq,
        )
        self.assertEqual(
            len(enq.calls), 1,
            "engine must ALWAYS ask the helper when pending > 0 — "
            "the orphan case (files pending without queue rows) "
            "looks the same as ordinary pending until the helper "
            "checks",
        )
        self.assertEqual(job.progress["jobs_enqueued"], 0)

    def test_step_skips_enqueue_when_nothing_pending_or_not_started(self):
                                                               
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            {"total": 10, "analyzed": 10},
            {"total": 10, "analyzed": 10},
        )
        enq = _stub_enqueue_missing(enqueued=999)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain()},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            enqueue_missing_fn=enq,
        )
        self.assertEqual(len(enq.calls), 0)

    def test_enqueue_error_becomes_blocker_reason(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_zero_of_425_not_started(),
            _coverage_zero_of_425_not_started(),
        )
        enq = _stub_enqueue_missing(enqueued=0, error="db_unavailable")
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            enqueue_missing_fn=enq,
        )
        self.assertEqual(
            job.progress.get("blocker_reason"), "db_unavailable",
            "an enqueue helper error must surface as blocker_reason",
        )


class StepBookkeepingTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_progress_carries_coverage_before_and_after(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4, succeeded=4)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        self.assertIn("coverage_before", job.progress)
        self.assertIn("coverage_after", job.progress)
                                            
        self.assertEqual(job.progress["coverage_before"]["scanned"], 0)
        self.assertEqual(job.progress["coverage_after"]["scanned"], 4)

    def test_progress_carries_last_stage_attempted(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4, succeeded=4)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        self.assertEqual(
            job.progress.get("last_stage_attempted"), "text_extraction",
        )

    def test_progress_carries_registered_drain_functions(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={
                "text_extraction": _stub_drain(processed=4, succeeded=4),
                "ocr":             _stub_drain(),
            },
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        registered = job.progress.get("registered_drain_functions") or []
        self.assertIn("text_extraction", registered)
        self.assertIn("ocr", registered)

    def test_progress_carries_lifetime_counters(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4, succeeded=4, failed=0)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            enqueue_missing_fn=_stub_enqueue_missing(enqueued=0),
        )
        self.assertEqual(job.progress["jobs_claimed"], 4)
        self.assertEqual(job.progress["jobs_completed"], 4)
        self.assertEqual(job.progress["jobs_failed"], 0)

    def test_lifetime_counters_accumulate_across_steps(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
            _coverage_with_pending(scanned=4, pending=6),
            _coverage_with_pending(scanned=8, pending=2),
        )
        drain = _stub_drain(processed=4, succeeded=4)
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        first_claimed = job.progress["jobs_claimed"]
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": drain},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        self.assertGreater(
            job.progress["jobs_claimed"], first_claimed,
            "lifetime counters must accumulate across steps",
        )

    def test_pending_by_stage_present(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        self.assertIn("pending_by_stage", job.progress)


class WallclockFailurePathTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_wallclock_with_zero_scanned_transitions_to_failed(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                  
        import time as _time
        job.started_at = _time.time() - 5 * 60.0
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=425),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={},              
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            max_wallclock_seconds=DEFAULT_MAX_WALLCLOCK_SECONDS,
        )
        self.assertEqual(
            job.status, DEEP_ANSWER_STATUS_FAILED,
            "wallclock-cap with 0 scanned MUST fail, not silent-finalize",
        )
        self.assertEqual(
            job.error, "scan_timed_out_no_files_processed",
        )

    def test_wallclock_with_some_scanned_still_finalizes_ready(self):
                                                                 
                                                                   
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        import time as _time
        job.started_at = _time.time() - 5 * 60.0
        loader = _coverage_loader(
            _coverage_with_pending(scanned=200, pending=225),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
            max_wallclock_seconds=DEFAULT_MAX_WALLCLOCK_SECONDS,
        )
        self.assertEqual(job.status, DEEP_ANSWER_STATUS_READY)


class DebugSnapshotTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def _job_after_one_step(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = _coverage_loader(
            _coverage_with_pending(scanned=0, pending=10),
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4, succeeded=4)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        return job

    def test_debug_snapshot_carries_required_fields(self):
        job = self._job_after_one_step()
        debug = debug_job_snapshot(job)
        for field in [
            "job_id", "vault_id", "intent", "status", "error",
            "elapsed_seconds",
            "coverage_before", "coverage_after",
            "last_stage_attempted", "blocker_reason",
            "no_progress_polls",
            "jobs_enqueued", "jobs_claimed", "jobs_completed",
            "jobs_failed",
            "registered_drain_functions", "pending_by_stage",
        ]:
            self.assertIn(field, debug)

    def test_debug_snapshot_is_json_serialisable(self):
        job = self._job_after_one_step()
        json.dumps(debug_job_snapshot(job))                  

    def test_debug_snapshot_never_carries_credential_values(self):
                                                                 
                                                           
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                            
        job.results = {
            "envelope": {
                "password": "hunter2leak",
                "token":    "tok-leak-99",
                "extracted_text": "Cmd-Z secret-pin-1234",
            },
        }
        job.status = DEEP_ANSWER_STATUS_READY
                                                  
        loader = _coverage_loader(
            _coverage_with_pending(scanned=4, pending=6),
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": _stub_drain(processed=4, succeeded=4)},
            final_results_fn=_stub_final({"envelope": {"type": "x"}}),
        )
        debug = debug_job_snapshot(job)
        raw = json.dumps(debug)
        self.assertNotIn("hunter2leak", raw)
        self.assertNotIn("tok-leak-99", raw)
        self.assertNotIn("secret-pin-1234", raw)
                                                               
                                                             
        self.assertNotIn("results", debug)
        self.assertNotIn("envelope", debug)

    def test_debug_snapshot_closed_set_keys_only(self):
        job = self._job_after_one_step()
        debug = debug_job_snapshot(job)
        allowed = {
            "job_id", "vault_id", "intent", "status", "error",
            "elapsed_seconds",
            "coverage_before", "coverage_after",
            "last_stage_attempted", "blocker_reason",
            "no_progress_polls",
            "jobs_enqueued", "jobs_claimed", "jobs_completed",
            "jobs_failed",
            "registered_drain_functions", "pending_by_stage",
        }
        self.assertEqual(set(debug.keys()), allowed)


class SafeJobSnapshotRegressionTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_results_only_present_when_status_ready(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        job.results = {"envelope": {"type": "credential_files"}}
        job.status = DEEP_ANSWER_STATUS_SCANNING
        snap = safe_job_snapshot(job)
        self.assertIsNone(snap["results"])


class RouteWiringTests(unittest.TestCase):
    def test_debug_endpoint_registered(self):
        from routes import deep_answer_routes
                                                       
        paths = [r.path for r in deep_answer_routes.router.routes]
        self.assertIn("/vault-analysis/deep-answer/{job_id}/debug", paths)

    def test_enqueue_missing_fn_is_imported(self):
        from routes import deep_answer_routes
        self.assertTrue(hasattr(deep_answer_routes, "_enqueue_missing_fn"))
                                                                
                                                                  
        out = deep_answer_routes._enqueue_missing_fn("not-a-vault")
        self.assertIsInstance(out, dict)
        self.assertIn("enqueued", out)


if __name__ == "__main__":
    unittest.main()
