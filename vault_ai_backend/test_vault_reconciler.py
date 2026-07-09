

from __future__ import annotations

import inspect
import unittest
from unittest import mock


class _FakeCursor:


    def __init__(self, rowcount: int = 0) -> None:
        self.queries: list[tuple[str, tuple]] = []
        self._rowcount_per_call: list[int] = []
        self._default_rowcount = rowcount
        self._fetch_rows: list[list[tuple]] = []

    def queue_rowcount(self, n: int) -> None:
        self._rowcount_per_call.append(n)

    def queue_fetch(self, rows: list[tuple]) -> None:
        self._fetch_rows.append(rows)

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.queries.append((sql, params))
        if self._rowcount_per_call:
            self.rowcount = self._rowcount_per_call.pop(0)
        else:
            self.rowcount = self._default_rowcount

    def fetchall(self) -> list[tuple]:
        if self._fetch_rows:
            return self._fetch_rows.pop(0)
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def close(self) -> None:
        pass


class _FakeConn:


    def __init__(self, cursor: _FakeCursor) -> None:
        self._cur = cursor
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, *args, **kwargs) -> _FakeCursor:
        return self._cur

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed = True


def _patch_get_db(conn: _FakeConn):
    return mock.patch("vault_core.get_db", return_value=conn)


class StatusDriftRepairTests(unittest.TestCase):
    def test_repair_status_drift_runs_the_right_update(self) -> None:
        from vault_reconciler import repair_status_drift_for_vault
        cur = _FakeCursor(rowcount=42)
        with _patch_get_db(_FakeConn(cur)):
            n = repair_status_drift_for_vault("v-target")
        self.assertEqual(n, 42)
        self.assertEqual(len(cur.queries), 1)
        sql, params = cur.queries[0]
        self.assertIn("UPDATE uploaded_files", sql)
        self.assertIn("SET analysis_status = 'analyzed'", sql)
        self.assertIn("extracted_text IS NOT NULL", sql)
        self.assertIn("analysis_status IN ('not_started', 'pending')", sql)
        self.assertIn("WHERE vault_id = %s", sql)
        self.assertEqual(params, ("v-target",))

    def test_repair_status_drift_refuses_empty_vault_id(self) -> None:
        from vault_reconciler import repair_status_drift_for_vault
        cur = _FakeCursor()
        with _patch_get_db(_FakeConn(cur)):
            n = repair_status_drift_for_vault("")
        self.assertEqual(n, 0)
        self.assertEqual(cur.queries, [],
            "empty vault_id must NOT issue an unscoped UPDATE")

    def test_repair_status_drift_commits_after_update(self) -> None:
        from vault_reconciler import repair_status_drift_for_vault
        cur = _FakeCursor(rowcount=3)
        conn = _FakeConn(cur)
        with _patch_get_db(conn):
            repair_status_drift_for_vault("v1")
        self.assertEqual(conn.committed, 1)
        self.assertTrue(conn.closed)

    def test_source_guards_terminal_states_not_touched(self) -> None:
                                                                  
                                                        
        import vault_reconciler as vr
        src = inspect.getsource(vr.repair_status_drift_for_vault)
        self.assertIn("analysis_status IN ('not_started', 'pending')", src)
        self.assertNotIn("'unsupported'", src)
        self.assertNotIn("'failed'", src)


