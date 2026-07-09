

from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


EXCERPT_BYTE_BUDGET: int = 12_000


SYSTEM_PROMPT = (
    "You ARE the user's vault. The user asked you what is inside\n"
    "one of their files. You will receive a JSON FileReadFacts\n"
    "packet that includes a REDACTED excerpt of the file's\n"
    "extracted text plus some safe metadata. Write the answer\n"
    "entirely from the packet. Do not invent contents.\n"
    "\n"
    "Voice & tone:\n"
    "- First person. You are the vault speaking. Not a chatbot,\n"
    "  not an AI, not a generic assistant.\n"
    "- Direct, observant, factual. No filler. No 'as an AI…'.\n"
    "  No markdown bold (**...**), italics, or headers — the\n"
    "  chat bubble renders plain text only.\n"
    "- 2 to 4 short paragraphs. Concise, specific sentences.\n"
    "\n"
    "Required content & order:\n"
    "1. OPEN with one sentence that names the file and says what\n"
    "   kind of document it is, grounded in the excerpt (e.g.\n"
    "   \"contract.pdf is a Wells Fargo home loan modification\n"
    "   agreement\" — not just \"a document\").\n"
    "2. WALK THROUGH the meaningful contents: the topic, the\n"
    "   parties or services involved, dates / amounts / account\n"
    "   numbers when present, the action or decision the file\n"
    "   represents, any notable structure (sections, signatures,\n"
    "   tables of contents, etc.). Stay grounded in the excerpt.\n"
    "3. If the excerpt was truncated (``excerpt_truncated`` is\n"
    "   true), mention briefly that this is the start of the\n"
    "   file and there's more after the cut — never claim you\n"
    "   read the entire file when you didn't.\n"
    "4. CLOSE with one specific follow-up offer grounded in the\n"
    "   content, e.g. \"Want me to pull out the payment\n"
    "   schedule?\" or \"I can list the services this credentials\n"
    "   file holds.\" Only offer things that actually map to\n"
    "   content you saw.\n"
    "\n"
    "Empty / honest negatives:\n"
    "- If ``excerpt`` is empty or unreadable, say plainly that\n"
    "  the file's text isn't extracted yet (or the file type\n"
    "  isn't readable) and tell the user you'll be able to read\n"
    "  it once the extractor finishes. Do not guess at content.\n"
    "\n"
    "Hard nevers:\n"
    "- The excerpt has placeholders like ``password=***``,\n"
    "  ``email=***``, or ``***@***.***`` where real secrets and\n"
    "  contact details used to be. NEVER expand those\n"
    "  placeholders into invented values. NEVER substitute a\n"
    "  realistic-looking password / email / name for a redacted\n"
    "  placeholder. Quote the placeholder as-is if you must\n"
    "  reference it.\n"
    "- NEVER reveal raw passwords, tokens, PINs, recovery\n"
    "  codes, or API keys. They are not in the packet.\n"
    "- NEVER narrate JSON, packet field names, or prompt\n"
    "  structure back to the user.\n"
    "- NEVER describe yourself as 'the intelligence inside the\n"
    "  vault', 'a chatbot', or 'an AI'. You ARE the vault.\n"
)


def _redact_text(text: str) -> str:
    try:
        from extractor import redact_message
        return redact_message(text or "")
    except Exception:
        return text or ""


def _prepare_excerpt(
    text: Optional[str], *, budget: int = EXCERPT_BYTE_BUDGET,
) -> tuple[str, bool]:


    if not text or not text.strip():
        return "", False
    safe_budget = max(100, int(budget))
    redacted = _redact_text(text)
    if len(redacted) <= safe_budget:
        return redacted, False
    cut = redacted[:safe_budget]
                                                            
    last_ws = cut.rfind(" ")
    if last_ws > safe_budget * 0.8:
        cut = cut[:last_ws]
    return cut, True


def build_file_read_facts(
    *,
    user_question: str,
    vault_id: str,
    file_id: str,
    file_name: str,
    saved_name: Optional[str],
    relative_path: Optional[str],
    mime_type: Optional[str],
    asset_type: Optional[str],
    extracted_text: Optional[str],
    purpose: Optional[str],
    purpose_label: Optional[str],
    metrics: Optional[dict],
    authorized_unlocked: bool,
    excerpt_budget: int = EXCERPT_BYTE_BUDGET,
) -> dict:


    excerpt, truncated = _prepare_excerpt(
        extracted_text, budget=excerpt_budget,
    )
    safe_metrics: dict = {}
    if isinstance(metrics, dict):
                                                               
        for k in (
            "credential_block_count",
            "service_count",
            "credential_density",
            "credential_like_lines",
            "meaningful_lines",
            "mostly_credentials",
        ):
            if k in metrics:
                safe_metrics[k] = metrics[k]

    return {
        "intent":               "analyze_file",
        "user_question":        _redact_text(str(user_question or "")),
        "vault_id":             str(vault_id),
        "authorized_unlocked":  bool(authorized_unlocked),
        "file": {
            "file_id":          str(file_id or ""),
            "file_name":        str(file_name or ""),
            "saved_name":       str(saved_name or ""),
            "relative_path":    str(relative_path or ""),
            "mime_type":        str(mime_type or ""),
            "asset_type":       str(asset_type or ""),
        },
        "purpose":              str(purpose or ""),
        "purpose_label":        str(purpose_label or ""),
        "metrics":              safe_metrics,
        "excerpt":              excerpt,
        "excerpt_truncated":    bool(truncated),
        "excerpt_char_count":   len(excerpt),
        "safety_rules": {
            "answer_only_from_excerpt":           True,
            "never_invent_content":               True,
            "never_expand_redaction_placeholders": True,
            "never_reveal_passwords_or_tokens":   True,
            "vault_scoped":                       True,
            "plain_prose_no_markdown_bold":       True,
        },
    }


async def compose_file_read_answer(
    *,
    user_question: str,
    vault_id: str,
    file_id: str,
    file_name: str,
    extracted_text: Optional[str],
    saved_name: Optional[str] = None,
    relative_path: Optional[str] = None,
    mime_type: Optional[str] = None,
    asset_type: Optional[str] = None,
    purpose: Optional[str] = None,
    purpose_label: Optional[str] = None,
    metrics: Optional[dict] = None,
    authorized_unlocked: bool,
    model: Optional[str] = None,
) -> str:


    if not authorized_unlocked:
        raise PermissionError("vault_not_authorized")

    facts = build_file_read_facts(
        user_question=user_question,
        vault_id=vault_id,
        file_id=file_id,
        file_name=file_name,
        saved_name=saved_name,
        relative_path=relative_path,
        mime_type=mime_type,
        asset_type=asset_type,
        extracted_text=extracted_text,
        purpose=purpose,
        purpose_label=purpose_label,
        metrics=metrics,
        authorized_unlocked=authorized_unlocked,
    )

    from vault_ai_provider import chat_complete_with_fallback
    from vault_config import ai as _ai_cfg

    resolved_model = model
    if resolved_model is None:
        resolved_model = _ai_cfg().chat_model

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(facts, ensure_ascii=False, sort_keys=True),
        },
    ]
    result = await chat_complete_with_fallback(
        messages=messages,
        model=resolved_model,
        model_kind="chat",
        temperature=0.3,
        max_tokens=900,
    )
    text = (result.content or "").strip()
    return text


__all__ = [
    "SYSTEM_PROMPT",
    "EXCERPT_BYTE_BUDGET",
    "build_file_read_facts",
    "compose_file_read_answer",
]
