

from __future__ import annotations

import asyncio
import unittest
from unittest import mock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _stub_embed(text):
    return [0.0] * 1536


def _names(m):
    def _lookup(ids):
        return {fid: m.get(fid, fid) for fid in ids}
    return _lookup


def _stub_coverage_loader(loader_returns):
    def _loader(vault_id):
        return loader_returns
    return _loader


class _MemContinuationStore:


    def __init__(self):
        self.store: dict[str, dict] = {}

    def setter(self, *, vault_id, query, intent, breadth,
               file_ids_returned, coverage_at_time,
               retrieval_mode, set_at_unix):
        from vault_brain_continuation import BrainContinuation
        self.store[vault_id] = {
            "vault_id":          vault_id,
            "query_prefix":      str(query or "")[:80],
            "intent":            intent,
            "breadth":           breadth,
            "file_ids_returned": tuple(file_ids_returned),
            "coverage_at_time":  dict(coverage_at_time),
            "retrieval_mode":    retrieval_mode,
            "set_at_unix":       set_at_unix,
        }

    def loader(self, vault_id):
        from vault_brain_continuation import BrainContinuation
        raw = self.store.get(vault_id)
        if not raw:
            return None
        return BrainContinuation(**raw)


def _make_bundle(*, query, vault_id, chunks=(), file_ids=(),
                 mode="semantic", coverage=None):
    from vault_evidence_bundle import EvidenceBundle
    return EvidenceBundle(
        query=query, vault_id=vault_id,
        chunks=tuple(chunks),
        matching_file_ids=tuple(file_ids),
        coverage_at_time=dict(coverage or {}),
        retrieval_mode=mode,
    )


def _make_chunk(file_id, text="snippet", score=0.8, idx=0):
    from vault_evidence_bundle import EvidenceChunk
    return EvidenceChunk(
        chunk_id=f"c-{file_id}-{idx}",
        file_id=file_id, chunk_index=idx,
        text=text, extraction_source="pdf_text",
        score=score, char_start=0, char_end=len(text),
    )


class BroadQueryTests(unittest.TestCase):


    def test_broad_query_passes_broad_breadth_to_retrieval(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

        captured_kwargs = {}

        async def _retrieve(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "x"),
                        _make_chunk("f-2", "y")],
                file_ids=["f-1", "f-2"],
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about insurance?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={"total": 10},
            file_name_lookup=_names({"f-1": "a.pdf", "f-2": "b.pdf"}),
            retrieve_fn=_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1", total_files=10,
                files_with_all_chunks_embedded=10,
            )),
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.breadth, "broad")
        self.assertEqual(captured_kwargs.get("breadth"), "broad")

    def test_broad_query_with_incomplete_coverage_adds_hint(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        from vault_brain_answerer import COPY_BRAIN_STILL_INDEXING

        async def _retrieve(**kwargs):
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "x")],
                file_ids=["f-1"],
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Find anything about taxes",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={"total": 10},
            file_name_lookup=_names({"f-1": "a.pdf"}),
            retrieve_fn=_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1", total_files=10,
                files_with_all_chunks_embedded=3,
                pending_chunking_jobs=2,
            )),
        ))
        self.assertIn(COPY_BRAIN_STILL_INDEXING, decision.reply_body)

    def test_brain_coverage_dict_in_decision(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

        async def _retrieve(**kwargs):
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "x")],
                file_ids=["f-1"],
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about apples?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-1": "a.pdf"}),
            retrieve_fn=_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1", total_files=5,
                files_with_all_chunks_embedded=5,
            )),
        ))
        self.assertEqual(
            decision.brain_coverage_dict.get("total_files"), 5,
        )
        self.assertTrue(
            decision.brain_coverage_dict.get("is_complete"),
        )


