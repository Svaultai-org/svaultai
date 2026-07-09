

from __future__ import annotations

import asyncio
import inspect
import io
import re
import unittest
from unittest import mock

from vault_evidence_bundle import EvidenceBundle, EvidenceChunk


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class BroadRetrievalCandidateCollapseGuard(unittest.TestCase):


    def test_per_file_window_function_present_in_sql(self):
        import vault_brain_retrieval
        src = inspect.getsource(vault_brain_retrieval)
        self.assertIn(
            "_semantic_search_per_file", src,
            "Broad retrieval must call _semantic_search_per_file so "
            "candidate gathering is file-diverse before the final "
            "top_k trim.",
        )
        self.assertIn(
            "ROW_NUMBER() OVER", src,
            "_semantic_search_per_file must use ROW_NUMBER() to "
            "rank chunks per file_id.",
        )
        self.assertIn(
            "PARTITION BY file_id", src,
            "ROW_NUMBER() must PARTITION BY file_id so per-file "
            "ranking is correct.",
        )

    def test_broad_breadth_routes_to_per_file_path(self):


        from vault_brain_retrieval import (
            retrieve_evidence, RETRIEVAL_BREADTH_BROAD,
        )

        called = {"per_file": 0, "flat": 0}

        def fake_per_file(**kwargs):
            called["per_file"] += 1
            return []

        def fake_flat(**kwargs):
            called["flat"] += 1
            return []

        async def fake_embed(_q):
            return [0.0] * 1536

        with mock.patch(
            "vault_brain_retrieval._semantic_search_per_file",
            side_effect=fake_per_file,
        ), mock.patch(
            "vault_brain_retrieval._semantic_search",
            side_effect=fake_flat,
        ), mock.patch(
            "vault_brain_retrieval._chunk_text_lexical_search",
            return_value=[],
        ), mock.patch(
            "vault_brain_retrieval._lexical_search",
            return_value=[],
        ):
            _run(retrieve_evidence(
                vault_id="v1",
                query="anything about apartment?",
                key=b"k" * 32,
                embed_fn=fake_embed,
                coverage={},
                breadth=RETRIEVAL_BREADTH_BROAD,
            ))
        self.assertGreaterEqual(
            called["per_file"], 1,
            "Broad breadth must call _semantic_search_per_file at "
            "least once.",
        )
        self.assertEqual(
            called["flat"], 0,
            "Broad breadth must NOT fall through to the flat "
            "_semantic_search (the bug it fixes).",
        )

    def test_diversifier_returns_multiple_files_when_one_file_dominates(
        self,
    ):


        from vault_brain_retrieval import _diversify_across_files

                                                                    
        chunks = [
            EvidenceChunk(chunk_id=f"a{i}", file_id="A",
                          chunk_index=i, text=f"a{i}",
                          extraction_source="text",
                          score=0.95 - 0.01 * i,
                          char_start=0, char_end=10)
            for i in range(6)
        ] + [
            EvidenceChunk(chunk_id="b1", file_id="B",
                          chunk_index=0, text="b1",
                          extraction_source="text", score=0.30,
                          char_start=0, char_end=10),
            EvidenceChunk(chunk_id="c1", file_id="C",
                          chunk_index=0, text="c1",
                          extraction_source="text", score=0.28,
                          char_start=0, char_end=10),
            EvidenceChunk(chunk_id="d1", file_id="D",
                          chunk_index=0, text="d1",
                          extraction_source="text", score=0.26,
                          char_start=0, char_end=10),
        ]
        out = _diversify_across_files(
            chunks, max_files=8, max_chunks_per_file=2,
        )
        distinct = {c.file_id for c in out}
        self.assertGreaterEqual(
            len(distinct), 3,
            f"Diversifier collapsed to {len(distinct)} files; "
            "broad retrieval must return ≥3 distinct files when "
            "candidates exist from multiple files.",
        )
                       
        per_file = {}
        for c in out:
            per_file[c.file_id] = per_file.get(c.file_id, 0) + 1
        for fid, count in per_file.items():
            self.assertLessEqual(
                count, 2,
                f"Per-file cap violated: file {fid} returned "
                f"{count} chunks (cap was 2).",
            )


