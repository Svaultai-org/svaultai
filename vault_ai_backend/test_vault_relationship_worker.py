

from __future__ import annotations

import inspect
import unittest
from typing import Any, Optional
from unittest.mock import patch, MagicMock

import vault_analysis as va
import vault_relationship_worker as vrw


class WorkerSourceGuardTests(unittest.TestCase):
    def test_drain_exists(self):
        self.assertTrue(callable(vrw.drain_relationship_building))

    def test_drain_uses_claim(self):
        src = inspect.getsource(vrw.drain_relationship_building)
        self.assertIn("claim_next_analysis_job", src)

    def test_stage_filter_in_drain(self):
        src = inspect.getsource(vrw.drain_relationship_building)
        self.assertIn("_HANDLED_STAGE", src)

    def test_handled_stage_is_relationship_building(self):
        self.assertEqual(
            vrw._HANDLED_STAGE, va.STAGE_RELATIONSHIP_BUILDING,
        )

    def test_default_max_jobs_is_one(self):
                                                             
                                                                
        self.assertEqual(vrw.DEFAULT_MAX_JOBS_PER_DRAIN, 1)

    def test_processor_calls_pure_builder(self):
        src = inspect.getsource(vrw._process_one_relationship_job)
        self.assertIn("build_relationships_for_vault", src)
        self.assertIn("complete_analysis_job", src)

    def test_processor_uses_fail_analysis_job_on_exception(self):
        src = inspect.getsource(vrw._process_one_relationship_job)
        self.assertIn("fail_analysis_job", src)

    def _code_only(self) -> str:


        import ast
        src = inspect.getsource(vrw)
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        return src.replace(doc, "") if doc else src

    def test_module_never_decrypts(self):
        code_only = self._code_only()
        self.assertNotIn("decrypt_message", code_only)
        self.assertNotIn("decrypt_bytes", code_only)

    def test_module_never_reads_encrypted_columns(self):
        code_only = self._code_only()
        for col in (
            "encrypted_file_data",
            "summary_encrypted",
            "safe_preview_encrypted",
        ):
            self.assertNotIn(col, code_only)

    def test_module_never_touches_vault_items(self):
        code_only = self._code_only()
        self.assertNotIn("INSERT INTO vault_items", code_only)
        self.assertNotIn("vault_items", code_only)

    def test_module_never_executes_user_content(self):
        src = inspect.getsource(vrw)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)


class EnqueueSourceGuardTests(unittest.TestCase):
    def test_enqueue_uses_vault_id_as_sentinel(self):
                                                                
                                                               
        src = inspect.getsource(vrw.enqueue_relationship_building)
        self.assertIn("file_id=vault_id", src)
                                                                             
                                                                
        self.assertTrue(
            "STAGE_RELATIONSHIP_BUILDING" in src
            or "_HANDLED_STAGE" in src,
            "enqueue must reference the closed-set stage symbol",
        )

    def test_enqueue_does_not_pre_check_for_existing_pending_row(self):
                                                                 
                                              
        src = inspect.getsource(vrw.enqueue_relationship_building)
        self.assertNotIn(
            "SELECT", src.upper().replace("STAGE_RELATIONSHIP_BUILDING", ""),
        )


