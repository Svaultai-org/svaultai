

from __future__ import annotations

import ast
import asyncio
import inspect
import time
import unittest
from typing import Optional
from unittest import mock

from vault_chat_planner_pipeline import (
    run_pipeline,
    PipelineDecision,
)
from vault_followup_classifier import (
    INTENT_COVERAGE_COMPLETE_CHECK,
    INTENT_WANT_MORE_RESULTS,
    INTENT_PURE_REFERENT,
    INTENT_NOT_A_FOLLOWUP,
    reset_anchor_cache_for_tests,
)
from vault_result_context import (
    LastAssistantResult,
    RESULT_TYPE_CREDENTIAL_FILES,
    EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
    set_last_assistant_result,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


from test_vault_followup_classifier import fake_embed, fake_embed_disabled


def _reset_chat_memory():
    from vault_chat_memory import CHAT_MEMORY
    CHAT_MEMORY._data.clear()


def _credential_result(
    *, total_matches: int, file_ids: tuple[str, ...],
    is_partial: bool,
) -> LastAssistantResult:
    return LastAssistantResult(
        result_type=RESULT_TYPE_CREDENTIAL_FILES,
        query="find credentials",
        intent="search_files_for_credentials",
        file_ids_returned=file_ids,
        file_ids_excluded=(),
        total_matches_known=total_matches,
        coverage_at_time={"total": 425, "analyzed": 194, "pending": 122},
        is_partial=is_partial,
        evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
        timestamp_unix=time.time(),
    )


class FallThroughCases(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_no_last_result_returns_handled_false(self):
        decision = _run(run_pipeline(
            vault_id="v1",
            message="is that all?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "scan_complete": True},
            daemon_active_probe=lambda: False,
        ))
        self.assertFalse(decision.handled)
        self.assertEqual(decision.reason, "no_last_result")

    def test_unrelated_message_returns_handled_false(self):
        last = _credential_result(
            total_matches=2, file_ids=("a", "b"), is_partial=False,
        )
        set_last_assistant_result("v1", last)
        decision = _run(run_pipeline(
            vault_id="v1",
            message="what's the weather today?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "scan_complete": True},
            daemon_active_probe=lambda: False,
        ))
        self.assertFalse(decision.handled)
        self.assertEqual(decision.reason, "intent_not_followup")
                                                                
        self.assertEqual(decision.classification.intent, INTENT_NOT_A_FOLLOWUP)


class PureReferentDelegationTests(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_pure_referent_delegates_to_regex_resolver(self):
        last = _credential_result(
            total_matches=2, file_ids=("a", "b"), is_partial=False,
        )
        decision = _run(run_pipeline(
            vault_id="v1",
            message="open the first one",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "scan_complete": True},
            daemon_active_probe=lambda: False,
            last_result_override=last,
        ))
        self.assertFalse(decision.handled)
        self.assertTrue(decision.delegate_to_regex_resolver)
        self.assertEqual(
            decision.classification.intent, INTENT_PURE_REFERENT,
        )


class CoverageStyleFollowupTests(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_complete_scan_produces_full_answer_body(self):
        last = _credential_result(
            total_matches=3, file_ids=("a", "b", "c"), is_partial=False,
        )
        decision = _run(run_pipeline(
            vault_id="v1",
            message="is that all of them?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "analyzed": 100,
                                       "scan_complete": True},
            daemon_active_probe=lambda: False,
            last_result_override=last,
        ))
        self.assertTrue(decision.handled)
                                                                
                                                                     
        self.assertIn("100", decision.reply_body)         
        self.assertIn("3", decision.reply_body)                  

    def test_user_credential_only_files_wording_stays_in_planner(self):
        last = _credential_result(
            total_matches=2, file_ids=("a", "b"), is_partial=False,
        )
        decision = _run(run_pipeline(
            vault_id="v1",
            message=(
                "are these both the only files with list of "
                "credentials in it?"
            ),
            embed_fn=fake_embed_disabled,
            coverage_loader=lambda v: {
                "total": 2, "analyzed": 2, "scan_complete": True,
            },
            daemon_active_probe=lambda: False,
            last_result_override=last,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(
            decision.classification.intent,
            INTENT_COVERAGE_COMPLETE_CHECK,
        )
        self.assertIn("2", decision.reply_body)

    def test_partial_with_daemon_produces_wait_body(self):
        last = _credential_result(
            total_matches=1, file_ids=("a",), is_partial=True,
        )
        decision = _run(run_pipeline(
            vault_id="v1",
            message="is that all of them?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 425, "analyzed": 194,
                                       "pending": 122,
                                       "scan_complete": False},
            daemon_active_probe=lambda: True,
            last_result_override=last,
        ))
        self.assertTrue(decision.handled)
        self.assertIn("still", decision.reply_body.lower())
        self.assertIn("194", decision.reply_body)


class PipelineOrderGuaranteeTests(unittest.TestCase):


    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_pipeline_module_does_not_import_topic_classifier(self):
                                                                   
                                                                     
        import vault_chat_planner_pipeline as p
        src = inspect.getsource(p)
        for forbidden in (
            "list_by_tag", "list_logins", "detect_vault_intent",
            "_handle_list_by_tag", "search_files_for_credentials(",
            "from main import",
        ):
            self.assertNotIn(
                forbidden, src,
                f"pipeline must NOT touch topic-classifier surface: {forbidden!r}",
            )

    def test_handled_true_means_caller_short_circuits(self):
                                                                  
                                                                  
        decision = PipelineDecision(handled=True, reply_body="answer")
        self.assertTrue(decision.handled)

    def test_pipeline_function_runs_classifier_before_planner_in_source(self):
                                                     
                                                          
        import vault_chat_planner_pipeline as p
        src = inspect.getsource(p.run_pipeline)
        idx_classify = src.find("classify_followup(")
        idx_plan = src.find("plan_answer(")
        self.assertGreater(idx_classify, -1, "classify_followup not called")
        self.assertGreater(idx_plan, -1, "plan_answer not called")
        self.assertLess(
            idx_classify, idx_plan,
            "classify_followup must be called BEFORE plan_answer",
        )


class CannedCategoryLeakGuardTests(unittest.TestCase):
    FORBIDDEN_PHRASES = (
        "Bank Account", "ID Document", "Payment Card",
        "Saved Logins", "Saved Login",
        "Loyalty Card", "Insurance Card",
    )

    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_pipeline_body_never_contains_canned_categories(self):


        last = _credential_result(
            total_matches=2, file_ids=("a", "b"), is_partial=True,
        )
        phrasings = [
            "is that all?",
            "could there be more?",
            "what about other folders?",
            "include weak ones too",
        ]
        coverages = [
            {"total": 425, "analyzed": 194, "pending": 122,
             "scan_complete": False},
            {"total": 425, "analyzed": 425, "scan_complete": True},
        ]
        misses: list[tuple[str, str]] = []
        for phrasing in phrasings:
            for cov in coverages:
                for daemon in (True, False):
                    decision = _run(run_pipeline(
                        vault_id="v1",
                        message=phrasing,
                        embed_fn=fake_embed,
                        coverage_loader=lambda v: cov,
                        daemon_active_probe=lambda: daemon,
                        last_result_override=last,
                    ))
                    body = decision.reply_body
                    for phrase in self.FORBIDDEN_PHRASES:
                        if phrase in body:
                            misses.append((phrasing, phrase))
        self.assertEqual(misses, [])

    def test_pipeline_source_does_not_call_list_by_tag(self):
        import vault_chat_planner_pipeline as p
        src = inspect.getsource(p)
        self.assertNotIn("list_by_tag", src)
        self.assertNotIn("list_logins", src)


class InjectionGuaranteeTests(unittest.TestCase):
    def test_pipeline_module_does_not_instantiate_openai(self):
                                                                  
                                                                    
        import vault_chat_planner_pipeline as p
        src = inspect.getsource(p)
        for forbidden in (
            "import openai", "openai.OpenAI(",
            "openai.AsyncOpenAI(",
        ):
            self.assertNotIn(forbidden, src)


class ContextRetentionAcrossUnrelatedTurnsTests(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()
        reset_anchor_cache_for_tests()

    def test_context_survives_an_unrelated_turn(self):
                                                              
        last = _credential_result(
            total_matches=2, file_ids=("a", "b"), is_partial=False,
        )
        set_last_assistant_result("v1", last)
                                                                     
                                                
        d2 = _run(run_pipeline(
            vault_id="v1",
            message="what's the weather today?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "scan_complete": True},
            daemon_active_probe=lambda: False,
        ))
        self.assertFalse(d2.handled)
                                                                     
                                                           
        d3 = _run(run_pipeline(
            vault_id="v1",
            message="is that all?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: {"total": 100, "analyzed": 100,
                                       "scan_complete": True},
            daemon_active_probe=lambda: False,
        ))
        self.assertTrue(d3.handled)
                                                                 
                        
        self.assertIn("100", d3.reply_body)
        self.assertIn("2", d3.reply_body)


if __name__ == "__main__":
    unittest.main()
