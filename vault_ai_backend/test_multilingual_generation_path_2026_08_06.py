"""Production-shaped multilingual generation regressions.

The live layer is opt-in and never prints prompts or model output.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from vault_ai_provider import (
    chat_complete_with_fallback,
    completion_token_limit_kwargs,
    safe_provider_error_category,
)
from vault_chat_general_router import route_general_chat
from vault_chat_safety_sanitizer import localized_general_response_failed
from vault_multilingual import detect_language, detect_requested_language


LANGUAGE_NAMES = (
    "English", "Spanish", "French", "German", "Italian", "Portuguese",
    "Brazilian Portuguese", "Dutch", "Polish", "Romanian", "Russian",
    "Ukrainian", "Greek", "Turkish", "Arabic", "Hebrew", "Persian",
    "Farsi", "Urdu", "Hindi", "Bengali", "Punjabi", "Tamil", "Telugu",
    "Marathi", "Gujarati", "Nepali", "Sinhala", "Chinese", "Mandarin",
    "Japanese", "Korean", "Thai", "Vietnamese", "Indonesian", "Malay",
    "Tagalog", "Filipino", "Somali", "Swahili", "Amharic", "Hausa",
    "Yoruba", "Igbo", "Zulu", "Afrikaans",
)


@pytest.mark.parametrize("language_name", LANGUAGE_NAMES)
def test_general_language_matrix_is_model_generated_and_tool_free(language_name):
    message = f"Please reply in {language_name}"
    assert detect_requested_language(message)
    route = route_general_chat(message)
    assert route is not None
    assert route.model_response_required is True
    assert route.response == ""


@pytest.mark.parametrize("message,expected", (
    ("what can you do in Somali", "so"),
    ("tell me about yourself in Tagalog", "tl"),
    ("tell me about yourself in Filipino", "tl"),
    ("explain SVaultAI in French", "fr"),
    ("reply in Arabic", "ar"),
    ("answer in Brazilian Portuguese", "pt"),
    ("respond in Mandarin", "zh"),
    ("reply in Farsi", "fa"),
))
def test_explicit_language_survives_into_general_route(message, expected):
    route = route_general_chat(message)
    assert route is not None
    assert route.language == expected
    assert route.requested_language is True
    assert route.model_response_required is True


def test_general_generation_prompt_pins_resolved_language_and_correlation():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "response_language=_general_route.language" in source
    assert "language overrides browser locale and English defaults" in source
    assert "correlation_id=str(_chat_request_id or \"\")" in source
    assert "[CHAT-PROVIDER] generation_failed category=%s" in source


@pytest.mark.parametrize("model,key", (
    ("gpt-4o-mini", "max_tokens"),
    ("gpt-5-mini", "max_completion_tokens"),
    ("o3-mini", "max_completion_tokens"),
))
def test_provider_uses_model_compatible_token_limit(model, key):
    assert completion_token_limit_kwargs(model, 321) == {key: 321}


@pytest.mark.parametrize("status,name,expected", (
    (401, "SyntheticError", "provider_authentication"),
    (429, "SyntheticError", "provider_rate_limit"),
    (404, "SyntheticError", "provider_unsupported_model"),
    (400, "SyntheticError", "provider_bad_request"),
))
def test_provider_errors_are_safely_categorized(status, name, expected):
    error_type = type(name, (RuntimeError,), {})
    exc = error_type("details must not be logged")
    exc.status_code = status
    assert safe_provider_error_category(exc) == expected


@pytest.mark.parametrize("language,needle", (
    ("tl", "Tagalog"), ("fr", "français"), ("ar", "العربية"),
    ("so", "Af-Soomaali"), ("es", "español"), ("ja", "日本語"),
    ("hi", "हिंदी"), ("sw", "Kiswahili"), ("fa", "فارسی"),
))
def test_generation_failure_is_neutral_and_localized(language, needle):
    result = localized_general_response_failed(language)
    assert needle in result
    assert "search" not in result.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("output", (
    "Kumusta! Ako ang SvaultAI.",
    "Je suis SvaultAI, votre assistant.",
    "أنا SvaultAI، مساعدك الآمن.",
    "私はSvaultAIです。",
))
async def test_tool_free_stream_preserves_unicode_model_output(monkeypatch, output):
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test",
    )
    os.environ.setdefault("OPENAI_API_KEY", "test-key-not-a-secret")
    os.environ.setdefault("VAULTAI_ENV", "development")
    import main
    import vault_ai_provider

    class _Stream:
        def __aiter__(self):
            self._done = False
            return self

        async def __anext__(self):
            if self._done:
                raise StopAsyncIteration
            self._done = True
            delta = SimpleNamespace(content=output, tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    class _Completions:
        async def create(self, **kwargs):
            assert "tools" not in kwargs
            assert "tool_choice" not in kwargs
            return _Stream()

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions()),
    )
    monkeypatch.setattr(vault_ai_provider, "get_chat_client", lambda: client)
    chunks = []
    async for chunk in main.ai_stream(
        [{"role": "user", "content": "safe general chat"}],
        "vault-test", b"key", last_user_message="safe general chat",
        force_no_tools=True, correlation_id="safe-test-id",
    ):
        chunks.append(chunk.decode("utf-8"))
    assert "".join(chunks) == output


_LIVE_CASES = (
    ("fr", "Répondez brièvement en français."),
    ("ar", "أجب بإيجاز باللغة العربية."),
    ("ja", "日本語で短く答えてください。"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_language,prompt", _LIVE_CASES)
async def test_live_configured_provider_generates_requested_language(
    expected_language, prompt,
):
    if os.getenv("VAULTAI_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("set VAULTAI_RUN_LIVE_PROVIDER_TESTS=1 explicitly")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("live provider credential absent")
    result = await chat_complete_with_fallback(
        messages=[
            {"role": "system", "content": "Return one short sentence."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=80,
    )
    assert result.content.strip()
    assert detect_language(result.content) == expected_language
