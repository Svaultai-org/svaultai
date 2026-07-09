

from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field, replace
from typing import Optional


RESULT_TYPE_CREDENTIAL_FILES   = "credential_files"
RESULT_TYPE_FILE_TEXT          = "file_text"
RESULT_TYPE_SEMANTIC_SEARCH    = "semantic_search"
RESULT_TYPE_FOLDER_LIST        = "folder_list"
RESULT_TYPE_LIST_BY_TAG        = "list_by_tag"
RESULT_TYPE_RELATED_FILES      = "related_files"
RESULT_TYPE_FILE_RETRIEVAL     = "file_retrieval"
RESULT_TYPE_RECENT_UPLOADS     = "recent_uploads"

RESULT_TYPES = (
    RESULT_TYPE_CREDENTIAL_FILES,
    RESULT_TYPE_FILE_TEXT,
    RESULT_TYPE_SEMANTIC_SEARCH,
    RESULT_TYPE_FOLDER_LIST,
    RESULT_TYPE_LIST_BY_TAG,
    RESULT_TYPE_RELATED_FILES,
    RESULT_TYPE_FILE_RETRIEVAL,
    RESULT_TYPE_RECENT_UPLOADS,
)

                                                                  
EVIDENCE_SOURCE_EXTRACTED_TEXT  = "extracted_text"
EVIDENCE_SOURCE_FILENAME_ONLY   = "filename_only"
EVIDENCE_SOURCE_SEMANTIC        = "semantic"
EVIDENCE_SOURCE_FILENAME_AND_CONTENT = "filename_and_content"
EVIDENCE_SOURCE_ARCHIVE_INDEX   = "archive_index"
EVIDENCE_SOURCE_METADATA        = "metadata"
EVIDENCE_SOURCE_TAG_INDEX       = "tag_index"

EVIDENCE_SOURCES = (
    EVIDENCE_SOURCE_EXTRACTED_TEXT,
    EVIDENCE_SOURCE_FILENAME_ONLY,
    EVIDENCE_SOURCE_SEMANTIC,
    EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
    EVIDENCE_SOURCE_ARCHIVE_INDEX,
    EVIDENCE_SOURCE_METADATA,
    EVIDENCE_SOURCE_TAG_INDEX,
)


_STORAGE_KEY = "last_assistant_result_v2"


@dataclass(frozen=True)
class LastAssistantResult:


    result_type:         str
    query:               str
    intent:              str
    file_ids_returned:   tuple[str, ...]
    file_ids_excluded:   tuple[str, ...]
    total_matches_known: int
    coverage_at_time:    dict
    is_partial:          bool
    evidence_source:     str
    timestamp_unix:      float
    job_id:              Optional[str] = None

    def to_storage_dict(self) -> dict:


        return {
            "result_type":         str(self.result_type),
            "query":               str(self.query),
            "intent":              str(self.intent),
            "file_ids_returned":   [str(x) for x in self.file_ids_returned],
            "file_ids_excluded":   [str(x) for x in self.file_ids_excluded],
            "total_matches_known": int(self.total_matches_known),
            "coverage_at_time":    dict(self.coverage_at_time or {}),
            "is_partial":          bool(self.is_partial),
            "evidence_source":     str(self.evidence_source),
            "timestamp_unix":      float(self.timestamp_unix),
            "job_id":              (str(self.job_id) if self.job_id else None),
        }

    @classmethod
    def from_storage_dict(cls, raw: dict) -> Optional["LastAssistantResult"]:


        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                result_type=str(raw.get("result_type") or ""),
                query=str(raw.get("query") or ""),
                intent=str(raw.get("intent") or ""),
                file_ids_returned=tuple(
                    str(x) for x in (raw.get("file_ids_returned") or [])
                ),
                file_ids_excluded=tuple(
                    str(x) for x in (raw.get("file_ids_excluded") or [])
                ),
                total_matches_known=int(raw.get("total_matches_known") or 0),
                coverage_at_time=dict(raw.get("coverage_at_time") or {}),
                is_partial=bool(raw.get("is_partial")),
                evidence_source=str(raw.get("evidence_source") or ""),
                timestamp_unix=float(raw.get("timestamp_unix") or 0.0),
                job_id=(raw.get("job_id") if raw.get("job_id") else None),
            )
        except (TypeError, ValueError):
            return None

    def age_seconds(self, now_unix: Optional[float] = None) -> float:
        ref = float(now_unix) if now_unix is not None else time.time()
        return max(0.0, ref - float(self.timestamp_unix))


