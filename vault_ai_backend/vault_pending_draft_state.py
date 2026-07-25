"""State machine for a live ``pending_login_draft``.

Given a chat message and a live draft, decides whether the message
edits the draft, saves it, cancels it, regenerates a field, or is
unrelated. Applies the update to the draft (in memory) and returns
a suggested reply text.

The state machine is deterministic (no LLM). It is called BEFORE
the LLM intent classifier when a pending_login_draft exists, so
the classifier's misroute of "change the username to X" to
``generated_login_repair`` (which auto-saves) is preempted.

Callers are responsible for:
  * Persisting the mutated draft back to ``memory``.
  * Calling ``save_secret_tool`` when the action is CONFIRM_SAVE.
  * Popping the draft from memory after CONFIRM_SAVE or CANCEL.

Never logs plaintext credentials, PIN, email, or vault content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from vault_credential_command import (
    ACTION_CANCEL,
    ACTION_CONFIRM_SAVE,
    ACTION_EDIT_PENDING,
    ACTION_REGENERATE,
    ACTION_REPLACE_DRAFT,
    ACTION_SHOW_DRAFT,
    ACTION_UNRELATED,
    CredentialCommand,
    FIELD_EMAIL,
    FIELD_PASSWORD,
    FIELD_USERNAME,
    extract_credential_command,
)


# Outcome kinds returned to the caller. These map 1:1 to caller
# behavior — the caller does not need to inspect the CredentialCommand.
OUTCOME_UPDATED       = "updated"        # draft modified, reply to user, do NOT save
OUTCOME_SAVE_NOW      = "save_now"       # caller should persist the (unchanged) draft
OUTCOME_CANCELLED     = "cancelled"      # caller should pop the draft
OUTCOME_SHOWN         = "shown"          # caller should reply with draft summary
OUTCOME_REPLACED      = "replaced"       # caller should pop and re-prompt
OUTCOME_NO_ACTION     = "no_action"      # fall through to normal dispatch


@dataclass
class DraftOutcome:
    """Return type from ``apply_to_pending_draft``.

    ``kind`` is one of the OUTCOME_* constants.

    ``draft`` is the (possibly mutated) draft dict — the caller
    should replace ``memory["pending_login_draft"]`` with this.
    On OUTCOME_CANCELLED / OUTCOME_REPLACED / OUTCOME_SAVE_NOW the
    caller ignores this and just pops the memory entry.

    ``reply_text`` is the assistant response to send back. May be
    empty when the caller should build its own reply (e.g. for
    OUTCOME_SAVE_NOW where the caller wants "Saved your …" text).

    ``changed_fields`` is the set of field names that were mutated
    by this outcome (empty for save/cancel/show/no_action).
    """

    kind: str
    draft: dict
    reply_text: str = ""
    changed_fields: frozenset[str] = frozenset()


def _format_draft_reply(service: str,
                        username: Optional[str],
                        password: Optional[str],
                        prelude: str) -> str:
    """Build a short human reply that redraws the pending draft.
    Password is included because the assistant already sent it once
    in the original draft turn; we don't expose new secrets here."""
    lines: list[str] = []
    if prelude:
        lines.append(prelude)
        lines.append("")
    lines.append(f"Service: {service.title() if service else 'this login'}")
    if username:
        lines.append(f"Username: {username}")
    if password:
        lines.append(f"Password: {password}")
    lines.append("")
    lines.append("Say \"save it\" when you want me to store it.")
    return "\n".join(lines)


def _has_service(draft: Optional[dict]) -> bool:
    return isinstance(draft, dict) and bool(draft.get("service"))


def apply_to_pending_draft(
    *,
    user_message: str,
    draft: dict,
    generate_password: Callable[[], str],
    generate_username: Optional[Callable[[], str]] = None,
) -> DraftOutcome:
    """Consult the extractor and apply the resulting command to
    ``draft``. Returns a ``DraftOutcome`` telling the caller what
    to do next (save, cancel, updated, etc.).

    Never mutates the input dict — always returns a new dict when
    ``kind == OUTCOME_UPDATED``. Never raises.

    ``generate_password`` is a zero-arg callable the state machine
    invokes when the user asked to regenerate the password. The
    caller supplies it (usually ``generate_strong_password``).

    ``generate_username`` is optional. When None, a regenerate-
    username request falls through to OUTCOME_NO_ACTION so the
    existing ``generated_login_repair`` handler can service the
    request (that handler owns policy tightening). When supplied
    we call it directly.
    """
    # 2026-07-25 diagnostic entry marker.
    try:
        _dxr_len = len(user_message) if isinstance(user_message, str) else 0
        print(
            f"[BRAIN-TRACE-DXR] site=apply_to_pending_draft "
            f"msg_len={_dxr_len} draft_has_service={_has_service(draft)}",
            flush=True,
        )
    except Exception:
        pass
    if not _has_service(draft):
        return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft or {})

    try:
        cmd = extract_credential_command(
            user_message,
            has_pending_draft=True,
            pending_draft=draft,
        )
    except Exception:
        return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft)

    return _apply_command(
        cmd=cmd,
        draft=draft,
        generate_password=generate_password,
        generate_username=generate_username,
    )


