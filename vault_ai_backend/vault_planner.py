

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional


logger = logging.getLogger(__name__)


PLANNER_INTENTS: tuple[str, ...] = (
    "capability_question",                               
    "identity_question",                                           
    "casual_chat",                                          
    "vault_summary",                                        
    "vault_activity",                                            
    "document_search",                                   
    "file_read",                                                 
    "media_read",                                             
    "credential_lookup",                                          
    "credential_creation_draft",                               
    "credential_save_confirmation",                  
    "expiry_check",                                      
    "entity_lookup",                                        
    "category_browse",                                         
    "unknown",                                          
)


_VALID_TOOL_NAMES: frozenset[str] = frozenset({
    "get_vault_status", "get_vault_overview", "get_vault_intelligence",
    "list_vault_files", "list_files_by_category",
    "list_document_categories",
    "search_extracted_text", "search_vault_content",
    "read_file_text", "read_image_with_vision",
    "read_media_transcript", "list_file_chunks", "read_file_chunk",
    "inspect_uploaded_file", "get_file_metadata",
    "list_vault_entities", "find_files_for_entity",
    "list_file_relationships",
    "list_expiring_items", "get_expiry_alert",
    "get_vault_activity",
    "list_saved_credentials", "get_credential_metadata",
    "list_secrets", "retrieve_secret", "save_secret",
    "generate_credential_draft",
    "save_generated_credential_after_confirmation",
    "find_in_vault",
})


@dataclass(frozen=True)
class PlannerDecision:
    intent: str
    needs_vault_search: bool
    needs_file_reading: bool
    needs_ocr_image_pdf_reading: bool
    needs_credential_action: bool
    is_simple_capability_question: bool
    needs_stronger_model: bool
    planned_tools: tuple[str, ...] = field(default_factory=tuple)
    reasoning: str = ""
    confidence: float = 0.0
    source: str = "planner"                           

    def can_skip_tools(self) -> bool:


        return (
            self.is_simple_capability_question
            and not self.planned_tools
            and not self.needs_vault_search
            and not self.needs_file_reading
            and not self.needs_credential_action
        )


PLANNER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(PLANNER_INTENTS),
        },
        "needs_vault_search":           {"type": "boolean"},
        "needs_file_reading":           {"type": "boolean"},
        "needs_ocr_image_pdf_reading":  {"type": "boolean"},
        "needs_credential_action":      {"type": "boolean"},
        "is_simple_capability_question": {"type": "boolean"},
        "needs_stronger_model":         {"type": "boolean"},
        "planned_tools": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string"},
        },
        "reasoning": {
            "type": "string",
            "maxLength": 200,
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "intent",
        "needs_vault_search",
        "needs_file_reading",
        "needs_ocr_image_pdf_reading",
        "needs_credential_action",
        "is_simple_capability_question",
        "needs_stronger_model",
        "planned_tools",
        "reasoning",
        "confidence",
    ],
}


PLANNER_SYSTEM_PROMPT = """\
You classify what the user wants from a personal data vault and \
output ONE JSON object matching the provided schema. Output JSON \
only. Never prose. Never markdown. Never code blocks.

INTENTS (closed set — pick exactly one):
- capability_question        "what can you do", "what are you", \
"help me", "how does this work"
- identity_question          "who are you", "are you AI"
- casual_chat                greetings, thanks, "ok"
- vault_summary              "what's in my vault", "summarize", \
"how big is my vault"
- vault_activity             "what did I recently add", "what \
changed this week"
- document_search            "find me X for Y", "do I have", \
"show me my passport"
- file_read                  user names a specific file or asks \
"what does this file say"
- media_read                 "what's in this video", "transcribe \
this audio"
- credential_lookup          "what's my Chase password", "show \
login for X"
- credential_creation_draft  "create a username and password for \
X", "generate a password"
- credential_save_confirmation user said "save it", "save it \
now", "generate and save" — confirming a prior draft
- expiry_check               "what's expiring", "what should I \
renew", "when does my passport expire"
- entity_lookup              "who is in my vault", "what \
companies", "what people show up"
- category_browse            "show my tax documents", "list my \
IDs", "what categories of things do I have"
- unknown                    nothing else fits

FLAGS:
- needs_vault_search           vault-wide content/file search needed
- needs_file_reading           open a specific file's text
- needs_ocr_image_pdf_reading  read images / scanned PDFs / photos
- needs_credential_action      read / save / list / generate secrets
- is_simple_capability_question TRUE for capability_question / \
identity_question / casual_chat. FALSE otherwise.
- needs_stronger_model         TRUE only when the answer requires \
multi-file reasoning OR the user explicitly asked for deep \
analysis. FALSE by default.

planned_tools — closed-set tool names (empty list when no tools \
needed). Choose 0–6 from:
get_vault_status, get_vault_overview, get_vault_intelligence,
list_vault_files, list_files_by_category, list_document_categories,
search_extracted_text, search_vault_content,
read_file_text, read_image_with_vision, read_media_transcript,
list_file_chunks, read_file_chunk, inspect_uploaded_file,
get_file_metadata, list_vault_entities, find_files_for_entity,
list_file_relationships, list_expiring_items, get_expiry_alert,
get_vault_activity, list_saved_credentials,
get_credential_metadata, list_secrets, retrieve_secret,
save_secret, generate_credential_draft,
save_generated_credential_after_confirmation,
find_in_vault.

EXAMPLES (just for shape — the real input may differ):
- "What can you do?" → intent=capability_question, all flags \
FALSE except is_simple_capability_question=TRUE, planned_tools=[]
- "Find a photo ID for Louis Iodato" → intent=document_search, \
needs_vault_search=TRUE, needs_file_reading=TRUE, \
needs_ocr_image_pdf_reading=TRUE, \
planned_tools=["find_in_vault"]
- "Create username and password for Union Bank" → \
intent=credential_creation_draft, \
needs_credential_action=TRUE, \
planned_tools=["get_credential_metadata", \
"generate_credential_draft"]
- "Save it now" → intent=credential_save_confirmation, \
needs_credential_action=TRUE, \
planned_tools=["save_generated_credential_after_confirmation"]

reasoning: ≤140 chars short rationale.
confidence: 0.0–1.0, your honest belief in the classification.
"""