def set_last_assistant_result(
    vault_id: str,
    result: LastAssistantResult,
) -> None:

    if not vault_id:
        return
    if result.result_type not in RESULT_TYPES:
        raise ValueError(
            f"result_type must be one of RESULT_TYPES, got {result.result_type!r}"
        )
    if result.evidence_source not in EVIDENCE_SOURCES:
        raise ValueError(
            "evidence_source must be one of EVIDENCE_SOURCES, "
            f"got {result.evidence_source!r}"
        )
    from vault_chat_memory import get_memory
    memory = get_memory(vault_id)
    memory[_STORAGE_KEY] = result.to_storage_dict()


def get_last_assistant_result(
    vault_id: str,
) -> Optional[LastAssistantResult]:


    if not vault_id:
        return None
    from vault_chat_memory import CHAT_MEMORY, memory_key
    raw = CHAT_MEMORY.get(memory_key(vault_id))
    if not isinstance(raw, dict):
        return None
    snapshot = raw.get(_STORAGE_KEY)
    if not isinstance(snapshot, dict):
        return None
    return LastAssistantResult.from_storage_dict(snapshot)


def clear_last_assistant_result(vault_id: str) -> None:


    if not vault_id:
        return
    from vault_chat_memory import CHAT_MEMORY, memory_key
    raw = CHAT_MEMORY.get(memory_key(vault_id))
    if isinstance(raw, dict) and _STORAGE_KEY in raw:
        raw.pop(_STORAGE_KEY, None)


def make_credential_search_result(
    *,
    query: str,
    file_ids_returned: list[str],
    file_ids_excluded: list[str],
    total_matches_known: int,
    coverage: dict,
    is_partial: bool,
    job_id: Optional[str] = None,
    evidence_source: str = EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
) -> LastAssistantResult:


    return LastAssistantResult(
        result_type=RESULT_TYPE_CREDENTIAL_FILES,
        query=query,
        intent="search_files_for_credentials",
        file_ids_returned=tuple(str(x) for x in file_ids_returned),
        file_ids_excluded=tuple(str(x) for x in file_ids_excluded),
        total_matches_known=int(total_matches_known),
        coverage_at_time=dict(coverage or {}),
        is_partial=bool(is_partial),
        evidence_source=evidence_source,
        timestamp_unix=time.time(),
        job_id=job_id,
    )


__all__ = [
    "LastAssistantResult",
    "RESULT_TYPES",
    "RESULT_TYPE_CREDENTIAL_FILES",
    "RESULT_TYPE_FILE_TEXT",
    "RESULT_TYPE_SEMANTIC_SEARCH",
    "RESULT_TYPE_FOLDER_LIST",
    "RESULT_TYPE_LIST_BY_TAG",
    "RESULT_TYPE_RELATED_FILES",
    "RESULT_TYPE_FILE_RETRIEVAL",
    "RESULT_TYPE_RECENT_UPLOADS",
    "EVIDENCE_SOURCES",
    "EVIDENCE_SOURCE_EXTRACTED_TEXT",
    "EVIDENCE_SOURCE_FILENAME_ONLY",
    "EVIDENCE_SOURCE_SEMANTIC",
    "EVIDENCE_SOURCE_FILENAME_AND_CONTENT",
    "EVIDENCE_SOURCE_ARCHIVE_INDEX",
    "EVIDENCE_SOURCE_METADATA",
    "EVIDENCE_SOURCE_TAG_INDEX",
    "set_last_assistant_result",
    "get_last_assistant_result",
    "clear_last_assistant_result",
    "make_credential_search_result",
]
