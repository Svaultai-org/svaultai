"""Cross-worker binding of uploaded files to the session + turn
that produced them.

Before 2026-07-24 the chat handler decided "is there a pending
attachment save?" by SQL: any row in ``uploaded_files`` with
``needs_naming = TRUE`` and ``upload_status = 'complete'`` was
treated as pending. That flag is sticky — a video uploaded any
time in the past (possibly hours or days earlier) would satisfy
the query. Combined with the bare ``"yes"`` regex in the confirm
list, this let a stale unnamed upload hijack a later turn's
confirmation phrase. See the 2026-07-24 root-cause report for
the full timeline.

The structural fix in this module: every fresh upload writes a
binding into the shared chat-state store keyed by (vault_id,
uploaded_file_id) that records:

    * the session_id that owned the upload,
    * the turn_id that produced it,
    * the created_at wall-clock,
    * the filename and content_type for label rendering.

Bindings expire after ``ATTACHMENT_BINDING_TTL_SECONDS`` (default
300s). The pending-action arbiter admits an
``uploaded_files.needs_naming = TRUE`` row as a live pending
attachment ONLY when a matching binding still exists for THIS
session. Without a binding — because it expired, the session
changed, or the upload predates this deploy — the attachment is
invisible to the arbiter and cannot hijack a confirmation phrase.

No database migration is required. The DB row and its
``needs_naming`` flag remain the source of truth for the
naming-required UI; the binding is a separate, TTL-bounded
gating record that lives in Redis and expires without any
Python-side GC loop.

Security invariants (preserved):
    * Vault IDs and session IDs are hashed by
      ``vault_chat_state_store.compose_key`` before they compose
      any Redis key.
    * Filename and content_type are stored to render short user-
      facing labels; they never contain plaintext credentials.
    * No decrypted vault content, no PINs, no keys are stored.

Public API (used by ``main.py`` upload endpoint and the pending-
action arbiter):

    bind_upload(*, vault_id, session_id, turn_id, uploaded_file_id,
                filename, content_type, ttl_seconds?) -> None
    resolve_active_upload(*, vault_id, session_id, max_age_seconds?,
                          now?) -> Optional[UploadBinding]
    clear_binding(*, vault_id, uploaded_file_id) -> bool
    file_still_pending_name(binding) -> bool
    clear_all_for_vault(vault_id) -> int
    _reset_store_for_test()
    _bindings_for_test(vault_id) -> list[UploadBinding]
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from vault_chat_state_store import (
    compose_index_key, compose_key, get_chat_state_backend,
)


logger = logging.getLogger(__name__)


ATTACHMENT_BINDING_TTL_SECONDS: int = 300


_BUCKET: str = "upload_binding"


@dataclass(frozen=True)
class UploadBinding:
    vault_id:          str
    session_id:        Optional[str]
    turn_id:           str
    uploaded_file_id:  str
    filename:          str
    content_type:      str
    created_at:        float
    expires_at:        float

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at


def _now() -> float:
    return time.time()


def _serialize(b: UploadBinding) -> bytes:
    return json.dumps({
        "vault_id":         b.vault_id,
        "session_id":       b.session_id,
        "turn_id":          b.turn_id,
        "uploaded_file_id": b.uploaded_file_id,
        "filename":         b.filename,
        "content_type":     b.content_type,
        "created_at":       b.created_at,
        "expires_at":       b.expires_at,
    }, separators=(",", ":")).encode("utf-8")


def _deserialize(raw: bytes) -> Optional[UploadBinding]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
        return UploadBinding(
            vault_id=str(d.get("vault_id") or ""),
            session_id=(
                str(d["session_id"])
                if d.get("session_id") is not None else None
            ),
            turn_id=str(d.get("turn_id") or ""),
            uploaded_file_id=str(d.get("uploaded_file_id") or ""),
            filename=str(d.get("filename") or ""),
            content_type=str(d.get("content_type") or ""),
            created_at=float(d.get("created_at") or 0.0),
            expires_at=float(d.get("expires_at") or 0.0),
        )
    except Exception:
        logger.warning("[UPLOAD-BINDING] deserialize_failed")
        return None


def _key(vault_id: str, uploaded_file_id: str) -> str:
    return compose_key(
        bucket=_BUCKET, vault_id=vault_id, sub=uploaded_file_id,
    )


def _idx_key(vault_id: str) -> str:
    return compose_index_key(bucket=_BUCKET, vault_id=vault_id)


def bind_upload(
    *,
    vault_id: str,
    session_id: Optional[str],
    turn_id: str,
    uploaded_file_id: str,
    filename: str,
    content_type: str,
    ttl_seconds: Optional[int] = None,
) -> None:
    """Record that this upload belongs to this session and this
    turn. Idempotent — re-binding the same file_id refreshes the
    session/turn/created_at. NEVER raises."""
    if not (vault_id and uploaded_file_id):
        return
    ttl = int(
        ttl_seconds if ttl_seconds is not None
        else ATTACHMENT_BINDING_TTL_SECONDS
    )
    if ttl <= 0:
        ttl = ATTACHMENT_BINDING_TTL_SECONDS
    now = _now()
    b = UploadBinding(
        vault_id=vault_id,
        session_id=(session_id or None),
        turn_id=str(turn_id or ""),
        uploaded_file_id=str(uploaded_file_id),
        filename=str(filename or "")[:120],
        content_type=str(content_type or "")[:80],
        created_at=now,
        expires_at=now + ttl,
    )
    try:
        backend = get_chat_state_backend()
        backend.set(_key(vault_id, uploaded_file_id), _serialize(b), ttl)
        backend.sadd(_idx_key(vault_id), uploaded_file_id, ttl)
    except Exception:
        logger.exception(
            "[UPLOAD-BINDING] write_failed vault=%s file=%s",
            (vault_id or "")[:8] + "…",
            (uploaded_file_id or "")[:8] + "…",
        )


def _read_binding(
    vault_id: str, uploaded_file_id: str,
) -> Optional[UploadBinding]:
    try:
        backend = get_chat_state_backend()
        raw = backend.get(_key(vault_id, uploaded_file_id))
    except Exception:
        logger.exception("[UPLOAD-BINDING] read_failed")
        return None
    if raw is None:
        try:
            backend.srem(_idx_key(vault_id), uploaded_file_id)
        except Exception:
            pass
        return None
    return _deserialize(raw)


def _list_bindings(vault_id: str) -> list[UploadBinding]:
    try:
        backend = get_chat_state_backend()
        members = backend.smembers(_idx_key(vault_id))
    except Exception:
        logger.exception("[UPLOAD-BINDING] index_read_failed")
        return []
    now = _now()
    out: list[UploadBinding] = []
    dead: list[str] = []
    for file_id in members:
        b = _read_binding(vault_id, file_id)
        if b is None:
            dead.append(file_id)
            continue
        if b.is_expired(now):
            dead.append(file_id)
            continue
        out.append(b)
    if dead:
        try:
            for stale in dead:
                backend.srem(_idx_key(vault_id), stale)
        except Exception:
            pass
    return out


def resolve_active_upload(
    *,
    vault_id: str,
    session_id: Optional[str] = None,
    max_age_seconds: int = ATTACHMENT_BINDING_TTL_SECONDS,
    now: Optional[float] = None,
) -> Optional[UploadBinding]:
    """Return the newest live binding for THIS session, or None.

    An upload is "active" iff:
      * a binding exists for it in the shared store,
      * the binding belongs to the given ``session_id`` (or was
        stamped without a session — kept for backwards
        compatibility with older upload paths that haven't yet
        threaded the session id),
      * the binding was created within ``max_age_seconds``.
    """
    if not vault_id:
        return None
    when = float(now) if now is not None else _now()
    live = _list_bindings(vault_id)
    if not live:
        return None
    fresh: list[UploadBinding] = []
    for b in live:
        if (when - float(b.created_at)) > float(max_age_seconds):
            continue
        if b.session_id is not None:
            if session_id is None or b.session_id != session_id:
                continue
        fresh.append(b)
    if not fresh:
        return None
    fresh.sort(key=lambda b: b.created_at, reverse=True)
    return fresh[0]


def file_still_pending_name(binding: UploadBinding) -> bool:
    """Cross-check the DB row for ``needs_naming = TRUE``.

    Returns True if the file is still awaiting a name in the DB,
    False if it has already been named (or the row is missing).
    Silently returns True on any transient DB failure so we don't
    accidentally drop a legitimate pending attachment because of
    a flaky connection.
    """
    if binding is None or not binding.uploaded_file_id:
        return False
    try:
        import main as _m
    except Exception:
        logger.exception(
            "[UPLOAD-BINDING] main_import_failed_for_verify",
        )
        return True
    try:
        row = _m.get_pending_named_file(binding.vault_id)
    except Exception:
        logger.exception(
            "[UPLOAD-BINDING] verify_query_failed vault=%s",
            (binding.vault_id or "")[:8] + "…",
        )
        return True
    if not row:
        return False
    return str(row.get("id") or "") == binding.uploaded_file_id


def clear_binding(
    *, vault_id: str, uploaded_file_id: str,
) -> bool:
    if not (vault_id and uploaded_file_id):
        return False
    try:
        backend = get_chat_state_backend()
        backend.delete(_key(vault_id, uploaded_file_id))
        backend.srem(_idx_key(vault_id), uploaded_file_id)
        return True
    except Exception:
        logger.exception("[UPLOAD-BINDING] clear_failed")
        return False


def clear_all_for_vault(vault_id: str) -> int:
    if not vault_id:
        return 0
    try:
        backend = get_chat_state_backend()
        members = backend.smembers(_idx_key(vault_id))
    except Exception:
        return 0
    count = 0
    for file_id in members:
        try:
            backend.delete(_key(vault_id, file_id))
            count += 1
        except Exception:
            pass
    try:
        backend.sclear(_idx_key(vault_id))
    except Exception:
        pass
    return count


def _reset_store_for_test() -> None:
    from vault_chat_state_store import (
        reset_chat_state_backend_for_tests,
    )
    reset_chat_state_backend_for_tests()


def _bindings_for_test(vault_id: str) -> list[UploadBinding]:
    return _list_bindings(vault_id)


__all__ = [
    "ATTACHMENT_BINDING_TTL_SECONDS",
    "UploadBinding",
    "bind_upload",
    "resolve_active_upload",
    "file_still_pending_name",
    "clear_binding",
    "clear_all_for_vault",
]