class ContinuationExcludesChunkIdsGuard(unittest.TestCase):


    def test_brain_continuation_carries_chunk_ids(self):
        import vault_brain_continuation as bc
        bc.reset_for_tests()
        bc.set_last_brain_evidence(
            vault_id="v1", query="apartment",
            intent="search_vault_content", breadth="broad",
            file_ids_returned=["F1", "F2"],
            chunk_ids_returned=["A", "B", "C"],
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )
        got = bc.get_last_brain_evidence("v1")
        self.assertIsNotNone(got)
        self.assertEqual(got.chunk_ids_returned, ("A", "B", "C"))
        self.assertEqual(got.file_ids_returned, ("F1", "F2"))

    def test_brain_continuation_chunk_ids_optional_for_legacy_setter(
        self,
    ):


        import vault_brain_continuation as bc
        bc.reset_for_tests()
        bc.set_last_brain_evidence(
            vault_id="v1", query="apartment",
            intent="search_vault_content", breadth="broad",
            file_ids_returned=["F1"],
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )
        got = bc.get_last_brain_evidence("v1")
        self.assertIsNotNone(got)
        self.assertEqual(got.chunk_ids_returned, tuple())

    def test_retrieve_passes_excluded_chunk_ids_into_sql(self):


        import vault_brain_retrieval as br
        src = inspect.getsource(br._semantic_search_per_file)
        self.assertIn(
            "chunk_id::text NOT IN", src,
            "_semantic_search_per_file must push excluded_chunk_ids "
            "into the SQL WHERE clause.",
        )

    def test_chat_pipeline_excludes_prior_chunk_ids_on_continuation(self):


        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        import vault_brain_continuation as bc
        from vault_brain_coverage import BrainCoverage

        bc.reset_for_tests()
                                                       
        prior_cont = bc.BrainContinuation(
            vault_id="v1", query_prefix="apartment",
            intent="search_vault_content", breadth="broad",
            file_ids_returned=("F1", "F2"),
            chunk_ids_returned=("A", "B", "C"),
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )

        captured: dict = {}

        async def fake_retrieve(**kwargs):
            captured.update(kwargs)
            return EvidenceBundle(
                query=kwargs.get("query", ""),
                vault_id=kwargs.get("vault_id", "v1"),
                chunks=(),
                matching_file_ids=(),
                coverage_at_time={},
                retrieval_mode="no_matches",
            )

        async def fake_embed(_q):
            return [0.0] * 1536

        _run(run_brain_chat_pipeline(
            vault_id="v1",
            message="search deeper",
            key=b"k" * 32,
            embed_fn=fake_embed,
            coverage={},
            retrieve_fn=fake_retrieve,
            brain_coverage_loader=lambda v: BrainCoverage(vault_id=v),
            continuation_loader=lambda v: prior_cont,
            continuation_setter=lambda **_: None,
        ))
        self.assertIn(
            "excluded_chunk_ids", captured,
            "Chat pipeline must forward excluded_chunk_ids on a "
            "continuation turn.",
        )
        self.assertEqual(
            tuple(captured["excluded_chunk_ids"]),
            ("A", "B", "C"),
        )

    def test_continuation_state_is_vault_scoped(self):


        import vault_brain_continuation as bc
        bc.reset_for_tests()
        bc.set_last_brain_evidence(
            vault_id="vault-A", query="x", intent="search_vault_content",
            breadth="broad", file_ids_returned=["F1"],
            chunk_ids_returned=["chunk-from-A"],
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )
        self.assertIsNone(bc.get_last_brain_evidence("vault-B"))
        got_a = bc.get_last_brain_evidence("vault-A")
        self.assertIsNotNone(got_a)
        self.assertEqual(got_a.chunk_ids_returned, ("chunk-from-A",))

    def test_continuation_can_be_cleared(self):


        import vault_brain_continuation as bc
        bc.reset_for_tests()
        bc.set_last_brain_evidence(
            vault_id="v1", query="x", intent="search_vault_content",
            breadth="broad", file_ids_returned=["F1"],
            chunk_ids_returned=["A"],
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )
        self.assertIsNotNone(bc.get_last_brain_evidence("v1"))
        bc.clear_last_brain_evidence("v1")
        self.assertIsNone(bc.get_last_brain_evidence("v1"))

    def test_chat_pipeline_accumulates_chunk_ids_across_turns(self):


        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        import vault_brain_continuation as bc
        from vault_brain_coverage import BrainCoverage

        bc.reset_for_tests()
        prior_cont = bc.BrainContinuation(
            vault_id="v1", query_prefix="apartment",
            intent="search_vault_content", breadth="broad",
            file_ids_returned=("F1",),
            chunk_ids_returned=("A", "B"),
            coverage_at_time={}, retrieval_mode="semantic",
            set_at_unix=1.0,
        )

        async def fake_retrieve(**kwargs):
            return EvidenceBundle(
                query=kwargs.get("query", ""),
                vault_id=kwargs.get("vault_id", "v1"),
                chunks=(
                    EvidenceChunk(chunk_id="C", file_id="F2",
                                  chunk_index=0, text="...",
                                  extraction_source="text",
                                  score=0.5, char_start=0, char_end=3),
                    EvidenceChunk(chunk_id="D", file_id="F2",
                                  chunk_index=1, text="...",
                                  extraction_source="text",
                                  score=0.4, char_start=0, char_end=3),
                ),
                matching_file_ids=("F2",),
                coverage_at_time={},
                retrieval_mode="semantic",
            )

        async def fake_embed(_q):
            return [0.0] * 1536

        captured: dict = {}

        def fake_setter(**kwargs):
            captured.update(kwargs)

        _run(run_brain_chat_pipeline(
            vault_id="v1",
            message="search deeper",
            key=b"k" * 32,
            embed_fn=fake_embed,
            coverage={},
            file_name_lookup=lambda ids: {fid: fid for fid in ids},
            retrieve_fn=fake_retrieve,
            brain_coverage_loader=lambda v: BrainCoverage(vault_id=v),
            continuation_loader=lambda v: prior_cont,
            continuation_setter=fake_setter,
        ))
        self.assertEqual(
            tuple(captured.get("chunk_ids_returned", ())),
            ("A", "B", "C", "D"),
            "Setter must receive the deduped union of prior + new "
            "chunk_ids.",
        )


