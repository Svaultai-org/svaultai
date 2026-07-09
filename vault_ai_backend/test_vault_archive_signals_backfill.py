

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import patch

import vault_analysis as va
import vault_understanding as vu


@dataclass
class FakeDBStore:
                                                         
    select_results: list = field(default_factory=list)
    executed: list = field(default_factory=list)
    committed: int = 0
    rolled_back: int = 0


class FakeCursor:
    def __init__(self, store: FakeDBStore):
        self.store = store
        self.last_sql: str = ""
        self.last_params: tuple = ()
        self._pending_select: Any = None
        self.rowcount: int = 1

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.last_sql = sql
        self.last_params = tuple(params) if params else ()
        self.store.executed.append((sql, self.last_params))
        if "FROM uploaded_files u" in sql and "archive_index" in sql:
                                        
            self._pending_select = list(self.store.select_results)
        elif "UPDATE vault_file_understanding" in sql:
                                                  
            self._pending_select = None
        else:
            self._pending_select = None

    def fetchone(self):
        if not self._pending_select:
            return None
        return self._pending_select[0] if self._pending_select else None

    def fetchall(self):
        out = self._pending_select or []
        self._pending_select = None
        return list(out)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, store: FakeDBStore):
        self.store = store

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.store)

    def commit(self):
        self.store.committed += 1

    def rollback(self):
        self.store.rolled_back += 1

    def close(self):
        pass


def _install_fake_db(store: FakeDBStore):
    return patch(
        "vault_understanding._get_db",
        return_value=FakeConn(store),
    )


class HelperSourceGuardTests(unittest.TestCase):
    def test_helper_exists_and_is_public(self):
        self.assertTrue(hasattr(vu, "backfill_archive_signals"))

    def test_helper_signature(self):
        sig = inspect.signature(vu.backfill_archive_signals)
        self.assertIn("vault_id", sig.parameters)

    def test_sql_detects_archive_files_by_source_and_extension(self):
        src = inspect.getsource(vu.backfill_archive_signals)
                                                               
                                                            
        self.assertIn("'archive_index'", src)
        self.assertIn("zip", src)
        self.assertIn("tar", src)
        self.assertIn("tgz", src)
                                                               
                                            
        self.assertIn("tar.gz", src)

    def test_sql_is_vault_scoped(self):
        src = inspect.getsource(vu.backfill_archive_signals)
                                     
        flat = src.replace("\n", " ")
        self.assertIn("u.vault_id = %s", flat)
                                                         
        self.assertIn("v.vault_id = u.vault_id", flat)

    def test_helper_enqueues_archive_indexing(self):
        src = inspect.getsource(vu.backfill_archive_signals)
        self.assertIn("STAGE_ARCHIVE_INDEXING", src)
        self.assertIn("enqueue_analysis_job", src)

    def test_helper_skips_processing_rows(self):
        src = inspect.getsource(vu.backfill_archive_signals)
                                          
        self.assertIn("UNDERSTANDING_STATUS_PROCESSING", src)

    def test_helper_uses_direct_stale_marker(self):
        src = inspect.getsource(vu.backfill_archive_signals)
                                                          
                                                          
        self.assertIn("_mark_understanding_stale_direct", src)
        self.assertNotIn(
            "mark_stale_understandings_for_changed_text", src,
        )

    def test_returns_stable_shape(self):
        src = inspect.getsource(vu.backfill_archive_signals)
        for needle in (
            "matched_archives",
            "marked_stale",
            "archive_jobs_enqueued",
            "skipped_processing",
            "skipped_already_has_signals",
            "ran_at",
        ):
            self.assertIn(needle, src)

    def test_helper_never_executes_user_content(self):
        src = inspect.getsource(vu.backfill_archive_signals)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)


class AlreadyPopulatedDetectorTests(unittest.TestCase):
    def test_none_is_not_populated(self):
        self.assertFalse(
            vu._archive_signals_already_populated(None)
        )

    def test_empty_dict_is_not_populated(self):
        self.assertFalse(
            vu._archive_signals_already_populated({})
        )

    def test_dict_without_inner_files_is_not_populated(self):
        self.assertFalse(
            vu._archive_signals_already_populated({"format": "zip"})
        )

    def test_dict_with_empty_inner_files_is_not_populated(self):
        self.assertFalse(
            vu._archive_signals_already_populated(
                {"format": "zip", "inner_files": []},
            )
        )

    def test_dict_with_inner_files_is_populated(self):
        self.assertTrue(
            vu._archive_signals_already_populated(
                {
                    "format": "zip",
                    "inner_files": [{"path": "notes.md"}],
                },
            )
        )

    def test_json_string_form_is_handled(self):
        payload = json.dumps({
            "format": "zip",
            "inner_files": [{"path": "notes.md"}],
        })
        self.assertTrue(
            vu._archive_signals_already_populated(payload)
        )

    def test_malformed_json_is_not_populated(self):
        self.assertFalse(
            vu._archive_signals_already_populated("not-json{")
        )


