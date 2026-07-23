"""Generic per-vault "active entity" conversation context for VaultAI Chat.

Replaces the earlier login-only ``vault_chat_last_login_search`` store
with a single system that also serves file, secure item, ID document,
note, folder, generated-login-draft, storage/billing card, and crypto
wallet follow-ups.

## What is NEVER stored

  * passwords, PINs, seed phrases, private keys, tokens
  * decrypted plaintext of any encrypted DB column
  * fields from vault_items.encrypted_data
  * OTP secrets
  * full account numbers / SSNs / IDs (only masked labels)

The store rejects unknown entity types and unknown actions LOUDLY so
a caller cannot silently smuggle a new label past the safety
checklist below.

## Scope + lifetime

  * Per-vault (`vault_id`) and per-session (`session_id`). If a
    session-scoped record is read from a different session id, it is
    treated as absent — the entity did not exist for THIS session.
    (Callers that don't yet thread `session_id` still get the old
    per-vault behavior — with the same TTL / label restrictions.)

  * TTL-bounded. Default 900 s (`VAULTAI_ACTIVE_ENTITY_TTL_S`).
    Expired records are lazily evicted on read.

  * Cleared on:
      - session revoke (auth_local.revoke_all_sessions_for_vault)
      - vault delete
      - explicit topic change (chat handler's explicit-different-
        intent branches call clear_active_entity)

## 2026-07-24 cross-worker migration

  Prior to 2026-07-24 the store was a per-process ``dict`` guarded by
  ``threading.Lock``. Under Uvicorn ``--workers 2`` an entity set on
  worker A was invisible to worker B on the next turn — the same
  worker-hop class of bug that the credential draft, chat memory, and
  secure delete intent modules were migrated to fix. This module now
  reads/writes through ``vault_chat_state_store`` (Redis in prod;
  in-memory shim in dev / test / Redis-outage). Public API is
  unchanged; every existing caller keeps working. The session-scope
  guarantee is preserved: a record stamped with a ``session_id``
  is only readable by a request that presents the same
  ``session_id``.

None of this weakens the existing PIN, trusted-device, masking, or
password-reveal gates. This module has no ability to reveal a
password, sign a transaction, delete a vault, or bypass any
enforcement point. Follow-up "show me" re-renders a MASKED card.
Password reveal goes through the same
``vault_confirmation_required_card`` flow it always did.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Any, Iterable, Optional

from vault_chat_state_store import (
    compose_key, get_chat_state_backend,
)


logger = logging.getLogger(__name__)




ENTITY_LOGIN:                 str = "login"
ENTITY_FILE:                  str = "file"
ENTITY_FILE_LIST:             str = "file_list"
ENTITY_SECURE_ITEM:           str = "secure_item"
ENTITY_ID_DOCUMENT:           str = "id_document"
ENTITY_NOTE:                  str = "note"
ENTITY_FOLDER:                str = "folder"
ENTITY_GENERATED_LOGIN_DRAFT: str = "generated_login_draft"
ENTITY_STORAGE_CARD:          str = "storage_card"
ENTITY_BILLING_CARD:          str = "billing_card"
ENTITY_CRYPTO_WALLET:         str = "crypto_wallet"




ENTITY_TYPES: frozenset[str] = frozenset({
    ENTITY_LOGIN,
    ENTITY_FILE,
    ENTITY_FILE_LIST,
    ENTITY_SECURE_ITEM,
    ENTITY_ID_DOCUMENT,
    ENTITY_NOTE,
    ENTITY_FOLDER,
    ENTITY_GENERATED_LOGIN_DRAFT,
    ENTITY_STORAGE_CARD,
    ENTITY_BILLING_CARD,
    ENTITY_CRYPTO_WALLET,
})




ACTION_SHOW:     str = "show"
ACTION_OPEN:     str = "open"
ACTION_VIEW:     str = "view"
ACTION_RENAME:   str = "rename"
ACTION_DELETE:   str = "delete"
ACTION_COPY:     str = "copy"
ACTION_SAVE:     str = "save"
ACTION_UPGRADE:  str = "upgrade"
ACTION_EDIT:     str = "edit"
ACTION_DOWNLOAD: str = "download"
ACTION_MORE:     str = "more"

ALLOWED_ACTIONS: frozenset[str] = frozenset({
    ACTION_SHOW,
    ACTION_OPEN,
    ACTION_VIEW,
    ACTION_RENAME,
    ACTION_DELETE,
    ACTION_COPY,
    ACTION_SAVE,
    ACTION_UPGRADE,
    ACTION_EDIT,
    ACTION_DOWNLOAD,
    ACTION_MORE,
})




_ALLOWED_REF_KEYS: frozenset[str] = frozenset({
    "id",
    "file_id",
    "item_id",
    "draft_id",
    "query",
    "kind",
    "vault_id",
    "count",
    "service",
    "asset_type",
    "content_type",
    "relative_path",
    "offset",
    "page_size",
    "total_count",
})




_FORBIDDEN_REF_KEYS: frozenset[str] = frozenset({
    "password",
    "pin",
    "passcode",
    "passphrase",
    "seed",
    "mnemonic",
    "private_key",
    "spend_key",
    "view_key",
    "secret",
    "token",
    "api_key",
    "encrypted_data",
    "plaintext",
    "credentials",
    "ssn",
    "account_number",
})


DEFAULT_TTL_SECONDS: int = int(
    os.getenv("VAULTAI_ACTIVE_ENTITY_TTL_S", "900"),
)


MAX_LABEL_CHARS:    int = 80
MAX_QUERY_CHARS:    int = 80
MAX_CANDIDATES:     int = 25


_BUCKET: str = "active_entity"


def _now() -> float:
    return time.time()


def _short_session_id(session_id: Optional[str]) -> Optional[str]:
    if not session_id or not isinstance(session_id, str):
        return None
    return session_id.strip() or None


def _redis_key(vault_id: str) -> str:
    return compose_key(bucket=_BUCKET, vault_id=vault_id)


def _serialize(record: dict[str, Any]) -> bytes:
    safe = dict(record)
    actions = safe.get("allowed_actions")
    if isinstance(actions, tuple):
        safe["allowed_actions"] = list(actions)
    return json.dumps(safe, ensure_ascii=False).encode("utf-8")


def _deserialize(raw: Optional[bytes]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        logger.warning("[ACTIVE-ENTITY] deserialize_failed")
        return None
    if not isinstance(d, dict):
        return None
    actions = d.get("allowed_actions")
    if isinstance(actions, list):
        d["allowed_actions"] = tuple(a for a in actions if isinstance(a, str))
    return d


def _validate_ref(entity_ref: Any) -> Optional[dict[str, Any]]:
    """Return a safe copy of `entity_ref` or None on rejection."""
    if entity_ref is None:
        return {}
    if not isinstance(entity_ref, dict):
        return None
    safe: dict[str, Any] = {}
    for k, v in entity_ref.items():
        if not isinstance(k, str):
            return None
        klow = k.lower()

        if klow in _FORBIDDEN_REF_KEYS:
            logger.warning(
                "[ACTIVE-ENTITY] rejected_forbidden_ref_key %s", klow,
            )
            return None

        if klow not in _ALLOWED_REF_KEYS:
            logger.warning(
                "[ACTIVE-ENTITY] rejected_unknown_ref_key %s", klow,
            )
            return None

        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            if isinstance(v, str) and len(v) > 128:
                v = v[:128]
            safe[klow] = v
        else:
            logger.warning(
                "[ACTIVE-ENTITY] rejected_nonscalar_ref_value key=%s type=%s",
                klow, type(v).__name__,
            )
            return None
    return safe


def _validate_actions(actions: Optional[Iterable[str]]) -> tuple[str, ...]:
    if actions is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for a in actions:
        if not isinstance(a, str):
            continue
        alow = a.strip().lower()
        if not alow or alow in seen:
            continue
        if alow not in ALLOWED_ACTIONS:
            logger.warning(
                "[ACTIVE-ENTITY] rejected_unknown_action %s", alow,
            )
            continue
        seen.add(alow)
        out.append(alow)
    return tuple(out)


def _validate_candidates(
    candidates: Optional[list[dict[str, Any]]],
) -> list[dict[str, Any]]:

    if not candidates:
        return []
    out: list[dict[str, Any]] = []
    for c in candidates[:MAX_CANDIDATES]:
        safe = _validate_ref(c)
        if safe is None:
            continue
        out.append(safe)
    return out


def set_active_entity(
    vault_id: str,
    *,
    entity_type: str,
    entity_ref: Optional[dict[str, Any]] = None,
    display_label: str = "",
    query: Optional[str] = None,
    allowed_actions: Optional[Iterable[str]] = None,
    session_id: Optional[str] = None,
    is_multi: bool = False,
    candidates: Optional[list[dict[str, Any]]] = None,
    ttl_seconds: Optional[int] = None,
) -> bool:
    """Record the currently-active entity for `vault_id`.

    Returns True on write, False on rejection (unknown entity type,
    forbidden ref key, empty vault id, etc.). NEVER raises. NEVER
    stores anything the safety checklist bans.
    """
    if not vault_id or not isinstance(vault_id, str):
        return False
    if entity_type not in ENTITY_TYPES:
        logger.warning(
            "[ACTIVE-ENTITY] rejected_unknown_entity_type type=%s",
            entity_type,
        )
        return False

    safe_ref = _validate_ref(entity_ref)
    if safe_ref is None:
        return False

    safe_label = ""
    if isinstance(display_label, str):
        safe_label = display_label.strip()[:MAX_LABEL_CHARS]

    safe_query: Optional[str] = None
    if isinstance(query, str):
        q = query.strip()
        if q:
            safe_query = q[:MAX_QUERY_CHARS]

    safe_actions = _validate_actions(allowed_actions)

    safe_candidates: list[dict[str, Any]] = []
    if is_multi and candidates:
        safe_candidates = _validate_candidates(candidates)

    ttl = int(
        ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS,
    )
    if ttl <= 0:
        ttl = DEFAULT_TTL_SECONDS
    now = _now()
    record: dict[str, Any] = {
        "vault_id":        vault_id,
        "session_id":      _short_session_id(session_id),
        "entity_type":     entity_type,
        "entity_ref":      safe_ref,
        "display_label":   safe_label,
        "query":           safe_query,
        "allowed_actions": safe_actions,
        "is_multi":        bool(is_multi),
        "candidates":      safe_candidates,
        "created_at":      now,
        "expires_at":      now + ttl,
    }
    try:
        backend = get_chat_state_backend()
        backend.set(_redis_key(vault_id), _serialize(record), ttl)
    except Exception:
        logger.exception(
            "[ACTIVE-ENTITY] write_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return False

    logger.info(
        "[ACTIVE-ENTITY] set vault=%s type=%s label_len=%d "
        "actions=%s multi=%s ttl=%d",
        (vault_id or "")[:8] + "…",
        entity_type,
        len(safe_label),
        ",".join(safe_actions) or "-",
        bool(is_multi),
        ttl,
    )
    return True


def get_active_entity(
    vault_id: str,
    *,
    session_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return a deep copy of the active-entity record, or None.

    If the stored record was written with a `session_id`, a caller
    reading from a DIFFERENT session sees None — this is the
    session-scope guarantee. A read without a session_id argument
    from a session-scoped record also returns None.
    """
    if not vault_id or not isinstance(vault_id, str):
        return None
    now = _now()
    try:
        backend = get_chat_state_backend()
        raw = backend.get(_redis_key(vault_id))
    except Exception:
        logger.exception(
            "[ACTIVE-ENTITY] read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    record = _deserialize(raw)
    if record is None:
        return None
    if now >= float(record.get("expires_at") or 0):
        try:
            backend.delete(_redis_key(vault_id))
        except Exception:
            pass
        return None

    stored_sid = record.get("session_id")
    if stored_sid is not None:
        requested_sid = _short_session_id(session_id)
        if requested_sid != stored_sid:
            return None
    return copy.deepcopy(record)


def clear_active_entity(vault_id: str) -> bool:
    """Forget the active entity. Returns True if one was cleared."""
    if not vault_id or not isinstance(vault_id, str):
        return False
    try:
        backend = get_chat_state_backend()
        # Best-effort check-before-delete so we can return an
        # accurate "was one present" boolean. Not strictly atomic
        # against a concurrent writer, but the same semantics as
        # the previous per-process dict implementation.
        raw = backend.get(_redis_key(vault_id))
        if raw is None:
            return False
        backend.delete(_redis_key(vault_id))
        return True
    except Exception:
        logger.exception(
            "[ACTIVE-ENTITY] clear_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return False


def entity_matches_action(record: dict[str, Any], action: str) -> bool:
    """True iff `action` is in the record's allowed_actions tuple.

    Safety helper — the chat handler dispatcher calls this before
    executing a follow-up so an out-of-band "delete" verb can't
    silently fall through to a delete flow for a login the entity
    record wasn't marked to allow.
    """
    if not isinstance(record, dict):
        return False
    if not isinstance(action, str) or not action.strip():
        return False
    return action.strip().lower() in (record.get("allowed_actions") or ())




def _reset_store_for_test() -> None:
    from vault_chat_state_store import (
        reset_chat_state_backend_for_tests,
    )
    reset_chat_state_backend_for_tests()


def _snapshot_for_test() -> dict[str, dict[str, Any]]:
    """Test-only. Returns a dict of currently-live entities, keyed
    by vault_id. Only enumerates the in-memory backend — a Redis
    backend has no safe SCAN we can use without a full keyspace
    walk. Tests should install the in-memory backend.
    """
    try:
        backend = get_chat_state_backend()
    except Exception:
        return {}
    kv = getattr(backend, "_kv", None)
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(kv, dict):
        return out
    prefix = f"chatst:v1:{_BUCKET}:"
    for key, entry in list(kv.items()):
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        # in-memory backend stores each entry as (expires_at, value_bytes)
        try:
            payload = entry[1]
        except Exception:
            continue
        record = _deserialize(payload)
        if record is None:
            continue
        vid = str(record.get("vault_id") or "")
        if not vid:
            continue
        out[vid] = record
    return out


__all__ = [
    "ENTITY_LOGIN",
    "ENTITY_FILE",
    "ENTITY_FILE_LIST",
    "ENTITY_SECURE_ITEM",
    "ENTITY_ID_DOCUMENT",
    "ENTITY_NOTE",
    "ENTITY_FOLDER",
    "ENTITY_GENERATED_LOGIN_DRAFT",
    "ENTITY_STORAGE_CARD",
    "ENTITY_BILLING_CARD",
    "ENTITY_CRYPTO_WALLET",
    "ENTITY_TYPES",
    "ACTION_SHOW",
    "ACTION_OPEN",
    "ACTION_VIEW",
    "ACTION_RENAME",
    "ACTION_DELETE",
    "ACTION_COPY",
    "ACTION_SAVE",
    "ACTION_UPGRADE",
    "ACTION_EDIT",
    "ACTION_DOWNLOAD",
    "ACTION_MORE",
    "ALLOWED_ACTIONS",
    "DEFAULT_TTL_SECONDS",
    "MAX_LABEL_CHARS",
    "MAX_QUERY_CHARS",
    "MAX_CANDIDATES",
    "set_active_entity",
    "get_active_entity",
    "clear_active_entity",
    "entity_matches_action",
]
