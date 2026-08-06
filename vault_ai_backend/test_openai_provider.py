

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import os
import re
import unittest
from unittest import mock

from vault_ai_provider import (
    ChatCompletionResult,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_OPENAI,
    PROVIDERS,
    ProviderConfigurationError,
    active_fallback_provider_name,
    active_provider_name,
    chat_complete_with_fallback,
    get_chat_client,
    get_chat_client_sync,
    is_valid_provider,
    check_provider_readiness,
    safe_provider_error_category,
    safe_provider_request_id,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class ClosedSetProviderTests(unittest.TestCase):
    def test_only_openai_is_in_the_closed_set(self):
        self.assertEqual(PROVIDERS, (PROVIDER_OPENAI,))
        self.assertEqual(PROVIDER_OPENAI, "openai")

    def test_is_valid_provider_accepts_openai(self):
        self.assertTrue(is_valid_provider(PROVIDER_OPENAI))

    def test_is_valid_provider_rejects_everything_else(self):
        for v in ("hermes", "vendor_x", "", None, 0, ["openai"]):
            self.assertFalse(is_valid_provider(v))

    def test_active_provider_is_always_openai(self):
        self.assertEqual(active_provider_name(), PROVIDER_OPENAI)
        self.assertEqual(active_fallback_provider_name(), PROVIDER_OPENAI)


class ClientConstructionTests(unittest.TestCase):
    def setUp(self):
        self._prev_key = os.environ.get("OPENAI_API_KEY")

    def tearDown(self):
        if self._prev_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._prev_key

    def test_openai_client_constructs_with_key(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        client = get_chat_client()
        self.assertIsNotNone(client)

    def test_openai_client_raises_without_key(self):
        os.environ.pop("OPENAI_API_KEY", None)
        with self.assertRaises(ProviderConfigurationError):
            get_chat_client()

    def test_explicit_unknown_provider_rejected(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        for v in ("hermes", "vendor_x", "nous"):
            with self.subTest(v=v):
                with self.assertRaises(ProviderConfigurationError):
                    get_chat_client(provider=v)

    def test_sync_client_factory_constructs(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        client = get_chat_client_sync()
        self.assertIsNotNone(client)

    def test_sync_client_factory_rejects_unknown_provider(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        with self.assertRaises(ProviderConfigurationError):
            get_chat_client_sync(provider="hermes")


class ChatCompletionResultShapeTests(unittest.TestCase):
    def test_to_dict_does_not_leak_content(self):
        r = ChatCompletionResult(
            provider_used="openai",
            model="gpt-4o-mini",
            content="this would leak the response if to_dict were naive",
            finish_reason="stop",
        )
        d = r.to_dict()
                                             
        self.assertEqual(d["provider_used"], "openai")
        self.assertEqual(d["model"], "gpt-4o-mini")
        self.assertEqual(d["finish_reason"], "stop")
        self.assertEqual(d["used_fallback"], False)
                                                
        self.assertIn("content_len", d)
        self.assertNotIn("content", d)
        self.assertNotIn("messages", d)
        for v in d.values():
            self.assertNotIn(
                "leak the response", str(v),
                "to_dict() must NEVER include the response content",
            )


class ChatCompleteTests(unittest.TestCase):
    def setUp(self):
        self._prev_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"

    def tearDown(self):
        if self._prev_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._prev_key

    def test_chat_complete_returns_typed_result(self):
                                                                
        fake_response = mock.MagicMock()
        fake_response.choices = [
            mock.MagicMock(
                message=mock.MagicMock(content="hi from the vault"),
                finish_reason="stop",
            )
        ]
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_response,
        )
        with mock.patch(
            "vault_ai_provider.get_chat_client",
            return_value=fake_client,
        ):
            result = _run(chat_complete_with_fallback(
                messages=[{"role": "user", "content": "hello"}],
                model="gpt-4o-mini",
            ))
        self.assertIsInstance(result, ChatCompletionResult)
        self.assertEqual(result.provider_used, "openai")
        self.assertEqual(result.model, "gpt-4o-mini")
        self.assertEqual(result.content, "hi from the vault")
        self.assertEqual(result.finish_reason, "stop")
        self.assertFalse(result.used_fallback)


class ProviderReadinessTests(unittest.TestCase):
    def setUp(self):
        self._prev_key = os.environ.get("OPENAI_API_KEY")

    def tearDown(self):
        if self._prev_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._prev_key

    def test_missing_credential_is_reported_without_a_probe(self):
        os.environ.pop("OPENAI_API_KEY", None)
        result = _run(check_provider_readiness(model="gpt-test"))
        self.assertFalse(result.credential_present)
        self.assertEqual(result.provider_authentication_status, "not_configured")
        self.assertNotIn("key", result.to_dict())

    def test_successful_metadata_probe_sends_no_prompt(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        client = mock.MagicMock()
        client.models.retrieve = mock.AsyncMock(return_value=object())
        client.chat.completions.create = mock.AsyncMock(return_value=object())
        with mock.patch("vault_ai_provider.get_chat_client", return_value=client):
            result = _run(check_provider_readiness(model="gpt-test"))
        client.models.retrieve.assert_awaited_once_with("gpt-test")
        self.assertEqual(client.chat.completions.create.await_count, 1)
        self.assertTrue(result.provider_reachable)
        self.assertEqual(result.billing_rate_limit_category, "ready")

    def test_billing_inactive_is_distinct_and_request_id_is_safe(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
        exc = RuntimeError("secret provider message")
        exc.status_code = 429
        exc.body = {"error": {"code": "billing_not_active"}}
        exc.request_id = "req_safe_123"
        client = mock.MagicMock()
        client.models.retrieve = mock.AsyncMock(return_value=object())
        client.chat.completions.create = mock.AsyncMock(side_effect=exc)
        with mock.patch("vault_ai_provider.get_chat_client", return_value=client):
            result = _run(check_provider_readiness(model="gpt-test"))
        self.assertEqual(result.billing_rate_limit_category,
                         "provider_billing_inactive")
        self.assertEqual(result.request_id, "req_safe_123")
        self.assertNotIn("secret provider message", str(result.to_dict()))

    def test_closed_error_categories(self):
        cases = (
            (401, {}, "provider_authentication"),
            (429, {}, "provider_rate_limit"),
            (404, {}, "provider_unsupported_model"),
            (500, {}, "provider_unavailable"),
        )
        for status, body, expected in cases:
            exc = RuntimeError("must remain private")
            exc.status_code = status
            exc.body = body
            self.assertEqual(safe_provider_error_category(exc), expected)

    def test_timeout_and_header_request_id(self):
        exc = TimeoutError("private")
        exc.response = mock.MagicMock(headers={"x-request-id": "req_header"})
        self.assertEqual(safe_provider_error_category(exc), "provider_timeout")
        self.assertEqual(safe_provider_request_id(exc), "req_header")


class SourceGuardTests(unittest.TestCase):
    def test_provider_module_has_no_hermes_references(self):
        with open("vault_ai_provider.py", "r", encoding="utf-8") as f:
            src = f.read()
        for needle in (
            "PROVIDER_HERMES",
            "hermes_chat_model",
            "hermes_intent_model",
            "hermes_base_url",
            "hermes_api_key_env",
            "NOUS_API_KEY",
            "_hermes_client",
            "nousresearch",
        ):
            self.assertNotIn(needle, src, f"vault_ai_provider.py must "
                             f"not contain {needle!r}")

    def test_module_only_owns_async_openai_construction(self):
        with open("vault_ai_provider.py", "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("AsyncOpenAI(", src)


if __name__ == "__main__":
    unittest.main()
