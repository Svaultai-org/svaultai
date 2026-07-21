"""Pending secure-item drafts (files, attachments, one-shot secrets)
awaiting user "save this / save it" confirmation.

Backed by ``vault_chat_state_store`` so drafts survive worker-hop
in a multi-worker Uvicorn deploy. Prior to 2026-07-22 this module
held drafts in a per-process ``_store`` dict; the "attach file" or
"generate item" turn would land on worker A and "save this" would
round-robin to worker B whose dict was empty, and the assistant
would falsely reply "I don't have a pending save right now" even
though the user had literally just attached the file.

Public API (unchanged from the pre-fix module):

    store_secure_item_draft(
        vault_id, category, title, field?, value?, notes?,
        network?, ttl_seconds?,
    ) → SecureItemDraft
    get_latest_secure_item_draft(vault_id) → Optional[SecureItemDraft]
    consume_secure_item_draft(vault_id, draft_id?) → Optional[SecureItemDraft]
    update_pending_secure_item_draft_title(vault_id, title) → Optional[SecureItemDraft]
    clear_secure_item_drafts_for_vault(vault_id) → int
    _reset_store_for_test()
    _drafts_for_test(vault_id) → list[SecureItemDraft]

Storage model, security notes, and TTL policy match
``vault_credential_draft`` — see that module's docstring.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from vault_chat_state_store import (
    compose_index_key, compose_key, get_chat_state_backend,
)


logger = logging.getLogger(__name__)


DRAFT_TTL_SECONDS: int = 600


_BUCKET: str = "sec_item_draft"


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


def _serialize(draft: SecureItemDraft) -> bytes:
    payload = {
        "draft_id":   draft.draft_id,
        "vault_id":   draft.vault_id,
        "category":   draft.category,
        "title":      draft.title,
        "field":      draft.field,
        "value":      draft.value,
        "notes":      draft.notes,
        "created_at": draft.created_at,
        "expires_at": draft.expires_at,
        "saved":      draft.saved,
        "network":    draft.network,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _deserialize(raw: bytes) -> Optional[SecureItemDraft]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.warning(
            "sec_item_draft deserialization failed (%s) — "
            "dropping the entry", type(e).__name__,
        )
        return None
    try:
        return SecureItemDraft(
            draft_id=str(d.get("draft_id") or ""),
            vault_id=str(d.get("vault_id") or ""),
            category=str(d.get("category") or ""),
            title=str(d.get("title") or ""),
            field=(str(d["field"]) if d.get("field") is not None else None),
            value=(str(d["value"]) if d.get("value") is not None else None),
            notes=(str(d["notes"]) if d.get("notes") is not None else None),
            created_at=float(d.get("created_at") or 0.0),
            expires_at=float(d.get("expires_at") or 0.0),
            saved=bool(d.get("saved") or False),
            network=(str(d["network"]) if d.get("network") is not None else None),
        )
    except Exception as e:
        logger.warning(
            "sec_item_draft field parse failed (%s) — dropping "
            "the entry", type(e).__name__,
        )
        return None


def _write(draft: SecureItemDraft, ttl_seconds: int) -> None:
    backend = get_chat_state_backend()
    kv_key = compose_key(
        bucket=_BUCKET, vault_id=draft.vault_id, sub=draft.draft_id,
    )
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=draft.vault_id,
    )
    backend.set(kv_key, _serialize(draft), ttl_seconds)
    backend.sadd(idx_key, draft.draft_id, ttl_seconds)


def _read_by_draft_id(
    vault_id: str, draft_id: str,
) -> Optional[SecureItemDraft]:
    if not (vault_id and draft_id):
        return None
    backend = get_chat_state_backend()
    kv_key = compose_key(
        bucket=_BUCKET, vault_id=vault_id, sub=draft_id,
    )
    raw = backend.get(kv_key)
    if raw is None:
        idx_key = compose_index_key(
            bucket=_BUCKET, vault_id=vault_id,
        )
        backend.srem(idx_key, draft_id)
        return None
    return _deserialize(raw)


def _read_all(vault_id: str) -> list[SecureItemDraft]:
    if not vault_id:
        return []
    backend = get_chat_state_backend()
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=vault_id,
    )
    members = backend.smembers(idx_key)
    out: list[SecureItemDraft] = []
    dead: list[str] = []
    for draft_id in members:
        kv_key = compose_key(
            bucket=_BUCKET, vault_id=vault_id, sub=draft_id,
        )
        raw = backend.get(kv_key)
        if raw is None:
            dead.append(draft_id)
            continue
        draft = _deserialize(raw)
        if draft is None:
            dead.append(draft_id)
            continue
        out.append(draft)
    for stale in dead:
        backend.srem(idx_key, stale)
    return out


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
    _write(draft, ttl)
    return draft


def get_latest_secure_item_draft(
    *, vault_id: str,
) -> Optional[SecureItemDraft]:
    if not vault_id:
        return None
    now = _now()
    candidates = [
        d for d in _read_all(vault_id)
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
    if draft_id:
        target = _read_by_draft_id(vault_id, draft_id)
        if target is None or target.is_expired(now) or target.saved:
            return None
    else:
        candidates = [
            d for d in _read_all(vault_id)
            if not d.is_expired(now) and not d.saved
        ]
        if not candidates:
            return None
        target = max(candidates, key=lambda d: d.created_at)
    backend = get_chat_state_backend()
    kv_key = compose_key(
        bucket=_BUCKET, vault_id=target.vault_id, sub=target.draft_id,
    )
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=target.vault_id,
    )
    backend.delete(kv_key)
    backend.srem(idx_key, target.draft_id)
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
    candidates = [
        d for d in _read_all(vault_id)
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

    ttl = max(1, int(updated.expires_at - now))
    _write(updated, ttl)
    return updated


def clear_secure_item_drafts_for_vault(vault_id: str) -> int:
    if not vault_id:
        return 0
    backend = get_chat_state_backend()
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=vault_id,
    )
    members = backend.smembers(idx_key)
    count = 0
    for draft_id in members:
        kv_key = compose_key(
            bucket=_BUCKET, vault_id=vault_id, sub=draft_id,
        )
        backend.delete(kv_key)
        count += 1
    backend.sclear(idx_key)
    return count


def _drafts_for_test(vault_id: str) -> list[SecureItemDraft]:
    return _read_all(vault_id)


def _reset_store_for_test() -> None:
    from vault_chat_state_store import (
        reset_chat_state_backend_for_tests,
    )
    reset_chat_state_backend_for_tests()


__all__ = [
    "SecureItemDraft",
    "DRAFT_TTL_SECONDS",
    "store_secure_item_draft",
    "get_latest_secure_item_draft",
    "consume_secure_item_draft",
    "clear_secure_item_drafts_for_vault",
]
