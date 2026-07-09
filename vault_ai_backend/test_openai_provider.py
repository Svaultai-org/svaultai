

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
