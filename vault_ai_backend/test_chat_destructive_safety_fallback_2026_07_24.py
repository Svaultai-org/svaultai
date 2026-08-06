"""Regression tests for the deterministic destructive-action
safety fallback (adjustments 1 and 3 of the 2026-07-24 chat-brain
rebuild).

Coverage:
    * classify_destructive_message recognizes bare
      yes/no/cancel/nope/etc.
    * classify_destructive_message returns UNCLEAR for compound
      or long phrasings — those are the model's job.
    * When the semantic decider fails AND a destructive pending
      action is live:
        - bare "yes" → deterministic confirm executes the delete
        - bare "no" → deterministic cancel cancels the delete
        - anything else → clarification prompt (never falls
          through to legacy routing)
    * When there is NO destructive pending, decider fallthrough
      still delegates to the existing pipeline (non-destructive
      fallback OK per adjustment 3).
"""

from __future__ import annotations

import asyncio
import json
import unittest

from vault_chat_destructive_safety_fallback import (
    SAFETY_CANCEL,
    SAFETY_CONFIRM,
    SAFETY_UNCLEAR,
    build_clarification_prompt,
    classify_destructive_message,
)
from vault_chat_semantic_decider import CONFIDENCE_LOW
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_FALLTHROUGH,
)


VAULT = "vault-failsafe-test"
SESS = "session-fs"


class TestClassifier(unittest.TestCase):
    """The deterministic classifier is intentionally narrow. This
    test locks the exact CONFIRM / CANCEL / UNCLEAR contract."""

    def test_bare_yes_family_returns_confirm(self):
        for phrase in [
            "yes", "Yes", "yes.", "yes!", "yeah", "yep", "yup",
            "y", "ya", "yea", "ok", "okay", "confirm", "confirmed",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    classify_destructive_message(phrase),
                    SAFETY_CONFIRM,
                    f"{phrase!r} should be safety-confirm",
                )

    def test_bare_no_family_returns_cancel(self):
        for phrase in [
            "no", "No", "no.", "nope", "nah", "n",
            "cancel", "stop", "don't", "do not",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    classify_destructive_message(phrase),
                    SAFETY_CANCEL,
                    f"{phrase!r} should be safety-cancel",
                )

    def test_compound_phrasings_return_unclear(self):
        # These are the model's job. When the model is down, we
        # refuse to guess.
        for phrase in [
            "yeah go ahead and delete that one",
            "sure thing",
            "actually maybe don't",
            "on second thought i'm not sure",
            "delete my instagram login please",
            "which one did you mean",
            "hi",
            "",
            "yes but wait",
            "no wait",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    classify_destructive_message(phrase),
                    SAFETY_UNCLEAR,
                    f"{phrase!r} should be safety-unclear",
                )

    def test_none_and_non_string_return_unclear(self):
        for v in (None, 42, [], {}, object()):
            self.assertEqual(
                classify_destructive_message(v),
                SAFETY_UNCLEAR,
            )

    def test_long_message_returns_unclear(self):
        long_msg = "yes " * 20      # 80 chars — over 30-char cap
        self.assertEqual(
            classify_destructive_message(long_msg),
            SAFETY_UNCLEAR,
        )


class TestClarificationPrompt(unittest.TestCase):

    def test_prompt_uses_target_label(self):
        prompt = build_clarification_prompt("Instagram login")
        self.assertIn("Instagram login", prompt)
        self.assertIn("yes", prompt.lower())
        self.assertIn("no", prompt.lower())

    def test_prompt_falls_back_when_label_empty(self):
        prompt = build_clarification_prompt("")
        self.assertIn("that saved item", prompt)


# --------------------------------------------------------------------
# End-to-end failsafe behavior against the brain.
# --------------------------------------------------------------------

class _StubResult:
    def __init__(self, content: str):
        self.content = content


def _run(coro):
    return asyncio.run(coro)


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


async def _run_brain(user_message: str, *, provider_returns,
                     vault_id: str = VAULT, session_id: str = SESS):
    """Run the brain with a stub provider that returns ``provider_returns``
    (a dict, an Exception, or None to simulate no content)."""
    import vault_chat_semantic_decider as sd
    from vault_chat_brain import run_chat_brain

    async def stub(**kwargs):
        if isinstance(provider_returns, Exception):
            raise provider_returns
        if provider_returns is None:
            return _StubResult("")     # empty content
        if isinstance(provider_returns, str):
            return _StubResult(provider_returns)
        return _StubResult(json.dumps(provider_returns))

    orig = sd.decide

    async def patched(snapshot, *, timeout_s=None, ai_provider=None):
        return await orig(snapshot, timeout_s=timeout_s,
                          ai_provider=(ai_provider or stub))

    sd.decide = patched
    try:
        return await run_chat_brain(
            vault_id=vault_id, session_id=session_id,
            turn_id="t-1", vault_name="Personal",
            reply_language="en",
            user_message=user_message,
            memory=dict(), key=b"\x00" * 32,
        )
    finally:
        sd.decide = orig


