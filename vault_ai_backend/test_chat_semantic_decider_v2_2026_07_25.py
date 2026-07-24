"""Tests for the SemanticDeciderV2 prompt contract and async
``decide_v2`` function.

Uses a deterministic mock provider — no live LLM calls in CI.
The mock returns a caller-configured JSON string; the tests
assert that ``decide_v2`` parses it into a validated
``SemanticDecisionV2`` (or a fallthrough on any failure).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Optional

import vault_chat_semantic_decider_v2 as sdd
import vault_chat_semantic_decision_v2 as sd


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ctx(user_message="hi", known_target_ids=frozenset()):
    return sdd.SemanticDecisionV2Context(
        vault_id="vault-decider-test",
        session_id="sess-decider-test",
        user_message=user_message,
        active_drafts=(),
        pending_actions=(),
        focus=None,
        recent_turns=(),
        conversation_digest="",
        known_target_ids=known_target_ids,
    )


class _MockResult:
    def __init__(self, content: str):
        self.content = content


def _make_provider(content: str):
    async def _p(**_kwargs):
        return _MockResult(content=content)
    return _p


def _timeout_provider():
    async def _p(**_kwargs):
        await asyncio.sleep(10.0)
        return _MockResult(content="never")
    return _p


def _raising_provider(exc: Exception):
    async def _p(**_kwargs):
        raise exc
    return _p


def _valid_dict(**overrides):
    base = {
        "schema_version": sd.SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        "intent":         sd.INTENT_CHAT,
        "target":         {"kind": sd.TARGET_KIND_NONE, "id": None},
        "field_patch":    {},
        "requested_operations": [],
        "authorization":  {"granted": False},
        "confidence":     0.95,
        "reason":         "greeting",
    }
    base.update(overrides)
    return base


# =====================================================================
# Prompt contract
# =====================================================================

class PromptContractTest(unittest.TestCase):

    def test_prompt_shape_is_system_plus_user(self):
        messages = sdd.build_prompt_v2(_ctx())
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")

    def test_user_payload_carries_snapshot(self):
        messages = sdd.build_prompt_v2(_ctx(user_message="hello there"))
        user_payload = json.loads(messages[1]["content"])
        self.assertIn("snapshot", user_payload)
        self.assertEqual(
            user_payload["snapshot"]["user_message"], "hello there",
        )

    def test_system_prompt_mentions_schema_version(self):
        messages = sdd.build_prompt_v2(_ctx())
        system = messages[0]["content"]
        self.assertIn(
            str(sd.SEMANTIC_DECISION_V2_SCHEMA_VERSION), system,
        )

    def test_system_prompt_lists_all_intents(self):
        messages = sdd.build_prompt_v2(_ctx())
        system = messages[0]["content"]
        for intent in sd.INTENTS:
            with self.subTest(intent=intent):
                self.assertIn(intent, system)

    def test_prompt_does_not_leak_user_message_into_system(self):
        messages = sdd.build_prompt_v2(
            _ctx(user_message="my password is TotallyReal99!"),
        )
        self.assertNotIn(
            "TotallyReal99!", messages[0]["content"],
        )
        # It DOES appear in the user message (the point of the prompt),
        # but confirm the flow: system is a rendered template only.
        self.assertIn("TotallyReal99!", messages[1]["content"])


# =====================================================================
# decide_v2 — happy paths
# =====================================================================

class DecideHappyPathTest(unittest.TestCase):

    def test_valid_response_parses_ok(self):
        provider = _make_provider(json.dumps(_valid_dict()))
        r = _run(sdd.decide_v2(_ctx(), ai_provider=provider))
        self.assertEqual(r.intent, sd.INTENT_CHAT)
        self.assertFalse(r.is_fallthrough())
        self.assertEqual(r.error, "")

    def test_known_target_ids_flow_through(self):
        provider = _make_provider(json.dumps(_valid_dict(
            intent=sd.INTENT_EDIT_DRAFT,
            target={"kind": "draft", "id": "d-1"},
            field_patch={"username": {
                "op": "replace", "value": "alice@example.org",
            }},
            reason="user changed the username",
        )))
        r = _run(sdd.decide_v2(
            _ctx(known_target_ids=frozenset({"d-1"})),
            ai_provider=provider,
        ))
        self.assertEqual(r.intent, sd.INTENT_EDIT_DRAFT)
        self.assertEqual(r.target.id, "d-1")


# =====================================================================
# decide_v2 — failure paths
# =====================================================================

class DecideFailurePathTest(unittest.TestCase):

    def test_empty_content_fallthrough(self):
        r = _run(sdd.decide_v2(_ctx(),
                               ai_provider=_make_provider("")))
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "empty_content")

    def test_non_json_fallthrough(self):
        r = _run(sdd.decide_v2(_ctx(),
                               ai_provider=_make_provider("not json")))
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "json_parse_failed")

    def test_unknown_intent_fallthrough(self):
        r = _run(sdd.decide_v2(_ctx(), ai_provider=_make_provider(
            json.dumps(_valid_dict(intent="explode")),
        )))
        self.assertTrue(r.is_fallthrough())
        self.assertTrue(r.error.startswith("unknown_intent"))

    def test_unknown_target_id_fallthrough(self):
        r = _run(sdd.decide_v2(
            _ctx(known_target_ids=frozenset({"d-1"})),
            ai_provider=_make_provider(json.dumps(_valid_dict(
                intent=sd.INTENT_EDIT_DRAFT,
                target={"kind": "draft", "id": "d-NEVER-SEEN"},
                field_patch={"username": {
                    "op": "replace", "value": "x@y.z",
                }},
                reason="the model made this id up",
            ))),
        ))
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "unknown_target_id")

    def test_transport_error_fallthrough(self):
        r = _run(sdd.decide_v2(
            _ctx(),
            ai_provider=_raising_provider(RuntimeError("network")),
        ))
        self.assertTrue(r.is_fallthrough())
        self.assertTrue(r.error.startswith("transport:"))

    def test_timeout_fallthrough(self):
        # decide_v2's inner wait_for uses to+2.0 as the wait; we
        # pass a tiny timeout so the sleeping provider fires the
        # timeout path quickly.
        r = _run(sdd.decide_v2(
            _ctx(),
            ai_provider=_timeout_provider(),
            timeout_s=0.05,
        ))
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "timeout")

    def test_bad_confidence_fallthrough(self):
        r = _run(sdd.decide_v2(_ctx(), ai_provider=_make_provider(
            json.dumps(_valid_dict(confidence=2.0)),
        )))
        self.assertTrue(r.is_fallthrough())
        self.assertTrue(r.error.startswith("invalid_confidence"))

    def test_authorization_scope_mismatch_fallthrough(self):
        r = _run(sdd.decide_v2(_ctx(), ai_provider=_make_provider(
            json.dumps(_valid_dict(
                intent=sd.INTENT_CONFIRM_DRAFT,
                target={"kind": "draft", "id": "d-1"},
                authorization={
                    "granted": True,
                    "scope": {"target_id": "d-DIFFERENT",
                              "action": "save"},
                },
                reason="looks good",
            )),
        )))
        self.assertTrue(r.is_fallthrough())
        self.assertTrue(
            "authorization_scope_target_id_mismatch" in r.error,
            f"unexpected error: {r.error!r}",
        )

    def test_bad_context_type_fallthrough(self):
        r = _run(sdd.decide_v2(
            "not a context",  # type: ignore[arg-type]
            ai_provider=_make_provider(json.dumps(_valid_dict())),
        ))
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "context_invalid")


# =====================================================================
# Provider is called with the right kwargs
# =====================================================================

class ProviderKwargsTest(unittest.TestCase):

    def test_provider_receives_expected_kwargs(self):
        captured: dict = {}

        async def _p(**kwargs):
            captured.update(kwargs)
            return _MockResult(content=json.dumps(_valid_dict()))

        _run(sdd.decide_v2(_ctx(), ai_provider=_p))

        self.assertIn("messages", captured)
        self.assertEqual(captured["model_kind"], "intent")
        self.assertEqual(captured["temperature"], 0.0)
        self.assertEqual(captured["max_tokens"], sdd.DECIDER_V2_MAX_TOKENS)
        self.assertEqual(
            captured["response_format"], {"type": "json_object"},
        )
        # timeout must be positive; defaults to DECIDER_V2_TIMEOUT_S
        self.assertGreater(captured["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