class OrphanQueueRepairTests(unittest.TestCase):
    def test_deletes_pending_jobs_for_already_analyzed_files(self) -> None:
        from vault_reconciler import repair_orphan_queue_rows_for_vault
        cur = _FakeCursor(rowcount=17)
        with _patch_get_db(_FakeConn(cur)):
            n = repair_orphan_queue_rows_for_vault("v-target")
        self.assertEqual(n, 17)
        sql, params = cur.queries[0]
        self.assertIn("DELETE FROM vault_analysis_jobs vaj", sql)
        self.assertIn("USING uploaded_files uf", sql)
        self.assertIn("vaj.file_id::text = uf.id", sql)
        self.assertIn("uf.vault_id = %s", sql)
        self.assertIn("uf.analysis_status = 'analyzed'", sql)
        self.assertIn("vaj.status = 'pending'", sql)
        self.assertEqual(params, ("v-target",))

    def test_refuses_empty_vault_id(self) -> None:
        from vault_reconciler import repair_orphan_queue_rows_for_vault
        cur = _FakeCursor()
        with _patch_get_db(_FakeConn(cur)):
            n = repair_orphan_queue_rows_for_vault("")
        self.assertEqual(n, 0)
        self.assertEqual(cur.queries, [])

    def test_source_guards_no_processing_or_succeeded_deletion(self) -> None:
        import vault_reconciler as vr
        src = inspect.getsource(vr.repair_orphan_queue_rows_for_vault)
                                               
        self.assertIn("vaj.status = 'pending'", src)
                                                                     
        self.assertNotIn("vaj.status = 'processing'", src)
        self.assertNotIn("vaj.status = 'succeeded'", src)


class StuckProcessingRepairTests(unittest.TestCase):
    def test_resets_processing_rows_past_stale_cutoff(self) -> None:
        from vault_reconciler import repair_stuck_processing_for_vault
        cur = _FakeCursor(rowcount=4)
        with _patch_get_db(_FakeConn(cur)):
            n = repair_stuck_processing_for_vault("v1", stale_seconds=300)
        self.assertEqual(n, 4)
        sql, params = cur.queries[0]
        self.assertIn("UPDATE vault_analysis_jobs", sql)
        self.assertIn("SET status = 'pending'", sql)
        self.assertIn("locked_at = NULL", sql)
        self.assertIn("locked_by = NULL", sql)
        self.assertIn("status = 'processing'", sql)
                                                                    
                                                
        self.assertIn("NOW() - (%s || ' seconds')::interval", sql)
        self.assertIn("[reconciler:stale_lease]", sql)
                                   
        self.assertEqual(params, ("v1", "300"))

    def test_attempts_counter_not_reset(self) -> None:
                                                                  
                                                              
        import vault_reconciler as vr
        src = inspect.getsource(vr.repair_stuck_processing_for_vault)
        self.assertNotIn("attempts = 0", src)
        self.assertNotIn("attempts = attempts", src)


class PendingAndNotStartedRepairTests(unittest.TestCase):
    def test_delegates_to_central_enqueue_helper(self) -> None:
        from vault_reconciler import repair_pending_and_not_started_for_vault
        with mock.patch(
            "vault_analysis.enqueue_missing_analysis_jobs",
            return_value={"enqueued": 9, "error": None},
        ) as helper:
            n = repair_pending_and_not_started_for_vault("v-target")
        self.assertEqual(n, 9)
        helper.assert_called_once_with("v-target")

    def test_helper_error_surfaces_as_zero_count_not_raise(self) -> None:
        from vault_reconciler import repair_pending_and_not_started_for_vault
        with mock.patch(
            "vault_analysis.enqueue_missing_analysis_jobs",
            return_value={"enqueued": 0, "error": "db_unavailable"},
        ):
            n = repair_pending_and_not_started_for_vault("v1")
        self.assertEqual(n, 0)

    def test_helper_raise_caught_returns_zero(self) -> None:
        from vault_reconciler import repair_pending_and_not_started_for_vault
        with mock.patch(
            "vault_analysis.enqueue_missing_analysis_jobs",
            side_effect=RuntimeError("DB exploded"),
        ):
            n = repair_pending_and_not_started_for_vault("v1")
        self.assertEqual(n, 0,
            "reconciler must NEVER raise — daemon's loop has to keep running")

    def test_refuses_empty_vault_id(self) -> None:
        from vault_reconciler import repair_pending_and_not_started_for_vault
        with mock.patch(
            "vault_analysis.enqueue_missing_analysis_jobs",
        ) as helper:
            n = repair_pending_and_not_started_for_vault("")
        self.assertEqual(n, 0)
        helper.assert_not_called()


