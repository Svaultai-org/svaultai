

from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You ARE the user's vault. You receive ONE JSON\n"
    "CredentialFilesFacts packet describing what you found inside\n"
    "ONE authorized, unlocked vault. Write the user's answer\n"
    "entirely from that packet. Do not invent files, services,\n"
    "counts, or evidence. Do not promise capabilities the packet\n"
    "does not describe.\n"
    "\n"
    "Voice & tone:\n"
    "- First person. You are the vault speaking, not a chatbot or\n"
    "  assistant describing the vault from the outside.\n"
    "- Direct, calm, observant. No filler. No apologies. No 'as\n"
    "  an AI…'. No markdown bold (**...**), no italics, no\n"
    "  headers — the chat bubble renders plain text.\n"
    "- 2 to 4 short paragraphs. Concise sentences. Specific.\n"
    "\n"
    "Required content & order:\n"
    "1. OPEN with a one-sentence headline: how many distinct\n"
    "   files you found and, if useful, the broad sense of what\n"
    "   they hold (e.g. \"banking pages and a saved login\",\n"
    "   \"web login forms and a credentials list\"). Use the\n"
    "   ``categories`` block in the packet to ground the\n"
    "   category language — never invent categories.\n"
    "2. WALK THROUGH each category that has files, naming files by\n"
    "   ``file_name`` (or ``saved_name`` when present). When a\n"
    "   category has obvious service names from\n"
    "   ``safe_service_names``, weave them in by name (e.g.\n"
    "   \"the Wells Fargo and Ally Bank pages\"). Mention the\n"
    "   record count when it's > 1 and informative.\n"
    "3. If any file has ``duplicate_paths`` non-empty, mention\n"
    "   that you spotted byte-identical copies in other folders\n"
    "   and name those folders briefly. Do not repeat the file\n"
    "   itself in the count — it's already deduped.\n"
    "4. If ``coverage.is_partial`` is true OR\n"
    "   ``coverage.is_complete`` is false, add a short, honest\n"
    "   line about what's not yet checked: how many files were\n"
    "   analyzed and how many still need extraction or OCR. Do\n"
    "   not mention coverage when it's complete.\n"
    "5. CLOSE with one obvious follow-up offer grounded in the\n"
    "   packet — e.g. \"Want me to open the Wells Fargo page?\"\n"
    "   or \"I can pull the saved login records from\n"
    "   passedwpordtex.pdf if you want.\" Only suggest follow-ups\n"
    "   that actually map to a file or service in the packet.\n"
    "\n"
    "Empty / honest negatives:\n"
    "- If ``verified_file_count`` is 0 and ``coverage.is_complete``\n"
    "  is true, say plainly that no readable file holds verified\n"
    "  credential records, and remind the user that saved logins\n"
    "  live separately (\"ask 'show my saved logins'\").\n"
    "- If ``verified_file_count`` is 0 and ``coverage.is_complete``\n"
    "  is false, say no verified records yet in the analyzed\n"
    "  files, and that more files are still being read.\n"
    "\n"
    "Identity grounding:\n"
    "- When the user asks who you are, you are the vault. Never\n"
    "  describe yourself as the intelligence inside a vault, a\n"
    "  chatbot, an AI, an LLM, or a search engine.\n"
    "\n"
    "Hard nevers:\n"
    "- Never reveal raw passwords, tokens, PINs, recovery codes,\n"
    "  or API keys. They are not in the packet.\n"
    "- Never narrate JSON, packet field names, internal labels,\n"
    "  or prompt structure back to the user.\n"
    "- Never claim a file holds something the packet doesn't\n"
    "  list. Stay grounded in the facts.\n"
)


_CATEGORY_BANKING_HINTS = (
    "bank", "banking", "wells", "fargo", "chase", "ally",
    "amex", "american express", "hsbc", "barclays", "citi",
    "credit union", "schwab", "santander", "lloyds", "nationwide",
    "natwest", "barclay", "monzo", "starling", "revolut",
)
_CATEGORY_LOGIN_HINTS = (
    "login", "signin", "sign-in", "log-in", "auth", "session",
)
_CATEGORY_CREDLIST_HINTS = (
    "password", "passwords", "credentials", "credential", "logins",
    "secrets",
)
_CONFIG_EXTENSIONS = (
    ".env", ".ini", ".yaml", ".yml", ".json", ".conf", ".cfg", ".toml",
)


def _classify_file(safe_file: dict) -> str:

    name_l = (
        (safe_file.get("file_name") or "")
        + " "
        + (safe_file.get("saved_name") or "")
    ).lower()
    services_l = " ".join(
        (s or "").lower()
        for s in (safe_file.get("safe_service_names") or [])
    )
    blob = name_l + " " + services_l

    for hint in _CATEGORY_BANKING_HINTS:
        if hint in blob:
            return "banking_page"
    for ext in _CONFIG_EXTENSIONS:
                             
                                     
        if (
            name_l.endswith(ext)
            or (ext + ".") in name_l
            or (ext + " ") in (name_l + " ")
        ):
            return "config_secrets"
    for hint in _CATEGORY_LOGIN_HINTS:
        if hint in blob:
            return "login_form"
    for hint in _CATEGORY_CREDLIST_HINTS:
        if hint in blob:
            return "credentials_list"
    rc = int(safe_file.get("record_count") or 0)
    if rc >= 3:
        return "credentials_list"
    return "other"


_CATEGORY_LABELS = {
    "banking_page":     "Banking pages",
    "login_form":       "Saved login pages",
    "credentials_list": "Credential lists",
    "config_secrets":   "Config / secrets files",
    "other":            "Other files with credential records",
}