class HelperBehaviourTests(unittest.TestCase):
    def test_empty_signals_row_gets_marked_stale_and_enqueued(self):
                                                              
                                       
        store = FakeDBStore(select_results=[
            ("file-a", "ready", {}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
        self.assertEqual(result["matched_archives"], 1)
        self.assertEqual(result["marked_stale"], 1)
        self.assertEqual(result["archive_jobs_enqueued"], 1)
        self.assertEqual(result["skipped_processing"], 0)
        self.assertEqual(result["skipped_already_has_signals"], 0)
                                           
        enqueue.assert_called_once()
        self.assertEqual(
            enqueue.call_args.kwargs["stage"],
            va.STAGE_ARCHIVE_INDEXING,
        )

    def test_already_populated_signals_is_skipped(self):
        store = FakeDBStore(select_results=[
            ("file-a", "ready",
             {"format": "zip",
              "inner_files": [{"path": "notes.md"}]}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
        self.assertEqual(result["matched_archives"], 1)
        self.assertEqual(result["marked_stale"], 0)
        self.assertEqual(result["archive_jobs_enqueued"], 0)
        self.assertEqual(result["skipped_already_has_signals"], 1)
        enqueue.assert_not_called()

    def test_processing_row_is_skipped(self):
        store = FakeDBStore(select_results=[
            ("file-a", "processing", {}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
        self.assertEqual(result["matched_archives"], 1)
        self.assertEqual(result["marked_stale"], 0)
        self.assertEqual(result["archive_jobs_enqueued"], 0)
        self.assertEqual(result["skipped_processing"], 1)
        enqueue.assert_not_called()

    def test_understanding_row_missing_still_enqueues_archive_indexing(self):
                                                                  
                                                       
        store = FakeDBStore(select_results=[
            ("file-a", None, None),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
                                                               
                       
        self.assertEqual(result["marked_stale"], 0)
        self.assertEqual(result["archive_jobs_enqueued"], 1)
        enqueue.assert_called_once()

    def test_failed_status_still_enqueues_but_no_stale_flip(self):
                                                               
                                                                
        store = FakeDBStore(select_results=[
            ("file-a", "failed", {}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
        self.assertEqual(result["marked_stale"], 0)
        self.assertEqual(result["archive_jobs_enqueued"], 1)
        enqueue.assert_called_once()

    def test_mixed_rows_count_correctly(self):
        store = FakeDBStore(select_results=[
            ("file-a", "ready",      {}),                                              
            ("file-b", "processing", {}),                                              
            ("file-c", "ready",      {"inner_files": [{"path": "x"}]}),                    
            ("file-d", "stale",      None),                                            
            ("file-e", None,         None),                                         
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-x") as enqueue:
            result = vu.backfill_archive_signals("vault-x")
        self.assertEqual(result["matched_archives"], 5)
        self.assertEqual(result["marked_stale"], 2)
        self.assertEqual(result["archive_jobs_enqueued"], 3)
        self.assertEqual(result["skipped_processing"], 1)
        self.assertEqual(result["skipped_already_has_signals"], 1)
        self.assertEqual(enqueue.call_count, 3)


class IdempotencyTests(unittest.TestCase):
    def test_helper_relies_on_partial_unique_index_for_dedup(self):
                                                        
                                                           
        src = inspect.getsource(vu.backfill_archive_signals)
                                                            
                 
        self.assertNotIn(
            "FROM vault_analysis_jobs",
            src.upper().replace("VAULT_ANALYSIS_JOBS", "vault_analysis_jobs"),
        )

    def test_second_call_with_same_state_is_a_no_op_to_DB(self):


        store = FakeDBStore(select_results=[
            ("file-a", "ready",
             {"format": "zip",
              "inner_files": [{"path": "notes.md"}]}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            r1 = vu.backfill_archive_signals("vault-x")
            r2 = vu.backfill_archive_signals("vault-x")
        self.assertEqual(r1["archive_jobs_enqueued"], 0)
        self.assertEqual(r2["archive_jobs_enqueued"], 0)
        enqueue.assert_not_called()


class CrossVaultSafetyTests(unittest.TestCase):
    def test_vault_id_appears_in_select_params(self):
        store = FakeDBStore(select_results=[])
        with _install_fake_db(store):
            vu.backfill_archive_signals("vault-x")
                                                               
        sql, params = store.executed[0]
        self.assertIn("u.vault_id = %s", sql)
        self.assertEqual(params, ("vault-x",))

    def test_vault_id_appears_in_stale_update_params(self):
        store = FakeDBStore(select_results=[
            ("file-a", "ready", {}),
        ])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.backfill_archive_signals("vault-x")
                                    
        update_stmts = [
            (s, p) for s, p in store.executed
            if "UPDATE vault_file_understanding" in s
        ]
        self.assertEqual(len(update_stmts), 1)
        _, params = update_stmts[0]
                                        
        self.assertIn("vault-x", params)
                      
        self.assertIn("file-a", params)


class DirectStaleMarkerTests(unittest.TestCase):
    def test_uses_correct_status_filter(self):
        src = inspect.getsource(vu._mark_understanding_stale_direct)
        self.assertIn("'stale'", src)
                                                             
                                                           
        self.assertIn("'pending'", src)
        self.assertIn("'ready'", src)
        self.assertIn("'stale'", src)
                                                              
                                                               
    def test_does_not_touch_version_columns(self):
                                                           
                                                                
        src = inspect.getsource(vu._mark_understanding_stale_direct)
                                                          
                                                             
        import ast as _ast
        try:
            tree = _ast.parse(src)
            doc = _ast.get_docstring(tree.body[0]) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("analysis_version", code_only)
        self.assertNotIn("source_text_version", code_only)


class EndpointSourceGuardTests(unittest.TestCase):
    def test_endpoint_is_registered(self):
        import main
        src = inspect.getsource(main)
        self.assertIn(
            '"/vault-analysis/backfill-archive-signals"',
            src,
        )

    def test_endpoint_uses_trusted_device_dependency(self):
        import main
        fn = main.vault_analysis_backfill_archive_signals_endpoint
        src = inspect.getsource(fn)
        self.assertIn("verify_trusted_device", src)

    def test_endpoint_verifies_pin(self):
        import main
        fn = main.vault_analysis_backfill_archive_signals_endpoint
        src = inspect.getsource(fn)
        self.assertIn("verify_vault_pin", src)

    def test_endpoint_calls_helper(self):
        import main
        fn = main.vault_analysis_backfill_archive_signals_endpoint
        src = inspect.getsource(fn)
        self.assertIn("backfill_archive_signals", src)

    def test_endpoint_is_vault_scoped(self):
        import main
        fn = main.vault_analysis_backfill_archive_signals_endpoint
        src = inspect.getsource(fn)
                                                            
                           
        self.assertIn("vault_id = principal", src)
                                                       
        self.assertNotIn("payload.vault_id", src)

    def test_endpoint_has_rate_limiter(self):
        import main
        src = inspect.getsource(main)
        idx = src.find(
            '"/vault-analysis/backfill-archive-signals"',
        )
        self.assertGreater(idx, -1)
        window = src[max(0, idx - 200):idx + 200]
        self.assertIn("@limiter.limit", window)

    def test_request_body_shape(self):
        import main
                                                                        
        fields = main.BackfillArchiveSignalsRequest.model_fields
        self.assertIn("vault_name", fields)
        self.assertIn("pin", fields)


class HelperSafetyTests(unittest.TestCase):
    def test_helper_does_not_touch_vault_items(self):
        src = inspect.getsource(vu.backfill_archive_signals)
        self.assertNotIn("INSERT INTO vault_items", src)
        self.assertNotIn("vault_items", src)

    def test_helper_does_not_log_credential_or_inner_content(self):
        src = inspect.getsource(vu.backfill_archive_signals)
        for forbidden in (
            "logger.info(\"%s\", password",
            "logger.info(\"%s\", archive_signals",
            "logger.info(\"%s\", inner_files",
        ):
            self.assertNotIn(forbidden, src)

    def test_helper_does_not_decrypt_any_content(self):
                                                             
                                                             
        src = inspect.getsource(vu.backfill_archive_signals)
        self.assertNotIn("decrypt_message", src)
        self.assertNotIn("decrypt_bytes", src)


if __name__ == "__main__":
    unittest.main()