class TextLikeUnsupportedRepairTests(unittest.TestCase):
    def test_requeues_octet_stream_html_and_js_without_reading_content(self):
        from vault_reconciler import repair_text_like_unsupported_for_vault

        select_cur = _FakeCursor()
        select_cur.queue_fetch([
            ("f-html", "Loginatt.html", "application/octet-stream"),
            ("f-js", "login.js", "application/octet-stream"),
            ("f-bin", "encrypted.bin", "application/octet-stream"),
        ])
        select_cur.queue_fetch([(2,)])
        conn = _FakeConn(select_cur)

        with mock.patch("vault_core.get_db", return_value=conn):
            n = repair_text_like_unsupported_for_vault("v1")

        self.assertEqual(n, 2)
        select_sql, select_params = select_cur.queries[0]
        self.assertIn("analysis_status = 'unsupported'", select_sql)
        self.assertIn("extracted_text IS NULL", select_sql)
        self.assertNotIn("encrypted_file_data", select_sql)
        self.assertNotIn("extracted_text,", select_sql)
        self.assertEqual(select_params, ("v1",))

        update_sql, update_params = select_cur.queries[1]
        self.assertIn("SET analysis_status = 'pending'", update_sql)
        self.assertIn("id::text = ANY(%s)", update_sql)
        self.assertIn("INSERT INTO vault_analysis_jobs", update_sql)
        self.assertEqual(update_params, ("v1", ["f-html", "f-js"], "v1"))
        self.assertEqual(conn.committed, 1)

    def test_refuses_empty_vault_id(self):
        from vault_reconciler import repair_text_like_unsupported_for_vault
        cur = _FakeCursor()
        with _patch_get_db(_FakeConn(cur)):
            n = repair_text_like_unsupported_for_vault("")
        self.assertEqual(n, 0)
        self.assertEqual(cur.queries, [])


class ReconcileVaultTests(unittest.TestCase):
    def test_returns_closed_set_report(self) -> None:
        from vault_reconciler import reconcile_vault, ReconcilerReport
        with mock.patch(
            "vault_reconciler.repair_status_drift_for_vault",
            return_value=3,
        ), mock.patch(
            "vault_reconciler.repair_orphan_queue_rows_for_vault",
            return_value=5,
        ), mock.patch(
            "vault_reconciler.repair_stuck_processing_for_vault",
            return_value=1,
        ), mock.patch(
            "vault_reconciler.repair_text_like_unsupported_for_vault",
            return_value=2,
        ), mock.patch(
            "vault_reconciler.repair_pending_and_not_started_for_vault",
            return_value=7,
        ):
            report = reconcile_vault("v1")
        self.assertIsInstance(report, ReconcilerReport)
        self.assertEqual(report.vault_id, "v1")
        self.assertEqual(report.status_drift_repaired, 3)
        self.assertEqual(report.orphan_queue_rows_deleted, 5)
        self.assertEqual(report.stuck_processing_requeued, 1)
        self.assertEqual(report.pending_or_not_started_enqueued, 7)
        self.assertEqual(report.text_like_unsupported_requeued, 2)
        self.assertEqual(report.total_repairs(), 18)
        self.assertIsNone(report.error)

    def test_to_dict_has_only_closed_set_keys(self) -> None:
        from vault_reconciler import ReconcilerReport
        r = ReconcilerReport(
            vault_id="v1",
            status_drift_repaired=1,
            orphan_queue_rows_deleted=1,
            stuck_processing_requeued=1,
            pending_or_not_started_enqueued=1,
        )
        d = r.to_dict()
        self.assertEqual(
            set(d.keys()),
            {
                "vault_id", "status_drift_repaired",
                "orphan_queue_rows_deleted", "stuck_processing_requeued",
                "pending_or_not_started_enqueued",
                "missing_chunks_enqueued",
                "missing_embeddings_repaired",
                "wrong_dim_embeddings_nulled",
                "stale_chunking_jobs_reset",
                "text_like_unsupported_requeued",
                "total_repairs", "error",
            },
        )
                                                                
                                    
        flat = repr(d)
        for sentinel in ("extracted_text", "password", "BEGIN PRIVATE",
                         "hunter2", "tok-"):
            self.assertNotIn(sentinel, flat)

    def test_per_step_exception_surfaces_in_error_field_does_not_raise(self) -> None:
        from vault_reconciler import reconcile_vault
        with mock.patch(
            "vault_reconciler.repair_status_drift_for_vault",
            side_effect=RuntimeError("DB exploded"),
        ):
            report = reconcile_vault("v1")
        self.assertIsNotNone(report.error)
        self.assertIn("status_drift", report.error)
        self.assertEqual(report.total_repairs(), 0)

    def test_orphan_exception_after_drift_succeeded_preserves_drift_count(self) -> None:
        from vault_reconciler import reconcile_vault
        with mock.patch(
            "vault_reconciler.repair_status_drift_for_vault",
            return_value=3,
        ), mock.patch(
            "vault_reconciler.repair_orphan_queue_rows_for_vault",
            side_effect=RuntimeError("boom"),
        ):
            report = reconcile_vault("v1")
        self.assertEqual(report.status_drift_repaired, 3)
        self.assertEqual(report.orphan_queue_rows_deleted, 0)
        self.assertIsNotNone(report.error)

    def test_empty_vault_id_returns_error_report(self) -> None:
        from vault_reconciler import reconcile_vault
        report = reconcile_vault("")
        self.assertEqual(report.error, "empty_vault_id")
        self.assertEqual(report.total_repairs(), 0)

    def test_idempotent_second_run_is_no_op(self) -> None:
                                                                  
        from vault_reconciler import reconcile_vault
        with mock.patch(
            "vault_reconciler.repair_status_drift_for_vault",
            return_value=0,
        ), mock.patch(
            "vault_reconciler.repair_orphan_queue_rows_for_vault",
            return_value=0,
        ), mock.patch(
            "vault_reconciler.repair_stuck_processing_for_vault",
            return_value=0,
        ), mock.patch(
            "vault_reconciler.repair_pending_and_not_started_for_vault",
            return_value=0,
        ):
            report = reconcile_vault("v1")
        self.assertEqual(report.total_repairs(), 0)
        self.assertIsNone(report.error)