class ContinuationTests(unittest.TestCase):


    def setUp(self):
        import vault_brain_continuation
        vault_brain_continuation.reset_for_tests()

    def test_continuation_persists_after_first_broad_turn(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

        store = _MemContinuationStore()

        async def _retrieve(**kwargs):
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "x"),
                        _make_chunk("f-2", "y")],
                file_ids=["f-1", "f-2"],
            )

        _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about insurance?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-1": "a.pdf", "f-2": "b.pdf"}),
            retrieve_fn=_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1",
            )),
            continuation_loader=store.loader,
            continuation_setter=store.setter,
            now_unix=1700.0,
        ))
        self.assertIn("v-1", store.store)
        self.assertEqual(
            list(store.store["v-1"]["file_ids_returned"]),
            ["f-1", "f-2"],
        )

    def test_continuation_excludes_prior_file_ids(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

        store = _MemContinuationStore()

                                                         
        async def _retrieve1(**kwargs):
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "x"),
                        _make_chunk("f-2", "y")],
                file_ids=["f-1", "f-2"],
            )

        _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about insurance?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-1": "a", "f-2": "b"}),
            retrieve_fn=_retrieve1,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1",
            )),
            continuation_loader=store.loader,
            continuation_setter=store.setter,
            now_unix=1700.0,
        ))

                                                           
        captured_kwargs = {}

        async def _retrieve2(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-3", "z")],
                file_ids=["f-3"],
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="show more",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-3": "c"}),
            retrieve_fn=_retrieve2,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1",
            )),
            continuation_loader=store.loader,
            continuation_setter=store.setter,
            now_unix=1800.0,
        ))
                                                        
        excluded = captured_kwargs.get("excluded_file_ids") or ()
        self.assertIn("f-1", excluded)
        self.assertIn("f-2", excluded)
        self.assertNotIn("f-3", excluded)
        self.assertEqual(decision.breadth, "continuation")
        self.assertEqual(decision.intent, "continue_last_search")
                                                                    
        stored_after = store.store["v-1"]["file_ids_returned"]
        self.assertEqual(list(stored_after), ["f-1", "f-2", "f-3"])


class EmbeddingFallbackTests(unittest.TestCase):


    def test_lexical_fallback_surfaces_warning(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        from vault_brain_answerer import COPY_BRAIN_LEXICAL_FALLBACK

        async def _retrieve(**kwargs):
            return _make_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=[_make_chunk("f-1", "snippet")],
                file_ids=["f-1"],
                mode="chunk_text_lexical",
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="What's my Chase password?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-1": "logins.txt"}),
            retrieve_fn=_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1", total_files=1,
                files_with_all_chunks_embedded=1,
            )),
        ))
        self.assertIn(COPY_BRAIN_LEXICAL_FALLBACK, decision.reply_body)


class CrossVaultTests(unittest.TestCase):


    def setUp(self):
        import vault_brain_continuation
        vault_brain_continuation.reset_for_tests()

    def test_continuation_is_vault_scoped(self):
        from vault_brain_continuation import (
            set_last_brain_evidence, get_last_brain_evidence,
        )
        set_last_brain_evidence(
            vault_id="alice",
            query="my secret query",
            intent="search_vault_content",
            breadth="broad",
            file_ids_returned=["a1", "a2"],
            coverage_at_time={},
            retrieval_mode="semantic",
            set_at_unix=1.0,
        )
        self.assertIsNotNone(get_last_brain_evidence("alice"))
        self.assertIsNone(get_last_brain_evidence("bob"))


class LegacyChatPipelineSignatureTests(unittest.TestCase):


    def test_legacy_retrieve_fn_signature_still_works(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

                                                                
        async def _legacy_retrieve(*, vault_id, query, key, embed_fn,
                                    coverage, top_k=8,
                                    min_similarity=0.20):
            return _make_bundle(
                query=query, vault_id=vault_id,
                chunks=[_make_chunk("f-1", "snippet")],
                file_ids=["f-1"],
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about clouds?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage={},
            file_name_lookup=_names({"f-1": "a.pdf"}),
            retrieve_fn=_legacy_retrieve,
            brain_coverage_loader=_stub_coverage_loader(BrainCoverage(
                vault_id="v-1",
            )),
        ))
                                                                      
        self.assertTrue(decision.handled)


if __name__ == "__main__":
    unittest.main()
