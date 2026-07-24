"""SemanticDeciderV2 — prompt contract and provider-facing async
``decide_v2`` function for the chat-brain v2 semantic reasoning
path.

Scope of this module (commit 2)
-------------------------------
This module defines:

    * ``SemanticDecisionV2Context`` — a self-contained input
      object describing everything the v2 decider needs to
      produce a decision. Deliberately NOT ``TurnSnapshot`` —
      integration with the existing snapshot happens in commit
      5, so commit 2 does not modify any existing chat-brain
      file.

    * ``build_prompt_v2(context)`` — pure function that renders
      the system + user messages the model receives.

    * ``decide_v2(context, *, ai_provider, timeout_s)`` — async
      function that invokes an ``ai_provider`` callable, parses
      its response with
      ``vault_chat_semantic_decision_v2.parse_semantic_decision_v2``,
      and returns a validated ``SemanticDecisionV2``.

Never raises. Failure modes — timeout, transport error, empty
content, malformed JSON, unknown intent, invalid schema, etc. —
all resolve to a fallthrough ``SemanticDecisionV2`` with the
``error`` field populated so callers and logs can see why.

Not in this module (deferred to later commits)
----------------------------------------------

    * Any wiring into ``vault_chat_brain.run_chat_brain``.
    * Any policy-layer check (target.id ∈ snapshot, focus binding,
      confidence-threshold execution decisions). This module
      returns a *validated* decision, not an *authorized* one.
    * Any writes to Redis (drafts, focus, auth). This module is
      read-only w.r.t. state.
    * Any feature-flag reading. Callers decide when to invoke
      ``decide_v2``.

Security invariants preserved by this module
--------------------------------------------

    * Never logs raw ``user_message``, model prompt bytes, model
      raw response, or the parsed decision's ``reason`` field
      in production log lines.
    * Never inspects a ``password_ref`` beyond passing it
      through. The prompt-facing context should already be a
      redacted view (produced by ``Draft.to_prompt_dict()``);
      this module does not re-check that assertion, but it does
      not introduce any new exposure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

from vault_chat_semantic_decision_v2 import (
    SEMANTIC_DECISION_V2_SCHEMA_VERSION,
    SemanticDecisionV2,
    make_fallthrough,
    parse_semantic_decision_v2,
)


logger = logging.getLogger(__name__)


DECIDER_V2_TIMEOUT_S:      float = 10.0
DECIDER_V2_MAX_TOKENS:     int   = 800


# -------------------------------------------------------------------
# Context input — self-contained view for the decider.
# -------------------------------------------------------------------

@dataclass(frozen=True)
class SemanticDecisionV2Context:
    """Everything the v2 decider needs to produce a decision.

    Fields:

        vault_id
            Opaque vault identifier. Used only for correlation
            logging (never sent to the model directly except via
            the redacted context this dataclass wraps).

        session_id
            Opaque session identifier. Same treatment as vault_id.

        user_message
            The current user turn's raw text. Sent to the model
            as the primary reasoning target.

        active_drafts
            Tuple of redacted draft views (see
            ``vault_chat_draft.Draft.to_prompt_dict``). MUST NOT
            contain raw secret values.

        pending_actions
            Tuple of safe-view pending-action dicts (see
            ``vault_chat_pending_action.PendingAction.to_prompt_dict``).

        focus
            Optional focus dict. In on mode this is a real
            persisted focus; in shadow mode it may be a
            synthesized ephemeral focus with
            ``synthetic_shadow=True``.

        recent_turns
            Bounded tuple of prior turn dicts (role, text). MUST
            already be truncated by the caller.

        conversation_digest
            Short factual summary of conversation state so far.

        known_target_ids
            Union of draft_id + pending_action.action_id +
            active_entity id, populated from
            ``active_drafts``/``pending_actions``/etc. by the
            caller. The parser uses this to reject decisions
            with unknown ``target.id`` early.
    """
    vault_id:              str
    session_id:            Optional[str]
    user_message:          str
    active_drafts:         Tuple[dict, ...] = ()
    pending_actions:       Tuple[dict, ...] = ()
    focus:                 Optional[dict]   = None
    recent_turns:          Tuple[dict, ...] = ()
    conversation_digest:   str              = ""
    known_target_ids:      frozenset[str]   = field(default_factory=frozenset)


# -------------------------------------------------------------------
# Prompt contract
# -------------------------------------------------------------------

_SYSTEM_PROMPT_V2: str = """\
You are the intent arbiter for the VaultAI chat brain — a
zero-knowledge personal vault plus assistant. You receive a
compact snapshot of the current turn (user_message, active
drafts, pending actions, conversational focus, recent turns,
conversation digest) and must return EXACTLY ONE structured
decision as a single JSON object. No prose. No markdown fences.

