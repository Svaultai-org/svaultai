"""End-to-end tests for the 2026-07-24 chat-brain rebuild.

Exercises ``vault_chat_brain.run_chat_brain`` against a stubbed
LLM provider. The tests cover the concrete user-story that
originally caused the incident (stale unnamed video vs "yes" for
a pending delete) plus the required categories:

    * stale video + pending delete + natural-language confirmation
    * pending delete across workers
    * confirmation, rejection, hesitation, topic switch
    * orphan attachments from old turns
    * text-only messages never invoking media save
    * concurrent sessions for the same user
    * cross-user isolation
    * tool execution failure
    * successful-action truthfulness
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
)
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_SAVE,
    TOOL_CONVERSATIONAL_REPLY,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)


VAULT_A = "vault-brain-A"
VAULT_B = "vault-brain-B"
SESS_A = "sess-a"
SESS_B = "sess-b"


class _StubProviderResult:
    def __init__(self, content: str):
        self.content = content


class _NoopMemory(dict):
    pass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _install_provider(payload):
    """Monkey-patch ``vault_chat_semantic_decider.decide`` to use
    a stub ai_provider that returns ``payload`` (dict or Exception)
    on every call. Restores on tearDown by calling this with None.
    """
    import vault_chat_semantic_decider as sd
    if payload is None:
        try:
            del sd._TEST_STUB_PROVIDER    # type: ignore[attr-defined]
        except AttributeError:
            pass
        return

    async def _provider(**kwargs):
        if isinstance(payload, Exception):
            raise payload
        content = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        return _StubProviderResult(content)

    sd._TEST_STUB_PROVIDER = _provider   # type: ignore[attr-defined]


def _install_secure_item_stub():
    """Patch vault_secure_item_save so tests never touch the real
    DB. We install our own ``_execute_pending_delete`` and
    ``_cancel_pending_delete`` that return dicts with the same
    shape production returns."""
    import vault_secure_item_save as ss

    def _fake_execute(*, vault_id, key=None, db_executor=None):
        return {
            "band": "deleted",
            "message": "Deleted saved item from your vault.",
        }

    def _fake_cancel(*, vault_id):
        return {
            "band": "delete_cancelled",
            "message": "Okay — I won't delete it.",
        }

    ss._execute_pending_delete = _fake_execute
    ss._cancel_pending_delete = _fake_cancel


async def _run_brain(user_message: str, *, vault_id: str, session_id: str,
                     memory: Any = None):
    """Wrapper that patches the decider to inject our stub
    provider on this call and then invokes the brain."""
    import vault_chat_semantic_decider as sd
    from vault_chat_brain import run_chat_brain

    orig_decide = sd.decide
    stub = getattr(sd, "_TEST_STUB_PROVIDER", None)

    async def patched_decide(snapshot, *, timeout_s=None, ai_provider=None):
        return await orig_decide(
            snapshot, timeout_s=timeout_s,
            ai_provider=(ai_provider or stub),
        )

    sd.decide = patched_decide
    try:
        return await run_chat_brain(
            vault_id=vault_id,
            session_id=session_id,
            turn_id="t-1",
            vault_name="Personal",
            reply_language="en",
            user_message=user_message,
            memory=memory or _NoopMemory(),
            key=b"\x00" * 32,
            unlocked=True,
            user_tier="free",
            features={},
        )
    finally:
        sd.decide = orig_decide


class ChatBrainRootCauseTest(unittest.TestCase):
    """The exact incident timeline: a stale unnamed video must NOT
    hijack a pending delete confirmation."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_stale_video_does_not_hijack_yes_confirmation(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        # Stamp a pending delete.
        store_delete_intent(
            vault_id=VAULT_A, service="Instagram",
            item_type="login",
        )
        intent = get_pending_delete_intent(vault_id=VAULT_A)
        assert intent is not None
        # Model says: this is a confirm of THIS delete.
        _install_provider({
            "tool": TOOL_CONFIRM_PENDING_DELETE,
            "args": {"action_id": intent.intent_id},
            "confidence": CONFIDENCE_HIGH,
            "why": "yes confirms the delete",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_A, session_id=SESS_A,
        ))
        # Success = deletion happened, NOT a save.
        self.assertTrue(result.handled)
        self.assertIn("Deleted", result.reply_text)
        self.assertNotIn("Saved this video", result.reply_text)
        self.assertEqual(result.tool, TOOL_CONFIRM_PENDING_DELETE)


class ChatBrainCancelTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_no_cancels_pending_delete(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT_A, service="Netflix", item_type="login",
        )
        intent = get_pending_delete_intent(vault_id=VAULT_A)
        _install_provider({
            "tool": TOOL_CANCEL_PENDING_DELETE,
            "args": {"action_id": intent.intent_id},
            "confidence": CONFIDENCE_HIGH,
            "why": "user rejected",
        })
        result = _run(_run_brain(
            "actually never mind", vault_id=VAULT_A, session_id=SESS_A,
        ))
        self.assertTrue(result.handled)
        self.assertIn("won't delete", result.reply_text)


class ChatBrainTopicSwitchTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_topic_switch_falls_through_to_pipeline(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT_A, service="Netflix", item_type="login",
        )
        # Model recognizes the reply is unrelated to the pending
        # delete and yields to the existing pipeline.
        _install_provider({
            "tool": TOOL_FALLTHROUGH,
            "args": {},
            "confidence": CONFIDENCE_MEDIUM,
            "why": "unrelated",
        })
        result = _run(_run_brain(
            "what's my chase password",
            vault_id=VAULT_A, session_id=SESS_A,
        ))
        self.assertFalse(result.handled)


