

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


DRAFT_TTL_SECONDS: int = 600

_lock = threading.Lock()
                                                                    
_store: dict[str, dict[str, "CredentialDraft"]] = {}


@dataclass(frozen=True)
class CredentialDraft:


    draft_id:     str
    vault_id:     str
    service_name: str
    username:     str
    password:     str
    created_at:   float
    expires_at:   float
                                        
                                                               
    saved:        bool = False
                                                              
                                                              
    service_key:  str = ""

    def __repr__(self) -> str:                          
        return (
            f"CredentialDraft(draft_id={self.draft_id!r}, "
            f"vault_id_prefix={self.vault_id[:8]!r}..., "
            f"service_name={self.service_name!r}, "
            f"username_len={len(self.username)}, "
            f"password=<REDACTED>, saved={self.saved})"
        )

    __str__ = __repr__

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def to_public_dict(self) -> dict:


        return {
            "draft_id":     self.draft_id,
            "service_name": self.service_name,
            "username":     self.username,
            "password":     self.password,
            "expires_at":   int(self.expires_at),
            "saved":        bool(self.saved),
        }


def _service_key(service_name: str) -> str:
    return (service_name or "").strip().lower()


def _now() -> float:
    return time.time()


def _gc_expired(vault_id: str, now: float) -> None:

    bucket = _store.get(vault_id)
    if not bucket:
        return
    dead = [d for d, draft in bucket.items() if draft.is_expired(now)]
    for d in dead:
        bucket.pop(d, None)
    if not bucket:
        _store.pop(vault_id, None)


def store_draft(
    *,
    vault_id: str,
    service_name: str,
    username: str,
    password: str,
    ttl_seconds: Optional[int] = None,
) -> CredentialDraft:


    if not vault_id:
        raise ValueError("vault_id required")
    if not service_name:
        raise ValueError("service_name required")
    if not username:
        raise ValueError("username required")
    if not password:
        raise ValueError("password required")

    ttl = int(ttl_seconds if ttl_seconds is not None else DRAFT_TTL_SECONDS)
    if ttl <= 0:
        ttl = DRAFT_TTL_SECONDS

    now = _now()
    draft_id = uuid.uuid4().hex
    draft = CredentialDraft(
        draft_id=draft_id,
        vault_id=vault_id,
        service_name=service_name.strip(),
        username=username,
        password=password,
        created_at=now,
        expires_at=now + ttl,
        saved=False,
        service_key=_service_key(service_name),
    )
    with _lock:
        bucket = _store.setdefault(vault_id, {})
        bucket[draft_id] = draft
    return draft


def get_draft(
    *,
    vault_id: str,
    draft_id: Optional[str] = None,
    service_name: Optional[str] = None,
) -> Optional[CredentialDraft]:


    if not vault_id:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        bucket = _store.get(vault_id)
        if not bucket:
            return None
        if draft_id:
            d = bucket.get(draft_id)
            if d is not None and not d.is_expired(now) and not d.saved:
                return d
            return None
        candidates = [
            d for d in bucket.values()
            if not d.is_expired(now) and not d.saved
        ]
        if service_name:
            key = _service_key(service_name)
            scoped = [d for d in candidates if d.service_key == key]
            if scoped:
                candidates = scoped
            else:
                return None
        if not candidates:
            return None
                           
        return max(candidates, key=lambda d: d.created_at)


def consume_draft(
    *,
    vault_id: str,
    draft_id: Optional[str] = None,
    service_name: Optional[str] = None,
) -> Optional[CredentialDraft]:


    d = get_draft(
        vault_id=vault_id,
        draft_id=draft_id,
        service_name=service_name,
    )
    if d is None:
        return None
    with _lock:
        bucket = _store.get(vault_id)
        if bucket is not None:
            bucket.pop(d.draft_id, None)
            if not bucket:
                _store.pop(vault_id, None)
                                                             
                                                             
    return CredentialDraft(
        draft_id=d.draft_id,
        vault_id=d.vault_id,
        service_name=d.service_name,
        username=d.username,
        password=d.password,
        created_at=d.created_at,
        expires_at=d.expires_at,
        saved=True,
        service_key=d.service_key,
    )


def clear_drafts_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    with _lock:
        bucket = _store.pop(vault_id, None)
    return len(bucket) if bucket else 0


def _drafts_for_test(vault_id: str) -> list[CredentialDraft]:


    with _lock:
        bucket = _store.get(vault_id) or {}
        return list(bucket.values())


def _reset_store_for_test() -> None:

    with _lock:
        _store.clear()


__all__ = [
    "CredentialDraft",
    "DRAFT_TTL_SECONDS",
    "store_draft",
    "get_draft",
    "consume_draft",
    "clear_drafts_for_vault",
]
