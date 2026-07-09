

from __future__ import annotations

import asyncio
import inspect
import math
import re
import unittest
from typing import Optional

from vault_followup_classifier import (
    FOLLOWUP_INTENTS,
    INTENT_COVERAGE_COMPLETE_CHECK,
    INTENT_WANT_MORE_RESULTS,
    INTENT_CHECK_OTHER_LOCATIONS,
    INTENT_RERUN_WITH_DIFFERENT_FILTER,
    INTENT_PURE_REFERENT,
    INTENT_NOT_A_FOLLOWUP,
    MODE_A_CONFIDENCE_THRESHOLD,
    classify_followup,
    classify_mode_a,
    classify_mode_b,
    reset_anchor_cache_for_tests,
)


_DIM = 256                                      
_WORD_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _stem(word: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if word.endswith(suf) and len(word) > len(suf) + 2:
            return word[: -len(suf)]
    return word


_STOPWORDS = {
    "the", "a", "an", "is", "it", "of", "to", "in", "and", "or",
    "i", "you", "me", "we", "us", "my", "your",
    "do", "did", "does", "be", "been",
    "have", "has", "had",
}


import hashlib


def _det_hash(word: str) -> int:


    return int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)


def _bag_vector(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for raw in _WORD_TOKEN_RE.findall(text.lower()):
        word = _stem(raw)
        if word in _STOPWORDS:
            continue
        h = _det_hash(word) % _DIM
        vec[h] += 1.0
                   
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


async def fake_embed(text: str) -> Optional[list[float]]:
    return _bag_vector(text)


async def fake_embed_disabled(text: str) -> Optional[list[float]]:
    return None


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class CoverageCompleteCheckEquivalenceTests(unittest.TestCase):


    EQUIVALENT_PHRASINGS = [
        "is that all?",
        "is this everything?",
        "have you checked every file?",
        "have you scanned every file in my vault?",
        "did you check the whole vault?",
        "is the scan complete?",
        "are these the complete results?",
        "are those all the files you found?",
        "have you looked at all of them?",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_phrasing_classifies_as_coverage_complete_check(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.EQUIVALENT_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_COVERAGE_COMPLETE_CHECK:
                misclassifications.append((phrasing, result.intent))
                                                               
                                                           
        self.assertLessEqual(
            len(misclassifications), 1,
            f"Coverage-question phrasings misclassified: {misclassifications!r}",
        )


class WantMoreResultsEquivalenceTests(unittest.TestCase):
    EQUIVALENT_PHRASINGS = [
        "are there more?",
        "could there be more matches somewhere?",
        "show me more results",
        "what else did you find?",
        "give me additional results",
        "are there any other matches you can show?",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_phrasing_classifies_as_want_more_results(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.EQUIVALENT_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_WANT_MORE_RESULTS:
                misclassifications.append((phrasing, result.intent))
        self.assertLessEqual(
            len(misclassifications), 1,
            f"want_more_results phrasings misclassified: {misclassifications!r}",
        )


class CheckOtherLocationsEquivalenceTests(unittest.TestCase):
    EQUIVALENT_PHRASINGS = [
        "what about other folders?",
        "did you check the archives folder?",
        "did you look inside zip archives?",
        "what about my downloads subfolder?",
        "is there a folder you skipped checking?",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_phrasing_classifies_as_check_other_locations(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.EQUIVALENT_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_CHECK_OTHER_LOCATIONS:
                misclassifications.append((phrasing, result.intent))
        self.assertLessEqual(
            len(misclassifications), 1,
            f"check_other_locations phrasings misclassified: {misclassifications!r}",
        )


class RerunWithDifferentFilterEquivalenceTests(unittest.TestCase):
    EQUIVALENT_PHRASINGS = [
        "include the weak matches too",
        "show me unsupported files too",
        "include archived files",
        "broaden the search to include maybes",
        "use a looser filter please",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_phrasing_classifies_as_rerun_with_filter(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.EQUIVALENT_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_RERUN_WITH_DIFFERENT_FILTER:
                misclassifications.append((phrasing, result.intent))
        self.assertLessEqual(
            len(misclassifications), 1,
            f"rerun_with_filter phrasings misclassified: {misclassifications!r}",
        )


class PureReferentEquivalenceTests(unittest.TestCase):
    EQUIVALENT_PHRASINGS = [
        "open the first one",
        "show me the strong one",
        "show the top one please",
        "delete that file",
        "rename the second result",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_phrasing_classifies_as_pure_referent(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.EQUIVALENT_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_PURE_REFERENT:
                misclassifications.append((phrasing, result.intent))
        self.assertLessEqual(
            len(misclassifications), 1,
            f"pure_referent phrasings misclassified: {misclassifications!r}",
        )


class NotAFollowupRecognitionTests(unittest.TestCase):


    UNRELATED_PHRASINGS = [
        "what is the weather today",
        "remind me to call mom tomorrow",
        "create me a new login for chase bank",
        "tell me a joke",
        "what is two plus two",
    ]

    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_unrelated_messages_classify_as_not_a_followup(self):
        misclassifications: list[tuple[str, str]] = []
        for phrasing in self.UNRELATED_PHRASINGS:
            result = _run(classify_followup(
                phrasing, embed_fn=fake_embed,
            ))
            if result.intent != INTENT_NOT_A_FOLLOWUP:
                misclassifications.append((phrasing, result.intent))
        self.assertLessEqual(
            len(misclassifications), 1,
            f"unrelated phrasings misclassified as a follow-up: {misclassifications!r}",
        )


class ClosedSetOutputTests(unittest.TestCase):
    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_every_call_returns_a_known_intent_string(self):
                                                                     
        for msg in [
            "", "?", "asdfqwer", "is that all?",
            "what the hell is going on here",
            "open it", "are there more?",
        ]:
            result = _run(classify_followup(msg, embed_fn=fake_embed))
            self.assertIn(
                result.intent, FOLLOWUP_INTENTS,
                f"classifier returned non-closed-set intent: {result.intent!r}",
            )

    def test_empty_message_returns_not_a_followup(self):
        result = _run(classify_followup("", embed_fn=fake_embed))
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)
        self.assertEqual(result.mode, "noop_no_message")

    def test_disabled_embedder_returns_low_confidence(self):
        reset_anchor_cache_for_tests()
        result = _run(classify_followup(
            "is that all?", embed_fn=fake_embed_disabled,
        ))
                                                              
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)
        self.assertEqual(result.confidence, 0.0)

    def test_credential_only_files_followup_survives_disabled_embedder(self):
        reset_anchor_cache_for_tests()
        result = _run(classify_followup(
            "are these both the only files with list of credentials in it?",
            embed_fn=fake_embed_disabled,
            last_result_summary={
                "result_type": "credential_files",
                "intent": "search_files_for_credentials",
                "total_matches_known": 2,
                "is_partial": False,
            },
        ))
        self.assertEqual(result.intent, INTENT_COVERAGE_COMPLETE_CHECK)
        self.assertEqual(result.mode, "token_shape")


class ModeBFallbackTests(unittest.TestCase):
    def setUp(self):
        reset_anchor_cache_for_tests()

    def test_mode_b_invoked_only_when_mode_a_low_confidence(self):
                                                                    
                        
        invoked = {"called": False}

        async def fake_llm(message, summary):
            invoked["called"] = True
            return {"intent": INTENT_NOT_A_FOLLOWUP, "confidence": 1.0}

        result = _run(classify_followup(
            "is that all of them",                                       
            embed_fn=fake_embed,
            llm_fallback_fn=fake_llm,
        ))
        self.assertEqual(result.intent, INTENT_COVERAGE_COMPLETE_CHECK)
        self.assertFalse(
            invoked["called"],
            "Mode B must not be called when Mode A is confident",
        )

    def test_mode_b_invoked_when_mode_a_low_confidence(self):
        invoked = {"called": False, "msg": None}

        async def fake_llm(message, summary):
            invoked["called"] = True
            invoked["msg"] = message
            return {"intent": INTENT_COVERAGE_COMPLETE_CHECK, "confidence": 0.92}

                                                                  
        result = _run(classify_followup(
            "zzzzz xyzzy purple platypus",
            embed_fn=fake_embed,
            llm_fallback_fn=fake_llm,
            mode_a_threshold=0.99,                
        ))
        self.assertTrue(invoked["called"])
        self.assertEqual(result.intent, INTENT_COVERAGE_COMPLETE_CHECK)
        self.assertEqual(result.mode, "mode_b_llm")

    def test_mode_b_returns_garbage_intent_collapses_to_not_a_followup(self):
        async def fake_llm(message, summary):
            return {"intent": "something_we_dont_recognise", "confidence": 0.99}
        result = _run(classify_mode_b(
            "anything", None, fake_llm,
        ))
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)

    def test_mode_b_low_confidence_collapses_to_not_a_followup(self):
        async def fake_llm(message, summary):
            return {"intent": INTENT_COVERAGE_COMPLETE_CHECK, "confidence": 0.30}
        result = _run(classify_mode_b("anything", None, fake_llm))
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)

    def test_mode_b_exception_caught_returns_not_a_followup(self):
        async def fake_llm(message, summary):
            raise RuntimeError("LLM exploded")
        result = _run(classify_mode_b("anything", None, fake_llm))
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)

    def test_mode_b_without_fn_no_op(self):
        result = _run(classify_mode_b("anything", None, None))
        self.assertEqual(result.intent, INTENT_NOT_A_FOLLOWUP)

    def test_mode_b_never_returns_a_phrase_to_render(self):
                                                                     
                                                                   
        import vault_followup_classifier as vfc
        src = inspect.getsource(vfc)
                                                                      
        self.assertNotIn("body", src.lower().split("classification")[0]
                         if "classification" in src.lower() else src.lower())
        self.assertNotIn("reply_text", src)


class NoPhraseMatchingInModuleTests(unittest.TestCase):


    def test_module_has_no_inline_phrase_if_statements(self):
                                                            
                                                         
        import ast, vault_followup_classifier as vfc
        src = inspect.getsource(vfc)
        tree = ast.parse(src)
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
        self.assertEqual(
            bad, [],
            f"classifier must not phrase-match user wording — found: {bad!r}",
        )

    def test_anchors_live_in_data_not_in_code(self):
                                                                   
                                                    
        import vault_followup_classifier as vfc
        self.assertIsInstance(vfc._ANCHORS, dict)
        for intent, anchors in vfc._ANCHORS.items():
            self.assertIn(intent, FOLLOWUP_INTENTS)
            self.assertGreater(len(anchors), 0)


if __name__ == "__main__":
    unittest.main()
