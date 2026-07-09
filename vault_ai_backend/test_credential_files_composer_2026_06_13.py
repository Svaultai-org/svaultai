

from __future__ import annotations

import asyncio
import re
import unittest
from unittest import mock


def _make_verified_row(
    *,
    file_id: str,
    file_name: str,
    record_count: int = 1,
    evidence_source: str = "file_text",
    safe_service_names=None,
    password_present: bool = True,
    duplicate_paths=None,
) -> dict:
    return {
        "file_id":               file_id,
        "file_name":             file_name,
        "saved_name":            file_name,
        "relative_path":         "/",
        "mime_type":             "application/pdf",
        "asset_type":            "file",
        "evidence_source":       evidence_source,
        "evidence_source_label": "file text",
        "record_count":          record_count,
        "safe_service_names":    list(safe_service_names or []),
        "password_present":      password_present,
        "duplicate_paths":       list(duplicate_paths or []),
    }


class TestDedupVerifiedMatchesByFileId(unittest.TestCase):
    def setUp(self):
        from vault_inventory import _dedupe_verified_matches_by_file_id
        self._dedupe = _dedupe_verified_matches_by_file_id

    def test_same_file_id_collapsed_once(self):
        rows = [
            _make_verified_row(
                file_id="abc",
                file_name="passedwpordtex.pdf",
                record_count=3,
                safe_service_names=["AOL"],
            ),
            _make_verified_row(
                file_id="abc",
                file_name="passedwpordtex.pdf",
                record_count=4,
                safe_service_names=["AOL", "Gmail"],
            ),
        ]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 1)
                                 
        self.assertEqual(out[0]["record_count"], 7)
                                                             
        self.assertEqual(out[0]["safe_service_names"], ["AOL", "Gmail"])

    def test_distinct_file_ids_preserved(self):
        rows = [
            _make_verified_row(file_id="a", file_name="a.pdf"),
            _make_verified_row(file_id="b", file_name="b.pdf"),
        ]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual({r["file_id"] for r in out}, {"a", "b"})

    def test_password_present_or_ed(self):
        rows = [
            _make_verified_row(
                file_id="x", file_name="x.pdf", password_present=False,
            ),
            _make_verified_row(
                file_id="x", file_name="x.pdf", password_present=True,
            ),
        ]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["password_present"])

    def test_evidence_sources_union(self):
        rows = [
            _make_verified_row(
                file_id="y", file_name="y.pdf", evidence_source="file_text",
            ),
            _make_verified_row(
                file_id="y", file_name="y.pdf", evidence_source="ocr",
            ),
        ]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["evidence_sources"], ["file_text", "ocr"])

    def test_safe_service_names_capped_at_five(self):
        rows = [
            _make_verified_row(
                file_id="z", file_name="z.pdf",
                safe_service_names=["a", "b", "c", "d"],
            ),
            _make_verified_row(
                file_id="z", file_name="z.pdf",
                safe_service_names=["e", "f", "g"],
            ),
        ]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["safe_service_names"]), 5)

    def test_empty_input_passes_through(self):
        self.assertEqual(self._dedupe([]), [])

    def test_row_without_file_id_passes_through(self):
        rows = [{"file_name": "ghost.pdf", "record_count": 1}]
        out = self._dedupe(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file_name"], "ghost.pdf")


class TestCredentialFilesFactsShape(unittest.TestCase):
    def setUp(self):
        from vault_credential_files_composer import (
            build_credential_files_facts,
        )
        self._build = build_credential_files_facts

    def test_authorized_unlocked_required_for_credible_packet(self):
                                                              
                                                              
        facts = self._build(
            user_question="any files with credentials?",
            vault_id="vault-1",
            verified_matches=[],
            scanned_count=0,
            not_scanned_count=0,
            is_partial=False,
            authorized_unlocked=False,
        )
        self.assertFalse(facts["authorized_unlocked"])

    def test_basic_shape_with_one_match(self):
        row = _make_verified_row(
            file_id="abc",
            file_name="passedwpordtex.pdf",
            record_count=7,
            safe_service_names=["AOL"],
        )
        row["evidence_sources"] = ["file_text"]
        facts = self._build(
            user_question="any files with credentials?",
            vault_id="vault-1",
            verified_matches=[row],
            scanned_count=194,
            not_scanned_count=215,
            is_partial=True,
            coverage_extra={
                "total": 425,
                "scanned": 194,
                "pending": 215,
                "unsupported": 40,
                "failed": 37,
            },
            authorized_unlocked=True,
        )
        self.assertEqual(
            facts["intent"], "search_files_for_credentials",
        )
        self.assertEqual(facts["verified_file_count"], 1)
        self.assertEqual(facts["total_records_across_files"], 7)
        self.assertEqual(len(facts["verified_credential_files"]), 1)
        cov = facts["coverage"]
        self.assertEqual(cov["total_files"], 425)
        self.assertEqual(cov["analyzed_files"], 194)
        self.assertEqual(cov["pending_files"], 215)
        self.assertEqual(cov["unsupported_files"], 40)
        self.assertEqual(cov["failed_files"], 37)
        self.assertTrue(cov["is_partial"])
        self.assertFalse(cov["is_complete"])

    def test_empty_matches_with_complete_coverage_allows_negative_claim(self):
        facts = self._build(
            user_question="any files with credentials?",
            vault_id="vault-1",
            verified_matches=[],
            scanned_count=10,
            not_scanned_count=0,
            is_partial=False,
            coverage_extra={
                "total": 10, "scanned": 10, "pending": 0,
            },
            authorized_unlocked=True,
        )
        self.assertEqual(facts["verified_file_count"], 0)
        self.assertTrue(facts["coverage"]["is_complete"])
        self.assertTrue(facts["negative_claim_allowed"])

    def test_empty_matches_with_partial_coverage_blocks_negative_claim(self):
        facts = self._build(
            user_question="any files with credentials?",
            vault_id="vault-1",
            verified_matches=[],
            scanned_count=5,
            not_scanned_count=5,
            is_partial=True,
            authorized_unlocked=True,
        )
        self.assertFalse(facts["coverage"]["is_complete"])
        self.assertFalse(facts["negative_claim_allowed"])

    def test_safety_floor_no_password_values_in_packet(self):
                                                                  
                                                                  
        row = _make_verified_row(
            file_id="abc", file_name="a.pdf",
        )
        row["password"] = "hunter2"
        row["secret_value"] = "totally-not-leaked"
        row["chunk_text"] = "raw extracted text that must not surface"
        facts = self._build(
            user_question="",
            vault_id="v",
            verified_matches=[row],
            scanned_count=1, not_scanned_count=0, is_partial=False,
            authorized_unlocked=True,
        )
        blob = str(facts)
        self.assertNotIn("hunter2", blob)
        self.assertNotIn("totally-not-leaked", blob)
        self.assertNotIn("raw extracted text", blob)


class TestComposerRoundTrip(unittest.TestCase):
    def test_authorized_unlocked_required(self):
        from vault_credential_files_composer import (
            compose_credential_files_answer,
        )
        async def go():
            await compose_credential_files_answer(
                user_question="any files with credentials?",
                vault_id="v",
                verified_matches=[],
                scanned_count=0,
                not_scanned_count=0,
                is_partial=False,
                authorized_unlocked=False,
            )
        with self.assertRaises(PermissionError):
            asyncio.run(go())

    def test_composer_calls_provider_with_facts_packet(self):
                                                                
                                                        
        from vault_credential_files_composer import (
            compose_credential_files_answer,
        )
        from vault_ai_provider import ChatCompletionResult

        captured: dict = {}

        async def fake_call(*, messages, model, model_kind,
                            temperature, max_tokens=None,
                            response_format=None, timeout=60):
            captured["messages"] = messages
            captured["model_kind"] = model_kind
            return ChatCompletionResult(
                provider_used="hermes",
                model=model or "test-model",
                content=(
                    "I found 1 unique file with verified credential "
                    "records: passedwpordtex.pdf. It contains 7 "
                    "credential-shaped records. I've only fully "
                    "analyzed 194 of 425 files so far — these "
                    "results are incomplete."
                ),
                finish_reason="stop",
                used_fallback=False,
            )

        with mock.patch(
            "vault_ai_provider.chat_complete_with_fallback",
            new=fake_call,
        ):
            row = _make_verified_row(
                file_id="abc",
                file_name="passedwpordtex.pdf",
                record_count=7,
                safe_service_names=["AOL"],
            )
            text = asyncio.run(compose_credential_files_answer(
                user_question="any files with credentials?",
                vault_id="v",
                verified_matches=[row],
                scanned_count=194,
                not_scanned_count=215,
                is_partial=True,
                coverage_extra={
                    "total": 425, "scanned": 194, "pending": 215,
                    "unsupported": 40, "failed": 37,
                },
                authorized_unlocked=True,
            ))

                                                            
        self.assertIn("messages", captured)
        msgs = captured["messages"]
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
                                                         
        body = msgs[1]["content"]
        self.assertIn("verified_credential_files", body)
        self.assertIn("coverage", body)
        self.assertIn("passedwpordtex.pdf", body)
                                                               
                    
        self.assertIn("passedwpordtex.pdf", text)
        self.assertIn("194", text)


class TestChatEndpointWiresComposer(unittest.TestCase):
    def setUp(self):
        with open("main.py", "r", encoding="utf-8") as f:
            self._src = f.read()

    def test_credential_path_imports_composer(self):
        self.assertIn(
            "from vault_credential_files_composer import",
            self._src,
        )
        self.assertIn(
            "compose_credential_files_answer",
            self._src,
        )

    def test_composer_trace_log_present(self):
        self.assertIn(
            "[CHAT-TRACE] credential_files_composer",
            self._src,
        )
        self.assertIn(
            "composer_used=",
            self._src,
        )

    def test_envelope_message_is_composer_output_when_available(self):
                                                             
                                                             
        self.assertRegex(
            self._src,
            r"reply_message\s*=\s*composer_message",
        )
        self.assertRegex(
            self._src,
            r"_build_credential_files_envelope\(\s*[\s\S]{0,200}?"
            r"message\s*=\s*reply_message",
        )


class TestIdentityCopy(unittest.TestCase):
    def test_no_intelligence_inside_phrase(self):
        from tools import SYSTEM_PROMPT
        self.assertNotIn(
            "the intelligence inside this user's personal life vault",
            SYSTEM_PROMPT,
        )
        self.assertNotIn(
            "intelligence inside the vault",
            SYSTEM_PROMPT,
        )
        self.assertNotIn(
            "intelligence layer of a personal life vault",
            SYSTEM_PROMPT,
        )

    def test_vault_identity_phrasing_present(self):
                                                                     
                                                       
        from tools import SYSTEM_PROMPT
        lower = SYSTEM_PROMPT.lower()
                                               
        self.assertIn("i'm your vault", lower)
                                                        
        self.assertIn("vault", lower)
                                            
        self.assertIn("never say", lower)

    def test_vaultai_brand_framing_rejected(self):
        from tools import SYSTEM_PROMPT
                                                            
                                                                
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("never say", lower)
                                                                
                                                                 
        idx = SYSTEM_PROMPT.find("VaultAI")
        if idx != -1:
            window_start = max(0, idx - 400)
            window = SYSTEM_PROMPT[window_start:idx + 200].lower()
            self.assertTrue(
                "never say" in window or "never" in window,
                "'VaultAI' must only appear in a forbidden-framing "
                "context, not as a positive identity",
            )


class TestComposerPromptForbidsMarkdown(unittest.TestCase):
    def test_prompt_forbids_markdown_bold(self):
        from vault_credential_files_composer import SYSTEM_PROMPT
                                                            
                                                               
        lower = SYSTEM_PROMPT.lower()
        self.assertTrue(
            "no markdown" in lower or "plain prose" in lower,
            "composer prompt must steer Hermes away from "
            "markdown formatting that the chat bubble doesn't "
            "render",
        )
        self.assertIn("**", SYSTEM_PROMPT)                       

    def test_prompt_forbids_intelligence_inside_phrase(self):
        from vault_credential_files_composer import SYSTEM_PROMPT
        self.assertIn(
            "intelligence inside",
            SYSTEM_PROMPT.lower(),
            "composer prompt should explicitly forbid the old "
            "identity wording so the LLM doesn't drift back to it",
        )


if __name__ == "__main__":
    unittest.main()
