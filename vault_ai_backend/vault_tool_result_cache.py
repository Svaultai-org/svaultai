

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)


CACHEABLE_TOOLS: frozenset[str] = frozenset({
                  
    "get_vault_status",
    "get_vault_overview",
    "get_vault_intelligence",
                                    
    "list_vault_files",
    "list_files_by_category",
    "list_document_categories",
    "get_file_metadata",
    "inspect_uploaded_file",
    "list_file_chunks",
                                                     
    "list_vault_entities",
    "find_files_for_entity",
    "list_file_relationships",
                      
    "list_expiring_items",
    "get_expiry_alert",
                                                 
    "get_vault_activity",
                                                               
                                   
    "list_saved_credentials",
    "get_credential_metadata",
    "list_secrets",
                                                    
    "search_extracted_text",
    "search_vault_content",
})


NEVER_CACHEABLE_TOOLS: frozenset[str] = frozenset({
                                                                 
    "save_secret",
    "save_generated_credential_after_confirmation",
                                            
    "retrieve_secret",
                                                              
                
    "read_file_text",
    "read_image_with_vision",
    "read_media_transcript",
    "read_file_chunk",
                                                                
                                                               
    "generate_credential_draft",
                                                            
                                                          
    "find_in_vault",
})


SHORT_TTL_TOOLS: frozenset[str] = frozenset({
    "get_vault_activity",
})


DEFAULT_TTL_SECS: float = float(
    os.getenv("VAULTAI_TOOL_CACHE_TTL_SECS", "300"),
)
SHORT_TTL_SECS: float = float(
    os.getenv("VAULTAI_TOOL_CACHE_SHORT_TTL_SECS", "60"),
)
MAX_CACHE_ENTRIES: int = int(
    os.getenv("VAULTAI_TOOL_CACHE_MAX_ENTRIES", "10000"),
)


INVALIDATION_RULES: dict[str, frozenset[str]] = {
    "file_uploaded": frozenset({
        "get_vault_status", "get_vault_overview",
        "get_vault_intelligence",
        "list_vault_files", "list_files_by_category",
        "list_document_categories",
        "get_vault_activity",
        "search_extracted_text", "search_vault_content",
        "list_vault_entities", "find_files_for_entity",
        "inspect_uploaded_file", "get_file_metadata",
        "list_file_chunks",
    }),
    "file_deleted": frozenset({
        "get_vault_status", "get_vault_overview",
        "get_vault_intelligence",
        "list_vault_files", "list_files_by_category",
        "list_document_categories",
        "get_vault_activity",
        "search_extracted_text", "search_vault_content",
        "list_vault_entities", "find_files_for_entity",
        "list_file_relationships",
        "inspect_uploaded_file", "get_file_metadata",
        "list_file_chunks",
        "list_expiring_items", "get_expiry_alert",
    }),
    "file_renamed": frozenset({
        "list_vault_files",
        "get_file_metadata", "inspect_uploaded_file",
        "search_extracted_text",
    }),
    "file_analysis_changed": frozenset({
        "get_vault_intelligence", "get_vault_status",
        "get_vault_overview",
        "list_document_categories", "list_files_by_category",
        "list_vault_entities", "find_files_for_entity",
        "list_file_relationships",
        "inspect_uploaded_file", "list_file_chunks",
        "search_extracted_text", "search_vault_content",
    }),
    "credential_saved": frozenset({
        "list_saved_credentials", "list_secrets",
        "get_credential_metadata",
        "get_vault_status", "get_vault_overview",
        "get_vault_intelligence",
        "get_vault_activity",
    }),
    "credential_edited": frozenset({
        "list_saved_credentials", "list_secrets",
        "get_credential_metadata",
        "get_vault_intelligence",
    }),
    "credential_deleted": frozenset({
        "list_saved_credentials", "list_secrets",
        "get_credential_metadata",
        "get_vault_status", "get_vault_overview",
        "get_vault_intelligence",
    }),
    "expiry_updated": frozenset({
        "list_expiring_items", "get_expiry_alert",
        "get_vault_intelligence",
    }),
}


@dataclass(frozen=True)
class _CacheKey:
    vault_id:  str
    token_id:  str
    tool_name: str
    args_hash: str

    def short(self) -> str:


        return (
            f"{self.vault_id[:8]}/"
            f"{self.token_id[:6]}/"
            f"{self.tool_name}/"
            f"{self.args_hash[:8]}"
        )


