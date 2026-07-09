

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI


logger = logging.getLogger(__name__)


PROVIDER_OPENAI: str = "openai"

PROVIDERS: tuple[str, ...] = (PROVIDER_OPENAI,)


DEFAULT_TIMEOUT_SECONDS: float = 60.0
DEFAULT_MAX_RETRIES: int = 2


class ProviderConfigurationError(RuntimeError):
    pass


def is_valid_provider(name: Any) -> bool:
    return isinstance(name, str) and name in PROVIDERS


def active_provider_name() -> str:


    return PROVIDER_OPENAI


def active_fallback_provider_name() -> str:

    return PROVIDER_OPENAI


def _openai_client(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> AsyncOpenAI:


    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderConfigurationError(
            "OpenAI provider selected but OPENAI_API_KEY is not set"
        )
    return AsyncOpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
    )


def get_chat_client(
    provider: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> AsyncOpenAI:


    if provider is not None and provider != PROVIDER_OPENAI:
        raise ProviderConfigurationError(
            f"unsupported provider {provider!r}; only "
            f"{PROVIDER_OPENAI!r} is supported"
        )
    return _openai_client(timeout=timeout, max_retries=max_retries)


@dataclass(frozen=True)
class ChatCompletionResult:


    provider_used: str
    model:         str
    content:       str
    finish_reason: Optional[str] = None
    used_fallback: bool = False

    def to_dict(self) -> dict:


        return {
            "provider_used": str(self.provider_used),
            "model":         str(self.model),
            "finish_reason": str(self.finish_reason or ""),
            "used_fallback": bool(self.used_fallback),
            "content_len":   len(self.content or ""),
        }


async def chat_complete_with_fallback(
    *,
    messages: list[dict],
    model: Optional[str] = None,
    model_kind: str = "chat",
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ChatCompletionResult:


    resolved_model = model if model is not None else \
        _resolve_model_name(model_kind)
    return await _do_chat_complete(
        model=resolved_model,
        messages=messages,
        temperature=temperature, max_tokens=max_tokens,
        response_format=response_format, timeout=timeout,
    )


def _resolve_model_name(model_kind: str) -> str:

    from vault_config import ai as _ai_cfg
    cfg = _ai_cfg()
    if model_kind == "chat":
        return cfg.openai_chat_model
    if model_kind == "intent":
        return cfg.openai_intent_model
    raise ValueError(
        f"unknown model_kind {model_kind!r} "
        "(expected 'chat' or 'intent')"
    )


async def _do_chat_complete(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: Optional[int],
    response_format: Optional[dict],
    timeout: float,
) -> ChatCompletionResult:


    client = get_chat_client(timeout=timeout)
    kwargs: dict = {
        "model":    model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = int(max_tokens)
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = await client.chat.completions.create(**kwargs)
    content = (response.choices[0].message.content or "")
    finish = getattr(response.choices[0], "finish_reason", None)
    return ChatCompletionResult(
        provider_used=PROVIDER_OPENAI,
        model=model,
        content=content,
        finish_reason=str(finish) if finish else None,
        used_fallback=False,
    )


def get_chat_client_sync(
    provider: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
):


    if provider is not None and provider != PROVIDER_OPENAI:
        raise ProviderConfigurationError(
            f"unsupported provider {provider!r}; only "
            f"{PROVIDER_OPENAI!r} is supported"
        )
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderConfigurationError(
            "OpenAI provider selected but OPENAI_API_KEY is not set"
        )
    return OpenAI(api_key=api_key, timeout=timeout)


__all__ = [
                
    "PROVIDER_OPENAI",
    "PROVIDERS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
             
    "ProviderConfigurationError",
                 
    "is_valid_provider",
    "active_provider_name",
    "active_fallback_provider_name",
                       
    "get_chat_client",
    "get_chat_client_sync",
                            
    "ChatCompletionResult",
    "chat_complete_with_fallback",
]
