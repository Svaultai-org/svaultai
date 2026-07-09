

from __future__ import annotations

import asyncio
import inspect
import os
import time
import unittest
from unittest import mock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCursor:
    def __init__(self, *, single_results=None, multi_results=None,
                 raise_on_execute=False, rowcount=0):
                                                                     
                                                                
        self._single = list(single_results or [])
        self._multi = list(multi_results or [])
        self._raise = raise_on_execute
        self._affected = rowcount
        self.executed: list[tuple] = []

    def execute(self, sql, params=None):
        if self._raise:
            raise RuntimeError("simulated execute failure")
        self.executed.append((sql, params))

    def fetchone(self):
        if not self._single:
            return None
        return self._single.pop(0)

    def fetchall(self):
        if not self._multi:
            return []
        return self._multi.pop(0)

    @property
    def rowcount(self):
        return self._affected

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class BrainCoverageTests(unittest.TestCase):
    def test_empty_vault_id_returns_error(self):
        from vault_brain_coverage import brain_coverage_for_vault
        c = brain_coverage_for_vault("")
        self.assertEqual(c.vault_id, "")
        self.assertEqual(c.error, "empty_vault_id")

    def test_coverage_percentage_empty_vault_is_one(self):
        from vault_brain_coverage import BrainCoverage
        c = BrainCoverage(vault_id="v")
        self.assertEqual(c.coverage_percentage, 1.0)
        self.assertTrue(c.is_complete)

    def test_coverage_percentage_half_indexed(self):
        from vault_brain_coverage import BrainCoverage
        c = BrainCoverage(
            vault_id="v", total_files=10,
            files_with_all_chunks_embedded=5,
        )
        self.assertAlmostEqual(c.coverage_percentage, 0.5)
        self.assertFalse(c.is_complete)

    def test_coverage_percentage_excludes_unsupported(self):
        from vault_brain_coverage import BrainCoverage
                                                    
        c = BrainCoverage(
            vault_id="v", total_files=10, unsupported_files=2,
            files_with_all_chunks_embedded=5,
        )
        self.assertAlmostEqual(c.coverage_percentage, 0.625)

    def test_coverage_complete_threshold_drives_is_complete(self):
        from vault_brain_coverage import BrainCoverage
                                                            
                                                                    
        c = BrainCoverage(
            vault_id="v", total_files=20,
            files_with_all_chunks_embedded=19,
        )
        self.assertTrue(c.is_complete)

    def test_pending_jobs_make_incomplete(self):
        from vault_brain_coverage import BrainCoverage
        c = BrainCoverage(
            vault_id="v", total_files=10,
            files_with_all_chunks_embedded=10,
            pending_chunking_jobs=2,
        )
        self.assertFalse(c.is_complete)

    def test_failed_jobs_surface_has_failures(self):
        from vault_brain_coverage import BrainCoverage
        c = BrainCoverage(
            vault_id="v", failed_chunking_jobs=1,
        )
        self.assertTrue(c.has_failures)

    def test_to_dict_redacts_vault_id(self):
        from vault_brain_coverage import BrainCoverage
        c = BrainCoverage(vault_id="abc-def-1234-very-long-id")
        d = c.to_dict()
        self.assertNotIn("very-long-id", str(d["vault_id"]))
        self.assertTrue(d["vault_id"].endswith("…"))


