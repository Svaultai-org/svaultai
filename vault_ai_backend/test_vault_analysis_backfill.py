

from __future__ import annotations

import inspect
import unittest


class _StubbedBackfillHarness:


    def __init__(self, *, candidates, active_job_files=()):
        self._candidates = list(candidates)
        self._active_job_files = set(active_job_files)
        self.reset_calls: list[tuple[str, str]] = []
        self.enqueue_calls: list[dict] = []

    def select_chunked_unsupported(self, vault_id):
        return [r for r in self._candidates if r.get("_vault_id") == vault_id]

    def active_jobs(self, file_ids):
        return self._active_job_files.intersection(file_ids)

    def reset_to_pending(self, *, vault_id, file_id):
        self.reset_calls.append((vault_id, file_id))

    def enqueue(self, *, vault_id, file_id, stage):
        self.enqueue_calls.append(
            {"vault_id": vault_id, "file_id": file_id, "stage": stage}
        )
        return f"job-{file_id}"


def _patch_backfill_with(harness, *, monkeypatch_target=None):


    import vault_analysis as va
    import vault_analysis_worker as worker

    originals = {
        "_select_chunked_unsupported_for_backfill":
            worker._select_chunked_unsupported_for_backfill,
        "_file_ids_with_active_text_extraction_jobs":
            worker._file_ids_with_active_text_extraction_jobs,
        "_reset_file_to_pending":
            worker._reset_file_to_pending,
        "enqueue_analysis_job":
            va.enqueue_analysis_job,
    }

    worker._select_chunked_unsupported_for_backfill = harness.select_chunked_unsupported
    worker._file_ids_with_active_text_extraction_jobs = harness.active_jobs
    worker._reset_file_to_pending = (
        lambda *, vault_id, file_id: harness.reset_to_pending(
            vault_id=vault_id, file_id=file_id,
        )
    )
    va.enqueue_analysis_job = harness.enqueue

    return originals


def _restore_originals(originals):
    import vault_analysis as va
    import vault_analysis_worker as worker
    worker._select_chunked_unsupported_for_backfill = (
        originals["_select_chunked_unsupported_for_backfill"]
    )
    worker._file_ids_with_active_text_extraction_jobs = (
        originals["_file_ids_with_active_text_extraction_jobs"]
    )
    worker._reset_file_to_pending = originals["_reset_file_to_pending"]
    va.enqueue_analysis_job = originals["enqueue_analysis_job"]


def _chunked_row(
    *, file_id, file_name="harmless.pdf", content_type="application/pdf",
    storage_mode="chunks", vault_id="vault-a",
):
    return {
        "id": file_id,
        "file_name": file_name,
        "content_type": content_type,
        "storage_mode": storage_mode,
        "_vault_id": vault_id,
    }


