

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import patch

import vault_analysis as va
import vault_understanding as vu
import vault_understanding_search as vus


@dataclass
class FakeDBStore:
    update_returning_rows: list = field(default_factory=list)
    select_results: list = field(default_factory=list)
    executed: list = field(default_factory=list)
    committed: int = 0
    rolled_back: int = 0


class FakeCursor:
    def __init__(self, store: FakeDBStore):
        self.store = store
        self.last_sql: str = ""
        self.last_params: tuple = ()
        self._select_results = list(store.select_results)
        self._returning_rows: list = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.last_sql = sql
        self.last_params = tuple(params) if params else ()
        self.store.executed.append((sql, self.last_params))
                                                              
        if "UPDATE vault_file_understanding" in sql and "RETURNING" in sql:
            self._returning_rows = list(self.store.update_returning_rows)
            self.rowcount = len(self._returning_rows)
        elif "COUNT(*)" in sql:
            self._returning_rows = list(self._select_results)
            self.rowcount = len(self._returning_rows)
        else:
            self._returning_rows = []
            self.rowcount = 1

    def fetchone(self):
        if not self._returning_rows:
            return None
        return self._returning_rows[0]

    def fetchall(self):
        out = list(self._returning_rows)
        self._returning_rows = []
        return out

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
        self.assertTrue(
            hasattr(vu, "mark_stale_understandings_for_changed_text"),
            "the stale-detection helper must be a public name on "
            "vault_understanding",
        )

    def test_helper_signature(self):
        sig = inspect.signature(
            vu.mark_stale_understandings_for_changed_text
        )
        params = sig.parameters
        self.assertIn("vault_id", params)
                                                               
                               
        self.assertIn("file_id", params)
        self.assertEqual(
            params["file_id"].kind,
            inspect.Parameter.KEYWORD_ONLY,
            "file_id MUST be keyword-only — positional callsites "
            "are too easy to swap with vault_id",
        )
        self.assertIn("current_analysis_version", params)

    def test_helper_sql_compares_versions_correctly(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
                                    
                                                                     
        self.assertIn("source_text_version", src)
        self.assertIn("extracted_text_version", src)
        self.assertIn("analysis_version", src)
                                                                   
                                                              
        self.assertIn("< ", src)

    def test_helper_status_set_is_stale(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        self.assertIn("'stale'", src)

    def test_helper_skips_processing_rows(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
                                                                   
                                                                  
        self.assertIn("'pending'", src)
        self.assertIn("'ready'", src)
        self.assertIn("'stale'", src)
        self.assertNotIn("'processing'", src.split("WHERE")[1] if "WHERE" in src else src)

    def test_helper_vault_scoped(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
                                                            
                                                            
        self.assertIn("v.vault_id", src)
        self.assertIn("vault_id = v.vault_id", src.replace("\n", " "))

    def test_helper_enqueues_file_understanding_jobs(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        self.assertIn("enqueue_analysis_job", src)
        self.assertIn("STAGE_FILE_UNDERSTANDING", src)

    def test_helper_returns_stable_shape(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        for needle in ("stale_marked", "jobs_enqueued", "file_ids",
                       "vault_id", "ran_at"):
            self.assertIn(needle, src)

    def test_helper_never_runs_user_content_through_eval(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)


class HelperBehaviourTests(unittest.TestCase):
    def test_marks_returned_file_ids_as_stale(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",), ("file-b",)],
        )
        with _install_fake_db(store), \
                patch(
                    "vault_analysis.enqueue_analysis_job",
                    return_value="job-1",
                ):
            result = vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
        self.assertEqual(result["stale_marked"], 2)
        self.assertEqual(result["vault_id"], "vault-x")
        self.assertEqual(sorted(result["file_ids"]),
                         ["file-a", "file-b"])

    def test_no_stale_rows_returns_zero_counts(self):
        store = FakeDBStore(update_returning_rows=[])
        with _install_fake_db(store), \
                patch(
                    "vault_analysis.enqueue_analysis_job",
                    return_value="job-1",
                ) as enqueue:
            result = vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
        self.assertEqual(result["stale_marked"], 0)
        self.assertEqual(result["jobs_enqueued"], 0)
                                                         
        enqueue.assert_not_called()

    def test_enqueues_one_job_per_stale_file(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",), ("file-b",), ("file-c",)],
        )
        with _install_fake_db(store), \
                patch(
                    "vault_analysis.enqueue_analysis_job",
                    return_value="job-x",
                ) as enqueue:
            result = vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
        self.assertEqual(enqueue.call_count, 3)
                                                          
                                   
        for call in enqueue.call_args_list:
            kwargs = call.kwargs
            self.assertEqual(kwargs["vault_id"], "vault-x")
            self.assertEqual(kwargs["stage"], va.STAGE_FILE_UNDERSTANDING)
            self.assertIn(kwargs["file_id"],
                          {"file-a", "file-b", "file-c"})
        self.assertEqual(result["jobs_enqueued"], 3)

    def test_enqueue_failure_does_not_stop_remaining_files(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",), ("file-b",), ("file-c",)],
        )
                                                               
        calls = {"n": 0}

        def _enqueue(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return "job-id"

        with _install_fake_db(store), \
                patch(
                    "vault_analysis.enqueue_analysis_job",
                    side_effect=_enqueue,
                ):
            result = vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
        self.assertEqual(result["stale_marked"], 3)
                        
        self.assertEqual(result["jobs_enqueued"], 2)

    def test_per_file_call_narrows_scope(self):
        store = FakeDBStore(update_returning_rows=[("file-a",)])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.mark_stale_understandings_for_changed_text(
                "vault-x", file_id="file-a",
            )
                                                                
                      
        executed_sql = "\n".join(sql for sql, _ in store.executed)
        self.assertIn("v.file_id = %s", executed_sql)

    def test_vault_wide_call_does_not_narrow_to_file_id(self):
        store = FakeDBStore(update_returning_rows=[])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
        executed_sql = "\n".join(sql for sql, _ in store.executed)
                                                              
        self.assertNotIn("v.file_id = %s", executed_sql)

    def test_custom_analysis_version_propagates_to_sql(self):
        store = FakeDBStore(update_returning_rows=[])
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.mark_stale_understandings_for_changed_text(
                "vault-x", current_analysis_version=99,
            )
                                                                 
                               
        target_versions = [
            params for sql, params in store.executed
            if "UPDATE vault_file_understanding" in sql
        ]
        self.assertTrue(target_versions)
        self.assertIn(99, target_versions[0])

    def test_helper_returns_iso_timestamp_in_ran_at(self):
        store = FakeDBStore(update_returning_rows=[])
        with _install_fake_db(store):
            result = vu.mark_stale_understandings_for_changed_text(
                "vault-x",
            )
                                                                  
        self.assertIn("T", result["ran_at"])

    def test_commit_runs_after_update(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",)],
        )
        with _install_fake_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.mark_stale_understandings_for_changed_text("vault-x")
                                          
        self.assertEqual(store.committed, 1)


class TextExtractionWorkerHookTests(unittest.TestCase):
    def test_text_extraction_worker_calls_stale_helper_after_persist(self):
        import vault_analysis_worker as vaw
        src = inspect.getsource(vaw._process_one_text_extraction_job)
        persist_idx = src.find("mark_file_analysis_analyzed")
        stale_idx = src.find("mark_stale_understandings_for_changed_text")
        self.assertGreater(persist_idx, -1)
        self.assertGreater(stale_idx, -1)
        self.assertLess(
            persist_idx, stale_idx,
            "stale housekeeping MUST run AFTER the file row's "
            "extracted_text_version has been bumped — otherwise "
            "the comparison sees the OLD version and skips the row",
        )

    def test_text_extraction_worker_passes_file_id_to_stale_helper(self):
        import vault_analysis_worker as vaw
        src = inspect.getsource(vaw._process_one_text_extraction_job)
                                                                  
                                                                 
        self.assertIn("mark_stale_understandings_for_changed_text", src)
                                                
                                                            
        idx = src.find("mark_stale_understandings_for_changed_text")
        chunk = src[idx:idx + 400]
        self.assertIn("file_id=file_id", chunk)


class OCRWorkerHookTests(unittest.TestCase):
    def test_ocr_worker_calls_stale_helper_after_persist(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow._process_one_ocr_job)
        persist_idx = src.find("mark_file_analysis_analyzed")
        stale_idx = src.find("mark_stale_understandings_for_changed_text")
        self.assertGreater(persist_idx, -1)
        self.assertGreater(stale_idx, -1)
        self.assertLess(
            persist_idx, stale_idx,
            "stale housekeeping MUST run AFTER OCR's bump of "
            "extracted_text_version",
        )

    def test_ocr_worker_passes_file_id_to_stale_helper(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow._process_one_ocr_job)
        idx = src.find("mark_stale_understandings_for_changed_text")
        self.assertGreater(idx, -1)
        chunk = src[idx:idx + 400]
        self.assertIn("file_id=file_id", chunk)


class ChatHandlerHookTests(unittest.TestCase):
    def test_chat_handler_runs_stale_sweep_before_understanding_drain(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        sweep_idx = src.find("mark_stale_understandings_for_changed_text")
        drain_idx = src.find("drain_file_understanding")
        self.assertGreater(sweep_idx, -1)
        self.assertGreater(drain_idx, -1)
        self.assertLess(
            sweep_idx, drain_idx,
            "the vault-wide stale sweep MUST run BEFORE "
            "drain_file_understanding so freshly-enqueued stale "
            "rebuilds get picked up in the same chat turn",
        )

    def test_chat_handler_sweep_is_vault_wide_not_file_scoped(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                                 
                                                                 
        idx = src.find("mark_stale_understandings_for_changed_text(vault_id)")
        self.assertGreater(
            idx, -1,
            "chat handler must call the helper with vault_id alone, "
            "no file_id kwarg",
        )

    def test_chat_handler_stale_sweep_exception_is_swallowed(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                             
                                                    
        idx = src.find("mark_stale_understandings_for_changed_text(vault_id)")
                                                               
                               
        forward = src[idx:idx + 600]
        self.assertIn("except Exception", forward)


class SearchStaleDowngradeTests(unittest.TestCase):
    def _make_row(
        self,
        *,
        understanding_status: str,
        purpose: str = "generic_text",
        purpose_label: str = "general text",
        topics: Optional[list] = None,
        entities: Optional[dict] = None,
        file_name: str = "doc.pdf",
        file_id: str = "file-1",
    ) -> dict:
        return {
            "file_id":              file_id,
            "file_name":            file_name,
            "saved_name":           None,
            "relative_path":        None,
            "content_type":         None,
            "asset_type":           "file",
            "extracted_text":       None,
            "extracted_text_encrypted": None,
            "understanding_status": understanding_status,
            "document_purpose":     purpose,
            "purpose_label":        purpose_label,
            "summary_encrypted":    None,
            "safe_preview_encrypted": None,
            "topics_jsonb":         topics or [],
            "entities_jsonb":       entities or {},
            "dates_jsonb":          [],
            "detected_categories_jsonb": [],
            "searchable_terms_jsonb": [],
        }

    def test_stale_row_still_appears_in_results(self):
        rows = [self._make_row(
            understanding_status="stale",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
                                                              
                                                        
        self.assertEqual(len(report["results"]), 1)

    def test_stale_row_confidence_is_demoted_to_weak(self):
        rows = [self._make_row(
            understanding_status="stale",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
        match = report["results"][0]
        self.assertEqual(match["confidence"], "weak",
                         "a stale row MUST be downgraded to weak — "
                         "the underlying signal may have moved on")

    def test_stale_row_reason_has_refresh_suffix(self):
        rows = [self._make_row(
            understanding_status="stale",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
        match = report["results"][0]
        self.assertIn("(being refreshed)", match["match_reason"])

    def test_stale_row_carries_is_stale_flag(self):
        rows = [self._make_row(
            understanding_status="stale",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
        match = report["results"][0]
        self.assertTrue(match.get("is_stale"))

    def test_ready_row_keeps_strong_confidence(self):
        rows = [self._make_row(
            understanding_status="ready",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
        match = report["results"][0]
                                                  
        self.assertEqual(match["confidence"], "strong")
        self.assertNotIn("(being refreshed)", match["match_reason"])
        self.assertFalse(match.get("is_stale"))

    def test_stale_count_returned_separately(self):
        rows = [
            self._make_row(
                understanding_status="ready",
                file_id="file-ready",
                entities={"names": ["Wells Fargo"]},
            ),
            self._make_row(
                understanding_status="stale",
                file_id="file-stale",
                entities={"names": ["Wells Fargo"]},
            ),
            self._make_row(
                understanding_status="pending",
                file_id="file-pending",
            ),
        ]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "wells fargo",
            )
                                                                    
        self.assertEqual(report["pending_count"], 2)
        self.assertEqual(report["stale_count"], 1)


class FormatSearchReplyStaleTests(unittest.TestCase):
    def test_results_with_stale_mentions_refresh(self):
        reply = vus.format_search_reply(
            query="wells fargo",
            results=[{"file_name": "statement.pdf",
                      "match_reason": "entity match: Wells Fargo "
                                      "(being refreshed)"}],
            pending_count=2,
            stale_count=1,
        )
        self.assertIn("being re-analyzed", reply)
                                                             
        self.assertIn("1 file still being analyzed", reply)

    def test_no_results_with_stale_mentions_refresh(self):
        reply = vus.format_search_reply(
            query="wells fargo", results=[],
            pending_count=2, stale_count=2,
        )
        self.assertIn("being re-analyzed", reply)

    def test_no_stale_no_refresh_mention(self):
        reply = vus.format_search_reply(
            query="wells fargo",
            results=[{"file_name": "statement.pdf",
                      "match_reason": "entity match"}],
            pending_count=0, stale_count=0,
        )
        self.assertNotIn("being re-analyzed", reply)
        self.assertNotIn("still being analyzed", reply)


class CoverageFormatterStaleTests(unittest.TestCase):
    def test_being_refreshed_surfaces_distinctly(self):
        text = vu.format_coverage_for_chat({
            "total_files":            10,
            "files_understood":       7,
            "files_pending":          3,
            "files_being_refreshed":  2,
            "files_text_only":        0,
            "files_needing_ocr":      0,
            "files_needing_transcription": 0,
            "files_unsupported":      0,
        })
                                             
        self.assertIn("1 pending", text)
        self.assertIn("2 being re-analyzed", text)

    def test_no_stale_no_being_refreshed_mention(self):
        text = vu.format_coverage_for_chat({
            "total_files":            10,
            "files_understood":       8,
            "files_pending":          2,
            "files_being_refreshed":  0,
            "files_text_only":        0,
            "files_needing_ocr":      0,
            "files_needing_transcription": 0,
            "files_unsupported":      0,
        })
        self.assertIn("2 pending", text)
        self.assertNotIn("being re-analyzed", text)

    def test_only_stale_no_truly_pending_does_not_double_count(self):
        text = vu.format_coverage_for_chat({
            "total_files":            5,
            "files_understood":       2,
            "files_pending":          3,             
            "files_being_refreshed":  3,
            "files_text_only":        0,
            "files_needing_ocr":      0,
            "files_needing_transcription": 0,
            "files_unsupported":      0,
        })
                                                                  
                                           
        self.assertNotIn("3 pending", text)
        self.assertIn("3 being re-analyzed", text)


class StaleHelperSafetyTests(unittest.TestCase):
    def test_helper_never_inserts_into_vault_items(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        self.assertNotIn("vault_items", src)
        self.assertNotIn("INSERT INTO vault_items", src)

    def test_helper_logs_never_carry_plaintext(self):
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
                                                                
                                                                 
        for forbidden in ("plaintext",
                          "summary_encrypted",
                          "safe_preview_encrypted"):
            self.assertNotIn(
                forbidden, src,
                f"the housekeeping helper MUST NOT touch {forbidden} "
                "values — it's a status flipper, not a decryptor",
            )

    def test_helper_is_cross_vault_safe(self):


        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
                                                               
        flat = src.replace("\n", " ")
        self.assertIn("u.vault_id = v.vault_id", flat)
        self.assertIn("v.vault_id = %s", flat)


class StaleCountForVaultTests(unittest.TestCase):
    def test_count_returns_zero_when_no_rows(self):
        store = FakeDBStore(select_results=[(0,)])
        with _install_fake_db(store):
            n = vu.stale_understanding_count_for_vault("vault-x")
        self.assertEqual(n, 0)

    def test_count_returns_db_value(self):
        store = FakeDBStore(select_results=[(7,)])
        with _install_fake_db(store):
            n = vu.stale_understanding_count_for_vault("vault-x")
        self.assertEqual(n, 7)

    def test_count_filters_by_vault_id_and_stale_status(self):
        store = FakeDBStore(select_results=[(0,)])
        with _install_fake_db(store):
            vu.stale_understanding_count_for_vault("vault-x")
        executed_sql = "\n".join(sql for sql, _ in store.executed)
        self.assertIn("vault_id = %s", executed_sql)
        self.assertIn("status = %s", executed_sql)
                                          
        params = [p for _, p in store.executed][0]
        self.assertIn("stale", params)
        self.assertIn("vault-x", params)


class FileSearchEnvelopeStaleTests(unittest.TestCase):
    def test_envelope_passes_stale_count(self):
        import main
        env = main._build_file_search_envelope(
            query="wells fargo",
            results=[{
                "file_id": "f1",
                "file_name": "doc.pdf",
                "match_type": "entity",
                "match_reason": "entity match: Wells Fargo (being refreshed)",
                "confidence": "weak",
                "is_stale": True,
            }],
            message="",
            pending_count=2,
            stale_count=1,
        )
        payload = json.loads(env)
        self.assertEqual(payload["stale_count"], 1)
        self.assertEqual(payload["pending_count"], 2)
                                          
        self.assertTrue(payload["results"][0]["is_stale"])

    def test_envelope_handles_missing_stale_count_default(self):
        import main
        env = main._build_file_search_envelope(
            query="x",
            results=[],
            message="",
            pending_count=0,
        )
        payload = json.loads(env)
                                         
        self.assertEqual(payload["stale_count"], 0)


class IdempotencyTests(unittest.TestCase):
    def test_helper_does_not_pre_check_existing_jobs(self):
                                                               
                                                               
        src = inspect.getsource(
            vu.mark_stale_understandings_for_changed_text
        )
        self.assertNotIn(
            "SELECT", src.split("UPDATE")[0] if "UPDATE" in src else "",
        )
                                                           
                                                                
        self.assertNotIn("already_pending", src)


if __name__ == "__main__":
    unittest.main()
