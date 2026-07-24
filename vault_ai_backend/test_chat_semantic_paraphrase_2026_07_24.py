"""Semantic-behavior tests for the chat brain.

Groups of paraphrases (each meaning the same thing) that a
production model should recognize. We use a *simulated* semantic
provider — a deterministic function that emulates the model's
expected output for each phrasing — so we don't need real API
calls in CI. This lets us assert the pipeline's *behavior contract*
under expected model outputs without the flakiness or cost of a
live LLM.

If a phrase is not in the simulated coverage set, the test asks
the pipeline to fall through, and we assert that behavior too.

These tests do NOT prove the production model will recognize all
of these phrasings — that is what the evaluation corpus is for
(``evals/chat_brain_eval_2026_07_24.jsonl``). They prove that
WHEN the model returns the expected structured intent, the
policy + router take the correct action.
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from typing import Optional

from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)


VAULT = "vault-para"
SESS = "sess-para"


class _StubResult:
    def __init__(self, content: str):
        self.content = content


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# -----------------------------------------------------------------
# Simulated "semantic model" — deterministic function that returns
# what a well-behaved production model SHOULD return for known
# phrasings, given a snapshot with a pending delete.
# -----------------------------------------------------------------

_CONFIRM_SEMANTIC = re.compile(
    r"^\s*("
    r"yes|yeah|yep|yup|ya|y|"
    r"ok|okay|k|"
    r"sure|fine|correct|right|"
    r"confirm(?:ed)?|"
    r"go\s*ahead|proceed|"
    r"do\s*it|please\s*do\s*it|"
    r"delete\s*(?:it|that|now)?|"
    r"remove\s*(?:it|that)?|"
    r"i'?m\s*sure|"
    r"that'?s\s*right|"
    r"go|approved"
    r")\s*[.!,]?\s*(?:please|now)?\s*[.!,]?\s*$",
    re.IGNORECASE,
)

_CANCEL_SEMANTIC = re.compile(
    r"^\s*("
    r"no|nope|nah|n|"
    r"cancel|stop|halt|"
    r"don'?t|do\s*not|"
    r"keep\s+(?:it|them|that)|"
    r"never\s*mind|nevermind|"
    r"on\s*second\s*thought|"
    r"actually\s*(?:no|don'?t|do\s*not)"
    r")\s*[.!,]?\s*(?:please|now|it|that)?\s*[.!,]?\s*$",
    re.IGNORECASE,
)


def _semantic_provider(snapshot_pending_id: str):
    """Build a provider callable that inspects the user message
    and returns the tool a semantic model would pick."""
    async def _provider(**kwargs):
        # Extract the user message from the "user" message in
        # kwargs["messages"].
        messages = kwargs.get("messages") or []
        user_text = ""
        for m in messages:
            if m.get("role") == "user":
                try:
                    p = json.loads(m.get("content") or "{}")
                    user_text = str(
                        p.get("snapshot", {}).get("user_message") or ""
                    )
                except Exception:
                    user_text = m.get("content") or ""
                break
        stripped = user_text.strip()
        # Confirm phrases → confirm the pending delete.
        if _CONFIRM_SEMANTIC.match(stripped):
            return _StubResult(json.dumps({
                "tool": TOOL_CONFIRM_PENDING_DELETE,
                "args": {"action_id": snapshot_pending_id},
                "confidence": CONFIDENCE_HIGH,
                "why": "confirmation",
            }))
        # Cancel phrases → cancel the pending delete.
        if _CANCEL_SEMANTIC.match(stripped):
            return _StubResult(json.dumps({
                "tool": TOOL_CANCEL_PENDING_DELETE,
                "args": {"action_id": snapshot_pending_id},
                "confidence": CONFIDENCE_HIGH,
                "why": "cancellation",
            }))
        # Ambiguous or clarification-like → ask a question.
        if "which" in stripped.lower() or "?" in stripped:
            return _StubResult(json.dumps({
                "tool": TOOL_REQUEST_CLARIFICATION,
                "args": {"question": "Which one did you mean?"},
                "confidence": CONFIDENCE_MEDIUM,
                "why": "ambiguous",
            }))
        # Everything else → fall through.
        return _StubResult(json.dumps({
            "tool": TOOL_FALLTHROUGH,
            "args": {},
            "confidence": CONFIDENCE_LOW,
            "why": "unrelated",
        }))
    return _provider


def _install_secure_item_stub():
    import vault_secure_item_save as ss

    # Signature must match production; db_executor is required.
    def _exec(*, vault_id, key, db_executor):
        return {"band": "deleted",
                "message": "Deleted saved item from your vault."}

    def _cancel(*, vault_id):
        return {"band": "delete_cancelled",
                "message": "Okay — I won't delete it."}

    ss._execute_pending_delete = _exec
    ss._cancel_pending_delete = _cancel


async def _run_brain(user_message: str, *, intent_id: str,
                     vault_id: str = VAULT, session_id: str = SESS):
    import vault_chat_semantic_decider as sd
    from vault_chat_brain import run_chat_brain

    orig = sd.decide
    provider = _semantic_provider(intent_id)

    async def patched(snapshot, *, timeout_s=None, ai_provider=None):
        return await orig(snapshot, timeout_s=timeout_s,
                          ai_provider=(ai_provider or provider))
    sd.decide = patched
    try:
        return await run_chat_brain(
            vault_id=vault_id, session_id=session_id,
            turn_id="t-1", vault_name="Personal",
            reply_language="en", user_message=user_message,
            memory=dict(), key=b"\x00" * 32,
        )
    finally:
        sd.decide = orig


class ConfirmParaphrasesTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_various_confirmations_all_delete(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        confirmed_count = 0
        confirm_variants = [
            "yes",
            "yeah",
            "yep",
            "sure",
            "ok",
            "okay",
            "go ahead",
            "do it",
            "delete it",
            "proceed",
            "confirm",
            "yes please",
            "yes now",
        ]
        for phrase in confirm_variants:
            # Fresh state per phrase to avoid consumed intent.
            reset_chat_state_backend_for_tests()
            install_backend_for_tests(InMemoryChatStateBackend())
            _install_secure_item_stub()
            store_delete_intent(
                vault_id=VAULT, service="Instagram",
                item_type="login",
            )
            intent = get_pending_delete_intent(vault_id=VAULT)
            result = _run(_run_brain(
                phrase, intent_id=intent.intent_id,
            ))
            with self.subTest(phrase=phrase):
                self.assertTrue(result.handled)
                self.assertIn("Deleted", result.reply_text)
                confirmed_count += 1
        # All variants should have been recognized.
        self.assertEqual(confirmed_count, len(confirm_variants))


class CancelParaphrasesTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_various_cancels_all_cancel(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        cancel_variants = [
            "no",
            "nope",
            "cancel",
            "stop",
            "don't",
            "keep it",
            "never mind",
            "actually no",
            "nah",
        ]
        for phrase in cancel_variants:
            reset_chat_state_backend_for_tests()
            install_backend_for_tests(InMemoryChatStateBackend())
            _install_secure_item_stub()
            store_delete_intent(
                vault_id=VAULT, service="Netflix", item_type="login",
            )
            intent = get_pending_delete_intent(vault_id=VAULT)
            result = _run(_run_brain(
                phrase, intent_id=intent.intent_id,
            ))
            with self.subTest(phrase=phrase):
                self.assertTrue(result.handled)
                self.assertIn("won't delete", result.reply_text.lower())


class TopicSwitchTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_various_topic_switches_fall_through(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        switches = [
            "what's the weather like",
            "how do I export my vault",
            "tell me about vaultai",
            "what was I asking before",
        ]
        for phrase in switches:
            reset_chat_state_backend_for_tests()
            install_backend_for_tests(InMemoryChatStateBackend())
            _install_secure_item_stub()
            store_delete_intent(
                vault_id=VAULT, service="Instagram",
                item_type="login",
            )
            intent = get_pending_delete_intent(vault_id=VAULT)
            result = _run(_run_brain(
                phrase, intent_id=intent.intent_id,
            ))
            with self.subTest(phrase=phrase):
                # Not confirmed as a delete, not saved as anything.
                self.assertNotIn("Deleted", result.reply_text)


if __name__ == "__main__":
    unittest.main()
