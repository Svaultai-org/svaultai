

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional


logger = logging.getLogger(__name__)


CONTEXT_CREDENTIAL_DRAFT:      str = "credential_draft"
CONTEXT_SECURE_ITEM_DRAFT:     str = "secure_item_draft"
CONTEXT_FILE_SEARCH_RESULTS:   str = "file_search_results"
                                                                 
                                                          
CONTEXT_SECURE_ITEM_RESULTS:   str = "secure_item_results"
                                                          
                                                              
CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION: str = (
    "secure_item_delete_confirmation"
)
CONTEXT_VAULT_QUESTION:        str = "vault_question"
CONTEXT_GENERAL_CHAT:          str = "general_chat"

ALL_CONTEXTS: frozenset[str] = frozenset({
    CONTEXT_CREDENTIAL_DRAFT,
    CONTEXT_SECURE_ITEM_DRAFT,
    CONTEXT_SECURE_ITEM_RESULTS,
    CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION,
    CONTEXT_FILE_SEARCH_RESULTS,
    CONTEXT_VAULT_QUESTION,
    CONTEXT_GENERAL_CHAT,
})


DEFAULT_TTL_SECONDS: int = int(
    os.getenv("VAULTAI_ACTIVE_CONTEXT_TTL_S", "1800"),
)


_lock = threading.Lock()
                                 
_store: dict[str, tuple[str, float]] = {}


def _now() -> float:
    return time.time()


def set_active_context(
    vault_id: str,
    context: str,
    *,
    ttl_seconds: Optional[int] = None,
) -> None:


    if not vault_id or not isinstance(vault_id, str):
        return
    if context not in ALL_CONTEXTS:
                                                              
                                                              
        logger.warning(
            "[ACTIVE-CTX] rejected_unknown_label vault=%s label=%s",
            (vault_id or "")[:8] + "…",
            context,
        )
        return
    ttl = int(ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS)
    if ttl <= 0:
        ttl = DEFAULT_TTL_SECONDS
    expires_at = _now() + ttl
    with _lock:
        _store[vault_id] = (context, expires_at)
                                                                     
    logger.info(
        "[ACTIVE-CTX] set vault=%s ctx=%s ttl=%d",
        (vault_id or "")[:8] + "…",
        context,
        ttl,
    )


def get_active_context(vault_id: str) -> Optional[str]:


    if not vault_id or not isinstance(vault_id, str):
        return None
    now = _now()
    with _lock:
        entry = _store.get(vault_id)
        if entry is None:
            return None
        label, expires_at = entry
        if now >= expires_at:
            _store.pop(vault_id, None)
            return None
        return label


def clear_active_context(vault_id: str) -> bool:


    if not vault_id or not isinstance(vault_id, str):
        return False
    with _lock:
        return _store.pop(vault_id, None) is not None


def _reset_store_for_test() -> None:

    with _lock:
        _store.clear()


def _snapshot_for_test() -> dict[str, tuple[str, float]]:

    with _lock:
        return dict(_store)


__all__ = [
    "CONTEXT_CREDENTIAL_DRAFT",
    "CONTEXT_SECURE_ITEM_DRAFT",
    "CONTEXT_SECURE_ITEM_RESULTS",
    "CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION",
    "CONTEXT_FILE_SEARCH_RESULTS",
    "CONTEXT_VAULT_QUESTION",
    "CONTEXT_GENERAL_CHAT",
    "ALL_CONTEXTS",
    "DEFAULT_TTL_SECONDS",
    "set_active_context",
    "get_active_context",
    "clear_active_context",
]