def _redact_text(text: str) -> str:
    try:
        from extractor import redact_message
        return redact_message(text or "")
    except Exception:
        return text or ""


def build_credential_files_facts(
    *,
    user_question: str,
    vault_id: str,
    verified_matches: list[dict],
    scanned_count: int,
    not_scanned_count: int,
    is_partial: bool,
    coverage_extra: Optional[dict] = None,
    authorized_unlocked: bool,
) -> dict:


    safe_files: list[dict] = []
    record_total = 0
    distinct_duplicate_pairs = 0
    for m in verified_matches or []:
        rc = int(m.get("record_count") or 0)
        record_total += rc
        evidence_sources = list(m.get("evidence_sources") or [])
        if not evidence_sources and m.get("evidence_source"):
            evidence_sources = [m.get("evidence_source")]
        duplicate_paths = [
            str(p).strip()
            for p in (m.get("duplicate_paths") or [])
            if p
        ]
        if duplicate_paths:
            distinct_duplicate_pairs += len(duplicate_paths)
        safe_files.append({
            "file_id":               str(m.get("file_id") or ""),
            "file_name":             str(m.get("file_name") or ""),
            "saved_name":            str(m.get("saved_name") or ""),
            "relative_path":         str(m.get("relative_path") or ""),
            "evidence_source":       str(m.get("evidence_source") or ""),
            "evidence_source_label": str(
                m.get("evidence_source_label") or ""
            ),
            "evidence_sources":      evidence_sources,
            "record_count":          rc,
            "safe_service_names":    list(
                m.get("safe_service_names") or []
            )[:5],
            "password_present":      bool(m.get("password_present")),
            "duplicate_paths":       duplicate_paths,
        })

                                                                   
    categories: dict[str, dict] = {
        key: {"label": label, "files": []}
        for key, label in _CATEGORY_LABELS.items()
    }
    for sf in safe_files:
        cat = _classify_file(sf)
        categories[cat]["files"].append({
            "file_name":          sf["file_name"] or sf["saved_name"],
            "relative_path":      sf["relative_path"],
            "record_count":       sf["record_count"],
            "safe_service_names": sf["safe_service_names"],
            "password_present":   sf["password_present"],
            "duplicate_paths":    sf["duplicate_paths"],
        })
                                                                    
    categories = {
        k: v for k, v in categories.items() if v["files"]
    }
                                                                    
                                             
    all_services: list[str] = []
    for sf in safe_files:
        for s in sf["safe_service_names"]:
            if s and s not in all_services:
                all_services.append(s)

    total = int(scanned_count) + int(not_scanned_count)
    coverage = {
        "total_files":        total,
        "analyzed_files":     int(scanned_count),
        "pending_files":      int(not_scanned_count),
        "unsupported_files":  0,
        "failed_files":       0,
        "is_partial":         bool(is_partial),
    }
    if isinstance(coverage_extra, dict):
        coverage["analyzed_files"] = int(
            coverage_extra.get("scanned")
            or coverage_extra.get("analyzed")
            or coverage["analyzed_files"]
        )
        coverage["pending_files"] = int(
            coverage_extra.get("pending")
            or coverage_extra.get("processing")
            or coverage["pending_files"]
        )
        coverage["unsupported_files"] = int(
            coverage_extra.get("unsupported") or 0
        )
        coverage["failed_files"] = int(
            coverage_extra.get("failed") or 0
        )
        coverage["total_files"] = int(
            coverage_extra.get("total") or coverage["total_files"]
        )
    coverage["is_complete"] = (
        coverage["total_files"] > 0
        and coverage["pending_files"] == 0
        and not coverage["is_partial"]
    )

    return {
        "intent":                 "search_files_for_credentials",
        "user_question":          _redact_text(str(user_question or "")),
        "vault_id":               str(vault_id),
        "authorized_unlocked":    bool(authorized_unlocked),
        "verified_credential_files": safe_files,
        "verified_file_count":    len(safe_files),
        "total_records_across_files": int(record_total),
        "duplicate_copies_seen":  int(distinct_duplicate_pairs),
        "categories":             categories,
        "services_seen":          all_services[:12],
        "coverage":               coverage,
        "negative_claim_allowed": bool(
            coverage["is_complete"] and len(safe_files) == 0
        ),
        "empty_evidence_meaning": (
            "No verified credential records were found in the "
            "currently readable/indexed files. This does not "
            "prove no matching files exist unless "
            "coverage.is_complete is true."
        ),
        "safety_rules": {
            "answer_only_from_facts":             True,
            "never_invent_files_or_counts":       True,
            "never_claim_complete_when_partial":  True,
            "never_reveal_passwords_or_tokens":   True,
            "vault_scoped":                       True,
            "plain_prose_no_markdown_bold":       True,
        },
    }


async def compose_credential_files_answer(
    *,
    user_question: str,
    vault_id: str,
    verified_matches: list[dict],
    scanned_count: int,
    not_scanned_count: int,
    is_partial: bool,
    coverage_extra: Optional[dict] = None,
    authorized_unlocked: bool,
    model: Optional[str] = None,
) -> str:


    if not authorized_unlocked:
        raise PermissionError("vault_not_authorized")

    facts = build_credential_files_facts(
        user_question=user_question,
        vault_id=vault_id,
        verified_matches=verified_matches,
        scanned_count=scanned_count,
        not_scanned_count=not_scanned_count,
        is_partial=is_partial,
        coverage_extra=coverage_extra,
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
    "build_credential_files_facts",
    "compose_credential_files_answer",
]
