

from __future__ import annotations

import ast
import inspect
import time
import unittest

from vault_followup_classifier import (
    INTENT_COVERAGE_COMPLETE_CHECK,
    INTENT_WANT_MORE_RESULTS,
    INTENT_CHECK_OTHER_LOCATIONS,
    INTENT_RERUN_WITH_DIFFERENT_FILTER,
    INTENT_PURE_REFERENT,
    INTENT_NOT_A_FOLLOWUP,
)
from vault_answer_planner import (
    plan_answer,
    AnswerPlan,
    FactPack,
    facts_from_inputs,
    compose_body,
    ACTIONS,
    ACTION_FULL_ANSWER,
    ACTION_PARTIAL_WITH_LIMITS,
    ACTION_WAIT_FOR_ANALYSIS,
    ACTION_CLARIFY,
    ACTION_CANT_CONFIRM,
)
from vault_result_context import (
    LastAssistantResult,
    RESULT_TYPE_CREDENTIAL_FILES,
    EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
)


def _result(
    *, match_count: int, file_ids: tuple[str, ...] = (),
    is_partial: bool = False,
) -> LastAssistantResult:
    return LastAssistantResult(
        result_type=RESULT_TYPE_CREDENTIAL_FILES,
        query="find credentials",
        intent="search_files_for_credentials",
        file_ids_returned=file_ids or tuple(f"f{i}" for i in range(match_count)),
        file_ids_excluded=(),
        total_matches_known=match_count,
        coverage_at_time={},
        is_partial=is_partial,
        evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
        timestamp_unix=time.time(),
    )


class FactExtractionTests(unittest.TestCase):
    def test_extracts_every_coverage_field(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=2),
            coverage={
                "total": 425, "analyzed": 194, "pending": 122,
                "not_started": 0, "processing": 0,
                "failed": 5, "unsupported": 104, "skipped": 0,
                "scan_complete": False,
            },
            daemon_active=True,
        )
        self.assertEqual(facts.match_count, 2)
        self.assertEqual(facts.total, 425)
        self.assertEqual(facts.analyzed, 194)
        self.assertEqual(facts.pending, 122)
        self.assertEqual(facts.failed, 5)
        self.assertEqual(facts.unsupported, 104)
        self.assertTrue(facts.daemon_active)
        self.assertTrue(facts.has_pending)
        self.assertTrue(facts.has_unsupported)
        self.assertTrue(facts.has_failed)
        self.assertFalse(facts.is_honestly_complete)

    def test_is_honestly_complete_derives_when_nothing_left(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=2),
            coverage={
                "total": 100, "analyzed": 90,
                "unsupported": 10,
                "pending": 0, "not_started": 0, "processing": 0,
            },
            daemon_active=False,
        )
                                                                     
                                                                     
        self.assertTrue(facts.is_honestly_complete)

    def test_empty_vault_is_honestly_complete(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=0),
            coverage={"total": 0},
            daemon_active=False,
        )
        self.assertTrue(facts.is_honestly_complete)


class BodyContainsLiveFactsTests(unittest.TestCase):


    def test_analyzed_count_appears_when_coverage_partial(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=2, is_partial=True),
            coverage={"total": 425, "analyzed": 194, "pending": 231,
                      "scan_complete": False},
            daemon_active=False,
        )
        body = compose_body(facts)
        self.assertIn("194", body, "analyzed count must surface")
        self.assertIn("425", body, "total count must surface")

    def test_match_count_appears(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=7, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        )
        body = compose_body(facts)
        self.assertIn("7", body, "match count must surface")

    def test_pending_appears_separately_from_unsupported(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 200, "analyzed": 100, "pending": 50,
                      "unsupported": 50, "scan_complete": False},
            daemon_active=False,
        )
        body = compose_body(facts)
                                                                  
                                                                   
        self.assertIn("50", body)
        self.assertIn("unsupported", body.lower())
                                                                      
                                                                  
        self.assertTrue(
            body.lower().count("50") >= 2
            or "still to scan" in body.lower(),
            f"pending and unsupported counts must be reported "
            f"separately: {body!r}",
        )

    def test_failed_appears_separately(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=0, is_partial=True),
            coverage={"total": 100, "analyzed": 50, "pending": 40,
                      "failed": 10, "scan_complete": False},
            daemon_active=False,
        )
        body = compose_body(facts)
        self.assertIn("10", body)
                                                                         
        self.assertTrue(
            "fail" in body.lower(),
            f"failed count must surface with a fail label: {body!r}",
        )

    def test_skipped_appears_when_present(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=0, is_partial=True),
            coverage={"total": 50, "analyzed": 30, "pending": 15,
                      "skipped": 5, "scan_complete": False},
            daemon_active=False,
        )
        body = compose_body(facts)
        self.assertIn("5", body)
        self.assertIn("skipped", body.lower())

    def test_zero_category_is_omitted(self):
                                                                    
                                                                    
        facts = facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 100, "analyzed": 50, "pending": 50,
                      "unsupported": 0, "failed": 0, "skipped": 0,
                      "scan_complete": False},
            daemon_active=False,
        )
        body = compose_body(facts)
        self.assertNotIn("unsupported", body.lower())
        self.assertNotIn("fail", body.lower())
        self.assertNotIn("skipped", body.lower())

    def test_daemon_active_state_appears(self):
        facts = facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 425, "analyzed": 100, "pending": 325,
                      "scan_complete": False},
            daemon_active=True,
        )
        body = compose_body(facts)
                                                                  
                                                
        self.assertIn("running", body.lower())