class BackfillOrchestrationTests(unittest.TestCase):
    def test_chunked_unsupported_pdf_is_reset_and_enqueued(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(file_id="f1", file_name="credentials.pdf"),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["reset_to_pending"], 1)
        self.assertEqual(report["jobs_enqueued"], 1)
        self.assertEqual(report["skipped_existing_jobs"], 0)
        self.assertEqual(harness.reset_calls, [("vault-a", "f1")])
        self.assertEqual(len(harness.enqueue_calls), 1)
        self.assertEqual(
            harness.enqueue_calls[0]["stage"], "text_extraction",
        )

    def test_chunked_unsupported_docx_is_reset_and_enqueued(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(
                file_id="f1", file_name="contract.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            ),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["reset_to_pending"], 1)
        self.assertEqual(report["jobs_enqueued"], 1)

    def test_chunked_unsupported_text_file_is_reset(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(
                file_id="f1", file_name="notes.txt",
                content_type="text/plain",
            ),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["reset_to_pending"], 1)

    def test_chunked_unsupported_mp4_is_NOT_reset(self):


        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(
                file_id="f1", file_name="trip.mp4",
                content_type="video/mp4",
            ),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["matched"], 1,
            "the row is still 'matched' by the SELECT")
        self.assertEqual(report["reset_to_pending"], 0,
            "but the text extractor can't handle it, so no reset")
        self.assertEqual(report["jobs_enqueued"], 0)
        self.assertEqual(harness.reset_calls, [])
        self.assertEqual(harness.enqueue_calls, [])

    def test_chunked_unsupported_zip_is_NOT_reset(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(
                file_id="f1", file_name="backup.zip",
                content_type="application/zip",
            ),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["reset_to_pending"], 0)

    def test_skips_rows_with_existing_active_job(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(
            candidates=[
                _chunked_row(file_id="f1", file_name="a.pdf"),
                _chunked_row(file_id="f2", file_name="b.pdf"),
            ],
            active_job_files={"f1"},                                
        )
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["reset_to_pending"], 1)
        self.assertEqual(report["jobs_enqueued"], 1)
        self.assertEqual(report["skipped_existing_jobs"], 1)
                                       
        self.assertEqual(harness.reset_calls, [("vault-a", "f2")])
        self.assertEqual(len(harness.enqueue_calls), 1)
        self.assertEqual(harness.enqueue_calls[0]["file_id"], "f2")

    def test_mixed_extractable_and_unextractable(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[
            _chunked_row(file_id="pdf", file_name="a.pdf"),
            _chunked_row(file_id="mp4", file_name="b.mp4",
                         content_type="video/mp4"),
            _chunked_row(file_id="docx", file_name="c.docx"),
            _chunked_row(file_id="zip", file_name="d.zip",
                         content_type="application/zip"),
        ])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report["matched"], 4)
                                               
        self.assertEqual(report["reset_to_pending"], 2)
        self.assertEqual(report["jobs_enqueued"], 2)
        reset_ids = {fid for _, fid in harness.reset_calls}
        self.assertEqual(reset_ids, {"pdf", "docx"})

    def test_empty_match_returns_zeros(self):
        from vault_analysis_worker import backfill_chunked_text_extraction_jobs
        harness = _StubbedBackfillHarness(candidates=[])
        originals = _patch_backfill_with(harness)
        try:
            report = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)
        self.assertEqual(report, {
            "matched":               0,
            "reset_to_pending":      0,
            "jobs_enqueued":         0,
            "skipped_existing_jobs": 0,
        })

    def test_idempotent_when_called_twice(self):


        from vault_analysis_worker import backfill_chunked_text_extraction_jobs

        starting_candidates = [
            _chunked_row(file_id="f1", file_name="a.pdf"),
            _chunked_row(file_id="f2", file_name="b.pdf"),
        ]
        harness = _StubbedBackfillHarness(candidates=starting_candidates)

                                                               
        def mutating_reset(*, vault_id, file_id):
            harness.reset_calls.append((vault_id, file_id))
            harness._candidates = [
                r for r in harness._candidates if r["id"] != file_id
            ]

        originals = _patch_backfill_with(harness)
        try:
            import vault_analysis_worker as worker
            worker._reset_file_to_pending = mutating_reset

            first = backfill_chunked_text_extraction_jobs("vault-a")
            second = backfill_chunked_text_extraction_jobs("vault-a")
        finally:
            _restore_originals(originals)

        self.assertEqual(first["reset_to_pending"], 2)
        self.assertEqual(first["jobs_enqueued"], 2)
                                      
        self.assertEqual(second["matched"], 0)
        self.assertEqual(second["reset_to_pending"], 0)
        self.assertEqual(second["jobs_enqueued"], 0)


