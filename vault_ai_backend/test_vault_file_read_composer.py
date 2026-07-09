

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from vault_file_read_composer import (
    EXCERPT_BYTE_BUDGET,
    SYSTEM_PROMPT,
    _prepare_excerpt,
    build_file_read_facts,
    compose_file_read_answer,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class ExcerptRedactionTests(unittest.TestCase):
    def test_password_label_is_redacted(self):
        text = "Service: gmail\npassword: Hunter2-real-secret\nemail: a@b.com"
        out, _ = _prepare_excerpt(text)
        self.assertNotIn("Hunter2-real-secret", out)
        self.assertIn("password=***", out)

    def test_email_is_redacted(self):
        text = "Please contact me at user@example.com about my account."
        out, _ = _prepare_excerpt(text)
        self.assertNotIn("user@example.com", out)
                                                       
                                                                
        self.assertTrue(
            "***" in out,
            "expected the email to be masked with *** placeholder",
        )

    def test_empty_text_returns_empty(self):
        out, truncated = _prepare_excerpt("")
        self.assertEqual(out, "")
        self.assertFalse(truncated)
        out, truncated = _prepare_excerpt(None)
        self.assertEqual(out, "")
        self.assertFalse(truncated)


class ExcerptTruncationTests(unittest.TestCase):
    def test_short_text_not_truncated(self):
        out, truncated = _prepare_excerpt("Short document text.")
        self.assertFalse(truncated)
        self.assertEqual(out, "Short document text.")

    def test_long_text_is_truncated_and_flagged(self):
        long_text = "lorem ipsum " * 5_000                 
        out, truncated = _prepare_excerpt(long_text)
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), EXCERPT_BYTE_BUDGET)
        self.assertGreater(len(out), 0)

    def test_custom_budget_respected(self):
        text = "x" * 5000
        out, truncated = _prepare_excerpt(text, budget=500)
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), 500)


class FileReadFactsShapeTests(unittest.TestCase):
    def _facts(self, **overrides):
        defaults = dict(
            user_question="what's in contract.pdf?",
            vault_id="vault-abc",
            file_id="file-001",
            file_name="contract.pdf",
            saved_name="contract.pdf",
            relative_path="/Family/Legal/",
            mime_type="application/pdf",
            asset_type="document",
            extracted_text=(
                "Loan Modification Agreement\n"
                "Borrower: Jane Doe\n"
                "Lender: Wells Fargo Home Mortgage\n"
                "Effective Date: 2024-03-15\n"
                "Principal Balance: $245,300.00\n"
            ),
            purpose="financial_document",
            purpose_label="Financial document",
            metrics={
                "credential_block_count": 0,
                "service_count":          0,
                "credential_density":     0.0,
                "credential_like_lines":  0,
                "meaningful_lines":       5,
                "mostly_credentials":     False,
            },
            authorized_unlocked=True,
        )
        defaults.update(overrides)
        return build_file_read_facts(**defaults)

    def test_packet_has_intent_and_file_identity(self):
        p = self._facts()
        self.assertEqual(p["intent"], "analyze_file")
        self.assertEqual(p["file"]["file_name"], "contract.pdf")
        self.assertEqual(p["file"]["relative_path"], "/Family/Legal/")
        self.assertEqual(p["vault_id"], "vault-abc")

    def test_packet_carries_redacted_excerpt(self):
                                                                  
                                                             
        p = self._facts(extracted_text=(
            "Borrower: Jane\npassword: REAL-SECRET-DO-NOT-LEAK\n"
        ))
        self.assertIn("Borrower: Jane", p["excerpt"])
        self.assertNotIn("REAL-SECRET-DO-NOT-LEAK", p["excerpt"])

    def test_packet_metrics_are_safe_projection(self):
        p = self._facts(metrics={
            "credential_block_count": 3,
            "raw_text":               "DO-NOT-LEAK-IF-LEAKED",
            "private_field":          "secret",
        })
                                      
        self.assertEqual(p["metrics"]["credential_block_count"], 3)
                                  
        self.assertNotIn("raw_text", p["metrics"])
        self.assertNotIn("private_field", p["metrics"])
        self.assertNotIn("DO-NOT-LEAK-IF-LEAKED", json.dumps(p))

    def test_truncation_flag_is_present(self):
        p = self._facts(extracted_text="abc " * 10_000)
        self.assertTrue(p["excerpt_truncated"])

    def test_empty_extracted_text(self):
        p = self._facts(extracted_text="")
        self.assertEqual(p["excerpt"], "")
        self.assertFalse(p["excerpt_truncated"])

    def test_packet_does_not_leak_password_values_at_any_field(self):
                                                                  
                                                               
        p = self._facts(
            user_question="my password is hunter2 — what's in this?",
            extracted_text="my password is hunter2",
        )
        blob = json.dumps(p)
        self.assertNotIn("hunter2", blob)