class BrainBreadthTests(unittest.TestCase):
    def test_narrow_default(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_NARROW,
        )
        self.assertEqual(
            classify_brain_breadth("hi").breadth, BREADTH_NARROW,
        )

    def test_broad_anything_about(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_BROAD,
        )
        self.assertEqual(
            classify_brain_breadth(
                "Do I have anything about insurance?",
            ).breadth, BREADTH_BROAD,
        )

    def test_broad_what_files_mention(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_BROAD,
        )
        self.assertEqual(
            classify_brain_breadth(
                "What files mention Ally Bank?",
            ).breadth, BREADTH_BROAD,
        )

    def test_broad_all_files_about(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_BROAD,
        )
        self.assertEqual(
            classify_brain_breadth(
                "Show me all files about my apartment",
            ).breadth, BREADTH_BROAD,
        )

    def test_broad_everything(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_BROAD,
        )
        self.assertEqual(
            classify_brain_breadth(
                "Find everything about taxes",
            ).breadth, BREADTH_BROAD,
        )

    def test_summary_phrase(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_SUMMARY,
        )
        self.assertEqual(
            classify_brain_breadth(
                "Summarize this folder",
            ).breadth, BREADTH_SUMMARY,
        )

    def test_summary_tldr(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_SUMMARY,
        )
        self.assertEqual(
            classify_brain_breadth(
                "TL;DR my taxes folder",
            ).breadth, BREADTH_SUMMARY,
        )

    def test_continuation_without_context_falls_to_broad(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_BROAD,
        )
        self.assertEqual(
            classify_brain_breadth(
                "Show more", has_continuation_context=False,
            ).breadth, BREADTH_BROAD,
        )

    def test_continuation_with_context_is_continuation(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_CONTINUATION,
        )
        self.assertEqual(
            classify_brain_breadth(
                "What else?", has_continuation_context=True,
            ).breadth, BREADTH_CONTINUATION,
        )

    def test_specific_narrow_credential_question(self):
        from vault_brain_breadth import (
            classify_brain_breadth, BREADTH_NARROW,
        )
                                                      
        self.assertEqual(
            classify_brain_breadth(
                "What's my Chase routing number?",
            ).breadth, BREADTH_NARROW,
        )