class BodyVariesWithStateTests(unittest.TestCase):


    def test_different_coverages_produce_different_bodies(self):
        a = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 100, "analyzed": 30, "pending": 70,
                      "scan_complete": False},
            daemon_active=False,
        ))
        b = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 500, "analyzed": 200, "pending": 300,
                      "scan_complete": False},
            daemon_active=False,
        ))
        self.assertNotEqual(a, b, "different coverage → different body")

    def test_different_match_counts_produce_different_bodies(self):
        a = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        ))
        b = compose_body(facts_from_inputs(
            last_result=_result(match_count=7, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        ))
        self.assertNotEqual(a, b)

    def test_complete_vs_partial_produce_different_bodies(self):
        a = compose_body(facts_from_inputs(
            last_result=_result(match_count=2, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        ))
        b = compose_body(facts_from_inputs(
            last_result=_result(match_count=2, is_partial=True),
            coverage={"total": 100, "analyzed": 30, "pending": 70,
                      "scan_complete": False},
            daemon_active=False,
        ))
        self.assertNotEqual(a, b)

    def test_daemon_active_vs_idle_produce_different_bodies(self):
        cov = {"total": 100, "analyzed": 30, "pending": 70,
               "scan_complete": False}
        a = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage=cov, daemon_active=True,
        ))
        b = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage=cov, daemon_active=False,
        ))
        self.assertNotEqual(a, b)

    def test_no_two_bodies_collapse_to_the_same_string_in_a_distinct_set(self):


        cases = [
                                  
            (False, True,  {"total": 100, "analyzed": 100, "scan_complete": True}, 2),
                                  
            (False, True,  {"total": 100, "analyzed": 100, "scan_complete": True}, 0),
                                     
            (True,  False, {"total": 100, "analyzed": 30, "pending": 70,
                            "scan_complete": False}, 1),
                                                 
            (True,  False, {"total": 100, "analyzed": 30, "pending": 60,
                            "unsupported": 10, "scan_complete": False}, 1),
                                            
            (True,  False, {"total": 100, "analyzed": 50, "pending": 40,
                            "failed": 10, "scan_complete": False}, 1),
        ]
                                                                
        bodies = []
        for i, (is_partial, _, cov, mc) in enumerate(cases):
            daemon_active = (i == 2)                                        
            body = compose_body(facts_from_inputs(
                last_result=_result(match_count=mc, is_partial=is_partial),
                coverage=cov,
                daemon_active=daemon_active,
            ))
            bodies.append(body)
        self.assertEqual(
            len(bodies), len(set(bodies)),
            f"distinct fact-packs must produce DISTINCT bodies; got: {bodies!r}",
        )


class DecisionTableActionTests(unittest.TestCase):
    def test_complete_scan_action_is_full_answer(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_COVERAGE_COMPLETE_CHECK,
            last_result=_result(match_count=2, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_FULL_ANSWER)
                                                 
        self.assertIn("100", plan.body)
        self.assertIn("2", plan.body)

    def test_partial_with_daemon_action_is_wait(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_COVERAGE_COMPLETE_CHECK,
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 425, "analyzed": 194, "pending": 231,
                      "scan_complete": False},
            daemon_active=True,
        )
        self.assertEqual(plan.action, ACTION_WAIT_FOR_ANALYSIS)
        self.assertIn("194", plan.body)
        self.assertIn("425", plan.body)
        self.assertIn("running", plan.body.lower())

    def test_partial_without_daemon_action_is_partial_with_limits(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_COVERAGE_COMPLETE_CHECK,
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 425, "analyzed": 194, "pending": 231,
                      "scan_complete": False},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_PARTIAL_WITH_LIMITS)
        self.assertIn("194", plan.body)
        self.assertIn("425", plan.body)
        self.assertIn("can't confirm", plan.body.lower())

    def test_filter_rerun_action_is_clarify(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_RERUN_WITH_DIFFERENT_FILTER,
            last_result=_result(match_count=1),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_CLARIFY)
        self.assertGreater(len(plan.clarification_options), 0)

    def test_pure_referent_delegates_with_empty_body(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_PURE_REFERENT,
            last_result=_result(match_count=1),
            coverage={"total": 100, "analyzed": 100},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_CANT_CONFIRM)
        self.assertEqual(plan.body, "")
        self.assertEqual(plan.reason, "intent_pure_referent_delegated")

    def test_no_last_result_asks_for_clarification(self):


        plan = plan_answer(
            message="x",
            followup_intent=INTENT_COVERAGE_COMPLETE_CHECK,
            last_result=None,
            coverage={"total": 100, "analyzed": 100},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_CANT_CONFIRM)
                                                                   
        low = plan.body.lower()
        self.assertTrue(
            "which result" in low or "re-run" in low or "fresh" in low
            or "tell me" in low,
            f"no-last-result body must ask for context: {plan.body!r}",
        )

    def test_check_other_locations_returns_honest_partial(self):
        plan = plan_answer(
            message="x",
            followup_intent=INTENT_CHECK_OTHER_LOCATIONS,
            last_result=_result(match_count=2),
            coverage={"total": 425, "analyzed": 425, "scan_complete": True},
            daemon_active=False,
        )
        self.assertEqual(plan.action, ACTION_PARTIAL_WITH_LIMITS)
                                                  
        self.assertIn("425", plan.body)