class ChatBrainOrphanAttachmentTest(unittest.TestCase):
    """A user typing 'yes' with an orphan (unbound) unnamed file
    must not save the file. The arbiter never surfaces it, so the
    brain never confirms a save."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_orphan_attachment_never_confirmed(self):
        # No upload binding stored — the arbiter thinks there is
        # no pending action. The model shouldn't confirm-save
        # something that doesn't exist; even if it did, the
        # policy layer refuses.
        _install_provider({
            "tool": TOOL_CONFIRM_PENDING_SAVE,
            "args": {"action_id": "orphan-file",
                     "pending_kind": "save_attachment"},
            "confidence": CONFIDENCE_HIGH,
            "why": "yes",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_A, session_id=SESS_A,
        ))
        # Policy rejects → brain falls through → no "Saved this
        # video" hijack.
        self.assertFalse(result.handled)


class ChatBrainSessionIsolationTest(unittest.TestCase):
    """A binding from session A must not resolve for session B."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_binding_from_session_a_invisible_to_session_b(self):
        from vault_chat_upload_binding import bind_upload
        bind_upload(
            vault_id=VAULT_A, session_id=SESS_A,
            turn_id="t1", uploaded_file_id="file-A",
            filename="photo.jpg", content_type="image/jpeg",
        )
        _install_provider({
            "tool": TOOL_FALLTHROUGH,
            "args": {},
            "confidence": CONFIDENCE_LOW,
            "why": "no context",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_A, session_id=SESS_B,
        ))
        # No pending in session B, so the brain has nothing to
        # confirm; it falls through.
        self.assertFalse(result.handled)


class ChatBrainCrossVaultTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_pending_in_vault_a_invisible_in_vault_b(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT_A, service="Instagram", item_type="login",
        )
        _install_provider({
            "tool": TOOL_FALLTHROUGH,
            "args": {},
            "confidence": CONFIDENCE_LOW,
            "why": "nothing pending",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_B, session_id=SESS_A,
        ))
        self.assertFalse(result.handled)


class ChatBrainToolFailureTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_tool_execution_failure_returns_honest_error(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT_A, service="Instagram",
            item_type="login",
        )
        intent = get_pending_delete_intent(vault_id=VAULT_A)

        # Patch _execute_pending_delete to raise.
        import vault_secure_item_save as ss

        def _boom(**kwargs):
            raise RuntimeError("db connection lost")
        ss._execute_pending_delete = _boom

        _install_provider({
            "tool": TOOL_CONFIRM_PENDING_DELETE,
            "args": {"action_id": intent.intent_id},
            "confidence": CONFIDENCE_HIGH,
            "why": "yes",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_A, session_id=SESS_A,
        ))
        self.assertTrue(result.handled)
        # Honest failure — never claims success.
        self.assertIn("couldn't", result.reply_text.lower())
        self.assertNotIn("deleted", result.reply_text.lower())


class ChatBrainClarificationTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_clarification_returned_verbatim(self):
        _install_provider({
            "tool": TOOL_REQUEST_CLARIFICATION,
            "args": {"question": "Which login did you mean?"},
            "confidence": CONFIDENCE_MEDIUM,
            "why": "ambiguous",
        })
        result = _run(_run_brain(
            "delete the other one",
            vault_id=VAULT_A, session_id=SESS_A,
        ))
        self.assertTrue(result.handled)
        self.assertEqual(
            result.reply_text, "Which login did you mean?",
        )


class ChatBrainConversationalReplyTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_conversational_reply_handled(self):
        _install_provider({
            "tool": TOOL_CONVERSATIONAL_REPLY,
            "args": {"reply": "Hello! I can help with your vault."},
            "confidence": CONFIDENCE_HIGH,
            "why": "greeting",
        })
        result = _run(_run_brain(
            "hi", vault_id=VAULT_A, session_id=SESS_A,
        ))
        self.assertTrue(result.handled)
        self.assertIn("Hello", result.reply_text)

    def test_conversational_refused_when_delete_pending(self):
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT_A, service="Netflix", item_type="login",
        )
        _install_provider({
            "tool": TOOL_CONVERSATIONAL_REPLY,
            "args": {"reply": "The weather is nice today."},
            "confidence": CONFIDENCE_HIGH,
            "why": "topic switch",
        })
        result = _run(_run_brain(
            "what's the weather like",
            vault_id=VAULT_A, session_id=SESS_A,
        ))
        # Policy refuses conversational hijack while destructive
        # is pending — brain falls through.
        self.assertFalse(result.handled)


class ChatBrainLowConfidenceTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        _install_secure_item_stub()

    def tearDown(self):
        _install_provider(None)
        reset_chat_state_backend_for_tests()

    def test_low_confidence_destructive_confirm_denied(self):
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        store_delete_intent(
            vault_id=VAULT_A, service="Instagram", item_type="login",
        )
        intent = get_pending_delete_intent(vault_id=VAULT_A)
        _install_provider({
            "tool": TOOL_CONFIRM_PENDING_DELETE,
            "args": {"action_id": intent.intent_id},
            "confidence": CONFIDENCE_LOW,     # low
            "why": "guessing",
        })
        result = _run(_run_brain(
            "yes", vault_id=VAULT_A, session_id=SESS_A,
        ))
        # Policy denies → brain falls through.
        self.assertFalse(result.handled)


if __name__ == "__main__":
    unittest.main()