def _conservative_fallback(reason: str) -> PlannerDecision:


    return PlannerDecision(
        intent="unknown",
        needs_vault_search=True,
        needs_file_reading=False,
        needs_ocr_image_pdf_reading=False,
        needs_credential_action=False,
        is_simple_capability_question=False,
        needs_stronger_model=False,
        planned_tools=(
            "get_vault_status",
            "list_vault_files",
            "search_extracted_text",
        ),
        reasoning=f"fallback: {reason}"[:200],
        confidence=0.0,
        source="fallback",
    )


def _validate_tools(raw: Any) -> tuple[str, ...]:


    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in raw[:6]:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name in _VALID_TOOL_NAMES and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def _planner_enabled() -> bool:


    val = os.getenv(
        "VAULTAI_PLANNER_ENABLED", "true",
    ).strip().lower()
    return val in ("1", "true", "yes", "on")


def _intent_to_simple_flag(intent: str) -> bool:
    return intent in (
        "capability_question",
        "identity_question",
        "casual_chat",
    )


def _coerce_decision(parsed: dict, source: str) -> PlannerDecision:


    intent = str(parsed.get("intent", "unknown"))
    if intent not in PLANNER_INTENTS:
        intent = "unknown"
    tools = _validate_tools(parsed.get("planned_tools"))
    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reasoning = str(parsed.get("reasoning", ""))[:200]
    return PlannerDecision(
        intent=intent,
        needs_vault_search=bool(parsed.get("needs_vault_search")),
        needs_file_reading=bool(parsed.get("needs_file_reading")),
        needs_ocr_image_pdf_reading=bool(
            parsed.get("needs_ocr_image_pdf_reading"),
        ),
        needs_credential_action=bool(
            parsed.get("needs_credential_action"),
        ),
        is_simple_capability_question=bool(
            parsed.get("is_simple_capability_question")
        ) or _intent_to_simple_flag(intent),
        needs_stronger_model=bool(parsed.get("needs_stronger_model")),
        planned_tools=tools,
        reasoning=reasoning,
        confidence=confidence,
        source=source,
    )


async def plan_user_message(
    *,
    message: str,
    recent_history: Optional[list[dict]] = None,
    locale: Optional[str] = None,
) -> PlannerDecision:


    if not isinstance(message, str) or not message.strip():
        return _conservative_fallback("empty_message")
    if not _planner_enabled():
        return _conservative_fallback("planner_disabled")

    try:
        from openai import AsyncOpenAI
        from vault_config import ai as _ai_cfg
    except Exception:
        return _conservative_fallback("openai_unavailable")

    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        return _conservative_fallback("no_api_key")

                                                                   
    convo: list[dict] = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT}
    ]
    if isinstance(recent_history, list) and recent_history:
        clipped = recent_history[-4:]
        for turn in clipped:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "")).strip().lower()
            content = str(turn.get("content", ""))[:400]
            if role in ("user", "assistant") and content:
                convo.append({"role": role, "content": content})
    user_block = message.strip()
    if locale:
        user_block = f"[locale: {locale}]\n{user_block}"
    convo.append({"role": "user", "content": user_block})

    try:
        client = AsyncOpenAI(
            api_key=api_key,
            timeout=float(os.getenv("VAULTAI_PLANNER_TIMEOUT_S", "8")),
        )
        resp = await client.chat.completions.create(
            model=_ai_cfg().intent_model,
            messages=convo,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "vault_planner_decision",
                    "strict": True,
                    "schema": PLANNER_JSON_SCHEMA,
                },
            },
            max_tokens=400,
            temperature=0.0,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("[PLANNER] call failed")
        return _conservative_fallback("api_error")

    try:
        parsed = json.loads(raw)
    except Exception:
        return _conservative_fallback("malformed_json")
    if not isinstance(parsed, dict):
        return _conservative_fallback("not_object")

    return _coerce_decision(parsed, source="planner")


__all__ = [
    "PLANNER_INTENTS",
    "PLANNER_JSON_SCHEMA",
    "PLANNER_SYSTEM_PROMPT",
    "PlannerDecision",
    "plan_user_message",
]