class NoCannedCategoryLeakTests(unittest.TestCase):
    FORBIDDEN_PHRASES = (
        "Bank Account", "ID Document", "Payment Card",
        "Saved Logins", "Saved Login",
        "Loyalty Card", "Insurance Card",
    )

    def test_no_canned_category_in_non_docstring_string_literals(self):
        import vault_answer_planner as vap
        tree = ast.parse(inspect.getsource(vap))
        docstring_node_ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                ds = ast.get_docstring(node, clean=False)
                if ds and node.body and isinstance(node.body[0], ast.Expr):
                    expr = node.body[0]
                    if isinstance(expr.value, ast.Constant):
                        docstring_node_ids.add(id(expr.value))
        bad: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if id(node) in docstring_node_ids:
                continue
            if not isinstance(node.value, str):
                continue
            for phrase in self.FORBIDDEN_PHRASES:
                if phrase in node.value:
                    bad.append((phrase, node.value[:80]))
        self.assertEqual(bad, [], f"canned category leaks: {bad!r}")

    def test_every_decision_branch_body_is_clean(self):
        cases = []
        for is_partial in (True, False):
            for cov in (
                {"total": 425, "analyzed": 194, "pending": 122,
                 "unsupported": 109, "failed": 5, "scan_complete": False},
                {"total": 100, "analyzed": 100, "scan_complete": True},
                {"total": 0},
            ):
                for daemon in (True, False):
                    for intent in (
                        INTENT_COVERAGE_COMPLETE_CHECK,
                        INTENT_WANT_MORE_RESULTS,
                        INTENT_CHECK_OTHER_LOCATIONS,
                        INTENT_RERUN_WITH_DIFFERENT_FILTER,
                    ):
                        cases.append((is_partial, cov, daemon, intent))
        for is_partial, cov, daemon, intent in cases:
            plan = plan_answer(
                message="x", followup_intent=intent,
                last_result=_result(match_count=2, is_partial=is_partial),
                coverage=cov, daemon_active=daemon,
            )
            for phrase in self.FORBIDDEN_PHRASES:
                self.assertNotIn(
                    phrase, plan.body,
                    f"canned category {phrase!r} leaked for "
                    f"intent={intent}, partial={is_partial}, "
                    f"daemon={daemon}, coverage={cov}",
                )


class NoPhraseMatchingInPlannerTests(unittest.TestCase):
    def test_planner_never_compares_message_to_user_phrases(self):
        import vault_answer_planner as vap
        tree = ast.parse(inspect.getsource(vap))
        FORBIDDEN_FRAGMENTS = (
            "is that all", "are these all", "only those",
            "are there more", "is this everything",
            "did you check", "what about",
        )
        bad: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                snippet = ast.unparse(node.test).lower()
                for frag in FORBIDDEN_FRAGMENTS:
                    if frag in snippet:
                        bad.append(snippet)
                        break
            if isinstance(node, ast.Compare):
                snippet = ast.unparse(node).lower()
                for frag in FORBIDDEN_FRAGMENTS:
                    if frag in snippet:
                        bad.append(snippet)
                        break
        self.assertEqual(bad, [])

    def test_planner_is_a_pure_function(self):
        import vault_answer_planner as vap
        src = inspect.getsource(vap)
        for forbidden in (
            "psycopg2", "get_db(", "openai", "client.chat",
            "decrypt_message", "encrypt_message",
            "embed_text",
        ):
            self.assertNotIn(forbidden, src)


class CompositionShapeTests(unittest.TestCase):


    def test_complete_no_match_body_differs_from_complete_with_match(self):
        a = compose_body(facts_from_inputs(
            last_result=_result(match_count=0, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        ))
        b = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=False),
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            daemon_active=False,
        ))
        self.assertNotEqual(a, b)

    def test_partial_body_with_failures_is_longer_than_without(self):
        without = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 100, "analyzed": 50, "pending": 50,
                      "scan_complete": False},
            daemon_active=False,
        ))
        with_extras = compose_body(facts_from_inputs(
            last_result=_result(match_count=1, is_partial=True),
            coverage={"total": 100, "analyzed": 50, "pending": 30,
                      "failed": 10, "unsupported": 10,
                      "scan_complete": False},
            daemon_active=False,
        ))
                                                                   
                                   
        self.assertGreater(len(with_extras), len(without))


if __name__ == "__main__":
    unittest.main()