def _apply_command(
    *,
    cmd: CredentialCommand,
    draft: dict,
    generate_password: Callable[[], str],
    generate_username: Optional[Callable[[], str]],
) -> DraftOutcome:
    action = cmd.action

    if action == ACTION_UNRELATED:
        return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft)

    if action == ACTION_CANCEL:
        return DraftOutcome(
            kind=OUTCOME_CANCELLED,
            draft=draft,
            reply_text="Okay, I dropped the draft. Nothing was saved.",
        )

    if action == ACTION_SHOW_DRAFT:
        opts = list(draft.get("username_options") or [])
        return DraftOutcome(
            kind=OUTCOME_SHOWN,
            draft=draft,
            reply_text=_format_draft_reply(
                service=str(draft.get("service") or ""),
                username=(opts[0] if opts else None),
                password=str(draft.get("password") or "") or None,
                prelude="Here's the current draft.",
            ),
        )

    if action == ACTION_REPLACE_DRAFT:
        return DraftOutcome(
            kind=OUTCOME_REPLACED,
            draft=draft,
            reply_text=(
                "Okay, I dropped the draft. Tell me what you'd "
                "like to create."
            ),
        )

    if action == ACTION_CONFIRM_SAVE:
        return DraftOutcome(kind=OUTCOME_SAVE_NOW, draft=draft)

    if action == ACTION_EDIT_PENDING:
        # Apply explicit fields on top of the draft. The draft schema
        # stores username in `username_options[0]` and password as
        # `password`. We keep the whole options list but replace the
        # head with the user's supplied value.
        new_draft = dict(draft)
        changed: set[str] = set()

        supplied_username = (
            cmd.explicit_fields.get(FIELD_USERNAME)
            or cmd.explicit_fields.get(FIELD_EMAIL)
        )
        if supplied_username:
            new_draft["username_options"] = [supplied_username]
            new_draft["explicit_username_supplied"] = True
            new_draft["policy_email_required"] = False
            changed.add(FIELD_USERNAME)

        if FIELD_PASSWORD in cmd.explicit_fields:
            new_draft["password"] = cmd.explicit_fields[FIELD_PASSWORD]
            changed.add(FIELD_PASSWORD)

        opts = list(new_draft.get("username_options") or [])
        prelude = f"Updated the {str(new_draft.get('service', '')).title()} login draft."
        return DraftOutcome(
            kind=OUTCOME_UPDATED,
            draft=new_draft,
            reply_text=_format_draft_reply(
                service=str(new_draft.get("service") or ""),
                username=(opts[0] if opts else None),
                password=str(new_draft.get("password") or "") or None,
                prelude=prelude,
            ),
            changed_fields=frozenset(changed),
        )

    if action == ACTION_REGENERATE:
        new_draft = dict(draft)
        changed: set[str] = set()
        service = str(new_draft.get("service") or "")

        # Password regen is safe to do inline — no policy lookup needed.
        if FIELD_PASSWORD in cmd.generate_fields:
            new_draft["password"] = generate_password()
            changed.add(FIELD_PASSWORD)

        # Username regen requires policy tightening, which lives in
        # main.py's generated_login_repair handler. If the caller
        # supplied a generator we run it; otherwise fall through so
        # that handler can pick up the request with full context.
        if FIELD_USERNAME in cmd.generate_fields and generate_username:
            new_draft["username_options"] = [generate_username()]
            new_draft["explicit_username_supplied"] = False
            changed.add(FIELD_USERNAME)
        elif FIELD_USERNAME in cmd.generate_fields:
            # Defer to the caller; we intentionally do not mutate.
            return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft)

        if not changed:
            return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft)

        opts = list(new_draft.get("username_options") or [])
        prelude = f"Regenerated your {service.title()} login draft."
        return DraftOutcome(
            kind=OUTCOME_UPDATED,
            draft=new_draft,
            reply_text=_format_draft_reply(
                service=service,
                username=(opts[0] if opts else None),
                password=str(new_draft.get("password") or "") or None,
                prelude=prelude,
            ),
            changed_fields=frozenset(changed),
        )

    return DraftOutcome(kind=OUTCOME_NO_ACTION, draft=draft)


__all__ = [
    "OUTCOME_UPDATED",
    "OUTCOME_SAVE_NOW",
    "OUTCOME_CANCELLED",
    "OUTCOME_SHOWN",
    "OUTCOME_REPLACED",
    "OUTCOME_NO_ACTION",
    "DraftOutcome",
    "apply_to_pending_draft",
]