class UnderstandingStatusTests(unittest.TestCase):
    def test_not_started_when_no_text(self):
                       
        from vault_brain_understanding import (
            understanding_status_for_file,
            UNDERSTANDING_NOT_STARTED,
        )
        cur = _FakeCursor(single_results=[None])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_NOT_STARTED)

    def test_failed_when_analysis_failed(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_FAILED,
        )
        cur = _FakeCursor(single_results=[
            ("failed", "not_available", "{}"),
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_FAILED)

    def test_unsupported(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_UNSUPPORTED,
        )
        cur = _FakeCursor(single_results=[
            ("unsupported", "not_available", "{}"),
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_UNSUPPORTED)

    def test_extracted_with_no_chunks(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_EXTRACTED,
        )
        cur = _FakeCursor(single_results=[
            ("analyzed", "available", "{}"),
            (0, 0),                        
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_EXTRACTED)

    def test_chunked_no_embeddings(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_CHUNKED,
        )
        cur = _FakeCursor(single_results=[
            ("analyzed", "available", "{}"),
            (5, 0),                        
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_CHUNKED)

    def test_embedded_when_all_chunks_embedded(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_EMBEDDED,
            is_fully_understood,
        )
        cur = _FakeCursor(single_results=[
            ("analyzed", "available", "{}"),
            (5, 5),                         
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_EMBEDDED)
        self.assertTrue(is_fully_understood(s))

    def test_partial_when_some_chunks_embedded(self):
        from vault_brain_understanding import (
            understanding_status_for_file, UNDERSTANDING_PARTIAL,
        )
        cur = _FakeCursor(single_results=[
            ("analyzed", "available", "{}"),
            (5, 2),
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            s = understanding_status_for_file("v-1", "f-1")
        self.assertEqual(s, UNDERSTANDING_PARTIAL)


class BrainContinuationTests(unittest.TestCase):
    def setUp(self):
        import vault_brain_continuation
        vault_brain_continuation.reset_for_tests()

    def test_set_then_get(self):
        from vault_brain_continuation import (
            set_last_brain_evidence, get_last_brain_evidence,
        )
        set_last_brain_evidence(
            vault_id="v-1",
            query="anything about insurance?",
            intent="search_vault_content",
            breadth="broad",
            file_ids_returned=["f-1", "f-2", "f-3"],
            coverage_at_time={"total": 10},
            retrieval_mode="semantic",
            set_at_unix=1700.0,
        )
        cont = get_last_brain_evidence("v-1")
        self.assertIsNotNone(cont)
        self.assertEqual(cont.vault_id, "v-1")
        self.assertEqual(cont.breadth, "broad")
        self.assertEqual(
            list(cont.file_ids_returned), ["f-1", "f-2", "f-3"],
        )

    def test_query_truncation(self):
        from vault_brain_continuation import (
            set_last_brain_evidence, get_last_brain_evidence,
            MAX_QUERY_PREFIX_CHARS,
        )
        long_q = "x" * 1000
        set_last_brain_evidence(
            vault_id="v-1", query=long_q,
            intent="i", breadth="b",
            file_ids_returned=[], coverage_at_time={},
            retrieval_mode="m", set_at_unix=1.0,
        )
        cont = get_last_brain_evidence("v-1")
        self.assertLessEqual(
            len(cont.query_prefix), MAX_QUERY_PREFIX_CHARS,
        )

    def test_clear(self):
        from vault_brain_continuation import (
            set_last_brain_evidence, get_last_brain_evidence,
            clear_last_brain_evidence,
        )
        set_last_brain_evidence(
            vault_id="v-1", query="q", intent="i", breadth="b",
            file_ids_returned=["a"], coverage_at_time={},
            retrieval_mode="m", set_at_unix=1.0,
        )
        clear_last_brain_evidence("v-1")
        self.assertIsNone(get_last_brain_evidence("v-1"))

    def test_to_debug_dict_no_query(self):
        from vault_brain_continuation import (
            set_last_brain_evidence, get_last_brain_evidence,
        )
        set_last_brain_evidence(
            vault_id="v-1", query="rumpelstiltskin-marker",
            intent="i", breadth="b",
            file_ids_returned=["f"], coverage_at_time={},
            retrieval_mode="m", set_at_unix=1.0,
        )
        cont = get_last_brain_evidence("v-1")
        debug = cont.to_debug_dict()
                                                             
        self.assertNotIn("rumpelstiltskin", repr(debug))


class DiversificationTests(unittest.TestCase):
    def _ch(self, file_id, score, chunk_index=0):
        from vault_evidence_bundle import EvidenceChunk
        return EvidenceChunk(
            chunk_id=f"c-{file_id}-{chunk_index}",
            file_id=file_id, chunk_index=chunk_index,
            text=f"t-{file_id}-{chunk_index}",
            extraction_source="pdf_text",
            score=score, char_start=0, char_end=10,
        )

    def test_one_file_dominates_without_diversification_cap(self):
        from vault_brain_retrieval import _diversify_across_files
        chunks = [self._ch("a", 0.9 - i * 0.01, i) for i in range(10)]
        out = _diversify_across_files(
            chunks, max_files=5, max_chunks_per_file=2,
        )
                                                            
        self.assertEqual(len(out), 2)
        self.assertTrue(all(c.file_id == "a" for c in out))

    def test_diversification_spreads_across_files(self):
        from vault_brain_retrieval import _diversify_across_files
                                                    
        chunks = []
        for f in ["a", "b", "c", "d", "e"]:
            for i in range(3):
                chunks.append(self._ch(f, 0.9 - i * 0.05, i))
        out = _diversify_across_files(
            chunks, max_files=5, max_chunks_per_file=2,
        )
                                                 
        self.assertEqual(len(out), 10)
        file_counts = {}
        for c in out:
            file_counts[c.file_id] = file_counts.get(c.file_id, 0) + 1
        for f in ["a", "b", "c", "d", "e"]:
            self.assertEqual(file_counts[f], 2)

    def test_diversification_caps_distinct_files(self):
        from vault_brain_retrieval import _diversify_across_files
        chunks = []
        for f in [f"f{i}" for i in range(10)]:
            chunks.append(self._ch(f, 0.5))
        out = _diversify_across_files(
            chunks, max_files=3, max_chunks_per_file=1,
        )
        self.assertEqual(len(out), 3)


class ContinueIntentTests(unittest.TestCase):
    def test_show_more_with_context(self):
        from vault_brain_intent import (
            classify_brain_intent, CONTINUE_LAST_SEARCH,
        )
        self.assertEqual(
            classify_brain_intent(
                "show more", has_continuation_context=True,
            ).intent,
            CONTINUE_LAST_SEARCH,
        )

    def test_show_more_without_context_falls_through(self):
        from vault_brain_intent import classify_brain_intent
                                                                  
        result = classify_brain_intent(
            "show more", has_continuation_context=False,
        )
        self.assertNotEqual(result.intent, "continue_last_search")

    def test_what_else_with_context(self):
        from vault_brain_intent import (
            classify_brain_intent, CONTINUE_LAST_SEARCH,
        )
        self.assertEqual(
            classify_brain_intent(
                "what else?", has_continuation_context=True,
            ).intent,
            CONTINUE_LAST_SEARCH,
        )


class CoverageAwareAnswererTests(unittest.TestCase):
    def _bundle(self, chunks=(), files=(),
                mode="semantic", coverage=None):
        from vault_evidence_bundle import EvidenceBundle
        return EvidenceBundle(
            query="q", vault_id="v",
            chunks=tuple(chunks),
            matching_file_ids=tuple(files),
            coverage_at_time=dict(coverage or {}),
            retrieval_mode=mode,
        )

    def _chunk(self, file_id="f-1", text="snippet"):
        from vault_evidence_bundle import EvidenceChunk
        return EvidenceChunk(
            chunk_id="c", file_id=file_id, chunk_index=0,
            text=text, extraction_source="pdf_text",
            score=0.8, char_start=0, char_end=10,
        )

    def _names(self, m):
        def _lookup(ids):
            return {fid: m.get(fid, fid) for fid in ids}
        return _lookup

    def test_coverage_incomplete_adds_still_indexing_hint(self):
        from vault_brain_answerer import (
            compose_brain_answer, COPY_BRAIN_STILL_INDEXING,
        )
        from vault_brain_coverage import BrainCoverage
        bundle = self._bundle(
            chunks=[self._chunk()],
            files=["f-1"],
        )
        coverage = BrainCoverage(
            vault_id="v", total_files=10,
            files_with_all_chunks_embedded=3,
        )
        ans = compose_brain_answer(
            intent="search_vault_content", bundle=bundle,
            file_name_lookup=self._names({"f-1": "a.pdf"}),
            brain_coverage=coverage,
        )
        self.assertIn(COPY_BRAIN_STILL_INDEXING, ans.reply_body)

    def test_coverage_complete_does_not_add_pending_hint(self):
        from vault_brain_answerer import (
            compose_brain_answer, COPY_BRAIN_STILL_INDEXING,
        )
        from vault_brain_coverage import BrainCoverage
        bundle = self._bundle(
            chunks=[self._chunk()],
            files=["f-1"],
        )
        coverage = BrainCoverage(
            vault_id="v", total_files=10,
            files_with_all_chunks_embedded=10,
        )
        ans = compose_brain_answer(
            intent="search_vault_content", bundle=bundle,
            file_name_lookup=self._names({"f-1": "a.pdf"}),
            brain_coverage=coverage,
        )
        self.assertNotIn(COPY_BRAIN_STILL_INDEXING, ans.reply_body)

    def test_failures_add_failure_hint(self):
        from vault_brain_answerer import (
            compose_brain_answer, COPY_BRAIN_HAS_FAILURES,
        )
        from vault_brain_coverage import BrainCoverage
        bundle = self._bundle(
            chunks=[self._chunk()],
            files=["f-1"],
        )
        coverage = BrainCoverage(
            vault_id="v", total_files=10,
            files_with_all_chunks_embedded=10,
            failed_chunking_jobs=1,
        )
        ans = compose_brain_answer(
            intent="search_vault_content", bundle=bundle,
            file_name_lookup=self._names({"f-1": "a.pdf"}),
            brain_coverage=coverage,
        )
        self.assertIn(COPY_BRAIN_HAS_FAILURES, ans.reply_body)

    def test_lexical_fallback_adds_warning(self):
        from vault_brain_answerer import (
            compose_brain_answer, COPY_BRAIN_LEXICAL_FALLBACK,
        )
        bundle = self._bundle(
            chunks=[self._chunk()],
            files=["f-1"],
            mode="chunk_text_lexical",
        )
        ans = compose_brain_answer(
            intent="search_vault_content", bundle=bundle,
            file_name_lookup=self._names({"f-1": "a.pdf"}),
            brain_coverage=None,
        )
        self.assertIn(COPY_BRAIN_LEXICAL_FALLBACK, ans.reply_body)


class ExtractionWorkerHooksTests(unittest.TestCase):


    WORKERS = [
        "vault_analysis_worker",
        "vault_ocr_worker",
        "vault_archive_worker",
        "vault_audio_worker",
        "vault_video_worker",
    ]

    def test_every_worker_enqueues_content_chunking(self):
        for module_name in self.WORKERS:
            module = __import__(module_name)
            src = inspect.getsource(module)
            self.assertIn(
                "STAGE_CONTENT_CHUNKING", src,
                f"{module_name} does not reference "
                "STAGE_CONTENT_CHUNKING",
            )
            self.assertIn(
                "enqueue_analysis_job", src,
                f"{module_name} does not call enqueue_analysis_job",
            )


class ReconcilerNewRepairsTests(unittest.TestCase):
    def test_missing_embeddings_repair_returns_count(self):
        from vault_reconciler import (
            repair_chunks_missing_embeddings_for_vault,
        )
                                                        
        cur = _FakeCursor(multi_results=[
            [("f-1",), ("f-2",)],
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            with mock.patch(
                "vault_analysis.enqueue_analysis_job",
                return_value="job-1",
            ):
                n = repair_chunks_missing_embeddings_for_vault("v-1")
        self.assertEqual(n, 2)

    def test_wrong_dim_or_model_repair_uses_config_dim(self):
        from vault_reconciler import (
            repair_wrong_dim_or_model_embeddings_for_vault,
        )
        cur = _FakeCursor(rowcount=3)
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            n = repair_wrong_dim_or_model_embeddings_for_vault("v-1")
        self.assertEqual(n, 3)
                                                               
        self.assertGreater(len(cur.executed), 0)
        sql, params = cur.executed[0]
                                                              
        self.assertEqual(params[0], "v-1")
        self.assertIsInstance(params[1], int)
        self.assertIsInstance(params[2], str)

    def test_stale_chunking_jobs_repair(self):
        from vault_reconciler import (
            repair_stale_chunking_jobs_for_vault,
        )
        cur = _FakeCursor(rowcount=2)
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            n = repair_stale_chunking_jobs_for_vault(
                "v-1", stale_after_seconds=600,
            )
        self.assertEqual(n, 2)

    def test_report_total_includes_new_fields(self):
        from vault_reconciler import ReconcilerReport
        r = ReconcilerReport(
            vault_id="v", status_drift_repaired=1,
            missing_embeddings_repaired=2,
            wrong_dim_embeddings_nulled=3,
            stale_chunking_jobs_reset=4,
        )
                            
        self.assertEqual(r.total_repairs(), 10)
        d = r.to_dict()
        self.assertIn("missing_embeddings_repaired", d)
        self.assertIn("wrong_dim_embeddings_nulled", d)
        self.assertIn("stale_chunking_jobs_reset", d)


class Phase5SourceSafetyTests(unittest.TestCase):


    def test_coverage_module_does_not_log_text(self):
        import vault_brain_coverage as v
        src = inspect.getsource(v)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            for forbidden in (" plaintext", " text,", " query",
                              "extracted_text"):
                self.assertNotIn(
                    forbidden, line,
                    f"vault_brain_coverage may log content: {line!r}",
                )

    def test_breadth_module_does_not_log_text(self):
        import vault_brain_breadth as v
                                                             
                                                                
        self.assertNotIn(
            "logger.", inspect.getsource(v),
            "vault_brain_breadth must not log — adding logging "
            "requires explicit safety review.",
        )

    def test_continuation_module_does_not_log_query(self):
        import vault_brain_continuation as v
        src = inspect.getsource(v)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            self.assertNotIn(
                "query", line,
                f"vault_brain_continuation may log query: {line!r}",
            )

    def test_understanding_module_does_not_log_file_id_or_content(self):
        import vault_brain_understanding as v
        src = inspect.getsource(v)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            for forbidden in (" file_id", "extracted_text"):
                self.assertNotIn(
                    forbidden, line,
                    f"vault_brain_understanding may log content: "
                    f"{line!r}",
                )


class Phase5ConfigKnobsTests(unittest.TestCase):
    def test_all_8_knobs_present(self):
        import vault_config
        vault_config.reset_for_tests()
        b = vault_config.brain()
        knobs = [
            "narrow_retrieval_top_k",
            "broad_retrieval_top_k",
            "max_files_per_query",
            "max_chunks_per_file_per_query",
            "summary_max_chunks",
            "diversify_by_file",
            "coverage_complete_threshold",
            "deep_continuation_page_size",
        ]
        for k in knobs:
            self.assertTrue(
                hasattr(b, k),
                f"BrainConfig missing knob {k}",
            )

    def test_env_overrides_work(self):
        import vault_config
        prior = dict(os.environ)
        try:
            os.environ["VAULTAI_BROAD_RETRIEVAL_TOP_K"] = "64"
            os.environ["VAULTAI_MAX_FILES_PER_QUERY"] = "20"
            vault_config.reset_for_tests()
            b = vault_config.brain()
            self.assertEqual(b.broad_retrieval_top_k, 64)
            self.assertEqual(b.max_files_per_query, 20)
        finally:
            os.environ.clear()
            os.environ.update(prior)
            vault_config.reset_for_tests()


if __name__ == "__main__":
    unittest.main()