class ReconcileAllVaultsAtStartupTests(unittest.TestCase):
    def test_iterates_distinct_vaults_from_uploaded_files(self) -> None:
        from vault_reconciler import reconcile_all_vaults_at_startup
        cur = _FakeCursor()
        cur.queue_fetch([("va",), ("vb",), ("vc",)])
        conn = _FakeConn(cur)
        with _patch_get_db(conn), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.side_effect = [
                ReconcilerReport(vault_id="va", status_drift_repaired=1),
                ReconcilerReport(vault_id="vb", status_drift_repaired=2),
                ReconcilerReport(vault_id="vc", status_drift_repaired=4),
            ]
            out = reconcile_all_vaults_at_startup()
        self.assertEqual(out["vaults_seen"], 3)
        self.assertEqual(out["vaults_failed"], 0)
        self.assertEqual(out["total_repairs"], 7)
                                                                   
                                                        
        sql, _ = cur.queries[0]
        self.assertIn("SELECT DISTINCT vault_id FROM uploaded_files", sql)

    def test_db_failure_returns_error_report_does_not_raise(self) -> None:
        from vault_reconciler import reconcile_all_vaults_at_startup
        with mock.patch(
            "vault_core.get_db",
            side_effect=RuntimeError("pool exhausted"),
        ):
            out = reconcile_all_vaults_at_startup()
        self.assertEqual(out["error"], "db_scan_failed")
        self.assertEqual(out["vaults_seen"], 0)


class NeverReadsFileContentTests(unittest.TestCase):


    def test_no_select_of_extracted_text_value(self) -> None:
        import vault_reconciler as vr
        src = inspect.getsource(vr)
                                                                  
                                                               
        self.assertNotIn("SELECT extracted_text", src)
                                                                      
        self.assertNotIn("decrypt_message", src)
        self.assertNotIn("decrypt_bytes", src)

    def test_no_credential_value_strings_in_module(self) -> None:
        import vault_reconciler as vr
        src = inspect.getsource(vr)
        for sentinel in ("password=", "hunter2", "BEGIN PRIVATE KEY"):
            self.assertNotIn(sentinel, src)


if __name__ == "__main__":
    unittest.main()
