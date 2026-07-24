"""Centralised confidence thresholds for the chat-brain v2 policy layer.

The v2 semantic decider returns a numeric ``confidence`` in the
range [0.0, 1.0]. Policy decisions (execute-vs-clarify,
destructive-vs-non-destructive, focus-bypass-vs-focus-bound) test
that value against thresholds. Those thresholds live here so no
policy rule scatters magic numbers across the codebase.

All thresholds are lower-bound inclusive: a rule that says
"requires >= NON_DESTRUCTIVE" accepts exactly the value 0.85.

Never import these into the v1 code path — v1 uses categorical
"low"/"medium"/"high" and its policies do not depend on floats.

This module is intentionally minimal and dependency-free so it
can be imported by any layer without risking a circular import.
"""

from __future__ import annotations


CONFIDENCE_EXECUTE_NON_DESTRUCTIVE: float = 0.85
"""Minimum confidence to execute a non-destructive intent
(confirm_draft on a save-flavored draft, cancel_draft, etc.).

Below this floor the policy layer downgrades to
``ask_clarification`` regardless of the model's reason.
"""


CONFIDENCE_EXECUTE_DESTRUCTIVE: float = 0.95
"""Minimum confidence to execute a destructive intent
(confirm_pending_action on a KIND_DELETE_SECURE_ITEM).

Higher than the non-destructive floor because the cost of a
false accept is asymmetric (destructive deletes are hard to
undo). The destructive-safety failsafe in
``vault_chat_brain._apply_destructive_failsafe`` remains a
separate, redundant last-resort check for deletes; the two
gates are additive, not substitutable.
"""


CONFIDENCE_EXECUTE_HIGH_CONTEXT: float = 0.95
"""Minimum confidence for a confirm decision to bypass the
default focus-binding rule (i.e. authorize a target that is
NOT the conversational focus).

At or above this threshold, the policy layer permits a
confirm decision whose ``target.id`` differs from
``snapshot.focus.id`` — the user has explicitly named or
disambiguated the target enough that the model is
confident the reference is unambiguous. Below the
threshold, the policy layer requires focus binding to
prevent hijack of a background pending action by a bare
confirmation.
"""


__all__ = [
    "CONFIDENCE_EXECUTE_NON_DESTRUCTIVE",
    "CONFIDENCE_EXECUTE_DESTRUCTIVE",
    "CONFIDENCE_EXECUTE_HIGH_CONTEXT",
]
