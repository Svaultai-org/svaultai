

from __future__ import annotations

import unittest

from vault_deep_answer import (
    DEEP_ANSWER_STATUS_READY,
    DEEP_ANSWER_STATUS_SCANNING,
    DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    DEEP_INTENT_SEARCH_FILES_ABOUT,
    _STALL_THRESHOLD_POLLS,
    _active_job_for,
    _normalize_query,
    reset_jobs_for_tests,
    safe_job_snapshot,
    start_or_resume_job,
    step_deep_answer,
)


class StartOrResumeJobDedupeTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_same_intent_same_query_returns_same_job_id(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        self.assertEqual(a.job_id, b.job_id,
            "second start MUST reuse the in-flight job, not create a "
            "new one — duplicate scan cards were the bug")

    def test_normalized_query_dedupes_across_casing_and_whitespace(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
            query="show me my Banking Documents",
        )
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
            query="  show me my   banking documents   ",
        )
        self.assertEqual(a.job_id, b.job_id)

    def test_existing_job_id_short_circuits_dedupe(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
            existing_job_id=a.job_id,
        )
        self.assertEqual(a.job_id, b.job_id)

    def test_different_vaults_get_distinct_jobs(self):
        a = start_or_resume_job(
            vault_id="vault-a",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        b = start_or_resume_job(
            vault_id="vault-b",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        self.assertNotEqual(a.job_id, b.job_id)

    def test_different_intents_get_distinct_jobs(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
            query="",
        )
        self.assertNotEqual(a.job_id, b.job_id)

    def test_different_queries_get_distinct_jobs(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
            query="banking documents",
        )
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_ABOUT,
            query="travel documents",
        )
        self.assertNotEqual(a.job_id, b.job_id)

    def test_terminal_job_does_NOT_dedupe_a_fresh_start(self):
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        a.status = DEEP_ANSWER_STATUS_READY                     
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        self.assertNotEqual(a.job_id, b.job_id,
            "terminal jobs must not steal new starts — the user is "
            "asking for a fresh scan, not a stale result")

    def test_active_job_for_returns_none_when_no_match(self):
        self.assertIsNone(_active_job_for(
            "v1", DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS, "",
        ))

    def test_active_job_for_finds_in_flight_job(self):
        created = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        found = _active_job_for(
            "v1", DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS, "",
        )
        self.assertIsNotNone(found)
        self.assertEqual(created.job_id, found.job_id)

    def test_normalize_query_collapses_whitespace_and_case(self):
        self.assertEqual(_normalize_query("  ShOw Me  Files  "),
            "show me files")
        self.assertEqual(_normalize_query(""), "")
        self.assertEqual(_normalize_query(None), "")

    def test_repeated_start_does_not_reset_progress(self):
                                                               
                                                                  
        a = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        a.progress = {"coverage": {"total": 10, "scanned": 4}}
        b = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        self.assertIs(a, b)
        self.assertEqual(b.progress["coverage"]["scanned"], 4,
            "dedupe MUST preserve in-flight progress; resetting to "
            "0 was the user-visible bug")


class StallBlockerReasonTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def _stub_loader(self, coverage):

        def _loader():
            return coverage
        return _loader

    def _stub_drain(self):
        def _drain(*, vault_id, key, max_jobs):
            return {"processed": 0, "succeeded": 0, "failed": 0}
        return _drain

    def _stub_final(self):
        def _final(*, vault_id, key, intent, query):
            return {"envelope": {"type": "stub"}}
        return _final

    def _enq_stub(self, enqueued=0):
        def _enq(vault_id):
            return {"enqueued": enqueued, "by_stage": {}, "error": None}
        return _enq

    def test_blocker_reason_set_immediately_when_drains_return_zero(self):
                                                                        
                                                                   
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = self._stub_loader(
            {"total": 10, "analyzed": 0, "pending": 10},
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": self._stub_drain()},
            final_results_fn=self._stub_final(),
            enqueue_missing_fn=self._enq_stub(enqueued=0),
        )
        self.assertEqual(
            job.progress.get("blocker_reason"),
            "files_pending_but_drains_returned_zero",
        )

    def test_blocker_reason_after_threshold_polls(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = self._stub_loader(
            {"total": 10, "analyzed": 0, "pending": 10},
        )
        for _ in range(_STALL_THRESHOLD_POLLS + 1):
            step_deep_answer(
                job=job, vault_id="v1", key=b"k" * 32,
                coverage_loader=loader,
                drain_fns={"text_extraction": self._stub_drain()},
                final_results_fn=self._stub_final(),
                enqueue_missing_fn=self._enq_stub(enqueued=0),
            )
        self.assertIsNotNone(job.progress.get("blocker_reason"))
        reason = job.progress["blocker_reason"]
        self.assertIn(
            reason,
            {
                "files_pending_but_drains_returned_zero",
                "scan_not_started_no_files_processed_yet",
                "scan_stalled_no_progress",
                "no_files_left_to_process",
                "empty_vault_no_files_to_scan",
            },
            f"reason={reason!r} not in closed set",
        )

    def test_progress_resets_stall_counter(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                         
        zero = self._stub_loader(
            {"total": 10, "analyzed": 0, "pending": 10},
        )
        for _ in range(2):
            step_deep_answer(
                job=job, vault_id="v1", key=b"k" * 32,
                coverage_loader=zero,
                drain_fns={"text_extraction": self._stub_drain()},
                final_results_fn=self._stub_final(),
                enqueue_missing_fn=self._enq_stub(enqueued=0),
            )
                                                                 
                                                                   
        moved = self._stub_loader(
            {"total": 10, "analyzed": 5, "pending": 5},
        )

        def _moving_drain(*, vault_id, key, max_jobs):
            return {"processed": 5, "succeeded": 5, "failed": 0}

        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=moved,
            drain_fns={"text_extraction": _moving_drain},
            final_results_fn=self._stub_final(),
            enqueue_missing_fn=self._enq_stub(enqueued=0),
        )
        self.assertEqual(job._no_progress_polls, 0)
        self.assertIsNone(job.progress.get("blocker_reason"))

    def test_no_progress_polls_field_exposed_on_snapshot(self):


        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        loader = self._stub_loader(
            {"total": 10, "analyzed": 0, "pending": 10},
        )
        step_deep_answer(
            job=job, vault_id="v1", key=b"k" * 32,
            coverage_loader=loader,
            drain_fns={"text_extraction": self._stub_drain()},
            final_results_fn=self._stub_final(),
        )
        snap = safe_job_snapshot(job)
        self.assertIn("no_progress_polls", snap["progress"])
        self.assertIn("blocker_reason", snap["progress"])


class FinalResultsTimingTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def test_results_is_None_in_snapshot_while_scanning(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
                                                                     
                                                                   
        job.results = {"envelope": {"type": "credential_files"}}
        job.status = DEEP_ANSWER_STATUS_SCANNING
        snap = safe_job_snapshot(job)
        self.assertIsNone(snap["results"])

    def test_results_present_only_when_status_ready(self):
        job = start_or_resume_job(
            vault_id="v1",
            intent=DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
            query="",
        )
        job.results = {"envelope": {"type": "credential_files"}}
        job.status = DEEP_ANSWER_STATUS_READY
        snap = safe_job_snapshot(job)
        self.assertIsNotNone(snap["results"])


if __name__ == "__main__":
    unittest.main()
