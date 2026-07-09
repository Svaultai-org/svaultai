

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


DEFAULT_KEEP_RECENT_TURNS:   int = 5                              
MAX_MEMORY_BLOCK_CHARS:      int = 2_000                                
MAX_LIST_ITEMS:              int = 12                                  
MAX_FILE_IDS:                int = 10
MAX_INSTRUCTIONS:            int = 8


_SECRET_PATTERNS = (
                                                             
    re.compile(
        r"\b(passwords?|pwd|pass|pwords?)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
                                   
    re.compile(
        r"\bpin(?:\s*code)?\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
                                      
    re.compile(
        r"\b(access[_\s]?token|auth[_\s]?token|api[_\s]?key|"
        r"token|secret)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
                                    
    re.compile(
        r"\bseed\s*phrase\s*[:=].*?(?:\n|$)",
        re.IGNORECASE,
    ),
                        
    re.compile(
        r"\bbackup\s*codes?\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
                                                              
    re.compile(
        r"\b(?:otp|2fa)\s*[:=]?\s*\d{4,8}\b",
        re.IGNORECASE,
    ),
)


_PENDING_CONFIRMATION_PATTERNS = (
    re.compile(r"\bsave\s+it\s+now\b",         re.IGNORECASE),
    re.compile(r"\bsave\s+it\b",               re.IGNORECASE),
    re.compile(r"\bsave\s+the\s+credential",   re.IGNORECASE),
    re.compile(r"\bgenerate\s+and\s+save\b",   re.IGNORECASE),
    re.compile(r"\buse\s+option\s+(\d+)\b",    re.IGNORECASE),
    re.compile(r"\bpick\s+(?:option\s+)?(\d+)\b", re.IGNORECASE),
    re.compile(r"\byes,?\s+do\s+it\b",         re.IGNORECASE),
    re.compile(r"\bconfirm(?:ed)?\b",          re.IGNORECASE),
)


_USER_INSTRUCTION_PATTERNS = (
    re.compile(r"\bfrom\s+now\s+on[, ]+([^\.\n]{4,160})", re.IGNORECASE),
    re.compile(r"\balways\s+([^\.\n]{4,160})",            re.IGNORECASE),
    re.compile(r"\bnever\s+([^\.\n]{4,160})",             re.IGNORECASE),
    re.compile(r"\bdon'?t\s+([^\.\n]{4,160})",            re.IGNORECASE),
    re.compile(r"\bplease\s+([^\.\n]{4,160})",            re.IGNORECASE),
)


_FILE_ID_PATTERNS = (
    re.compile(
        r"\bfile[_\s]id\b\s*[:=]?\s*['\"]?([A-Za-z0-9\-_]{8,64})['\"]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfile_([A-Za-z0-9]{6,32})\b",
    ),
    re.compile(
        r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    ),
)


_SERVICE_PATTERNS = (
                                                             
                                                                
    re.compile(
        r"\b(?:create|generate|make)\b[^\.\n]*?\bfor\s+"
        r"([A-Z][A-Za-z0-9'\-]*(?:\s+[A-Z][A-Za-z0-9'\-]*){0,2})"
    ),
                                                                  
    re.compile(
        r"\bfor\s+"
        r"([A-Z][A-Za-z0-9'\-]*(?:\s+[A-Z][A-Za-z0-9'\-]*){0,2})"
        r"(?:\s+(?:account|login|credential)|\s*[\.,!?]|$)",
        re.MULTILINE,
    ),
)


_CREDENTIAL_DRAFT_PATTERN = re.compile(
    r"\busername\s*[:=]\s*\S+[\s\S]{0,200}\bpassword\s*[:=]\s*\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompressedMemory:

    pending_drafts:         tuple[str, ...] = field(default_factory=tuple)
    pending_confirmations:  tuple[str, ...] = field(default_factory=tuple)
    selected_files:         tuple[str, ...] = field(default_factory=tuple)
    user_instructions:      tuple[str, ...] = field(default_factory=tuple)
    services_mentioned:     tuple[str, ...] = field(default_factory=tuple)
    summary_note:           str             = ""

    def is_empty(self) -> bool:
        return not (
            self.pending_drafts or self.pending_confirmations
            or self.selected_files or self.user_instructions
            or self.services_mentioned or self.summary_note
        )

    def to_system_block(self) -> str:

        payload: dict[str, object] = {}
        if self.pending_drafts:
            payload["pending_drafts"] = list(self.pending_drafts)
        if self.pending_confirmations:
            payload["pending_confirmations"] = list(
                self.pending_confirmations,
            )
        if self.selected_files:
            payload["selected_files"] = list(self.selected_files)
        if self.user_instructions:
            payload["user_instructions"] = list(self.user_instructions)
        if self.services_mentioned:
            payload["services_mentioned"] = list(self.services_mentioned)
        if self.summary_note:
            payload["summary_note"] = self.summary_note
        body = (
            "CONVERSATION MEMORY (compressed from older turns; "
            "deterministic, contains NO secrets). Use this to "
            "stay coherent across turns:\n"
            + json.dumps(payload, ensure_ascii=False)
        )
                   
        if len(body) > MAX_MEMORY_BLOCK_CHARS:
            body = body[:MAX_MEMORY_BLOCK_CHARS] + "…"
        return body


@dataclass(frozen=True)
class CompressionResult:
    head:               list[dict]
    memory_message:     Optional[dict]
    recent_messages:    list[dict]
    compression_summary: dict
    memory:             CompressedMemory

    def assembled(self) -> list[dict]:


        out: list[dict] = list(self.head)
        if self.memory_message is not None:
            out.append(self.memory_message)
        out.extend(self.recent_messages)
        return out


def _strip_secrets(text: str) -> str:


    if not isinstance(text, str) or not text:
        return ""
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    try:
        from extractor import redact_message
        out = redact_message(out)
    except Exception:
        pass
    return out


def _content_str(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    out.append(block["text"])
        return " ".join(out)
    return ""


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if not isinstance(it, str):
            continue
        s = it.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extract_signals(
    messages_to_compress: list[dict],
) -> CompressedMemory:


    drafts:        list[str] = []
    confirmations: list[str] = []
    files:         list[str] = []
    instructions:  list[str] = []
    services:      list[str] = []

    for msg in messages_to_compress:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        text = _content_str(msg)
        if not text:
            continue
        safe_text = _strip_secrets(text)

                                                                  
        if role == "assistant":
            if _CREDENTIAL_DRAFT_PATTERN.search(text):
                                                                   
                                            
                svc = services[-1] if services else "an unnamed service"
                drafts.append(
                    f"credential draft proposed for {svc} "
                    "(awaiting user save confirmation)"
                )

                                                                  
        if role == "user":
            for pat in _PENDING_CONFIRMATION_PATTERNS:
                m = pat.search(text)
                if m:
                    phrase = m.group(0).strip()
                    confirmations.append(
                        f"user said {phrase!r} — pending action"
                    )
                    break

                                      
        for pat in _FILE_ID_PATTERNS:
            for fid_match in pat.findall(safe_text):
                                                                  
                                      
                fid = (
                    fid_match
                    if isinstance(fid_match, str)
                    else " ".join(fid_match)
                )
                if fid and len(fid) >= 6:
                    files.append(fid)

                                     
        if role == "user":
            for pat in _USER_INSTRUCTION_PATTERNS:
                for m in pat.finditer(safe_text):
                    captured = m.group(1) if m.groups() else m.group(0)
                    if captured and len(captured) >= 3:
                        instructions.append(
                            f"user requested: {captured.strip()}"
                        )

                                    
        for pat in _SERVICE_PATTERNS:
            for m in pat.finditer(text):
                svc = m.group(1).strip()
                                                                 
                               
                svc = re.sub(
                    r"\s+(account|login|credential)$",
                    "", svc, flags=re.IGNORECASE,
                ).strip()
                if svc and len(svc) <= 60:
                    services.append(svc)

    summary_note = ""
    if messages_to_compress:
        first_user = next(
            (
                _content_str(m)[:120]
                for m in messages_to_compress
                if isinstance(m, dict)
                and m.get("role") == "user"
            ),
            "",
        )
        if first_user:
            summary_note = (
                "older conversation began with: "
                + _strip_secrets(first_user).strip()
            )

    return CompressedMemory(
        pending_drafts=tuple(
            _dedupe_keep_order(drafts)[:MAX_LIST_ITEMS]
        ),
        pending_confirmations=tuple(
            _dedupe_keep_order(confirmations)[:MAX_LIST_ITEMS]
        ),
        selected_files=tuple(
            _dedupe_keep_order(files)[:MAX_FILE_IDS]
        ),
        user_instructions=tuple(
            _dedupe_keep_order(instructions)[:MAX_INSTRUCTIONS]
        ),
        services_mentioned=tuple(
            _dedupe_keep_order(services)[:MAX_LIST_ITEMS]
        ),
        summary_note=summary_note,
    )


def compress_messages(
    messages: list[dict],
    *,
    keep_recent_turns: int = DEFAULT_KEEP_RECENT_TURNS,
) -> CompressionResult:


    if not isinstance(messages, list):
        return CompressionResult(
            head=[], memory_message=None,
            recent_messages=[],
            compression_summary={"reason": "not_a_list"},
            memory=CompressedMemory(),
        )

    keep = max(1, int(keep_recent_turns or DEFAULT_KEEP_RECENT_TURNS))
    keep_messages = keep * 2

                                                                    
    head: list[dict] = []
    rest: list[dict] = []
    body_started = False
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).lower()
        if not body_started and role not in ("user", "assistant"):
            head.append(m)
        else:
            body_started = True
            rest.append(m)

    if len(rest) <= keep_messages:
                              
        return CompressionResult(
            head=head,
            memory_message=None,
            recent_messages=rest,
            compression_summary={
                "compressed": False,
                "kept_count": len(rest),
                "summarized_count": 0,
            },
            memory=CompressedMemory(),
        )

    cutoff = len(rest) - keep_messages
    older = rest[:cutoff]
    recent = rest[cutoff:]

    memory = _extract_signals(older)
    memory_message: Optional[dict] = None
    if not memory.is_empty():
        memory_message = {
            "role":    "system",
            "content": memory.to_system_block(),
        }

    return CompressionResult(
        head=head,
        memory_message=memory_message,
        recent_messages=recent,
        compression_summary={
            "compressed":       True,
            "kept_count":       len(recent),
            "summarized_count": len(older),
            "memory_chars":     (
                len(memory_message["content"]) if memory_message else 0
            ),
        },
        memory=memory,
    )


__all__ = [
    "DEFAULT_KEEP_RECENT_TURNS",
    "MAX_MEMORY_BLOCK_CHARS",
    "CompressedMemory",
    "CompressionResult",
    "compress_messages",
]
