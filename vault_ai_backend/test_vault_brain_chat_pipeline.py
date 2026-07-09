

from __future__ import annotations

import asyncio
import logging
import unittest
from unittest import mock

from vault_brain_chat_pipeline import (
    run_brain_chat_pipeline,
    BrainPipelineDecision,
    REASON_NOT_VAULT_CONTENT,
    REASON_RETRIEVAL_EMPTY,
    REASON_BUNDLE_COMPOSED,
)
from vault_evidence_bundle import (
    EvidenceBundle, EvidenceChunk, empty_bundle,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _stub_embed(text):
                                                                  
                                                                   
    return [0.0] * 1536


def _names(name_map):
    def _lookup(file_ids):
        return {fid: name_map.get(fid, fid[:8]) for fid in file_ids}
    return _lookup


def _coverage(*, total=10, pending=0, failed=0, unsupported=0):
    return {
        "total": total, "analyzed": total - pending - failed - unsupported,
        "pending": pending, "failed": failed, "unsupported": unsupported,
        "scan_complete": pending == 0,
    }


class NotVaultContentFallsThroughTests(unittest.TestCase):


    def test_imperative_falls_through(self):
        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="save my Gmail password as foo",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_failing_retrieve,
        ))
        self.assertFalse(decision.handled)
        self.assertEqual(decision.reason, REASON_NOT_VAULT_CONTENT)

    def test_chitchat_falls_through(self):
        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="how are you?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_failing_retrieve,
        ))
        self.assertFalse(decision.handled)

    def test_show_saved_logins_falls_through(self):
        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="show me my saved logins",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_failing_retrieve,
        ))
        self.assertFalse(decision.handled)


async def _failing_retrieve(**_kwargs):
    raise AssertionError(
        "retrieve_fn must not be called for non-vault-content messages",
    )


class RetrievalSuccessfulTests(unittest.TestCase):


    def test_search_with_evidence(self):
        sentinel = "The blue contract expires on 2027-08-19."
        ch = EvidenceChunk(
            chunk_id="c-1", file_id="f-1", chunk_index=0,
            text=sentinel,
            extraction_source="pdf_text", score=0.85,
            char_start=0, char_end=len(sentinel),
        )

        async def _retrieve(**kwargs):
                                                       
            self.assertEqual(kwargs.get("vault_id"), "v-1")
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(ch,),
                matching_file_ids=("f-1",),
                coverage_at_time=kwargs.get("coverage") or {},
                retrieval_mode="semantic",
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about a blue contract?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({"f-1": "contract.pdf"}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.intent, "search_vault_content")
        self.assertFalse(decision.no_evidence)
        self.assertIn("contract.pdf", decision.reply_body)
        self.assertIn("blue contract", decision.reply_body)
        self.assertEqual(decision.retrieval_mode, "semantic")
        self.assertEqual(decision.reason, REASON_BUNDLE_COMPOSED)
        self.assertEqual(len(decision.evidence_rows), 1)
        self.assertEqual(decision.evidence_rows[0].file_name, "contract.pdf")

    def test_per_file_answer_with_evidence(self):
        ch = EvidenceChunk(
            chunk_id="c-1", file_id="f-1", chunk_index=0,
            text="Section 1: tenant duties.",
            extraction_source="pdf_text", score=0.7,
            char_start=0, char_end=24,
        )

        async def _retrieve(**kwargs):
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(ch,),
                matching_file_ids=("f-1",),
                coverage_at_time=kwargs.get("coverage") or {},
                retrieval_mode="semantic",
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="What does this PDF say?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({"f-1": "lease.pdf"}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.intent, "answer_from_file_content")
        self.assertIn("lease.pdf", decision.reply_body)