class DestructiveFailsafeConfirmTest(unittest.TestCase):
    """Model timeout / malformed / invalid + destructive pending
    + bare "yes" must still safely delete."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _stamp_delete(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Instagram",
            item_type="login",
        )

    def test_bare_yes_on_decider_timeout_confirms_delete(self):
        self._stamp_delete()
        result = _run(_run_brain(
            "yes",
            provider_returns=asyncio.TimeoutError(),
        ))
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)
        self.assertEqual(result.tool, TOOL_CONFIRM_PENDING_DELETE)

    def test_bare_yes_on_malformed_json_confirms_delete(self):
        self._stamp_delete()
        result = _run(_run_brain(
            "yes",
            provider_returns="not valid json {{",
        ))
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)

    def test_bare_yes_on_transport_error_confirms_delete(self):
        self._stamp_delete()
        result = _run(_run_brain(
            "yes",
            provider_returns=RuntimeError("network unreachable"),
        ))
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)

    def test_bare_yes_on_unknown_tool_confirms_delete(self):
        self._stamp_delete()
        result = _run(_run_brain(
            "yes",
            provider_returns={
                "tool": "made_up_tool",
                "args": {},
                "confidence": "high",
                "why": "invented",
            },
        ))
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)

    def test_bare_yes_on_valid_but_policy_rejected_confirms_delete(self):
        """LOW-confidence destructive confirm is policy-rejected.
        Instead of falling through to legacy routing (which
        would let bare "yes" hit the secure-item cascade and
        execute the delete without a proper trace), the fail-
        safe intercepts and executes it with an explicit
        deterministic-fallback trail."""
        self._stamp_delete()
        result = _run(_run_brain(
            "yes",
            provider_returns={
                "tool": TOOL_CONFIRM_PENDING_DELETE,
                "args": {"action_id": "does-not-match"},
                "confidence": CONFIDENCE_LOW,
                "why": "guessing",
            },
        ))
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)


class DestructiveFailsafeCancelTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_bare_no_on_decider_failure_cancels_delete(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Netflix", item_type="login",
        )
        result = _run(_run_brain(
            "no",
            provider_returns=asyncio.TimeoutError(),
        ))
        self.assertTrue(result.handled)
        self.assertIn("won't delete", result.reply_text.lower())
        self.assertEqual(result.tool, TOOL_CANCEL_PENDING_DELETE)

    def test_cancel_on_decider_failure_cancels_delete(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Netflix", item_type="login",
        )
        result = _run(_run_brain(
            "cancel",
            provider_returns=asyncio.TimeoutError(),
        ))
        self.assertTrue(result.handled)
        self.assertIn("won't delete", result.reply_text.lower())


class DestructiveFailsafeClarifyTest(unittest.TestCase):
    """Unclear message + decider failure + destructive pending →
    ask user to repeat. Never lets legacy routing execute a
    destructive action on ambiguous input."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_compound_phrase_on_decider_failure_asks_clarification(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Instagram", item_type="login",
        )
        result = _run(_run_brain(
            "yeah go ahead and delete it thanks",
            provider_returns=asyncio.TimeoutError(),
        ))
        # Handled by brain (not falling through to legacy).
        self.assertTrue(result.handled)
        # Result is a clarification, NOT a "Deleted" reply.
        self.assertNotIn("Deleted", result.reply_text)
        self.assertNotIn("won't delete", result.reply_text.lower())
        self.assertIn("yes", result.reply_text.lower())
        self.assertIn("no", result.reply_text.lower())

    def test_topic_switch_on_decider_failure_asks_clarification(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Instagram", item_type="login",
        )
        result = _run(_run_brain(
            "what's the weather like",
            provider_returns=asyncio.TimeoutError(),
        ))
        self.assertTrue(result.handled)
        self.assertNotIn("Deleted", result.reply_text)


class NonDestructivePendingFallthroughTest(unittest.TestCase):
    """When there is NO destructive pending, decider fallthrough
    still delegates to the existing pipeline — adjustment 3
    only restricts DESTRUCTIVE fallthrough."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_no_pending_and_decider_timeout_falls_through(self):
        result = _run(_run_brain(
            "what's my chase login",
            provider_returns=asyncio.TimeoutError(),
        ))
        # No destructive pending → brain falls through to
        # existing pipeline as intended.
        self.assertFalse(result.handled)


if __name__ == "__main__":
    unittest.main()
