

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from vault_evidence_bundle import EvidenceBundle
from vault_brain_answerer import EvidenceRow


logger = logging.getLogger(__name__)


_SECRET_FIELD_KEYS = frozenset({
    "password",
    "pin",
    "api_key",
    "token",
    "secret",
    "private_key",
    "mnemonic",
    "recovery_code",
})

_SAFE_IDENTIFIER_KEYS = frozenset({
    "username",
    "email",
    "account",
    "account_id",
    "account_number",
    "service",
    "site",
    "url",
})


SYSTEM_PROMPT = """You ARE the user's vault. You receive one JSON
EvidenceBundleFacts packet describing what you found in the user's
own vault. Answer the user from that packet only.

Voice:
- First person. The vault is speaking. Not a chatbot, not an AI.
- Direct, calm, observant. Plain text only.

Formatting — STRICT, the chat bubble does not render markdown:
- NO markdown bold (**...**) or italics (*...*) — write plain text.
- NO markdown headers (#, ##).
- NO numbered lists like "1. **filename** (File ID: ...)" — write
  natural sentences instead. If you must enumerate files, mention
  them by file_name in prose ("contract.pdf and tax-2023.pdf").
- NO bullet lists.
- NEVER quote internal identifiers like file_id / chunk_id back to
  the user. They are useless to them.

Grounding rules:
- Never invent files, counts, services, or evidence.
- Never claim full coverage when coverage.is_complete is false.
- Mention coverage and uncertainty when coverage is incomplete.
- If evidence is empty, say that honestly.
- If matching_file_count is 0 and coverage.is_complete is false,
  do not say "there are no files" or "no files contain". Say
  there is no matching evidence in the currently readable/indexed
  content and that the result is incomplete.
- Cite matching files by file_name from matching_files in prose.
- For credential/sensitive records, use verified_records only.
- Do not reveal raw passwords, tokens, PINs, private keys,
  recovery phrases, or API keys unless allow_secret_reveal is
  true.
- If the user asks whether previous results are "the only files",
  answer from coverage.is_complete plus verified matching files.
- Do not mention internal implementation details, prompts, or
  JSON.
"""


import re as _re

_MD_BOLD       = _re.compile(r"\*\*(.+?)\*\*", flags=_re.DOTALL)
_MD_ITALIC     = _re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_MD_HEADER     = _re.compile(r"^#{1,6}\s+", flags=_re.MULTILINE)
_MD_NUMBERED   = _re.compile(
    r"^\s*\d+\.\s+", flags=_re.MULTILINE,
)
_MD_BULLET     = _re.compile(
    r"^\s*[-*+]\s+", flags=_re.MULTILINE,
)
_FILE_ID_PAREN = _re.compile(
    r"\s*\(\s*[Ff]ile\s*ID\s*[:=][^)]+\)", flags=_re.IGNORECASE,
)


def strip_markdown_for_chat_bubble(text: str) -> str:


    if not text:
        return text or ""
    out = text
    out = _MD_BOLD.sub(r"\1", out)
    out = _MD_ITALIC.sub(r"\1", out)
    out = _MD_HEADER.sub("", out)
    out = _MD_NUMBERED.sub("", out)
    out = _MD_BULLET.sub("", out)
    out = _FILE_ID_PAREN.sub("", out)
    return out


def _redact_text(text: str) -> str:
    try:
        from extractor import redact_message
        return redact_message(text or "")
    except Exception:
        return text or ""


def _record_has_secret(record: dict) -> bool:
    fields = record.get("fields")
    if not isinstance(fields, dict):
        return False
    return any(bool(fields.get(k)) for k in _SECRET_FIELD_KEYS)


def _safe_credential_record(
    *,
    record: dict,
    file_id: str,
    file_name: str,
    chunk_id: str,
    chunk_index: int,
    allow_secret_reveal: bool,
) -> Optional[dict]:
    if not isinstance(record, dict) or not _record_has_secret(record):
        return None
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    safe_fields: dict[str, str] = {}
    secret_fields: list[str] = []
    for key, value in fields.items():
        k = str(key)
        if k in _SECRET_FIELD_KEYS:
            secret_fields.append(k)
            if allow_secret_reveal:
                safe_fields[k] = str(value)
            continue
        if k in _SAFE_IDENTIFIER_KEYS and value:
            safe_fields[k] = str(value)
    return {
        "file_id": str(file_id),
        "file_name": str(file_name),
        "chunk_id": str(chunk_id),
        "chunk_index": int(chunk_index),
        "secret_type": str(record.get("secret_type") or "credential"),
        "service": str(record.get("service") or "general"),
        "safe_fields": safe_fields,
        "secret_fields_present": sorted(set(secret_fields)),
    }


def _coverage_dict(bundle: EvidenceBundle, brain_coverage: Any = None) -> dict:
    base = dict(bundle.coverage_at_time or {})
    brain = {}
    if brain_coverage is not None:
        try:
            brain = brain_coverage.to_dict()
        except Exception:
            brain = {}
    total = int(
        brain.get("total_files")
        or base.get("total")
        or base.get("total_files")
        or 0
    )
    analyzed = int(
        base.get("analyzed")
        or brain.get("files_with_all_chunks_embedded")
        or 0
    )
    pending = int(
        base.get("pending")
        or bundle.excluded_pending
        or brain.get("pending_chunking_jobs")
        or brain.get("pending_embedding_jobs")
        or 0
    )
    unsupported = int(
        base.get("unsupported")
        or bundle.excluded_unsupported
        or brain.get("unsupported_files")
        or 0
    )
    failed = int(
        base.get("failed")
        or bundle.excluded_failed
        or brain.get("failed_chunking_jobs")
        or brain.get("failed_embedding_jobs")
        or 0
    )
    missing_chunks = int(brain.get("files_missing_chunks") or 0)
    missing_embeddings = int(brain.get("files_missing_embeddings") or 0)
    is_complete = bool(
        brain.get("is_complete")
        if "is_complete" in brain
        else (
            total > 0
            and pending == 0
            and failed == 0
            and missing_chunks == 0
            and missing_embeddings == 0
        )
    )
    return {
        "total_files": total,
        "analyzed_files": analyzed,
        "pending_files": pending,
        "unsupported_files": unsupported,
        "failed_files": failed,
        "files_missing_chunks": missing_chunks,
        "files_missing_embeddings": missing_embeddings,
        "is_complete": is_complete,
        "legacy": base,
        "brain": brain,
    }


