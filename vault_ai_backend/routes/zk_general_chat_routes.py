"""PIN-free general chat for a ZK vault.

This endpoint has no vault-data tools. The client resolves saved-item and file
lookups locally from already decrypted metadata. Only user-authored general
conversation text is sent to the AI provider. The route is opt-in and does
not replace the legacy encrypted /chat pipeline.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from rate_limit_sensitive import enforce_chat_rate_limit
from vault_ai_provider import chat_complete_with_fallback


logger = logging.getLogger(__name__)
router = APIRouter()

_SYSTEM = (
    "You are SVaultAI's general chat assistant. You have no access to this "
    "person's vault, saved items, files, photos, recordings, or account "
    "secrets. Answer general questions and follow-up questions from the "
    "conversation. Never claim you searched or changed vault content. If "
    "asked about private vault content, say the app must search it locally."
)


def _enabled() -> bool:
    return os.getenv("VAULTAI_ZK_GENERAL_CHAT_ENABLED", "false").strip().lower() == "true"


class GeneralTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ZkGeneralChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    history: list[GeneralTurn] = Field(default_factory=list, max_length=12)


class ZkGeneralChatResponse(BaseModel):
    reply: str
    mode: Literal["general"] = "general"


@router.post("/chat/zk/general", response_model=ZkGeneralChatResponse)
async def zk_general_chat(
    payload: ZkGeneralChatRequest,
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> ZkGeneralChatResponse:
    if not _enabled():
        raise HTTPException(status_code=404, detail="zk_general_chat_disabled")
    enforce_chat_rate_limit(request, vault_id=principal["vault_id"])
    messages = [
        {"role": "system", "content": _SYSTEM},
        *[turn.model_dump() for turn in payload.history],
        {"role": "user", "content": payload.message},
    ]
    try:
        result = await chat_complete_with_fallback(
            messages=messages, model_kind="chat", temperature=0.2,
            max_tokens=512, timeout=30,
        )
    except Exception as exc:
        logger.warning("ZK general chat unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Chat is temporarily unavailable",
        ) from None
    reply = result.content.strip()
    if not reply:
        raise HTTPException(status_code=503, detail="Chat is temporarily unavailable")
    return ZkGeneralChatResponse(reply=reply)