class RetrievalEmptyTests(unittest.TestCase):


    def test_no_evidence_returns_honest_fallback(self):
        async def _retrieve(**kwargs):
            return empty_bundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                coverage=kwargs.get("coverage") or {},
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about a purple unicorn?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertTrue(decision.no_evidence)
        self.assertEqual(decision.reason, REASON_RETRIEVAL_EMPTY)
        self.assertIn(
            "couldn't find matching vault content", decision.reply_body,
        )

    def test_pending_coverage_appended_to_fallback(self):
        async def _retrieve(**kwargs):
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(),
                matching_file_ids=(),
                coverage_at_time=kwargs.get("coverage") or {},
                retrieval_mode="no_matches",
                excluded_pending=3,
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Find anything about taxes.",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(total=10, pending=3),
            file_name_lookup=_names({}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertIn("still pending analysis", decision.reply_body)


class RetrievalRaisedTests(unittest.TestCase):


    def test_retrieve_raised_falls_to_honest_fallback(self):
        async def _retrieve(**kwargs):
            raise RuntimeError("DB went away")

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="Do I have anything about insurance?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertTrue(decision.no_evidence)
        self.assertIn("couldn't find matching vault content",
                      decision.reply_body)


class EmptyMessageTests(unittest.TestCase):
    def test_empty_message_returns_handled_false(self):
        decision = _run(run_brain_chat_pipeline(
            vault_id="v-1",
            message="",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({}),
            retrieve_fn=_failing_retrieve,
        ))
        self.assertFalse(decision.handled)


class NoLoggingOfQueryTests(unittest.TestCase):


    def test_query_text_not_logged(self):
        captured_records = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured_records.append(record)

        cap = _Cap()
        for name in ("vault_brain_chat_pipeline",
                     "vault_brain_retrieval",
                     "vault_brain_intent",
                     "vault_brain_answerer"):
            logging.getLogger(name).addHandler(cap)

        try:
            async def _retrieve(**kwargs):
                raise RuntimeError("simulated DB outage")

            secret_query = ("Do I have anything about "
                            "rumpelstiltskin-secret-marker?")
            _run(run_brain_chat_pipeline(
                vault_id="v-1",
                message=secret_query,
                key=b"\x00" * 32,
                embed_fn=_stub_embed,
                coverage=_coverage(),
                file_name_lookup=_names({}),
                retrieve_fn=_retrieve,
            ))
        finally:
            for name in ("vault_brain_chat_pipeline",
                         "vault_brain_retrieval",
                         "vault_brain_intent",
                         "vault_brain_answerer"):
                logging.getLogger(name).removeHandler(cap)

        for r in captured_records:
            self.assertNotIn(
                "rumpelstiltskin", r.getMessage(),
                f"query text leaked into log: {r.getMessage()!r}",
            )


class CredentialLookupRoutingTests(unittest.TestCase):


    def test_credential_lookup_runs_through_brain(self):
        ch = EvidenceChunk(
            chunk_id="c-1", file_id="f-1", chunk_index=0,
            text="Chase\nusername: alice@example.com\npassword: secret\n",
            extraction_source="pdf_text", score=0.85,
            char_start=0, char_end=10,
        )
        called_with_vault = []

        async def _retrieve(**kwargs):
            called_with_vault.append(kwargs.get("vault_id"))
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(ch,),
                matching_file_ids=("f-1",),
                coverage_at_time=kwargs.get("coverage") or {},
                retrieval_mode="semantic",
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-creds",
            message="What's my Chase password?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(),
            file_name_lookup=_names({"f-1": "logins.txt"}),
            retrieve_fn=_retrieve,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.intent, "credential_lookup")
                                                                       
        self.assertEqual(called_with_vault, ["v-creds"])
                                    
        self.assertIn("Chase", decision.reply_body)
                                         
        self.assertNotIn("secret", decision.reply_body)

    def test_credential_lookup_uses_memory_sweep_when_not_stubbed(self):
        import vault_brain_retrieval as retrieval
        seen = {"called": False}

        async def _memory_sweep(**kwargs):
            seen["called"] = True
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(
                    EvidenceChunk(
                        chunk_id="c-1", file_id="f-1", chunk_index=0,
                        text="Gmail\nusername: a@example.com\npassword: s1\n",
                        extraction_source="chunk", score=0.95,
                        char_start=0, char_end=10,
                    ),
                ),
                matching_file_ids=("f-1",),
                coverage_at_time=kwargs.get("coverage") or {},
                retrieval_mode="credential_memory_scan",
            )

        with mock.patch.object(
            retrieval, "retrieve_credential_evidence", _memory_sweep,
        ):
            decision = _run(run_brain_chat_pipeline(
                vault_id="v-creds",
                                                                  
                                                                     
                message="what's my gmail password?",
                key=b"\x00" * 32,
                embed_fn=_stub_embed,
                coverage=_coverage(),
                file_name_lookup=_names({"f-1": "gmail.html"}),
            ))

        self.assertTrue(seen["called"])
        self.assertTrue(decision.handled)
        self.assertEqual(decision.retrieval_mode, "credential_memory_scan")
        self.assertIn("gmail.html", decision.reply_body)

    def test_grounded_composer_receives_credential_bundle_facts(self):
        ch = EvidenceChunk(
            chunk_id="c-1", file_id="f-1", chunk_index=0,
            text="Gmail\nusername: a@example.com\npassword: s1\n",
            extraction_source="file_text", score=0.95,
            char_start=0, char_end=10,
        )
        captured = []

        async def _retrieve(**kwargs):
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=(ch,),
                matching_file_ids=("f-1",),
                coverage_at_time={
                    "total": 425, "analyzed": 245,
                    "pending": 51, "unsupported": 129, "failed": 0,
                },
                retrieval_mode="credential_memory_scan",
            )

        async def _compose(**kwargs):
            captured.append(kwargs)
            return (
                "No, I can't confirm those are the only credential files "
                "yet. I found 1 verified credential file from 245 readable "
                "files out of 425 total. Files: gmail.html"
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-creds",
            message="are these both the only files with credentials?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(total=425, pending=51, unsupported=129),
            file_name_lookup=_names({"f-1": "gmail.html"}),
            retrieve_fn=_retrieve,
            grounded_answer_compose_fn=_compose,
        ))

        self.assertTrue(decision.handled)
        self.assertIn("can't confirm", decision.reply_body)
        self.assertEqual(captured[0]["bundle"].vault_id, "v-creds")
        self.assertTrue(captured[0]["authorized_unlocked"])
        self.assertEqual(captured[0]["evidence_rows"][0].file_name, "gmail.html")
        self.assertNotIn("s1", decision.reply_body)

    def test_followup_only_files_uses_previous_credential_memory(self):
        from vault_brain_continuation import BrainContinuation

        ch1 = EvidenceChunk(
            chunk_id="c-1", file_id="f-1", chunk_index=0,
            text="Gmail\nusername: a@example.com\npassword: s1\n",
            extraction_source="file_text", score=0.95,
            char_start=0, char_end=10,
        )
        ch2 = EvidenceChunk(
            chunk_id="c-2", file_id="f-2", chunk_index=0,
            text="Yahoo\nusername: b@example.com\npassword: s2\n",
            extraction_source="file_text", score=0.95,
            char_start=0, char_end=10,
        )
        calls = []
        stored = []

        async def _retrieve(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                chunks = (ch1, ch2)
            else:
                chunks = (ch1, ch2)
            return EvidenceBundle(
                query=kwargs.get("query"),
                vault_id=kwargs.get("vault_id"),
                chunks=chunks,
                matching_file_ids=("f-1", "f-2"),
                coverage_at_time={
                    "total": 425, "analyzed": 245,
                    "pending": 51, "unsupported": 129, "failed": 0,
                },
                retrieval_mode="credential_memory_scan",
            )

        async def _compose(**kwargs):
            return (
                "No, I can't confirm they are the only files yet. "
                "I found 2 verified credential files from 245 readable "
                "files out of 425 total; 51 are pending and 129 are "
                "unsupported. Files: gmail.html, yahoo.html"
            )

        def _setter(**kwargs):
            stored.append(kwargs)

        d1 = _run(run_brain_chat_pipeline(
            vault_id="v-creds",
                                                                
                                                                   
            message="what's my gmail password?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(total=425, pending=51, unsupported=129),
            file_name_lookup=_names({
                "f-1": "gmail.html", "f-2": "yahoo.html",
            }),
            retrieve_fn=_retrieve,
            continuation_loader=lambda _vault_id: None,
            continuation_setter=_setter,
            grounded_answer_compose_fn=_compose,
        ))
        self.assertTrue(d1.handled)

        previous = BrainContinuation(
            vault_id="v-creds",
            query_prefix="find files with login credentials",
            intent="credential_lookup",
            breadth="broad",
            file_ids_returned=("f-1", "f-2"),
            chunk_ids_returned=("c-1", "c-2"),
            coverage_at_time={
                "total": 425, "analyzed": 245,
                "pending": 51, "unsupported": 129, "failed": 0,
            },
            retrieval_mode="credential_memory_scan",
            set_at_unix=1.0,
        )
        d2 = _run(run_brain_chat_pipeline(
            vault_id="v-creds",
            message="are these both the only files with list of credentials in it?",
            key=b"\x00" * 32,
            embed_fn=_stub_embed,
            coverage=_coverage(total=425, pending=51, unsupported=129),
            file_name_lookup=_names({
                "f-1": "gmail.html", "f-2": "yahoo.html",
            }),
            retrieve_fn=_retrieve,
            continuation_loader=lambda _vault_id: previous,
            continuation_setter=_setter,
            grounded_answer_compose_fn=_compose,
        ))

        self.assertTrue(d2.handled)
        self.assertIn("can't confirm", d2.reply_body)
        self.assertIn("gmail.html", d2.reply_body)
        self.assertIn("yahoo.html", d2.reply_body)
        self.assertEqual(calls[1]["vault_id"], "v-creds")
        self.assertEqual(calls[1]["query"], "find files with login credentials")


if __name__ == "__main__":
    unittest.main()
