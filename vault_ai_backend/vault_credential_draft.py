"""Generated credential drafts, awaiting user "save it" confirmation.

Backed by ``vault_chat_state_store`` so drafts survive worker-hop
in a multi-worker Uvicorn deploy. Prior to 2026-07-22 this module
held drafts in a per-process ``_store`` dict; the "generate login"
turn would land on worker A and the "save it" turn would round-
robin to worker B whose dict was empty, and the assistant would
falsely reply "I don't have a pending save right now" even though
the user had literally just been shown the draft.

Public API (unchanged from the pre-fix module — every caller in
main.py, vault_inspection_tools.py, and the tests continues to
work without modification):

    store_draft(vault_id, service_name, username, password, ttl_seconds?)
        → CredentialDraft
    get_draft(vault_id, draft_id?, service_name?)
        → Optional[CredentialDraft]
    consume_draft(vault_id, draft_id?, service_name?)
        → Optional[CredentialDraft]        (marks saved=True on return)
    clear_drafts_for_vault(vault_id) → int
    _reset_store_for_test()
    _drafts_for_test(vault_id) → list[CredentialDraft]

Storage model:

    Each draft is one Redis key:
        chatst:v1:cred_draft:<hashed vault_id>:<hashed draft_id>
      → JSON of {draft_id, vault_id, service_name, service_key,
                 username, password, created_at, expires_at, saved}

    A per-vault Set index enumerates all draft_ids currently held
    for that vault:
        chatst:v1:cred_draft:<hashed vault_id>:idx
      → Set of raw draft_id strings

    TTL is enforced by Redis (``PEX``); expired drafts vanish
    without a Python-side GC loop. The index entry itself may
    outlive its target key by <= DRAFT_TTL_SECONDS, but callers
    tolerate a missing GET (returning None → the index entry is
    lazily removed).

Security notes:

    * Vault IDs and draft IDs are SHA-256(first 16 hex)-hashed
      before they compose the Redis key, so raw IDs never appear
      in Redis command logs.
    * Username and password ARE stored in the value under Redis
      AUTH. That is unavoidable — "save it" has to recover those
      exact bytes on the following turn. Redis lives on the
      private production network with the same trust boundary as
      Postgres; the same values will be persisted to the vault
      table anyway on the save.
    * __repr__ / __str__ on ``CredentialDraft`` redact the
      password field so accidental log lines never print it.
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


_BUCKET: str = "cred_draft"


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
    opaque_server_storage: bool = False

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
            "opaque_server_storage": bool(self.opaque_server_storage),
        }


def _service_key(service_name: str) -> str:
    return (service_name or "").strip().lower()


def _now() -> float:
    return time.time()


def _serialize(draft: CredentialDraft) -> bytes:
    payload = {
        "draft_id":     draft.draft_id,
        "vault_id":     draft.vault_id,
        "service_name": draft.service_name,
        "service_key":  draft.service_key,
        "created_at":   draft.created_at,
        "expires_at":   draft.expires_at,
        "saved":        draft.saved,
        "opaque_server_storage": draft.opaque_server_storage,
    }
    if not draft.opaque_server_storage:
        payload["username"] = draft.username
        payload["password"] = draft.password
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _deserialize(raw: bytes) -> Optional[CredentialDraft]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.warning(
            "cred_draft deserialization failed (%s) — dropping "
            "the entry", type(e).__name__,
        )
        return None
    try:
        return CredentialDraft(
            draft_id=str(d.get("draft_id") or ""),
            vault_id=str(d.get("vault_id") or ""),
            service_name=str(d.get("service_name") or ""),
            username=str(d.get("username") or ""),
            password=str(d.get("password") or ""),
            created_at=float(d.get("created_at") or 0.0),
            expires_at=float(d.get("expires_at") or 0.0),
            saved=bool(d.get("saved") or False),
            service_key=str(d.get("service_key") or ""),
            opaque_server_storage=bool(d.get("opaque_server_storage") or False),
        )
    except Exception as e:
        logger.warning(
            "cred_draft field parse failed (%s) — dropping "
            "the entry", type(e).__name__,
        )
        return None


def _remaining_ttl(draft: CredentialDraft, now: float) -> int:
    return max(1, int(draft.expires_at - now))


def _write(draft: CredentialDraft, ttl_seconds: int) -> None:
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
) -> Optional[CredentialDraft]:
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


def _read_all(vault_id: str) -> list[CredentialDraft]:
    if not vault_id:
        return []
    backend = get_chat_state_backend()
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=vault_id,
    )
    members = backend.smembers(idx_key)
    out: list[CredentialDraft] = []
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


def store_draft(
    *,
    vault_id: str,
    service_name: str,
    username: str,
    password: str,
    ttl_seconds: Optional[int] = None,
    opaque_server_storage: bool = False,
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
    draft = CredentialDraft(
        draft_id=uuid.uuid4().hex,
        vault_id=vault_id,
        service_name=service_name.strip(),
        username=username,
        password=password,
        created_at=now,
        expires_at=now + ttl,
        saved=False,
        service_key=_service_key(service_name),
        opaque_server_storage=bool(opaque_server_storage),
    )
    if opaque_server_storage:
        # The caller receives the generated values for client-side
        # encryption, but server-side state contains metadata only.
        stored = CredentialDraft(
            draft_id=draft.draft_id,
            vault_id=draft.vault_id,
            service_name=draft.service_name,
            username="",
            password="",
            created_at=draft.created_at,
            expires_at=draft.expires_at,
            saved=False,
            service_key=draft.service_key,
            opaque_server_storage=True,
        )
        _write(stored, ttl)
    else:
        _write(draft, ttl)
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
    if draft_id:
        d = _read_by_draft_id(vault_id, draft_id)
        if d is not None and not d.is_expired(now) and not d.saved:
            return d
        return None
    candidates = [
        d for d in _read_all(vault_id)
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
    backend = get_chat_state_backend()
    kv_key = compose_key(
        bucket=_BUCKET, vault_id=d.vault_id, sub=d.draft_id,
    )
    idx_key = compose_index_key(
        bucket=_BUCKET, vault_id=d.vault_id,
    )
    backend.delete(kv_key)
    backend.srem(idx_key, d.draft_id)


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


def _drafts_for_test(vault_id: str) -> list[CredentialDraft]:
    return _read_all(vault_id)


def _reset_store_for_test() -> None:
    """Test-only. Reset the shared backend (works for in-memory
    backend; a Redis-backed test suite should also install an
    InMemoryChatStateBackend via install_backend_for_tests)."""
    from vault_chat_state_store import (
        reset_chat_state_backend_for_tests,
    )
    reset_chat_state_backend_for_tests()


__all__ = [
    "CredentialDraft",
    "DRAFT_TTL_SECONDS",
    "store_draft",
    "get_draft",
    "consume_draft",
    "clear_drafts_for_vault",
]
