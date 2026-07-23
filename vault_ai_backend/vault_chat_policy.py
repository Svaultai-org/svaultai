"""Deterministic authorization + safety gate for the chat brain.

Sits between the semantic decider (which produces a structured
``Decision``) and the router (which dispatches to the actual
tool). The policy layer's job is: given a ``TurnSnapshot`` and a
``Decision``, decide whether the decision is authorized to run.

Explicit rules — no model involvement:

  * ``confirm_pending_delete``:
      - A pending delete action MUST exist for this
        (vault_id, session_id).
      - The pending action MUST match the ``action_id`` argument
        the model provided (verbatim string match).
      - Confidence MUST be ``high``.
      - The deterministic safety layer (``vault_pending_draft_confirm``
        / narrow destructive-confirm regex) MUST also accept the
        user's message OR the model's confidence MUST be high AND
        the message MUST be short (defense in depth against
        model over-eager interpretation of an unrelated long
        reply).

  * ``cancel_pending_delete`` / ``cancel_pending_save``:
      - Cancellation is safe by definition; require only that a
        matching pending action exists.

  * ``confirm_pending_save``:
      - A pending action of a save kind MUST exist for this
        (vault_id, session_id).
      - ``action_id`` and ``pending_kind`` MUST match the arbiter's
        currently-active pending action.
      - Non-destructive, so confidence ``medium`` or higher is
        acceptable.

  * ``request_clarification`` / ``conversational_reply`` /
    ``fallthrough``:
      - Always authorized. These do not modify vault state.

Anything not authorized falls through to the existing chat
pipeline — the router treats a rejected decision as if the
decider had returned ``fallthrough``. This keeps the safety
posture "fail-open to the pre-2026-07-24 pipeline" rather than
"fail-closed and refuse to answer".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from vault_chat_pending_action import (
    KIND_NONE,
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_SECURE_ITEM,
    PendingAction,
)
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Decision,
)
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


# Defense-in-depth: destructive confirm requires the user's message
# to look like a genuine confirmation utterance. This regex is
# INTENTIONALLY narrow and covers ONLY the destructive-confirm
# path — it is not a general phrase list. The semantic decider
# handles paraphrase understanding; this exists purely as a
# guard against a model over-eager on an unrelated reply.
#
# The message must be short (≤ 80 chars after strip) AND match one
# of the patterns below. Longer replies are NOT accepted as
# destructive confirms via this narrow gate; the decider's
# high-confidence signal alone is not enough for a destructive
# action if the reply is long enough to plausibly be about
# something else.

_DESTRUCTIVE_CONFIRM_MAX_LEN: int = 80


# One "confirmation token" — a word or short phrase that reads as
# affirmation OR an action-verb the user commonly uses to confirm.
# The full destructive-confirm regex accepts a chain of these
# separated by whitespace/punctuation, so combinations like
# "yeah go ahead", "sure thing", "please proceed", "ok delete it"
# all match. Keeps the gate narrow enough to reject a long
# unrelated reply while broad enough not to mis-reject a natural
# affirmation.
_CONFIRM_TOKEN = (
    r"(?:"
    r"yes|yea|yeah|yep|yup|yee|y|ya|"
    r"ok|okay|k|"
    r"sure|fine|correct|right|thing|"
    r"confirm(?:ed)?|"
    r"proceed|approved|affirmative|"
    r"please|now|plz|"
    r"go\s*ahead|do\s*it|"
    r"go(?:\s+for\s+it)?|"
    r"delete(?:\s+(?:it|that|now))?|"
    r"remove(?:\s+(?:it|that))?|"
    r"it|that|this"
    r")"
)


_DESTRUCTIVE_CONFIRM_RE: re.Pattern[str] = re.compile(
    r"""
    ^\s*
    (?:
        (?:{tok})(?:[\s.!,]+{tok})*
      | i\s*(?:do|want\s*to|want|would\s*like\s*to)?\s*confirm
      | i'?m\s*sure
      | that'?s\s*(?:correct|right)
      | that\s*is\s*(?:correct|right)
    )
    [\s.!,]*
    $
    """.format(tok=_CONFIRM_TOKEN),
    re.IGNORECASE | re.VERBOSE,
)


_DESTRUCTIVE_CANCEL_RE: re.Pattern[str] = re.compile(
    r"""
    ^\s*
    (?:
        no | nope | nah | n
      | cancel | stop | halt
      | don'?t | do\s*not
      | keep\s*(?:it|them|that)
      | never\s*mind | nevermind
      | on\s*second\s*thought
      | actually\s*(?:no|don'?t|do\s*not)
    )
    [\s.!,]*
    (?:
        please | now | it | that | this
      | delete\s*it
    )?
    [\s.!,]*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class PolicyResult:
    approved: bool
    reason:   str = ""
    tool:     str = ""

    def as_fallthrough(self) -> bool:
        return not self.approved


APPROVED: str = "approved"


def _looks_like_destructive_confirm(user_message: str) -> bool:
    if not isinstance(user_message, str):
        return False
    stripped = user_message.strip()
    if not stripped:
        return False
    if len(stripped) > _DESTRUCTIVE_CONFIRM_MAX_LEN:
        return False
    return bool(_DESTRUCTIVE_CONFIRM_RE.match(stripped))


def _looks_like_destructive_cancel(user_message: str) -> bool:
    if not isinstance(user_message, str):
        return False
    stripped = user_message.strip()
    if not stripped:
        return False
    if len(stripped) > _DESTRUCTIVE_CONFIRM_MAX_LEN:
        return False
    return bool(_DESTRUCTIVE_CANCEL_RE.match(stripped))


def _action_ids_match(pending: PendingAction, args: dict) -> bool:
    supplied = str(args.get("action_id") or "")
    if not supplied:
        return False
    return supplied == pending.action_id


def authorize(
    *,
    snapshot: TurnSnapshot,
    decision: Decision,
) -> PolicyResult:
    """Return an authorization result for the decider's decision.

    NEVER raises. On any unexpected state returns a non-approving
    result so the router falls through to the existing pipeline.
    """
    tool = decision.tool
    if not isinstance(tool, str) or not tool:
        return PolicyResult(approved=False, reason="empty_tool")

    # -----------------------------------------------------------
    # Non-mutating decisions — always safe.
    # -----------------------------------------------------------
    if tool == TOOL_FALLTHROUGH:
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )
    if tool == TOOL_CONVERSATIONAL_REPLY:
        # Only harmless if the confidence is above LOW. A LOW-
        # confidence conversational reply might be the model
        # guessing at a vault question that should have gone to
        # fallthrough. Route those to fallthrough for safety.
        if decision.confidence == CONFIDENCE_LOW:
            return PolicyResult(
                approved=False, reason="low_confidence_conversational",
            )
        # If a destructive action is pending, do NOT let the
        # decider silently switch topics with a conversational
        # reply — the safer choice is fallthrough or a
        # clarification.
        if snapshot.pending_action.is_destructive:
            return PolicyResult(
                approved=False,
                reason="destructive_pending_conversational_refused",
            )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )
    if tool == TOOL_REQUEST_CLARIFICATION:
        question = str(decision.args.get("question") or "").strip()
        if not question:
            return PolicyResult(
                approved=False, reason="clarification_empty_question",
            )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )

    # -----------------------------------------------------------
    # Confirmation of a pending action — must match arbiter.
    # -----------------------------------------------------------
    pending = snapshot.pending_action

    if tool == TOOL_CONFIRM_PENDING_DELETE:
        if pending.kind != KIND_DELETE_SECURE_ITEM:
            return PolicyResult(
                approved=False,
                reason=f"no_pending_delete (kind={pending.kind})",
            )
        if not _action_ids_match(pending, decision.args):
            return PolicyResult(
                approved=False, reason="action_id_mismatch_delete",
            )
        if decision.confidence != CONFIDENCE_HIGH:
            return PolicyResult(
                approved=False,
                reason=f"confidence_not_high ({decision.confidence})",
            )
        # Defense in depth — the message must look like a confirm
        # utterance too. This prevents an over-eager model from
        # confirming a delete on a message that clearly isn't
        # a confirmation.
        if not _looks_like_destructive_confirm(snapshot.user_message):
            return PolicyResult(
                approved=False,
                reason="destructive_safety_gate_denied",
            )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )

    if tool == TOOL_CANCEL_PENDING_DELETE:
        if pending.kind != KIND_DELETE_SECURE_ITEM:
            return PolicyResult(
                approved=False,
                reason=f"no_pending_delete_to_cancel (kind={pending.kind})",
            )
        if not _action_ids_match(pending, decision.args):
            return PolicyResult(
                approved=False, reason="action_id_mismatch_cancel_delete",
            )
        # Cancellation is safe by definition — accept MEDIUM+ or
        # any confidence if the message looks like a cancel.
        if (
            decision.confidence == CONFIDENCE_LOW
            and not _looks_like_destructive_cancel(snapshot.user_message)
        ):
            return PolicyResult(
                approved=False,
                reason="low_confidence_cancel_delete_no_gate",
            )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )

    if tool == TOOL_CONFIRM_PENDING_SAVE:
        save_kinds = (
            KIND_SAVE_CREDENTIAL,
            KIND_SAVE_LOGIN_DRAFT,
            KIND_SAVE_ATTACHMENT,
            KIND_SAVE_SECURE_ITEM,
        )
        if pending.kind not in save_kinds:
            return PolicyResult(
                approved=False,
                reason=f"no_pending_save (kind={pending.kind})",
            )
        supplied_kind = decision.args.get("pending_kind")
        if supplied_kind != pending.kind:
            return PolicyResult(
                approved=False,
                reason=(
                    f"pending_kind_mismatch model={supplied_kind!r} "
                    f"actual={pending.kind!r}"
                ),
            )
        if not _action_ids_match(pending, decision.args):
            return PolicyResult(
                approved=False, reason="action_id_mismatch_save",
            )
        if decision.confidence == CONFIDENCE_LOW:
            return PolicyResult(
                approved=False, reason="low_confidence_save",
            )
        # Save-attachment is the historical hijack vector — hold
        # it to the same defense-in-depth bar as destructive
        # confirms.
        if pending.kind == KIND_SAVE_ATTACHMENT:
            if not _looks_like_destructive_confirm(snapshot.user_message):
                return PolicyResult(
                    approved=False,
                    reason="attachment_save_narrow_gate_denied",
                )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )

    if tool == TOOL_CANCEL_PENDING_SAVE:
        save_kinds = (
            KIND_SAVE_CREDENTIAL,
            KIND_SAVE_LOGIN_DRAFT,
            KIND_SAVE_ATTACHMENT,
            KIND_SAVE_SECURE_ITEM,
        )
        if pending.kind not in save_kinds:
            return PolicyResult(
                approved=False,
                reason=f"no_pending_save_to_cancel (kind={pending.kind})",
            )
        if not _action_ids_match(pending, decision.args):
            return PolicyResult(
                approved=False,
                reason="action_id_mismatch_cancel_save",
            )
        return PolicyResult(
            approved=True, reason=APPROVED, tool=tool,
        )

    return PolicyResult(
        approved=False, reason=f"unknown_tool:{tool!r}",
    )


def _log_policy(
    snapshot: TurnSnapshot,
    decision: Decision,
    result: PolicyResult,
) -> None:
    logger.info(
        "[POLICY] tool=%s approved=%s reason=%s "
        "pending_kind=%s dest=%s conf=%s vault=%s",
        decision.tool,
        result.approved,
        result.reason,
        snapshot.pending_action.kind,
        bool(snapshot.pending_action.is_destructive),
        decision.confidence,
        (snapshot.vault_id or "")[:8] + "…",
    )


__all__ = [
    "PolicyResult",
    "APPROVED",
    "authorize",
]
