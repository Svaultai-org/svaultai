

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


MAX_FILE_IDS_REMEMBERED  = 200
MAX_CHUNK_IDS_REMEMBERED = 600
MAX_QUERY_PREFIX_CHARS   = 80


@dataclass(frozen=True)
class BrainContinuation:


    vault_id:              str
    query_prefix:          str
    intent:                str
    breadth:               str
    file_ids_returned:     tuple[str, ...]
    coverage_at_time:      dict
    retrieval_mode:        str
    set_at_unix:           float
                                                             
                                                             
    chunk_ids_returned:    tuple[str, ...] = field(default_factory=tuple)

    def to_debug_dict(self) -> dict:

        return {
            "vault_id":          str(self.vault_id)[:8] + "…",
            "intent":            str(self.intent),
            "breadth":           str(self.breadth),
            "n_files_returned":  len(self.file_ids_returned),
            "n_chunks_returned": len(self.chunk_ids_returned),
            "retrieval_mode":    str(self.retrieval_mode),
            "set_at_unix":       float(self.set_at_unix),
        }


_MEMORY_KEY = "last_brain_evidence_v1"


def set_last_brain_evidence(
    *,
    vault_id: str,
    query: str,
    intent: str,
    breadth: str,
    file_ids_returned,
    coverage_at_time,
    retrieval_mode: str,
    set_at_unix: float,
    chunk_ids_returned=None,
) -> None:


    if not vault_id or not isinstance(vault_id, str):
        return
    try:
        cont = BrainContinuation(
            vault_id=str(vault_id),
            query_prefix=str(query or "")[:MAX_QUERY_PREFIX_CHARS],
            intent=str(intent or "")[:64],
            breadth=str(breadth or "")[:32],
            file_ids_returned=tuple(
                str(f) for f in (file_ids_returned or [])
            )[:MAX_FILE_IDS_REMEMBERED],
            chunk_ids_returned=tuple(
                str(c) for c in (chunk_ids_returned or [])
            )[:MAX_CHUNK_IDS_REMEMBERED],
            coverage_at_time=dict(coverage_at_time or {}),
            retrieval_mode=str(retrieval_mode or "")[:32],
            set_at_unix=float(set_at_unix or 0.0),
        )
    except Exception:
        logger.warning(
            "[brain-continuation] failed to construct context vault=%s",
            _short(vault_id),
        )
        return

    try:
        from vault_chat_memory import get_memory
        memory = get_memory(vault_id)
        memory[_MEMORY_KEY] = {
            "vault_id":           cont.vault_id,
            "query_prefix":       cont.query_prefix,
            "intent":             cont.intent,
            "breadth":            cont.breadth,
            "file_ids_returned":  list(cont.file_ids_returned),
            "chunk_ids_returned": list(cont.chunk_ids_returned),
            "coverage_at_time":   dict(cont.coverage_at_time),
            "retrieval_mode":     cont.retrieval_mode,
            "set_at_unix":        cont.set_at_unix,
        }
    except Exception:
                                                               
                                                              
        _FALLBACK_CACHE[vault_id] = cont


def get_last_brain_evidence(vault_id: str) -> Optional[BrainContinuation]:

    if not vault_id:
        return None
    try:
        from vault_chat_memory import get_memory
        memory = get_memory(vault_id) or {}
        raw = memory.get(_MEMORY_KEY)
        if isinstance(raw, dict) and raw.get("vault_id"):
            return BrainContinuation(
                vault_id=str(raw.get("vault_id") or ""),
                query_prefix=str(raw.get("query_prefix") or ""),
                intent=str(raw.get("intent") or ""),
                breadth=str(raw.get("breadth") or ""),
                file_ids_returned=tuple(
                    str(f) for f in (raw.get("file_ids_returned") or [])
                ),
                chunk_ids_returned=tuple(
                    str(c) for c in (raw.get("chunk_ids_returned") or [])
                ),
                coverage_at_time=dict(raw.get("coverage_at_time") or {}),
                retrieval_mode=str(raw.get("retrieval_mode") or ""),
                set_at_unix=float(raw.get("set_at_unix") or 0.0),
            )
    except Exception:
        pass
    return _FALLBACK_CACHE.get(vault_id)


def clear_last_brain_evidence(vault_id: str) -> None:

    if not vault_id:
        return
    try:
        from vault_chat_memory import get_memory
        memory = get_memory(vault_id) or {}
        if _MEMORY_KEY in memory:
            memory.pop(_MEMORY_KEY, None)
    except Exception:
        pass
    _FALLBACK_CACHE.pop(vault_id, None)


_FALLBACK_CACHE: dict[str, BrainContinuation] = {}


def reset_for_tests() -> None:

    _FALLBACK_CACHE.clear()


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "BrainContinuation",
    "MAX_FILE_IDS_REMEMBERED",
    "MAX_CHUNK_IDS_REMEMBERED",
    "MAX_QUERY_PREFIX_CHARS",
    "set_last_brain_evidence",
    "get_last_brain_evidence",
    "clear_last_brain_evidence",
    "reset_for_tests",
]