class BackfillSafetySourceGuardsTests(unittest.TestCase):
    def setUp(self):
        import vault_analysis_worker as worker
        self.module = worker
        self.helper_src = inspect.getsource(
            worker.backfill_chunked_text_extraction_jobs,
        )
        self.select_src = inspect.getsource(
            worker._select_chunked_unsupported_for_backfill,
        )
        self.reset_src = inspect.getsource(
            worker._reset_file_to_pending,
        )

    def test_select_is_vault_scoped(self):
        self.assertIn("WHERE vault_id = %s", self.select_src,
            "the SELECT must be keyed by vault_id")

    def test_select_only_targets_complete_uploads(self):
        self.assertIn("upload_status = 'complete'", self.select_src,
            "in-flight uploads MUST be excluded from the backfill")

    def test_select_only_targets_unsupported_rows(self):
                                                                  
                                             
        self.assertIn(
            "analysis_status = 'unsupported'", self.select_src,
        )
                                                                    
        self.assertNotIn("'analyzed'", self.select_src)
        self.assertNotIn("'failed'", self.select_src)

    def test_select_only_targets_chunked_storage(self):
        self.assertIn(
            "storage_mode IN ('chunks', 'chunked')", self.select_src,
            "inline rows are not the slice 2A.1 regression — must NOT "
            "be touched by this backfill",
        )

    def test_update_is_vault_scoped(self):
        self.assertIn("vault_id = %s", self.reset_src,
            "UPDATE WHERE clause must include vault_id so a leaked "
            "file_id can't escape the boundary")

    def test_update_only_flips_unsupported_chunked_rows(self):
                                                                   
                                                            
        self.assertIn(
            "analysis_status = 'unsupported'", self.reset_src,
        )
        self.assertIn(
            "storage_mode IN ('chunks', 'chunked')", self.reset_src,
        )

    def test_update_clears_last_error_and_completed_at(self):
                                                                   
                                                                  
        self.assertIn("analysis_last_error  = NULL", self.reset_src)
        self.assertIn("analysis_completed_at = NULL", self.reset_src)

    def test_helper_uses_text_extractor_support_gate(self):
                                                                  
                                                                  
        self.assertIn(
            "text_ext_mod.supports_text_extraction", self.helper_src,
        )

    def test_helper_uses_central_enqueue_for_idempotency(self):
                                                                   
                                                               
        self.assertIn(
            "va.enqueue_analysis_job", self.helper_src,
        )

    def test_helper_only_enqueues_text_extraction_stage(self):
        self.assertIn(
            "stage=va.STAGE_TEXT_EXTRACTION", self.helper_src,
            "the backfill MUST NOT silently enqueue any other stage",
        )

    def test_helper_does_not_create_login_items(self):
                                                                  
                                                
        self.assertNotIn("INSERT INTO vault_items", self.helper_src)
        self.assertNotIn("save_login", self.helper_src)


class BackfillEndpointTests(unittest.TestCase):
    def setUp(self):
        from routes import vault_analysis_admin_routes as admin
        self.module = admin
        self.endpoint_src = inspect.getsource(
            admin.vault_analysis_backfill_chunked_text_extraction,
        )
        self.module_src = inspect.getsource(admin)

    def test_endpoint_path_registered(self):
        self.assertIn(
            '"/vault-analysis/backfill-chunked-text-extraction"',
            self.module_src,
        )

    def test_endpoint_is_trusted_device_gated(self):
        self.assertIn("verify_trusted_device", self.endpoint_src)

    def test_endpoint_requires_pin(self):
                                                             
                                   
        self.assertIn("get_verified_vault_key", self.endpoint_src)
        self.assertIn("payload.pin", self.endpoint_src)

    def test_endpoint_is_vault_scoped(self):
                                                                
                                       
        self.assertIn('principal["vault_id"]', self.endpoint_src)

    def test_endpoint_delegates_to_helper(self):
        self.assertIn(
            "backfill_chunked_text_extraction_jobs", self.endpoint_src,
        )

    def test_endpoint_response_does_not_leak_extracted_text(self):
                                                               
                                                                
        self.assertNotIn("extracted_text", self.endpoint_src)
                                                                
                                     
        import vault_analysis_worker as worker
        helper_src = inspect.getsource(
            worker.backfill_chunked_text_extraction_jobs,
        )
        self.assertNotIn("encrypted_file_data", helper_src)
        self.assertNotIn("extracted_text", helper_src)


class BackfillReportShapeTests(unittest.TestCase):
    def test_empty_report_has_the_four_required_keys(self):
        from vault_analysis_worker import _empty_backfill_report
        report = _empty_backfill_report()
        for key in (
            "matched", "reset_to_pending",
            "jobs_enqueued", "skipped_existing_jobs",
        ):
            self.assertIn(key, report)
            self.assertEqual(report[key], 0)


if __name__ == "__main__":
    unittest.main()
