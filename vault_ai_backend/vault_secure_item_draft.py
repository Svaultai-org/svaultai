

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field as _field
from typing import Optional


DRAFT_TTL_SECONDS: int = 600


_lock = threading.Lock()
                                                                    
_store: dict[str, dict[str, "SecureItemDraft"]] = {}


@dataclass(frozen=True)
class SecureItemDraft:


    draft_id:    str
    vault_id:    str
    category:    str
    title:       str
    field:       Optional[str]
    value:       Optional[str]
    notes:       Optional[str]
    created_at:  float
    expires_at:  float
    saved:       bool = False
                                                                 
                                                              
    network:     Optional[str] = None

    def __repr__(self) -> str:                          
        return (
            f"SecureItemDraft(draft_id={self.draft_id!r}, "
            f"vault_id_prefix={self.vault_id[:8]!r}..., "
            f"category={self.category!r}, "
            f"title={self.title!r}, "
            f"field={self.field!r}, "
            f"value=<REDACTED>, saved={self.saved})"
        )

    __str__ = __repr__

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at


def _now() -> float:
    return time.time()


def _gc_expired(vault_id: str, now: float) -> None:

    bucket = _store.get(vault_id)
    if not bucket:
        return
    dead = [
        d for d, draft in bucket.items() if draft.is_expired(now)
    ]
    for d in dead:
        bucket.pop(d, None)
    if not bucket:
        _store.pop(vault_id, None)


def store_secure_item_draft(
    *,
    vault_id: str,
    category: str,
    title: str,
    field: Optional[str] = None,
    value: Optional[str] = None,
    notes: Optional[str] = None,
    network: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> SecureItemDraft:

    if not vault_id:
        raise ValueError("vault_id required")
    if not category:
        raise ValueError("category required")
    if not title:
        raise ValueError("title required")
    ttl = int(ttl_seconds if ttl_seconds is not None else DRAFT_TTL_SECONDS)
    if ttl <= 0:
        ttl = DRAFT_TTL_SECONDS
    now = _now()
    draft = SecureItemDraft(
        draft_id=uuid.uuid4().hex,
        vault_id=vault_id,
        category=category,
        title=title.strip(),
        field=field,
        value=value,
        notes=notes,
        created_at=now,
        expires_at=now + ttl,
        saved=False,
        network=network,
    )
    with _lock:
        bucket = _store.setdefault(vault_id, {})
        bucket[draft.draft_id] = draft
    return draft


def get_latest_secure_item_draft(
    *, vault_id: str,
) -> Optional[SecureItemDraft]:


    if not vault_id:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        bucket = _store.get(vault_id)
        if not bucket:
            return None
        candidates = [
            d for d in bucket.values()
            if not d.is_expired(now) and not d.saved
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.created_at)


def consume_secure_item_draft(
    *, vault_id: str, draft_id: Optional[str] = None,
) -> Optional[SecureItemDraft]:


    if not vault_id:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        bucket = _store.get(vault_id)
        if not bucket:
            return None
        if draft_id:
            target = bucket.get(draft_id)
            if target is None or target.is_expired(now) or target.saved:
                return None
        else:
            candidates = [
                d for d in bucket.values()
                if not d.is_expired(now) and not d.saved
            ]
            if not candidates:
                return None
            target = max(candidates, key=lambda d: d.created_at)
        bucket.pop(target.draft_id, None)
        if not bucket:
            _store.pop(vault_id, None)
    return SecureItemDraft(
        draft_id=target.draft_id,
        vault_id=target.vault_id,
        category=target.category,
        title=target.title,
        field=target.field,
        value=target.value,
        notes=target.notes,
        created_at=target.created_at,
        expires_at=target.expires_at,
        saved=True,
        network=target.network,
    )


def update_pending_secure_item_draft_title(
    *, vault_id: str, title: str,
) -> Optional[SecureItemDraft]:


    if not vault_id:
        return None
    safe_title = (title or "").strip()
    if not safe_title:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        bucket = _store.get(vault_id)
        if not bucket:
            return None
        candidates = [
            d for d in bucket.values()
            if not d.is_expired(now) and not d.saved
        ]
        if not candidates:
            return None
        target = max(candidates, key=lambda d: d.created_at)
        updated = SecureItemDraft(
            draft_id=target.draft_id,
            vault_id=target.vault_id,
            category=target.category,
            title=safe_title,
            field=target.field,
            value=target.value,
            notes=target.notes,
            created_at=target.created_at,
            expires_at=target.expires_at,
            saved=False,
            network=target.network,
        )
        bucket[target.draft_id] = updated
    return updated


def clear_secure_item_drafts_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    with _lock:
        bucket = _store.pop(vault_id, None)
    return len(bucket) if bucket else 0


def _drafts_for_test(vault_id: str) -> list[SecureItemDraft]:


    with _lock:
        bucket = _store.get(vault_id) or {}
        return list(bucket.values())


def _reset_store_for_test() -> None:

    with _lock:
        _store.clear()


__all__ = [
    "SecureItemDraft",
    "DRAFT_TTL_SECONDS",
    "store_secure_item_draft",
    "get_latest_secure_item_draft",
    "consume_secure_item_draft",
    "clear_secure_item_drafts_for_vault",
]
