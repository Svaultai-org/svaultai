"""Regression tests for ``vault_chat_semantic_decider``.

Model calls are stubbed via a callable ``ai_provider`` argument so
tests are deterministic and cost-free.

Covers:
    * healthy JSON response → validated Decision
    * malformed JSON → fallthrough
    * timeout → fallthrough
    * transport error → fallthrough
    * unknown tool name → fallthrough
    * args_schema mismatch → fallthrough
    * low confidence still parses, policy decides what to do
    * fast-path skips model call on trivial empty input
"""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import dataclass
from typing import Any, Optional

from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_NONE,
    KIND_SAVE_ATTACHMENT,
    PendingAction,
)
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Decision,
    decide,
)
from vault_chat_tool_registry import (
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_SAVE,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)
from vault_chat_turn_snapshot import TurnSnapshot


VAULT = "vault-decider-test"
SESSION = "session-1"


def _pending_delete(action_id: str = "delete-abc") -> PendingAction:
    return PendingAction(
        kind=KIND_DELETE_SECURE_ITEM,
        action_id=action_id,
        source_kind="secure_delete_intent",
        target_label="Instagram login",
        created_at=1_700_000_000.0,
        expires_at=1_700_000_600.0,
        vault_id=VAULT,
        session_id=None,
        is_destructive=True,
        metadata={"item_type": "login"},
    )


def _snapshot(user_msg: str, pending: Optional[PendingAction] = None) -> TurnSnapshot:
    from vault_chat_pending_action import NONE_PENDING
    return TurnSnapshot(
        vault_id=VAULT,
        session_id=SESSION,
        turn_id="t-1",
        vault_name="Personal",
        reply_language="en",
        user_message=user_msg,
        now=1_700_000_000.0,
        pending_action=(pending or NONE_PENDING),
        active_entity=None,
        recent_turns=(),
        tool_names=(TOOL_FALLTHROUGH, TOOL_CONFIRM_PENDING_DELETE),
        unlocked=True,
        user_tier="free",
        features={},
    )


class _StubResult:
    def __init__(self, content: str):
        self.content = content


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_provider(payload):
    """Build an async ai_provider callable that returns ``payload``
    (dict, str, or raises depending on shape)."""
    async def provider(**kwargs):
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, dict):
            return _StubResult(json.dumps(payload))
        return _StubResult(str(payload))
    return provider


class TestHealthyResponses(unittest.TestCase):

    def test_confirm_delete_high_confidence_parses(self):
        payload = {
            "tool": TOOL_CONFIRM_PENDING_DELETE,
            "args": {"action_id": "delete-abc"},
            "confidence": CONFIDENCE_HIGH,
            "why": "user said yes",
        }
        snap = _snapshot("yes", pending=_pending_delete())
        decision = _run(decide(
            snap, ai_provider=_make_provider(payload),
        ))
        self.assertEqual(decision.tool, TOOL_CONFIRM_PENDING_DELETE)
        self.assertEqual(decision.confidence, CONFIDENCE_HIGH)
        self.assertEqual(decision.args["action_id"], "delete-abc")

    def test_clarification_medium_confidence_parses(self):
        payload = {
            "tool": TOOL_REQUEST_CLARIFICATION,
            "args": {"question": "Which login did you mean?"},
            "confidence": CONFIDENCE_MEDIUM,
            "why": "ambiguous",
        }
        snap = _snapshot("delete the other one")
        decision = _run(decide(
            snap, ai_provider=_make_provider(payload),
        ))
        self.assertEqual(decision.tool, TOOL_REQUEST_CLARIFICATION)
        self.assertEqual(
            decision.args["question"], "Which login did you mean?",
        )


class TestParserFailures(unittest.TestCase):

    def test_malformed_json_falls_through(self):
        provider = _make_provider("not valid json at all {")
        snap = _snapshot("hi")
        decision = _run(decide(snap, ai_provider=provider))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertIn("json_parse_failed", decision.error)

    def test_wrapped_code_fence_recovers(self):
        payload = {
            "tool": TOOL_FALLTHROUGH,
            "args": {},
            "confidence": CONFIDENCE_LOW,
            "why": "delegating",
        }
        wrapped = "```json\n" + json.dumps(payload) + "\n```"
        async def provider(**kwargs):
            return _StubResult(wrapped)
        snap = _snapshot("what is the weather")
        decision = _run(decide(snap, ai_provider=provider))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertEqual(decision.error, "")

    def test_unknown_tool_name_falls_through(self):
        payload = {
            "tool": "invent_tool_that_doesnt_exist",
            "args": {},
            "confidence": CONFIDENCE_HIGH,
            "why": "made up",
        }
        snap = _snapshot("hi", pending=_pending_delete())
        decision = _run(decide(snap, ai_provider=_make_provider(payload)))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertIn("unknown_tool", decision.error)

    def test_missing_args_falls_through(self):
        payload = {
            "tool": TOOL_CONFIRM_PENDING_DELETE,
            "args": {},                                # missing action_id
            "confidence": CONFIDENCE_HIGH,
            "why": "yes",
        }
        snap = _snapshot("yes", pending=_pending_delete())
        decision = _run(decide(snap, ai_provider=_make_provider(payload)))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertIn("args_schema", decision.error)


class TestTransportFailures(unittest.TestCase):

    def test_transport_error_falls_through(self):
        async def raiser(**kwargs):
            raise RuntimeError("simulated openai crash")
        snap = _snapshot("hi", pending=_pending_delete())
        decision = _run(decide(snap, ai_provider=raiser))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertIn("transport", decision.error)

    def test_timeout_falls_through(self):
        async def slow(**kwargs):
            await asyncio.sleep(5.0)
            return _StubResult("{}")
        snap = _snapshot("hi", pending=_pending_delete())
        decision = _run(decide(
            snap, ai_provider=slow, timeout_s=0.05,
        ))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertIn("timeout", decision.error)


class TestFastPath(unittest.TestCase):

    def test_no_pending_and_empty_message_skips_model(self):
        calls = {"n": 0}
        async def provider(**kwargs):
            calls["n"] += 1
            return _StubResult('{"tool": "fallthrough"}')
        snap = _snapshot("")     # empty message; no pending
        decision = _run(decide(snap, ai_provider=provider))
        self.assertEqual(decision.tool, TOOL_FALLTHROUGH)
        self.assertEqual(calls["n"], 0)


if __name__ == "__main__":
    unittest.main()