class FileReadComposerPromptTests(unittest.TestCase):
    def test_prompt_demands_first_person_vault_identity(self):
        self.assertIn("You ARE the user's vault", SYSTEM_PROMPT)
        self.assertNotIn("you are an assistant", SYSTEM_PROMPT.lower())

    def test_prompt_demands_paragraphs(self):
        self.assertIn("2 to 4 short paragraphs", SYSTEM_PROMPT)

    def test_prompt_demands_grounded_walkthrough(self):
        self.assertIn("WALK THROUGH the meaningful contents", SYSTEM_PROMPT)
        self.assertIn("Stay grounded in the excerpt", SYSTEM_PROMPT)

    def test_prompt_demands_truncation_honesty(self):
        self.assertIn("excerpt_truncated", SYSTEM_PROMPT)
        self.assertIn(
            "never claim you", SYSTEM_PROMPT.lower(),
        )

    def test_prompt_demands_follow_up_offer(self):
        self.assertIn("CLOSE with one specific follow-up", SYSTEM_PROMPT)

    def test_prompt_forbids_markdown_and_brand_framing(self):
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("no markdown bold", lower)
                                                               
        self.assertIn("You ARE the vault", SYSTEM_PROMPT)

    def test_prompt_forbids_expanding_redaction_placeholders(self):
        self.assertIn("NEVER expand those", SYSTEM_PROMPT)
        self.assertIn("password=***", SYSTEM_PROMPT)


class ComposeFileReadAnswerTests(unittest.TestCase):
    def test_refuses_when_not_authorized_unlocked(self):
        async def _go():
            return await compose_file_read_answer(
                user_question="what's in it",
                vault_id="v1",
                file_id="f1",
                file_name="x.pdf",
                extracted_text="some text",
                authorized_unlocked=False,
            )
        with self.assertRaises(PermissionError):
            _run(_go())

    def test_returns_model_content_on_success(self):
        fake_result = mock.MagicMock()
        fake_result.content = (
            "contract.pdf is a Wells Fargo home loan modification "
            "agreement effective 2024-03-15.\n\nIt names Jane Doe "
            "as the borrower and lists a principal balance of "
            "$245,300.00.\n\nWant me to pull out the payment "
            "schedule?"
        )

        async def _fake_chat(*args, **kwargs):
            return fake_result

        async def _go():
                                                                
                                                               
            with mock.patch(
                "vault_ai_provider.chat_complete_with_fallback",
                side_effect=_fake_chat,
            ):
                return await compose_file_read_answer(
                    user_question="what's in contract.pdf?",
                    vault_id="v1",
                    file_id="f1",
                    file_name="contract.pdf",
                    extracted_text="Loan Modification Agreement\nBorrower: Jane Doe",
                    purpose="financial_document",
                    metrics={"meaningful_lines": 2},
                    authorized_unlocked=True,
                )

        out = _run(_go())
        self.assertIn("Wells Fargo", out)
        self.assertIn("payment schedule", out)


class ChatEndpointWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_analyze_file_imports_composer(self):
        self.assertIn(
            "from vault_file_read_composer import (",
            self._src,
        )
        self.assertIn(
            "compose_file_read_answer",
            self._src,
        )

    def test_analyze_file_calls_composer_first(self):
                                                               
                                                                    
        branch_start = self._src.find('if intent == "analyze_file":')
        self.assertGreater(branch_start, -1)
        composer_idx = self._src.find(
            "compose_file_read_answer(",
            branch_start,
        )
        deterministic_idx = self._src.find(
            "build_safe_file_analysis(",
            branch_start,
        )
        self.assertGreater(composer_idx, -1)
        self.assertGreater(deterministic_idx, -1)
                                                         
        self.assertLess(composer_idx, deterministic_idx)

    def test_composer_failure_falls_back_to_deterministic(self):
                                                                  
                                                                  
        branch_start = self._src.find('if intent == "analyze_file":')
        slice_ = self._src[branch_start:branch_start + 12000]
        self.assertIn("deterministic analyzer", slice_)
        self.assertIn("composer_reply = \"\"", slice_)
        self.assertIn("build_safe_file_analysis(", slice_)


if __name__ == "__main__":
    unittest.main()