The backend re-validates every decision structurally and
deterministically. Your job is meaning; the backend enforces
legality.

# THE DECISION SCHEMA

Return a JSON object with EXACTLY these top-level keys:

    schema_version         (integer — always {SCHEMA_VERSION})
    intent                 (string — one of the intents below)
    target                 (object — {"kind": ..., "id": ...})
    field_patch            (object — see below; may be empty)
    requested_operations   (array  — see below; may be empty)
    authorization          (object — see below)
    confidence             (number — in [0.0, 1.0])
    reason                 (string — one short sentence)

Any additional or misspelled top-level key REJECTS the decision.

# INTENTS (closed set)

    "edit_draft"                — user is modifying an existing draft
    "create_draft"              — user is starting a new draft
    "confirm_draft"             — user approves saving a draft
    "cancel_draft"              — user rejects a draft
    "confirm_pending_action"    — user approves a proposed pending action
    "cancel_pending_action"     — user rejects a proposed pending action
    "answer_question"           — reply from vault state (pipeline handles)
    "ask_clarification"         — you need more info; provide short question
    "chat"                      — greeting / capability / small talk
    "fallthrough"               — pipeline handles this turn (retrieval, generation, etc.)

# TARGET

    {"kind": "draft" | "pending_action" | "active_entity" | "none",
     "id":   "<verbatim id from snapshot>" | null}

The id MUST be one that appears in the snapshot. NEVER invent
an id. If you cannot ground a reference, use "kind":"none" and
choose "ask_clarification".

# FIELD_PATCH (only for create_draft / edit_draft)

    {
      "<field_name>": {
        "op": "replace" | "clear" | "regenerate" | "unchanged",
        "value": "<new value — only for op=replace>"
      }
    }

    * op=replace: MUST include "value".
    * op=clear:      MUST NOT include "value".
    * op=regenerate: MUST NOT include "value"; MUST have a matching
                     entry in requested_operations.
    * op=unchanged:  MUST NOT include "value"; a no-op.

    NEVER put a plaintext password in "value". Password
    regeneration is expressed by op=regenerate + a
    requested_operations entry.

# REQUESTED_OPERATIONS (only for create_draft / edit_draft)

    [ {"operation": "generate_password", "field": "password_ref",
       "policy_hint": "stronger" | "different" | null } ]

Currently the only supported operation is "generate_password"
on the "password_ref" field. Do not invent operations.

# AUTHORIZATION (only for confirm_* / cancel_*)

    {
      "granted": true | false,
      "scope": {
        "target_id": "<must equal target.id>",
        "action":    "save" | "delete" | "save_attachment" | null
      }
    }

    * granted=true is ONLY valid for the four confirm/cancel intents.
    * scope.target_id MUST equal target.id.
    * action MUST match target.kind (save→draft/pending; delete→pending;
      save_attachment→pending).

# CONFIDENCE

Numeric [0.0, 1.0]. The policy layer downgrades low-confidence
decisions to ask_clarification. Prefer ask_clarification over a
low-confidence execute.

# REASON

One short sentence describing your semantic interpretation.
Never repeat sensitive user values in the reason (no passwords,
no full credential strings). This is a debug field only — the
backend does NOT use it for authorization.

# HOW TO REASON

1. Read snapshot.user_message.
2. Consider snapshot.focus — what did the assistant just present
   or ask about? A short/generic confirmation ("yes", "ok") that
   is not clearly bound to the focus must NOT authorize a
   different target.
3. If the user is editing a draft field, use intent=edit_draft
   with a minimal field_patch. Do NOT save.
4. If the user is confirming a presented draft, use
   intent=confirm_draft with authorization.granted=true and
   scope.target_id equal to the draft's id.
5. If the user is asking about vault contents, choose
   intent=fallthrough — the pipeline reads the vault.
6. If ambiguous or if a required target is not in the snapshot,
   choose intent=ask_clarification with a short question in
   reason. Do NOT invent target ids.

# HARD RULES

    * JSON only. No prose before or after. No markdown fences.
    * Never invent intent names, target ids, operation names,
      field names, or actions.
    * Never fabricate a completed action.
    * Never include plaintext passwords or secret values anywhere
      in the decision.