@dataclass
class _Entry:
    result:     str
    expires_at: float


def _normalize_args(args: Any) -> Any:


    if isinstance(args, dict):
        out: dict = {}
        for k in sorted(args.keys()):
            v = _normalize_args(args[k])
            if v is None or v == "" or v == [] or v == {}:
                continue
            out[k] = v
        return out
    if isinstance(args, list):
        return [_normalize_args(x) for x in args]
    if isinstance(args, str):
        return args.strip()
    return args


def _hash_args(args: Any) -> str:
    norm = _normalize_args(args or {})
    try:
        blob = json.dumps(norm, sort_keys=True, ensure_ascii=False)
    except Exception:
                                                              
        blob = repr(norm)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ToolResultCache:


    def __init__(
        self,
        *,
        default_ttl: float = DEFAULT_TTL_SECS,
        short_ttl:   float = SHORT_TTL_SECS,
        max_size:    int   = MAX_CACHE_ENTRIES,
    ) -> None:
        self._default_ttl = float(default_ttl)
        self._short_ttl   = float(short_ttl)
        self._max_size    = int(max_size)
        self._lock = threading.RLock()
        self._entries: dict[_CacheKey, _Entry] = {}
        self._by_vault: dict[str, set[_CacheKey]] = {}
        self._by_session: dict[tuple[str, str], set[_CacheKey]] = {}

                                  
    def is_cacheable(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        if tool_name in NEVER_CACHEABLE_TOOLS:
            return False
        return tool_name in CACHEABLE_TOOLS

    def get(
        self,
        *,
        vault_id: str, token_id: str,
        tool_name: str, args: Any,
    ) -> Optional[str]:


        if not self.is_cacheable(tool_name):
            return None
        key = self._build_key(vault_id, token_id, tool_name, args)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                _emit_cache_event(
                    hit=False, tool_name=tool_name,
                    vault_id=vault_id, ttl_remaining=0.0,
                )
                return None
            if entry.expires_at <= now:
                              
                self._drop_locked(key)
                _emit_cache_event(
                    hit=False, tool_name=tool_name,
                    vault_id=vault_id, ttl_remaining=0.0,
                )
                return None
            ttl_remaining = entry.expires_at - now
            _emit_cache_event(
                hit=True, tool_name=tool_name,
                vault_id=vault_id,
                ttl_remaining=ttl_remaining,
            )
            return entry.result

    def put(
        self,
        *,
        vault_id: str, token_id: str,
        tool_name: str, args: Any, result: str,
    ) -> bool:


        if not self.is_cacheable(tool_name):
            return False
        if not isinstance(result, str) or not result:
            return False
        if not vault_id or not token_id:
            return False
        ttl = (
            self._short_ttl
            if tool_name in SHORT_TTL_TOOLS
            else self._default_ttl
        )
        key = self._build_key(vault_id, token_id, tool_name, args)
        expires_at = time.monotonic() + ttl
        with self._lock:
            self._evict_if_full_locked()
            self._entries[key] = _Entry(
                result=result, expires_at=expires_at,
            )
            self._by_vault.setdefault(
                vault_id, set(),
            ).add(key)
            self._by_session.setdefault(
                (vault_id, token_id), set(),
            ).add(key)
        return True

    def invalidate_for_event(
        self, *, vault_id: str, event: str,
    ) -> int:


        if not vault_id or not event:
            return 0
        invalidated_tools = INVALIDATION_RULES.get(event)
        if not invalidated_tools:
            return 0
        dropped = 0
        with self._lock:
            keys = list(self._by_vault.get(vault_id, set()))
            for k in keys:
                if k.tool_name in invalidated_tools:
                    self._drop_locked(k)
                    dropped += 1
        if dropped:
            logger.info(
                "[TOOL-CACHE] invalidated vault=%s event=%s "
                "entries_dropped=%d",
                (vault_id or "")[:8], event, dropped,
            )
        return dropped

    def invalidate_session(
        self, *, vault_id: str, token_id: str,
    ) -> int:


        if not vault_id or not token_id:
            return 0
        dropped = 0
        with self._lock:
            keys = list(self._by_session.get((vault_id, token_id), set()))
            for k in keys:
                self._drop_locked(k)
                dropped += 1
        if dropped:
            logger.info(
                "[TOOL-CACHE] invalidated_session vault=%s "
                "token=%s entries_dropped=%d",
                (vault_id or "")[:8],
                (token_id or "")[:6],
                dropped,
            )
        return dropped

    def invalidate_vault(self, *, vault_id: str) -> int:

        if not vault_id:
            return 0
        dropped = 0
        with self._lock:
            keys = list(self._by_vault.get(vault_id, set()))
            for k in keys:
                self._drop_locked(k)
                dropped += 1
        if dropped:
            logger.info(
                "[TOOL-CACHE] invalidated_vault vault=%s "
                "entries_dropped=%d",
                (vault_id or "")[:8], dropped,
            )
        return dropped

    def clear(self) -> int:

        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            self._by_vault.clear()
            self._by_session.clear()
        return n

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

                                 
    def _build_key(
        self, vault_id: str, token_id: str,
        tool_name: str, args: Any,
    ) -> _CacheKey:
        return _CacheKey(
            vault_id=vault_id or "",
            token_id=token_id or "",
            tool_name=tool_name or "",
            args_hash=_hash_args(args),
        )

    def _drop_locked(self, key: _CacheKey) -> None:
        self._entries.pop(key, None)
        bucket = self._by_vault.get(key.vault_id)
        if bucket is not None:
            bucket.discard(key)
            if not bucket:
                self._by_vault.pop(key.vault_id, None)
        sb = self._by_session.get((key.vault_id, key.token_id))
        if sb is not None:
            sb.discard(key)
            if not sb:
                self._by_session.pop((key.vault_id, key.token_id), None)

    def _evict_if_full_locked(self) -> None:
        if len(self._entries) < self._max_size:
            return
                                                               
                                                                 
        soonest = None
        soonest_t = float("inf")
        for k, e in self._entries.items():
            if e.expires_at < soonest_t:
                soonest = k
                soonest_t = e.expires_at
        if soonest is not None:
            self._drop_locked(soonest)


def _emit_cache_event(
    *,
    hit: bool, tool_name: str, vault_id: str,
    ttl_remaining: float,
) -> None:


    try:
        logger.info(
            "[TOOL-CACHE] cache_hit=%s tool_name=%s "
            "vault_prefix=%s ttl_remaining_s=%.1f",
            "true" if hit else "false",
            tool_name,
            (vault_id or "")[:8],
            max(0.0, float(ttl_remaining)),
        )
    except Exception:
                                                  
        pass


_GLOBAL_CACHE: Optional[ToolResultCache] = None
_GLOBAL_CACHE_LOCK = threading.Lock()


def get_cache() -> ToolResultCache:


    global _GLOBAL_CACHE
    with _GLOBAL_CACHE_LOCK:
        if _GLOBAL_CACHE is None:
            _GLOBAL_CACHE = ToolResultCache()
    return _GLOBAL_CACHE


def reset_cache_for_tests() -> None:

    global _GLOBAL_CACHE
    with _GLOBAL_CACHE_LOCK:
        _GLOBAL_CACHE = None


def maybe_get_cached(
    *,
    vault_id: str, token_id: str,
    tool_name: str, args: Any,
) -> Optional[str]:
    return get_cache().get(
        vault_id=vault_id, token_id=token_id,
        tool_name=tool_name, args=args,
    )


def maybe_store(
    *,
    vault_id: str, token_id: str,
    tool_name: str, args: Any, result: str,
) -> bool:
    return get_cache().put(
        vault_id=vault_id, token_id=token_id,
        tool_name=tool_name, args=args, result=result,
    )


def invalidate_for_event(*, vault_id: str, event: str) -> int:


    return get_cache().invalidate_for_event(
        vault_id=vault_id, event=event,
    )


def invalidate_session(*, vault_id: str, token_id: str) -> int:

    return get_cache().invalidate_session(
        vault_id=vault_id, token_id=token_id,
    )


__all__ = [
    "CACHEABLE_TOOLS",
    "NEVER_CACHEABLE_TOOLS",
    "SHORT_TTL_TOOLS",
    "DEFAULT_TTL_SECS",
    "SHORT_TTL_SECS",
    "INVALIDATION_RULES",
    "ToolResultCache",
    "get_cache",
    "reset_cache_for_tests",
    "maybe_get_cached",
    "maybe_store",
    "invalidate_for_event",
    "invalidate_session",
]