class BrainCoverageFullyEmbeddedGuard(unittest.TestCase):


    def _bc(self, **kwargs):
        from vault_brain_coverage import BrainCoverage
        return BrainCoverage(vault_id="v1", **kwargs)

    def test_coverage_percentage_uses_all_chunks_embedded(self):
        bc = self._bc(
            total_files=10, unsupported_files=0,
            files_with_embedded_chunks=10,                    
            files_with_all_chunks_embedded=3,                 
        )
        self.assertEqual(bc.coverage_percentage, 0.3,
                         "coverage_percentage must read "
                         "files_with_all_chunks_embedded, not the "
                         "legacy any-embedded field.")

    def test_is_complete_requires_no_partial_embeddings(self):
        bc = self._bc(
            total_files=10, unsupported_files=0,
            files_with_embedded_chunks=10,
            files_with_all_chunks_embedded=10,
            files_with_partial_embeddings=1,                    
        )
        self.assertFalse(
            bc.is_complete,
            "is_complete must be False when any file has partial "
            "embeddings.",
        )

    def test_is_complete_requires_zero_unembedded_chunks(self):
        bc = self._bc(
            total_files=10, unsupported_files=0,
            files_with_embedded_chunks=10,
            files_with_all_chunks_embedded=10,
            chunks_total=100, chunks_embedded=99,
            chunks_unembedded=1,
        )
        self.assertFalse(
            bc.is_complete,
            "is_complete must be False when any chunk is "
            "unembedded — even when files all have SOME embeddings.",
        )

    def test_chunk_coverage_percentage_distinct_from_file(self):
        bc = self._bc(
            total_files=2, unsupported_files=0,
            files_with_embedded_chunks=2,
            files_with_all_chunks_embedded=0,
            chunks_total=10, chunks_embedded=2,
            chunks_unembedded=8,
        )
                                              
        self.assertEqual(bc.coverage_percentage, 0.0)
                                  
        self.assertAlmostEqual(bc.chunk_coverage_percentage, 0.2)

    def test_to_dict_carries_new_fields(self):
        bc = self._bc(
            total_files=2, unsupported_files=0,
            files_with_all_chunks_embedded=1,
            files_with_partial_embeddings=1,
            chunks_total=4, chunks_embedded=3, chunks_unembedded=1,
        )
        d = bc.to_dict()
        for field in (
            "files_with_all_chunks_embedded",
            "files_with_partial_embeddings",
            "chunks_total", "chunks_embedded", "chunks_unembedded",
            "chunk_coverage_percentage",
        ):
            self.assertIn(field, d,
                          f"to_dict must surface {field!r}")

    def test_to_dict_no_plaintext_leakage(self):
        bc = self._bc(total_files=5)
        d = bc.to_dict()
                                                                    
        for k, v in d.items():
            self.assertNotIsInstance(
                v, bytes,
                f"to_dict[{k!r}] returned bytes — must be primitives",
            )
        self.assertTrue(
            str(d.get("vault_id", "")).endswith("…")
            or len(str(d.get("vault_id", ""))) <= 9,
            "vault_id in to_dict must be truncated.",
        )


class NoRawChatTextInLogsGuard(unittest.TestCase):


    def test_pending_file_override_print_does_not_format_raw_message(
        self,
    ):


        path = "main.py"
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except FileNotFoundError:
            import os
            path = os.path.join(
                os.path.dirname(__file__), "main.py",
            )
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()

                                                     
        match = re.search(
            r"\[CHAT-DEBUG\] pending_file_override.*?\)\s*$",
            src, re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "Could not locate the pending_file_override debug print "
            "in main.py — has it been renamed?",
        )
        block = match.group(0)
                                                                   
                                                         
        forbidden = re.search(
            r"raw_message_for_log\s*\[\s*:\s*\d+\s*\]",
            block,
        )
        self.assertIsNone(
            forbidden,
            "[CHAT-DEBUG] pending_file_override is printing a slice "
            "of raw_message_for_log — that's raw decrypted user "
            "text. Remove it.",
        )
                                                                       
        self.assertNotRegex(
            block,
            r"raw_message\s*=\s*\{raw_message_for_log",
            "[CHAT-DEBUG] pending_file_override still emits "
            "raw_message=... — remove that field.",
        )

    def test_pending_file_override_print_still_carries_length(self):


        path = "main.py"
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except FileNotFoundError:
            import os
            path = os.path.join(
                os.path.dirname(__file__), "main.py",
            )
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
                                                                 
                                                 
        self.assertIn(
            "raw_message_len=", src,
            "pending_file_override should still surface "
            "raw_message_len (the length, not the content).",
        )


if __name__ == "__main__":
    unittest.main()