"""


def _render_system_prompt() -> str:
    return _SYSTEM_PROMPT_V2.replace(
        "{SCHEMA_VERSION}", str(SEMANTIC_DECISION_V2_SCHEMA_VERSION),
    )


def build_prompt_v2(context: SemanticDecisionV2Context) -> list[dict]:
    """Render the [system, user] message pair for the model.

    The user message contains a JSON snapshot of the context.
    The caller is responsible for having redacted all secret
    fields before constructing the ``active_drafts`` /
    ``pending_actions`` views.
    """
    payload = {
        "user_message":         context.user_message,
        "active_drafts":        list(context.active_drafts),
        "pending_actions":      list(context.pending_actions),
        "focus":                context.focus,
        "recent_turns":         list(context.recent_turns),
        "conversation_digest":  context.conversation_digest,
        "known_target_ids":     sorted(context.known_target_ids),
    }
    return [
        {"role": "system", "content": _render_system_prompt()},
        {"role": "user",   "content": json.dumps(
            {"snapshot": payload,
             "instructions": "Choose exactly one intent. Return JSON only."},
            ensure_ascii=False,
        )},
    ]


# -------------------------------------------------------------------
# Async decider entrypoint
# -------------------------------------------------------------------

async def decide_v2(
    context:      SemanticDecisionV2Context,
    *,
    ai_provider:  Callable[..., Any],
    timeout_s:    Optional[float] = None,
) -> SemanticDecisionV2:
    """Invoke the AI provider and return a validated decision.

    Never raises. All failure modes resolve to a fallthrough
    ``SemanticDecisionV2`` with a diagnostic ``error``.

    ``ai_provider`` is a callable with the same async contract as
    v1's ``chat_complete_with_fallback`` — it receives keyword
    args ``messages``, ``model_kind``, ``temperature``,
    ``max_tokens``, ``response_format``, ``timeout`` and returns
    an object with a ``.content`` attribute. Tests supply
    deterministic providers.
    """
    if not isinstance(context, SemanticDecisionV2Context):
        return make_fallthrough(error="context_invalid")

    messages = build_prompt_v2(context)
    started = time.time()
    to = float(timeout_s) if timeout_s is not None else DECIDER_V2_TIMEOUT_S

    try:
        result = await asyncio.wait_for(
            ai_provider(
                messages=messages,
                model_kind="intent",
                temperature=0.0,
                max_tokens=DECIDER_V2_MAX_TOKENS,
                response_format={"type": "json_object"},
                timeout=to,
            ),
            timeout=to + 2.0,
        )
    except asyncio.TimeoutError:
        _log_v2("timeout", context, started, error="timeout")
        return make_fallthrough(error="timeout")
    except Exception as exc:
        _log_v2("transport", context, started,
                error=f"transport:{type(exc).__name__}")
        return make_fallthrough(error=f"transport:{type(exc).__name__}")

    content = getattr(result, "content", "") or ""
    if not isinstance(content, str) or not content.strip():
        _log_v2("empty", context, started, error="empty_content")
        return make_fallthrough(error="empty_content")

    decision = parse_semantic_decision_v2(
        content,
        known_target_ids=context.known_target_ids or None,
    )
    _log_v2(decision.intent, context, started,
            error=decision.error or "-",
            confidence_bucket=_bucket(decision.confidence))
    return decision


# -------------------------------------------------------------------
# Logging — safe fields only. NEVER logs user_message, prompt,
# raw content, reason, target.id, or any credential value.
# -------------------------------------------------------------------

def _log_v2(
    outcome:          str,
    context:          SemanticDecisionV2Context,
    started:          float,
    *,
    error:            str = "-",
    confidence_bucket: str = "-",
) -> None:
    logger.info(
        "[DECIDER_V2] outcome=%s vault=%s sess=%s "
        "drafts=%d pending=%d focus=%s "
        "conf_bucket=%s elapsed_ms=%d error=%s",
        outcome,
        _short(context.vault_id),
        _short(context.session_id or ""),
        len(context.active_drafts),
        len(context.pending_actions),
        (context.focus or {}).get("kind", "-") if isinstance(context.focus, dict) else "-",
        confidence_bucket,
        int((time.time() - started) * 1000),
        error,
    )


def _short(s: str) -> str:
    if not s:
        return "-"
    return s[:8] + "…"


def _bucket(conf: float) -> str:
    try:
        c = float(conf)
    except Exception:
        return "-"
    if c < 0.85:
        return "lt85"
    if c < 0.90:
        return "85to90"
    if c < 0.95:
        return "90to95"
    return "gte95"


__all__ = [
    "DECIDER_V2_TIMEOUT_S",
    "DECIDER_V2_MAX_TOKENS",
    "SemanticDecisionV2Context",
    "build_prompt_v2",
    "decide_v2",
]
