"""Dispatches an APPROVED semantic decision to a backend tool.

Never invoked with an unauthorized decision — the caller is
required to run ``vault_chat_policy.authorize`` first and only
call ``dispatch(...)`` when the policy result is approved.

The router owns:
    * calling into the source-specific consume function for a
      pending action (delete intent / credential draft / login
      draft / attachment / secure item draft),
    * composing the final user-facing reply,
    * cleaning up the corresponding source of truth.

The router does NOT:
    * make the authorization decision (that's the policy layer),
    * make the semantic decision (that's the decider),
    * touch inheritance, wallet, or any frozen area.

The router ALWAYS returns a ``RouterResult`` — never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_SECURE_ITEM,
    PendingAction,
)
from vault_chat_semantic_decider import Decision
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CANCEL_PENDING_SAVE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_SAVE,
    TOOL_CONVERSATIONAL_REPLY,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)
from vault_chat_turn_snapshot import TurnSnapshot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouterResult:
    handled:     bool
    reply_text:  str = ""
    tool:        str = ""
    metadata:    Optional[dict] = None

    @staticmethod
    def fallthrough() -> "RouterResult":
        return RouterResult(handled=False, reply_text="", tool="")


FALLTHROUGH: RouterResult = RouterResult(handled=False)


# -------------------------------------------------------------------
# Delete-confirm dispatch
# -------------------------------------------------------------------

def _confirm_pending_delete(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
    memory: Any = None,
) -> RouterResult:
    """Execute the pending delete via the same pathway the
    existing secure-item router uses. Reuses
    ``vault_secure_item_save._execute_pending_delete`` so we don't
    duplicate the actual DB delete logic — the router is a thin
    caller.
    """
    try:
        from vault_secure_item_save import _execute_pending_delete
    except Exception:
        logger.exception("[ROUTER] confirm_delete_import_failed")
        return FALLTHROUGH
    try:
        result = _execute_pending_delete(
            vault_id=snapshot.vault_id, key=key,
        )
    except Exception:
        logger.exception(
            "[ROUTER] confirm_delete_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text=(
                "I couldn't delete that right now. Try again in a "
                "moment."
            ),
            tool=TOOL_CONFIRM_PENDING_DELETE,
            metadata={"error": "delete_failed"},
        )
    reply = str(result.get("message") or "").strip()
    if not reply:
        # Defensive fallback — the existing pathway always sets a
        # message; only reachable if the DB delete returned an
        # unexpected shape.
        reply = "Deleted saved item from your vault."
    return RouterResult(
        handled=True,
        reply_text=reply,
        tool=TOOL_CONFIRM_PENDING_DELETE,
        metadata={"band": result.get("band")},
    )


def _cancel_pending_delete(
    *,
    snapshot: TurnSnapshot,
) -> RouterResult:
    try:
        from vault_secure_item_save import _cancel_pending_delete as _cancel
    except Exception:
        logger.exception("[ROUTER] cancel_delete_import_failed")
        return FALLTHROUGH
    try:
        result = _cancel(vault_id=snapshot.vault_id)
    except Exception:
        logger.exception(
            "[ROUTER] cancel_delete_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text="Okay — I won't delete it.",
            tool=TOOL_CANCEL_PENDING_DELETE,
            metadata={"error": "cancel_failed"},
        )
    reply = str(result.get("message") or "").strip() or (
        "Okay — I won't delete it."
    )
    return RouterResult(
        handled=True,
        reply_text=reply,
        tool=TOOL_CANCEL_PENDING_DELETE,
        metadata={"band": result.get("band")},
    )


# -------------------------------------------------------------------
# Save-confirm dispatch
# -------------------------------------------------------------------

def _confirm_pending_save(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
    memory: Any = None,
) -> RouterResult:
    pending = snapshot.pending_action
    if pending.kind == KIND_SAVE_CREDENTIAL:
        return _confirm_save_credential_draft(snapshot=snapshot, key=key,
                                              memory=memory)
    if pending.kind == KIND_SAVE_LOGIN_DRAFT:
        return _confirm_save_login_draft(snapshot=snapshot, key=key,
                                         memory=memory)
    if pending.kind == KIND_SAVE_ATTACHMENT:
        return _confirm_save_attachment(snapshot=snapshot, key=key)
    if pending.kind == KIND_SAVE_SECURE_ITEM:
        return _confirm_save_secure_item(snapshot=snapshot, key=key)
    return FALLTHROUGH


def _confirm_save_credential_draft(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
    memory: Any,
) -> RouterResult:
    try:
        from vault_credential_draft import consume_draft
    except Exception:
        logger.exception("[ROUTER] cred_consume_import_failed")
        return FALLTHROUGH
    try:
        draft = consume_draft(vault_id=snapshot.vault_id)
    except Exception:
        logger.exception(
            "[ROUTER] cred_consume_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        draft = None
    if draft is None:
        return FALLTHROUGH
    service = str(draft.service_name or "")
    fields = {"password": str(draft.password or "")}
    if draft.username:
        fields["username"] = str(draft.username or "")
    try:
        import main as _m
        _m.save_secret_tool(
            snapshot.vault_id,
            {
                "secret_type": "login",
                "service":     service,
                "fields":      fields,
            },
            key,
            generated=True,
        )
    except Exception:
        logger.exception(
            "[ROUTER] cred_save_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text=(
                f"I couldn't save the {service.title()} login right "
                "now. Try again in a moment."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"error": "cred_save_failed"},
        )
    _memory_clear(memory, "pending_login_draft")
    try:
        from vault_active_context import clear_active_context
        clear_active_context(snapshot.vault_id)
    except Exception:
        pass
    return RouterResult(
        handled=True,
        reply_text=(
            f"Saved your {service.title()} login to your vault "
            "\U0001F510"
        ),
        tool=TOOL_CONFIRM_PENDING_SAVE,
        metadata={"kind": KIND_SAVE_CREDENTIAL},
    )


def _confirm_save_login_draft(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
    memory: Any,
) -> RouterResult:
    try:
        d = memory.get("pending_login_draft") if memory is not None else None
    except Exception:
        d = None
    if not isinstance(d, dict) or not d.get("service"):
        return FALLTHROUGH
    service = str(d.get("service") or "")
    opts = list(d.get("username_options") or [])
    username = opts[0] if opts else None
    password = str(d.get("password") or "")
    email_required = bool(d.get("policy_email_required"))
    if email_required and not d.get("existing_email"):
        return RouterResult(
            handled=True,
            reply_text=(
                f"{service.title()} needs an email address as the "
                "username — send me the email you want to use and "
                "I'll save it with this password."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"kind": KIND_SAVE_LOGIN_DRAFT,
                      "need": "email"},
        )
    fields = {"password": password}
    if username:
        fields["username"] = username
    try:
        import main as _m
        _m.save_secret_tool(
            snapshot.vault_id,
            {
                "secret_type": "login",
                "service":     service,
                "fields":      fields,
            },
            key,
            generated=True,
        )
    except Exception:
        logger.exception(
            "[ROUTER] mem_login_save_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text=(
                f"I couldn't save the {service.title()} login "
                "right now. Try again in a moment."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"error": "mem_login_save_failed"},
        )
    _memory_clear(memory, "pending_login_draft")
    try:
        from vault_active_context import clear_active_context
        clear_active_context(snapshot.vault_id)
    except Exception:
        pass
    return RouterResult(
        handled=True,
        reply_text=(
            f"Saved your {service.title()} login to your vault "
            "\U0001F510"
        ),
        tool=TOOL_CONFIRM_PENDING_SAVE,
        metadata={"kind": KIND_SAVE_LOGIN_DRAFT},
    )


def _confirm_save_attachment(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
) -> RouterResult:
    """Save the freshly-bound attachment for THIS session. The
    pending-action arbiter already verified that the binding
    matches the current session AND that the DB row still has
    ``needs_naming = TRUE``. If either check has failed by the
    time we get here, we fall through instead of guessing at a
    name.
    """
    pending = snapshot.pending_action
    file_id = str(pending.metadata.get("uploaded_file_id") or "")
    if not file_id:
        return FALLTHROUGH
    content_type = str(pending.metadata.get("content_type") or "").lower()
    filename = str(pending.metadata.get("filename") or "")
    if content_type.startswith("audio/"):
        noun = "recording"
    elif content_type.startswith("video/"):
        noun = "video"
    elif content_type.startswith("image/"):
        noun = "image"
    else:
        noun = "file"
    try:
        import main as _m
        default_name = filename.strip() or noun
        try:
            clean = _m._normalize_asset_name(default_name)
        except Exception:
            clean = default_name
        if not clean or clean == "general":
            clean = noun
        result = _m.save_named_uploaded_asset(
            vault_id=snapshot.vault_id,
            file_id=file_id,
            saved_name=clean,
            key=key,
        )
    except Exception:
        logger.exception(
            "[ROUTER] attachment_save_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text=(
                f"I couldn't save that {noun} right now. Try again "
                "in a moment."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"error": "attachment_save_failed"},
        )
    if not isinstance(result, dict) or not result.get("saved_name"):
        return RouterResult(
            handled=True,
            reply_text=(
                f"I couldn't save that {noun} right now. Try again "
                "in a moment."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"error": "attachment_save_bad_shape"},
        )
    try:
        title = _m._title_case_asset(result["saved_name"])
    except Exception:
        title = str(result["saved_name"])
    # Clear the binding so a follow-up "yes" cannot re-consume it.
    try:
        from vault_chat_upload_binding import clear_binding
        clear_binding(
            vault_id=snapshot.vault_id, uploaded_file_id=file_id,
        )
    except Exception:
        pass
    return RouterResult(
        handled=True,
        reply_text=f"Saved this {noun} as {title}.",
        tool=TOOL_CONFIRM_PENDING_SAVE,
        metadata={"kind": KIND_SAVE_ATTACHMENT},
    )


def _confirm_save_secure_item(
    *,
    snapshot: TurnSnapshot,
    key: bytes,
) -> RouterResult:
    try:
        from vault_secure_item_save import confirm_pending_secure_item_save
    except Exception:
        logger.exception("[ROUTER] sec_save_import_failed")
        return FALLTHROUGH
    try:
        result = confirm_pending_secure_item_save(
            vault_id=snapshot.vault_id, key=key,
        )
    except Exception:
        logger.exception(
            "[ROUTER] sec_save_failed vault=%s",
            (snapshot.vault_id or "")[:8] + "…",
        )
        return RouterResult(
            handled=True,
            reply_text=(
                "I couldn't save that right now. Try again in a "
                "moment."
            ),
            tool=TOOL_CONFIRM_PENDING_SAVE,
            metadata={"error": "sec_save_failed"},
        )
    reply = str(result.get("message") or "").strip()
    if not reply:
        return FALLTHROUGH
    return RouterResult(
        handled=True,
        reply_text=reply,
        tool=TOOL_CONFIRM_PENDING_SAVE,
        metadata={"kind": KIND_SAVE_SECURE_ITEM,
                  "band": result.get("band")},
    )


def _cancel_pending_save(
    *,
    snapshot: TurnSnapshot,
    memory: Any = None,
) -> RouterResult:
    """Cancel any pending save. Non-destructive; we clear the
    matching source of truth and reply with a short honest
    acknowledgement. If the source is unknown we fall through so
    the existing pipeline can handle it."""
    pending = snapshot.pending_action
    label = pending.target_label or "that save"
    if pending.kind == KIND_SAVE_CREDENTIAL:
        try:
            from vault_credential_draft import consume_draft
            consume_draft(vault_id=snapshot.vault_id)
        except Exception:
            pass
    elif pending.kind == KIND_SAVE_LOGIN_DRAFT:
        _memory_clear(memory, "pending_login_draft")
    elif pending.kind == KIND_SAVE_ATTACHMENT:
        file_id = str(pending.metadata.get("uploaded_file_id") or "")
        if file_id:
            try:
                from vault_chat_upload_binding import clear_binding
                clear_binding(
                    vault_id=snapshot.vault_id,
                    uploaded_file_id=file_id,
                )
            except Exception:
                pass
    elif pending.kind == KIND_SAVE_SECURE_ITEM:
        try:
            from vault_secure_item_draft import (
                clear_secure_item_drafts_for_vault,
            )
            clear_secure_item_drafts_for_vault(snapshot.vault_id)
        except Exception:
            pass
    else:
        return FALLTHROUGH
    return RouterResult(
        handled=True,
        reply_text=f"Okay — I won't save {label}.",
        tool=TOOL_CANCEL_PENDING_SAVE,
        metadata={"kind": pending.kind},
    )


# -------------------------------------------------------------------
# Conversational / clarification
# -------------------------------------------------------------------

def _request_clarification(
    *,
    snapshot: TurnSnapshot,
    decision: Decision,
) -> RouterResult:
    question = str(decision.args.get("question") or "").strip()
    if not question:
        return FALLTHROUGH
    # Cap length defensively — the tool_registry already limits
    # via schema, but the model may still return whitespace-only
    # or excessively long content.
    if len(question) > 400:
        question = question[:400].rstrip() + "…"
    return RouterResult(
        handled=True,
        reply_text=question,
        tool=TOOL_REQUEST_CLARIFICATION,
        metadata={"pending_kind": snapshot.pending_action.kind},
    )


def _conversational_reply(
    *,
    snapshot: TurnSnapshot,
    decision: Decision,
) -> RouterResult:
    reply = str(decision.args.get("reply") or "").strip()
    if not reply:
        return FALLTHROUGH
    if len(reply) > 1200:
        reply = reply[:1200].rstrip() + "…"
    return RouterResult(
        handled=True,
        reply_text=reply,
        tool=TOOL_CONVERSATIONAL_REPLY,
        metadata={},
    )


# -------------------------------------------------------------------
# Public entry point
# -------------------------------------------------------------------

def dispatch(
    *,
    snapshot: TurnSnapshot,
    decision: Decision,
    key: bytes,
    memory: Any = None,
) -> RouterResult:
    tool = decision.tool
    if tool == TOOL_FALLTHROUGH:
        return FALLTHROUGH
    if tool == TOOL_CONFIRM_PENDING_DELETE:
        return _confirm_pending_delete(
            snapshot=snapshot, key=key, memory=memory,
        )
    if tool == TOOL_CANCEL_PENDING_DELETE:
        return _cancel_pending_delete(snapshot=snapshot)
    if tool == TOOL_CONFIRM_PENDING_SAVE:
        return _confirm_pending_save(
            snapshot=snapshot, key=key, memory=memory,
        )
    if tool == TOOL_CANCEL_PENDING_SAVE:
        return _cancel_pending_save(snapshot=snapshot, memory=memory)
    if tool == TOOL_REQUEST_CLARIFICATION:
        return _request_clarification(snapshot=snapshot, decision=decision)
    if tool == TOOL_CONVERSATIONAL_REPLY:
        return _conversational_reply(snapshot=snapshot, decision=decision)
    return FALLTHROUGH


def _memory_clear(memory: Any, key: str) -> None:
    if memory is None or not key:
        return
    try:
        memory.pop(key, None)
    except Exception:
        pass


__all__ = [
    "RouterResult",
    "FALLTHROUGH",
    "dispatch",
]
