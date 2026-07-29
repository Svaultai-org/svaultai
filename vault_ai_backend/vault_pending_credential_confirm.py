from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class PendingCredentialResult:
    reply_text: str
    service_name: str
    draft_id: str = ""
    source: str = "persistent"
    action: str = "save"


def _hint_draft_id(selection_hint: Any) -> Optional[str]:
    if not isinstance(selection_hint, dict):
        return None
    kind = str(selection_hint.get("kind") or "").strip().lower()
    if kind != "generated_login_draft":
        return None
    draft_id = str(selection_hint.get("id") or "").strip()
    if not draft_id or len(draft_id) > 128:
        return None
    return draft_id


def save_pending_credential(
    *,
    vault_id: str,
    key: bytes,
    memory: Any,
    save_secret_tool: Callable[..., Any],
    selection_hint: Any = None,
) -> Optional[PendingCredentialResult]:
    if not vault_id:
        return None

    draft_id = _hint_draft_id(selection_hint)
    try:
        from vault_credential_draft import (
            consume_draft,
            get_draft,
        )
        draft = get_draft(vault_id=vault_id, draft_id=draft_id)
    except Exception:
        draft = None

    if draft is not None:
        service = str(draft.service_name or "")
        fields = {"password": str(draft.password or "")}
        username = str(draft.username or "")
        if username:
            fields["username"] = username
        save_secret_tool(
            vault_id,
            {
                "secret_type": "login",
                "service": service,
                "fields": fields,
            },
            key,
            generated=True,
        )
        try:
            consume_draft(vault_id=vault_id, draft_id=draft.draft_id)
        except Exception:
            pass
        try:
            if isinstance(memory, dict):
                memory.pop("pending_login_draft", None)
                memory["last_generated_login"] = {
                    "service": service,
                    "generated_fields": list(fields.keys()),
                }
        except Exception:
            pass
        return PendingCredentialResult(
            reply_text=f"Saved your {service.title()} login to your vault \U0001F510",
            service_name=service,
            draft_id=str(draft.draft_id or ""),
            source="persistent",
        )

    try:
        legacy = memory.get("pending_login_draft") if memory is not None else None
    except Exception:
        legacy = None
    if not (isinstance(legacy, dict) and legacy.get("service")):
        return None

    service = str(legacy.get("service") or "")
    password = str(legacy.get("password") or "")
    options = list(legacy.get("username_options") or [])
    username = options[0] if options else None
    if (
        bool(legacy.get("policy_email_required"))
        and not legacy.get("existing_email")
        and not legacy.get("explicit_username_supplied")
    ):
        return PendingCredentialResult(
            reply_text=(
                f"{service.title()} needs an email address as the username - "
                "send me the email you want to use and I'll save it with "
                "this password."
            ),
            service_name=service,
            source="legacy_memory",
        )

    fields = {"password": password}
    if username:
        fields["username"] = username
    save_secret_tool(
        vault_id,
        {
            "secret_type": "login",
            "service": service,
            "fields": fields,
        },
        key,
        generated=True,
    )
    try:
        memory.pop("pending_login_draft", None)
        memory["last_generated_login"] = {
            "service": service,
            "generated_fields": list(fields.keys()),
        }
    except Exception:
        pass
    return PendingCredentialResult(
        reply_text=f"Saved your {service.title()} login to your vault \U0001F510",
        service_name=service,
        source="legacy_memory",
    )


def discard_pending_credential(
    *,
    vault_id: str,
    memory: Any,
    selection_hint: Any = None,
) -> Optional[PendingCredentialResult]:
    if not vault_id:
        return None

    draft_id = _hint_draft_id(selection_hint)
    try:
        from vault_credential_draft import (
            consume_draft,
            get_draft,
        )
        draft = get_draft(vault_id=vault_id, draft_id=draft_id)
    except Exception:
        draft = None

    if draft is not None:
        service = str(draft.service_name or "")
        try:
            consume_draft(vault_id=vault_id, draft_id=draft.draft_id)
        except Exception:
            pass
        try:
            if isinstance(memory, dict):
                memory.pop("pending_login_draft", None)
        except Exception:
            pass
        return PendingCredentialResult(
            reply_text=f"Discarded the {service.title()} login draft.",
            service_name=service,
            draft_id=str(draft.draft_id or ""),
            source="persistent",
            action="cancel",
        )

    try:
        legacy = memory.get("pending_login_draft") if memory is not None else None
    except Exception:
        legacy = None
    if isinstance(legacy, dict) and legacy.get("service"):
        service = str(legacy.get("service") or "")
        try:
            memory.pop("pending_login_draft", None)
        except Exception:
            pass
        return PendingCredentialResult(
            reply_text=f"Discarded the {service.title()} login draft.",
            service_name=service,
            source="legacy_memory",
            action="cancel",
        )
    return None


__all__ = [
    "PendingCredentialResult",
    "discard_pending_credential",
    "save_pending_credential",
]
