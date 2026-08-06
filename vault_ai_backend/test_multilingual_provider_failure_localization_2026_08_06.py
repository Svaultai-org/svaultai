"""Provider failures stay friendly, localized, safe, and retrieval-free."""

from __future__ import annotations

import pytest

from vault_ai_provider import safe_provider_error_category
from vault_chat_safety_sanitizer import localized_general_response_failed
from vault_multilingual import (
    detect_requested_language,
    has_requested_language_directive,
)


@pytest.mark.parametrize("prompt,code,needle", (
    ("reply in Spanish", "es", "español"),
    ("reply in French", "fr", "français"),
    ("reply in Tagalog", "tl", "Tagalog"),
    ("reply in Filipino", "tl", "Tagalog"),
    ("reply in Arabic", "ar", "العربية"),
    ("reply in Somali", "so", "Af-Soomaali"),
    ("reply in Japanese", "ja", "日本語"),
    ("reply in Hindi", "hi", "हिंदी"),
    ("reply in Swahili", "sw", "Kiswahili"),
    ("reply in Persian", "fa", "فارسی"),
))
def test_trusted_language_failure_templates(prompt, code, needle):
    assert detect_requested_language(prompt) == code
    copy = localized_general_response_failed(code)
    assert needle in copy
    assert any(token in copy.lower() for token in ("english", "inglés", "anglais", "ingles", "ingiriisi", "kiingereza", "انگلیسی", "الإنجليزية", "英語", "अंग्रेज़ी"))


def test_unknown_language_directive_uses_safe_unknown_copy():
    prompt = "reply in Klingon"
    assert detect_requested_language(prompt) is None
    assert has_requested_language_directive(prompt)
    copy = localized_general_response_failed("unknown")
    assert copy == (
        "I'm sorry, I can't reply in the requested language right now. "
        "We can continue in English, you can try again in a moment, or cancel."
    )


@pytest.mark.parametrize("status,code,expected", (
    (429, "billing_not_active", "provider_billing_inactive"),
    (429, "insufficient_quota", "provider_quota_exhausted"),
    (429, "rate_limit_exceeded", "provider_rate_limit"),
    (404, "model_not_found", "provider_unsupported_model"),
    (500, "internal_error", "provider_unavailable"),
))
def test_provider_categories_are_safe(status, code, expected):
    exc = RuntimeError("secret provider detail")
    exc.status_code = status
    exc.code = code
    assert safe_provider_error_category(exc) == expected


@pytest.mark.parametrize("name,expected", (
    ("TimeoutError", "provider_timeout"),
    ("APIConnectionError", "provider_unavailable"),
))
def test_transport_categories_are_safe(name, expected):
    exc = type(name, (RuntimeError,), {})("secret provider detail")
    assert safe_provider_error_category(exc) == expected


@pytest.mark.parametrize("code", ("es", "fr", "tl", "ar", "so", "ja", "hi", "sw", "fa", "unknown"))
def test_failure_copy_exposes_no_provider_diagnostics(code):
    lowered = localized_general_response_failed(code).lower()
    for forbidden in (
        "billing", "quota", "credit", "api key", "gpt-", "request id",
        "openai", "provider", "search",
    ):
        assert forbidden not in lowered


def test_failure_copy_offers_retry_english_and_cancel():
    english = localized_general_response_failed("unknown").lower()
    assert "continue in english" in english
    assert "try again" in english
    assert "cancel" in english