class DrainBehaviourTests(unittest.TestCase):
    def test_max_jobs_zero_is_a_no_op(self):
                                     
        with patch.object(
            va, "claim_next_analysis_job",
            side_effect=AssertionError("should not be called"),
        ):
            report = vrw.drain_relationship_building(
                vault_id="v", max_jobs=0,
            )
        self.assertEqual(report["processed"], 0)

    def test_claim_returns_none_breaks_loop(self):
        with patch.object(
            va, "claim_next_analysis_job", return_value=None,
        ), patch.object(
            va, "fail_analysis_job",
        ), patch.object(
            va, "complete_analysis_job",
        ):
            report = vrw.drain_relationship_building(
                vault_id="v", max_jobs=3,
            )
        self.assertEqual(report["processed"], 0)
        self.assertEqual(report["succeeded"], 0)

    def test_wrong_stage_row_released_back_to_queue(self):
                                                             
                                                  
        claims = iter([
            {"job_id": "j1", "stage": "file_understanding",
             "file_id": "f1"},
            None,                                           
        ])
        fail_calls = []
        with patch.object(
            va, "claim_next_analysis_job",
            side_effect=lambda **k: next(claims),
        ), patch.object(
            va, "fail_analysis_job",
            side_effect=lambda *a, **k: fail_calls.append(
                (a, k),
            ),
        ), patch.object(
            va, "complete_analysis_job",
        ):
            vrw.drain_relationship_building(
                vault_id="v", max_jobs=3,
            )
                                                      
        self.assertEqual(len(fail_calls), 1)
        self.assertEqual(fail_calls[0][1]["retry"], True)

    def test_successful_rebuild_calls_complete_job(self):
        claims = iter([
            {"job_id": "j1",
             "stage": va.STAGE_RELATIONSHIP_BUILDING,
             "file_id": "vault-x"},
            None,
        ])
        complete_calls = []
                                                         
        import vault_relationship_graph as rg
        with patch.object(
            va, "claim_next_analysis_job",
            side_effect=lambda **k: next(claims),
        ), patch.object(
            va, "fail_analysis_job",
        ), patch.object(
            va, "complete_analysis_job",
            side_effect=lambda j: complete_calls.append(j),
        ), patch.object(
            rg, "build_relationships_for_vault",
            return_value={"vault_id": "vault-x"},
        ):
            report = vrw.drain_relationship_building(
                vault_id="vault-x", max_jobs=1,
            )
        self.assertEqual(complete_calls, ["j1"])
        self.assertEqual(report["succeeded"], 1)
        self.assertEqual(report["failed"], 0)

    def test_builder_exception_triggers_fail_no_retry(self):
        claims = iter([
            {"job_id": "j1",
             "stage": va.STAGE_RELATIONSHIP_BUILDING,
             "file_id": "vault-x"},
            None,
        ])
        fail_calls = []
        import vault_relationship_graph as rg
        with patch.object(
            va, "claim_next_analysis_job",
            side_effect=lambda **k: next(claims),
        ), patch.object(
            va, "fail_analysis_job",
            side_effect=lambda *a, **k: fail_calls.append(
                (a, k),
            ),
        ), patch.object(
            va, "complete_analysis_job",
        ), patch.object(
            rg, "build_relationships_for_vault",
            side_effect=RuntimeError("simulated detector failure"),
        ):
            report = vrw.drain_relationship_building(
                vault_id="vault-x", max_jobs=1,
            )
        self.assertEqual(len(fail_calls), 1)
        self.assertEqual(fail_calls[0][0], ("j1",))
        self.assertEqual(fail_calls[0][1].get("retry"), False)
                                                 
                                                          
        self.assertIn(
            "simulated detector failure",
            fail_calls[0][1].get("error", ""),
        )
        self.assertEqual(report["succeeded"], 0)
        self.assertEqual(report["failed"], 1)


class EnqueueChainSourceGuardTests(unittest.TestCase):
    def test_understanding_worker_enqueues_after_complete(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
                                                           
                                                         
        complete_idx = src.rfind("complete_analysis_job")
        enqueue_idx = src.find("enqueue_relationship_building")
        self.assertGreater(complete_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(
            complete_idx, enqueue_idx,
            "understanding success must come BEFORE the "
            "relationship_building enqueue",
        )

    def test_embedding_worker_enqueues_after_cache_miss_path(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew._process_one_embedding_job)
                                                                
                                                             
        complete_idx = src.rfind("complete_analysis_job")
        enqueue_idx = src.rfind("enqueue_relationship_building")
        self.assertGreater(complete_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(complete_idx, enqueue_idx)

    def test_embedding_worker_enqueues_after_cache_hit_path_too(self):
                                                             
                                                            
        import vault_embedding_worker as vew
        src = inspect.getsource(vew._process_one_embedding_job)
                                                           
                                         
        n_enqueue = src.count("enqueue_relationship_building")
        self.assertGreaterEqual(n_enqueue, 2)


class ChatHandlerDrainOrderTests(unittest.TestCase):
    def test_relationship_drain_runs_after_embedding_drain(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        embedding_idx = src.find("drain_file_embedding")
        relationship_idx = src.find("drain_relationship_building")
        self.assertGreater(embedding_idx, -1)
        self.assertGreater(relationship_idx, -1)
        self.assertLess(
            embedding_idx, relationship_idx,
            "relationship drain must run AFTER embedding drain "
            "so the graph reads fresh vectors",
        )

    def test_relationship_drain_runs_after_understanding_drain(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        understanding_idx = src.find("drain_file_understanding")
        relationship_idx = src.find("drain_relationship_building")
        self.assertGreater(understanding_idx, -1)
        self.assertGreater(relationship_idx, -1)
        self.assertLess(
            understanding_idx, relationship_idx,
            "relationship drain must run AFTER understanding "
            "drain so the graph reads fresh signals",
        )

    def test_chat_handler_drain_swallows_exceptions(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                            
                                                        
        idx = src.find("drain_relationship_building")
        window = src[max(0, idx - 400):idx + 400]
        self.assertIn("except Exception", window)


class FailedBuildScrubbingTests(unittest.TestCase):
    def test_truncate_error_scrubs_password_shape(self):
        scrubbed = va._truncate_error(
            "build failed: password=hunter2 token=SECRET"
        )
        self.assertIn("password=<redacted>", scrubbed)
        self.assertNotIn("hunter2", scrubbed)
        self.assertNotIn("SECRET", scrubbed)


if __name__ == "__main__":
    unittest.main()
