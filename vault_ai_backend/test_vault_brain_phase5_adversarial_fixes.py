

from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest import mock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class ArchiveWorkerEnqueueGuard(unittest.TestCase):


    def test_archive_uses_va_not_ai_for_enqueue(self):
        import vault_archive_worker
        src = inspect.getsource(vault_archive_worker)
                                                                    
        self.assertNotIn(
            "ai.enqueue_analysis_job", src,
            "archive worker references ai.enqueue_analysis_job — "
            "but 'ai' is vault_archive_indexing, NOT vault_analysis. "
            "Should be va.enqueue_analysis_job.",
        )
                                                               
                                         
        self.assertIn(
            "va.enqueue_analysis_job", src,
            "archive worker is missing the va.enqueue_analysis_job "
            "call entirely.",
        )

    def test_archive_uses_va_stage_constant(self):
        import vault_archive_worker
        src = inspect.getsource(vault_archive_worker)
        self.assertNotIn(
            "ai.STAGE_CONTENT_CHUNKING", src,
            "archive worker references ai.STAGE_CONTENT_CHUNKING — "
            "'ai' (vault_archive_indexing) doesn't export that.",
        )
        self.assertIn(
            "va.STAGE_CONTENT_CHUNKING", src,
            "archive worker should use va.STAGE_CONTENT_CHUNKING",
        )


class ReconcilerStaleChunkingColumnGuard(unittest.TestCase):


    def test_no_claimed_at_in_stale_chunking_sql(self):


        import ast
        from vault_reconciler import (
            repair_stale_chunking_jobs_for_vault,
        )
        tree = ast.parse(
            inspect.getsource(repair_stale_chunking_jobs_for_vault),
        )
        sql_literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if "UPDATE" in v and "WHERE" in v:
                    sql_literals.append(v)
        self.assertTrue(
            sql_literals,
            "couldn't find a SQL literal in the function body",
        )
        for sql in sql_literals:
            self.assertNotIn(
                "claimed_at", sql,
                f"SQL still references the broken column: {sql!r}",
            )
            self.assertIn("locked_at", sql)
            self.assertIn("locked_by", sql)

    def test_repair_query_fires_locked_at_predicate(self):
        from vault_reconciler import (
            repair_stale_chunking_jobs_for_vault,
        )

        captured = {"sql": None, "params": None}

        class _Cur:
            rowcount = 1
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params
            def close(self):
                pass

        class _Conn:
            def cursor(self): return _Cur()
            def commit(self): pass
            def rollback(self): pass
            def close(self): pass

        with mock.patch("vault_core.get_db", return_value=_Conn()):
            repair_stale_chunking_jobs_for_vault(
                "v-1", stale_after_seconds=600,
            )
        self.assertIn("locked_at", captured["sql"])
        self.assertNotIn("claimed_at", captured["sql"])


class ContinuationSetterOnEmptyBundleGuard(unittest.TestCase):


    def test_setter_fires_on_empty_bundle_in_continuation(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        from vault_evidence_bundle import EvidenceBundle

        store_calls = []

                                        
        async def _retrieve(**kwargs):
                                                
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(),
                matching_file_ids=(),
                coverage_at_time={},
                retrieval_mode="semantic",
            )

        def _setter(**kwargs):
            store_calls.append(kwargs)

                                                              
        from vault_brain_continuation import BrainContinuation
        prior = BrainContinuation(
            vault_id="v-1",
            query_prefix="about apartment",
            intent="search_vault_content",
            breadth="broad",
            file_ids_returned=("A", "B", "C"),
            coverage_at_time={},
            retrieval_mode="semantic",
            set_at_unix=1.0,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="show more",
            key=b"\x00" * 32,
            embed_fn=lambda t: asyncio.sleep(0, result=[0.0]*1536),
            coverage={},
            retrieve_fn=_retrieve,
            file_name_lookup=lambda ids: {},
            brain_coverage_loader=lambda v: BrainCoverage(vault_id="v-1"),
            continuation_loader=lambda v: prior,
            continuation_setter=_setter,
            now_unix=2.0,
        ))
                                                                 
                              
        self.assertEqual(
            len(store_calls), 1,
            "continuation setter did not fire on empty bundle — "
            "next 'show more' will re-exclude the same set.",
        )
                                                                
                                      
        self.assertEqual(
            list(store_calls[0]["file_ids_returned"]),
            ["A", "B", "C"],
        )
                              
        self.assertEqual(store_calls[0]["set_at_unix"], 2.0)


class DiversificationPreservesRoundRobinOrderGuard(unittest.TestCase):


    def _ch(self, file_id, score, idx=0):
        from vault_evidence_bundle import EvidenceChunk
        return EvidenceChunk(
            chunk_id=f"c-{file_id}-{idx}",
            file_id=file_id, chunk_index=idx,
            text="t", extraction_source="pdf_text",
            score=score, char_start=0, char_end=1,
        )

    def test_round_robin_order_preserved_on_uneven_scores(self):
        from vault_brain_retrieval import _diversify_across_files
                                                               
                                                               
        chunks = [
            self._ch("A", 0.95, 0), self._ch("A", 0.94, 1),
            self._ch("B", 0.50, 0), self._ch("B", 0.49, 1),
            self._ch("C", 0.30, 0), self._ch("C", 0.29, 1),
        ]
        out = _diversify_across_files(
            chunks, max_files=3, max_chunks_per_file=2,
        )
                                                                 
                         
        first_three_files = [c.file_id for c in out[:3]]
        self.assertEqual(
            set(first_three_files), {"A", "B", "C"},
            "round-robin order not preserved — first 3 picks should "
            f"hit each file once but got {first_three_files}",
        )

    def test_top_k_trim_surfaces_all_files_on_uneven_scores(self):


        from vault_brain_retrieval import _diversify_across_files
        chunks = [
            self._ch("A", 0.95, 0), self._ch("A", 0.94, 1),
            self._ch("B", 0.50, 0),
            self._ch("C", 0.30, 0),
        ]
        out = _diversify_across_files(
            chunks, max_files=3, max_chunks_per_file=2,
        )
                                                                   
        trimmed = out[:3]
        file_set = {c.file_id for c in trimmed}
        self.assertEqual(
            file_set, {"A", "B", "C"},
            "top_k=3 trim collapsed to a single high-scoring file "
            f"set={file_set} — diversification failed.",
        )


class Phase5FixesSmokeCheck(unittest.TestCase):
    def test_chat_pipeline_still_handles_broad_query(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        from vault_evidence_bundle import EvidenceBundle, EvidenceChunk

        async def _retrieve(**kwargs):
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(
                    EvidenceChunk(
                        chunk_id="c", file_id="f", chunk_index=0,
                        text="snippet", extraction_source="pdf_text",
                        score=0.8, char_start=0, char_end=10,
                    ),
                ),
                matching_file_ids=("f",),
                coverage_at_time={},
                retrieval_mode="semantic",
            )

        async def _stub_embed(text):
            return [0.0] * 1536

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about insurance?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            retrieve_fn=_retrieve,
            file_name_lookup=lambda ids: {fid: "f.pdf" for fid in ids},
            brain_coverage_loader=lambda v: BrainCoverage(
                vault_id="v-1", total_files=1,
                files_with_embedded_chunks=1,
                files_with_all_chunks_embedded=1,
            ),
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.breadth, "broad")


if __name__ == "__main__":
    unittest.main()