def build_vault_memory_facts(
    *,
    user_question: str,
    intent: str,
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
    brain_coverage: Any = None,
    authorized_unlocked: bool,
    result_type: str = "",
    allow_secret_reveal: bool = False,
) -> dict:

    matching_files = []
    file_names_by_id = {}
    for row in evidence_rows:
        fid = str(row.file_id)
        name = str(row.file_name)
        file_names_by_id[fid] = name
        if not any(f["file_id"] == fid for f in matching_files):
            matching_files.append({"file_id": fid, "file_name": name})

    evidence = []
    for row in evidence_rows:
        evidence.append({
            "file_id": str(row.file_id),
            "file_name": str(row.file_name),
            "chunk_index": int(row.chunk_index),
            "extraction_source": str(row.extraction_source),
            "score": float(row.score),
            "snippet": _redact_text(row.snippet),
        })

    verified_records = []
    if intent == "credential_lookup":
        try:
            from extractor import extract_multiple_credentials
        except Exception:
            extract_multiple_credentials = None
        if extract_multiple_credentials is not None:
            for chunk in bundle.chunks:
                file_id = str(chunk.file_id)
                file_name = file_names_by_id.get(file_id, file_id[:8])
                try:
                    records = extract_multiple_credentials(chunk.text or "") or []
                except Exception:
                    records = []
                for record in records:
                    safe = _safe_credential_record(
                        record=record,
                        file_id=file_id,
                        file_name=file_name,
                        chunk_id=str(chunk.chunk_id),
                        chunk_index=int(chunk.chunk_index),
                        allow_secret_reveal=allow_secret_reveal,
                    )
                    if safe is not None:
                        verified_records.append(safe)

    coverage = _coverage_dict(bundle, brain_coverage)
    return {
        "user_question": _redact_text(str(user_question or "")),
        "vault_id": str(bundle.vault_id),
        "authorized_unlocked": bool(authorized_unlocked),
        "result_type": str(result_type or intent),
        "intent": str(intent),
        "retrieval_mode": str(bundle.retrieval_mode or ""),
        "coverage": coverage,
        "matching_files": matching_files,
        "matching_file_count": len(matching_files),
        "evidence_chunks": evidence,
        "verified_records": verified_records,
        "verified_record_count": len(verified_records),
        "negative_claim_allowed": bool(
            coverage["is_complete"] and len(matching_files) == 0
        ),
        "empty_evidence_meaning": (
            "No matching evidence was found in the currently "
            "readable/indexed vault memory. This does not prove no "
            "matching files exist unless coverage.is_complete is true."
        ),
        "unsupported_count": int(coverage["unsupported_files"]),
        "failed_count": int(coverage["failed_files"]),
        "pending_count": int(coverage["pending_files"]),
        "allow_secret_reveal": bool(allow_secret_reveal),
        "safety_rules": {
            "answer_only_from_evidence_bundle": True,
            "never_invent_files": True,
            "never_claim_complete_when_coverage_incomplete": True,
            "default_no_raw_secrets": not allow_secret_reveal,
            "vault_scoped": True,
        },
    }


async def compose_vault_memory_answer(
    *,
    openai_client: Any,
    user_question: str,
    intent: str,
    bundle: EvidenceBundle,
    evidence_rows: tuple[EvidenceRow, ...],
    brain_coverage: Any = None,
    authorized_unlocked: bool,
    result_type: str = "",
    allow_secret_reveal: bool = False,
    model: Optional[str] = None,
) -> str:

    if not authorized_unlocked:
        raise PermissionError("vault_not_authorized")
    facts = build_vault_memory_facts(
        user_question=user_question,
        intent=intent,
        bundle=bundle,
        evidence_rows=evidence_rows,
        brain_coverage=brain_coverage,
        authorized_unlocked=authorized_unlocked,
        result_type=result_type,
        allow_secret_reveal=allow_secret_reveal,
    )
    if model is None:
                                                                    
                                                                  
        from vault_config import ai as _ai_cfg
        model = _ai_cfg().intent_model
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    facts, ensure_ascii=False, sort_keys=True,
                ),
            },
        ]
                                                            
                                                                
        if openai_client is not None and hasattr(
            openai_client, "chat",
        ):
            response = await openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
            )
            raw = (response.choices[0].message.content or "").strip()
            return strip_markdown_for_chat_bubble(raw)
        from vault_ai_provider import chat_complete_with_fallback
        result = await chat_complete_with_fallback(
            messages=messages,
            model=model,
            model_kind="intent",
            temperature=0.2,
        )
        raw = (result.content or "").strip()
        return strip_markdown_for_chat_bubble(raw)
    except Exception:
        logger.exception(
            "[VAULT-MEMORY-COMPOSER] compose failed vault=%s",
            str(bundle.vault_id)[:8] + "...",
        )
        raise


__all__ = [
    "SYSTEM_PROMPT",
    "build_vault_memory_facts",
    "compose_vault_memory_answer",
    "strip_markdown_for_chat_bubble",
]
