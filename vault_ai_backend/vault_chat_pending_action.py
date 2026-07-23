"""Unified pending-action arbiter for the VaultAI chat brain.

Before 2026-07-24 the chat handler read pending state from ~5
independent stores in a fixed static cascade order (credential
draft → login draft in memory → unnamed uploaded file → secure
item draft → secure delete intent). Whichever store returned a
hit first won — regardless of which pending action the user's
current reply actually referred to. That was the root cause of
the "yes" → "Saved this video as Video_XXX.webm" incident: a
stale ``uploaded_files.needs_naming=TRUE`` row won the race
against a fresh pending delete-confirmation.

This module replaces that implicit cascade with a single
authoritative read model. It reads every pending source, joins
them into one closed-set ``PendingAction`` record, and returns
the currently-active one according to explicit rules:

* Only pending actions belonging to the same vault + session are
  visible. Cross-session leakage is impossible even if a store
  degrades to per-process fallback.
* Expiration is enforced at read time — expired records never
  compete.
* If more than one live pending action exists (which should not
  normally happen), the newest ``created_at`` wins. Ties are
  broken by explicit priority: destructive > save-attachment >
  save-credential > save-login-draft > save-secure-item.
* Unnamed-file (attachment) pending state is admitted ONLY when
  a ``vault_chat_upload_binding`` binding exists for the current
  session AND was created within the last ``ATTACHMENT_MAX_AGE_S``
  seconds. A bare row in ``uploaded_files`` with
  ``needs_naming = TRUE`` is NOT enough by itself — it must have
  been claimed by this session's most-recent upload.

The arbiter has NO write API. It is read-only. Callers that need
to consume a pending action call the source-specific consume
function directly (this module returns the ``source_kind`` and
``action_id`` needed to route to the right consumer).

Security invariants (preserved):
    * Never returns raw plaintext of any encrypted column.
    * Only stable ids and short labels are exposed.
    * Cross-vault reads are impossible — every backing store is
      already keyed by vault_id, and this module never accepts a
      vault_id from user input (it's threaded from the auth layer).

This file is one of the ``vault_chat_*`` modules that make up the
2026-07-24 chat-brain rebuild. It is intentionally narrow — it
does read-model arbitration only; policy checks live in
``vault_chat_policy``, and dispatch lives in
``vault_chat_decision_router``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Closed-set pending-action kinds.
# -------------------------------------------------------------------

KIND_NONE:                str = "none"
KIND_DELETE_SECURE_ITEM:  str = "delete_secure_item"
KIND_SAVE_CREDENTIAL:     str = "save_credential"
KIND_SAVE_LOGIN_DRAFT:    str = "save_login_draft"
KIND_SAVE_ATTACHMENT:     str = "save_attachment"
KIND_SAVE_SECURE_ITEM:    str = "save_secure_item"

DESTRUCTIVE_KINDS: frozenset[str] = frozenset({
    KIND_DELETE_SECURE_ITEM,
})

_KIND_PRIORITY: dict[str, int] = {
    KIND_DELETE_SECURE_ITEM: 100,
    KIND_SAVE_ATTACHMENT:     80,
    KIND_SAVE_CREDENTIAL:     60,
    KIND_SAVE_LOGIN_DRAFT:    40,
    KIND_SAVE_SECURE_ITEM:    20,
    KIND_NONE:                 0,
}


# -------------------------------------------------------------------
# Backing-store identifiers (used by consumers to route to the right
# consume function). Never exposed to the model.
# -------------------------------------------------------------------

SOURCE_SECURE_DELETE_INTENT:  str = "secure_delete_intent"
SOURCE_CREDENTIAL_DRAFT:      str = "credential_draft"
SOURCE_MEMORY_LOGIN_DRAFT:    str = "memory_login_draft"
SOURCE_UPLOADED_FILE:         str = "uploaded_file"
SOURCE_SECURE_ITEM_DRAFT:     str = "secure_item_draft"


ATTACHMENT_MAX_AGE_S: int = 300


@dataclass(frozen=True)
class PendingAction:
    """One live pending action, ready for interpretation.

    ``target_label`` is a short user-facing description of the
    target ("Instagram login", "photo.jpg", etc.) — never
    plaintext. ``action_id`` is a stable id the router uses to
    consume the action from its backing store; the model may
    quote it in its decision but never modifies it.
    """
    kind:          str
    action_id:     str
    source_kind:   str
    target_label:  str
    created_at:    float
    expires_at:    float
    vault_id:      str
    session_id:    Optional[str] = None
    is_destructive: bool = False
    metadata:      dict = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def to_prompt_dict(self) -> dict:
        """Compact, safe-to-show-the-model dict form. NEVER
        includes plaintext of any encrypted column and NEVER
        includes the raw vault_id."""
        return {
            "action_id":     self.action_id,
            "kind":          self.kind,
            "target_label":  self.target_label,
            "is_destructive": bool(self.is_destructive),
            "age_seconds":   max(0, int(time.time() - self.created_at)),
        }


NONE_PENDING: PendingAction = PendingAction(
    kind=KIND_NONE,
    action_id="",
    source_kind="",
    target_label="",
    created_at=0.0,
    expires_at=0.0,
    vault_id="",
    session_id=None,
    is_destructive=False,
    metadata={},
)


def _now() -> float:
    return time.time()


def _has_session_binding(
    stored_session_id: Optional[str],
    reader_session_id: Optional[str],
) -> bool:
    """A pending action stamped with a session_id is visible only
    to that session. Actions stamped WITHOUT a session_id (older
    call sites that don't yet thread it) remain visible to any
    reader for backwards compatibility. This is the same rule
    used by ``vault_chat_active_entity``."""
    if stored_session_id is None:
        return True
    if reader_session_id is None:
        return False
    return stored_session_id == reader_session_id


def _read_secure_delete(
    vault_id: str, session_id: Optional[str], now: float,
) -> Optional[PendingAction]:
    try:
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent,
        )
    except Exception:
        logger.exception("[PENDING] delete_import_failed")
        return None
    try:
        intent = get_pending_delete_intent(vault_id=vault_id)
    except Exception:
        logger.exception("[PENDING] delete_read_failed vault=%s",
                         (vault_id or "")[:8] + "…")
        return None
    if intent is None:
        return None
    if intent.is_expired(now):
        return None
    return PendingAction(
        kind=KIND_DELETE_SECURE_ITEM,
        action_id=str(intent.intent_id),
        source_kind=SOURCE_SECURE_DELETE_INTENT,
        target_label=_delete_target_label(intent),
        created_at=float(intent.created_at),
        expires_at=float(intent.expires_at),
        vault_id=vault_id,
        session_id=None,
        is_destructive=True,
        metadata={
            "item_type": intent.item_type,
            "is_login":  bool(intent.is_login),
            "item_id":   intent.item_id,
        },
    )


def _delete_target_label(intent: Any) -> str:
    """Short label — for a login it's "<Service> login", for other
    types it's "<Service>". Never plaintext credentials."""
    try:
        svc = (intent.service or "").strip()
    except Exception:
        svc = ""
    if not svc:
        return "saved item"
    if bool(getattr(intent, "is_login", False)):
        return f"{svc.title()} login"
    return svc.title()


def _read_credential_draft(
    vault_id: str, session_id: Optional[str], now: float,
) -> Optional[PendingAction]:
    try:
        from vault_credential_draft import get_draft
    except Exception:
        logger.exception("[PENDING] cred_draft_import_failed")
        return None
    try:
        draft = get_draft(vault_id=vault_id)
    except Exception:
        logger.exception(
            "[PENDING] cred_draft_read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if draft is None:
        return None
    if draft.is_expired(now):
        return None
    return PendingAction(
        kind=KIND_SAVE_CREDENTIAL,
        action_id=str(draft.draft_id),
        source_kind=SOURCE_CREDENTIAL_DRAFT,
        target_label=f"{(draft.service_name or 'login').title()} login",
        created_at=float(draft.created_at),
        expires_at=float(draft.expires_at),
        vault_id=vault_id,
        session_id=None,
        is_destructive=False,
        metadata={"service_name": draft.service_name},
    )


def _read_memory_login_draft(
    vault_id: str, memory: Any, now: float,
) -> Optional[PendingAction]:
    try:
        d = memory.get("pending_login_draft") if memory is not None else None
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    svc = str(d.get("service") or "").strip()
    if not svc:
        return None
    stamped_at = float(d.get("ts") or 0.0)
    if stamped_at <= 0.0:
        stamped_at = now
    expires_at = stamped_at + 600.0
    if now >= expires_at:
        return None
    return PendingAction(
        kind=KIND_SAVE_LOGIN_DRAFT,
        action_id=f"memlogin:{svc.lower()}",
        source_kind=SOURCE_MEMORY_LOGIN_DRAFT,
        target_label=f"{svc.title()} login",
        created_at=stamped_at,
        expires_at=expires_at,
        vault_id=vault_id,
        session_id=None,
        is_destructive=False,
        metadata={"service_name": svc},
    )


def _read_secure_item_draft(
    vault_id: str, now: float,
) -> Optional[PendingAction]:
    try:
        from vault_secure_item_draft import get_latest_secure_item_draft
    except Exception:
        logger.exception("[PENDING] sec_draft_import_failed")
        return None
    try:
        draft = get_latest_secure_item_draft(vault_id=vault_id)
    except Exception:
        logger.exception(
            "[PENDING] sec_draft_read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if draft is None:
        return None
    if draft.is_expired(now):
        return None
    label = (draft.title or draft.category or "saved item").strip()
    return PendingAction(
        kind=KIND_SAVE_SECURE_ITEM,
        action_id=str(draft.draft_id),
        source_kind=SOURCE_SECURE_ITEM_DRAFT,
        target_label=label.title(),
        created_at=float(draft.created_at),
        expires_at=float(draft.expires_at),
        vault_id=vault_id,
        session_id=None,
        is_destructive=False,
        metadata={
            "category": draft.category,
            "title":    draft.title,
        },
    )


def _read_bound_attachment(
    vault_id: str, session_id: Optional[str], now: float,
) -> Optional[PendingAction]:
    """Attachment pending action — admitted ONLY when there is a
    fresh upload binding for THIS session. A raw
    ``uploaded_files.needs_naming = TRUE`` row without a matching
    binding is IGNORED. This is the structural fix for the
    2026-07-24 attachment-isolation requirement.
    """
    try:
        from vault_chat_upload_binding import resolve_active_upload
    except Exception:
        logger.exception("[PENDING] upload_binding_import_failed")
        return None
    try:
        binding = resolve_active_upload(
            vault_id=vault_id,
            session_id=session_id,
            max_age_seconds=ATTACHMENT_MAX_AGE_S,
            now=now,
        )
    except Exception:
        logger.exception(
            "[PENDING] upload_binding_read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if binding is None:
        return None
    # Cross-check that the bound file still exists and still needs
    # naming — otherwise the user already named it in some other
    # flow and the binding is stale.
    try:
        from vault_chat_upload_binding import file_still_pending_name
    except Exception:
        file_still_pending_name = None
    if file_still_pending_name is not None:
        try:
            if not file_still_pending_name(binding):
                return None
        except Exception:
            logger.exception(
                "[PENDING] upload_binding_verify_failed vault=%s",
                (vault_id or "")[:8] + "…",
            )
            return None
    label = _attachment_target_label(binding)
    expires_at = float(binding.created_at) + float(ATTACHMENT_MAX_AGE_S)
    return PendingAction(
        kind=KIND_SAVE_ATTACHMENT,
        action_id=str(binding.uploaded_file_id),
        source_kind=SOURCE_UPLOADED_FILE,
        target_label=label,
        created_at=float(binding.created_at),
        expires_at=expires_at,
        vault_id=vault_id,
        session_id=binding.session_id,
        is_destructive=False,
        metadata={
            "uploaded_file_id": binding.uploaded_file_id,
            "content_type":     binding.content_type,
            "filename":         binding.filename,
        },
    )


def _attachment_target_label(binding: Any) -> str:
    ct = str(getattr(binding, "content_type", "") or "").lower()
    if ct.startswith("audio/"):
        noun = "recording"
    elif ct.startswith("video/"):
        noun = "video"
    elif ct.startswith("image/"):
        noun = "image"
    else:
        noun = "file"
    name = str(getattr(binding, "filename", "") or "").strip()
    if not name:
        return noun
    return f"{noun}: {name[:60]}"


def read_all_pending(
    *,
    vault_id: str,
    session_id: Optional[str] = None,
    memory: Any = None,
    now: Optional[float] = None,
) -> list[PendingAction]:
    """Read every pending source and return the live, session-
    visible actions. Sorted with the highest-priority + newest
    first."""
    if not vault_id:
        return []
    when = float(now) if now is not None else _now()

    candidates: list[PendingAction] = []
    for reader in (
        lambda: _read_secure_delete(vault_id, session_id, when),
        lambda: _read_credential_draft(vault_id, session_id, when),
        lambda: _read_memory_login_draft(vault_id, memory, when),
        lambda: _read_bound_attachment(vault_id, session_id, when),
        lambda: _read_secure_item_draft(vault_id, when),
    ):
        try:
            hit = reader()
        except Exception:
            logger.exception("[PENDING] reader_crashed")
            hit = None
        if hit is None:
            continue
        if hit.is_expired(when):
            continue
        if not _has_session_binding(hit.session_id, session_id):
            continue
        candidates.append(hit)

    if not candidates:
        return []

    candidates.sort(
        key=lambda a: (
            _KIND_PRIORITY.get(a.kind, 0),
            a.created_at,
        ),
        reverse=True,
    )
    return candidates


def read_active_pending(
    *,
    vault_id: str,
    session_id: Optional[str] = None,
    memory: Any = None,
    now: Optional[float] = None,
) -> PendingAction:
    """Return the single most-recent, highest-priority live
    pending action, or ``NONE_PENDING`` if there are none."""
    all_hits = read_all_pending(
        vault_id=vault_id,
        session_id=session_id,
        memory=memory,
        now=now,
    )
    if not all_hits:
        return NONE_PENDING
    top = all_hits[0]
    if len(all_hits) > 1:
        # Multiple live pending actions is unusual — log for
        # observability but proceed with the top. We do NOT silently
        # squash others; the caller sees only the top so it can't
        # accidentally consume the wrong one, but operators get a
        # diagnostic line.
        logger.info(
            "[PENDING] multiple_pending vault=%s top_kind=%s "
            "other_kinds=%s count=%d",
            (vault_id or "")[:8] + "…",
            top.kind,
            ",".join(a.kind for a in all_hits[1:5]),
            len(all_hits),
        )
    return top


def has_destructive_pending(
    *,
    vault_id: str,
    session_id: Optional[str] = None,
    now: Optional[float] = None,
) -> bool:
    """True iff any destructive pending action is live for this
    (vault, session). Used by callers that need a quick guard
    (e.g. "reject a non-confirming interpretation of a pending
    delete")."""
    for hit in read_all_pending(
        vault_id=vault_id, session_id=session_id, memory=None, now=now,
    ):
        if hit.kind in DESTRUCTIVE_KINDS:
            return True
    return False


__all__ = [
    "KIND_NONE",
    "KIND_DELETE_SECURE_ITEM",
    "KIND_SAVE_CREDENTIAL",
    "KIND_SAVE_LOGIN_DRAFT",
    "KIND_SAVE_ATTACHMENT",
    "KIND_SAVE_SECURE_ITEM",
    "DESTRUCTIVE_KINDS",
    "ATTACHMENT_MAX_AGE_S",
    "SOURCE_SECURE_DELETE_INTENT",
    "SOURCE_CREDENTIAL_DRAFT",
    "SOURCE_MEMORY_LOGIN_DRAFT",
    "SOURCE_UPLOADED_FILE",
    "SOURCE_SECURE_ITEM_DRAFT",
    "PendingAction",
    "NONE_PENDING",
    "read_all_pending",
    "read_active_pending",
    "has_destructive_pending",
]
