"""Shadow-mode diff logger for the chat brain v2.

Called only when ``VAULTAI_CHAT_BRAIN_MODE == "shadow"``:

    * v1 stays authoritative and its BrainResult is what the user sees;
    * v2 runs in read-only mode alongside;
    * this module produces one structured diff record per turn
      that captures the v2 verdict + a stable fingerprint for
      grouping disagreements without leaking sensitive values.

Disagreement categories (design memo rev 3, adopted here)
---------------------------------------------------------
    * ``intent_equivalent`` — v1 and v2 chose semantically-equivalent
      tools/intents.
    * ``different_semantics`` — v1 and v2 chose materially different
      outcomes given the same evidence.
    * ``insufficient_shadow_context`` — v2 lacked focus/state context
      that would only exist in ``on`` mode (e.g., focus records not
      yet stamped). NOT a v2 defect.
    * ``v2_validation_error`` — v2 returned a malformed decision,
      unknown target, or failed schema/policy validation. This IS
      a v2 defect.

Logging restrictions (design memo rev 4)
----------------------------------------
    * Raw target/vault/session IDs are NEVER emitted — a stable
      HMAC-8 fingerprint stands in.
    * Free-form ``reason`` / ``diagnostic`` text is NEVER emitted
      in production shadow logs.
    * User message text, model prompt bytes, model raw response,
      authorization contents, password references, and any
      credential values are NEVER emitted.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from vault_chat_policy_v2 import (
    OUTCOME_ALLOW,
    OUTCOME_CLARIFY,
    OUTCOME_REJECT,
    PolicyResultV2,
)
from vault_chat_semantic_decision_v2 import SemanticDecisionV2


logger = logging.getLogger(__name__)


# =====================================================================
# Disagreement categories (closed set)
# =====================================================================

MATCH_INTENT_EQUIVALENT:        str = "intent_equivalent"
MATCH_DIFFERENT_SEMANTICS:      str = "different_semantics"
MATCH_INSUFFICIENT_CONTEXT:     str = "insufficient_shadow_context"
MATCH_V2_VALIDATION_ERROR:      str = "v2_validation_error"

MATCH_CATEGORIES: frozenset[str] = frozenset({
    MATCH_INTENT_EQUIVALENT,
    MATCH_DIFFERENT_SEMANTICS,
    MATCH_INSUFFICIENT_CONTEXT,
    MATCH_V2_VALIDATION_ERROR,
})


# =====================================================================
# Fingerprint
# =====================================================================

_ENV_FINGERPRINT_SECRET: str = "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"
_DEFAULT_FINGERPRINT_SECRET: bytes = b"chat_brain_v2_default_shadow_fp_v1"

_HMAC_HEX_LEN: int = 16   # 8 bytes = 64-bit correlation


def _process_secret() -> bytes:
    """Read the fingerprint secret from the environment. Falls
    back to a constant default when unset — that default is safe
    for grouping within a single process but does not need to be
    stable across processes if operators do not set the env.
    """
    v = os.environ.get(_ENV_FINGERPRINT_SECRET, "").strip()
    if v:
        return v.encode("utf-8")
    return _DEFAULT_FINGERPRINT_SECRET


def fingerprint(
    *,
    intent:         str,
    target_kind:    Optional[str],
    target_id:      Optional[str],
    reason_code:    str,
    outcome:        str,
) -> str:
    """Stable HMAC-SHA256 truncated to 16 hex chars over the
    grouping key. The raw ``target_id`` is folded into the HMAC
    input but never emitted."""
    key = _process_secret()
    msg = (
        f"{intent or '-'}|{target_kind or '-'}|{target_id or '-'}|"
        f"{reason_code or '-'}|{outcome or '-'}"
    ).encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return mac[:_HMAC_HEX_LEN]


def target_id_fingerprint(vault_id: str, target_id: str) -> str:
    """Short correlation for a specific target across records
    without emitting the raw id. Used inside the DiffRecord's
    display fields."""
    if not target_id:
        return "-"
    key = _process_secret()
    msg = f"target|{vault_id or '-'}|{target_id}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:_HMAC_HEX_LEN]


def _short_correlation(s: str) -> str:
    """Non-secret short correlation for vault/session/turn ids.
    Uses the process secret so operators can group without
    reconstructing the raw id."""
    if not s:
        return "-"
    key = _process_secret()
    return hmac.new(key, s.encode("utf-8"), hashlib.sha256).hexdigest()[:_HMAC_HEX_LEN]


# =====================================================================
# Confidence bucketing (no raw float in logs)
# =====================================================================

def _confidence_bucket(conf: Optional[float]) -> str:
    if conf is None:
        return "-"
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


# =====================================================================
# Diff record
# =====================================================================

@dataclass(frozen=True)
class ShadowDiffRecordV2:
    """One shadow-mode observation. Fields are chosen to be safe
    to log to production telemetry without exposing user data.

    All ``*_hmac8`` fields are HMAC-SHA256 truncated to 16 hex
    chars (8 bytes / 64-bit correlation). ``target_id`` in the
    HMAC input is combined with the vault id to prevent
    cross-vault correlation.
    """
    vault_hmac8:            str
    session_hmac8:          str
    turn_hmac8:             str
    v1_tool:                str            # v1 legacy tool name if handled
    v1_handled:             bool
    v2_intent:              str
    v2_target_kind:         str
    v2_target_id_hmac8:     str
    v2_outcome:             str
    v2_reason_code:         str
    v2_confidence_bucket:   str
    v2_fingerprint:         str
    match:                  str            # one of MATCH_CATEGORIES
    note:                   str = ""

    def to_log_line(self) -> str:
        return (
            f"turn={self.turn_hmac8} vault={self.vault_hmac8} "
            f"sess={self.session_hmac8} "
            f"v1_tool={self.v1_tool or '-'} v1_handled={int(self.v1_handled)} "
            f"v2_intent={self.v2_intent} "
            f"v2_target_kind={self.v2_target_kind or '-'} "
            f"v2_target_hmac8={self.v2_target_id_hmac8} "
            f"v2_outcome={self.v2_outcome} "
            f"v2_reason={self.v2_reason_code} "
            f"v2_conf_bucket={self.v2_confidence_bucket} "
            f"v2_fp={self.v2_fingerprint} "
            f"match={self.match}"
            + (f" note={self.note}" if self.note else "")
        )


# =====================================================================
# Category classifier
# =====================================================================

# Map a v1 tool name → its normalized-intent equivalent for
# match-vs-different classification. v1 uses tool names like
# "confirm_pending_delete"; v2 uses intent names like
# "confirm_pending_action". This mapping is intentional and
# is checked at test time (see tests).
_V1_TOOL_TO_V2_INTENT_FAMILY: dict[str, frozenset[str]] = {
    "confirm_pending_delete": frozenset({
        "confirm_pending_action",
    }),
    "cancel_pending_delete":  frozenset({
        "cancel_pending_action",
    }),
    "confirm_pending_save":   frozenset({
        "confirm_draft", "confirm_pending_action",
    }),
    "cancel_pending_save":    frozenset({
        "cancel_draft", "cancel_pending_action",
    }),
    "request_clarification":  frozenset({
        "ask_clarification",
    }),
    "conversational_reply":   frozenset({
        "chat", "answer_question",
    }),
    "fallthrough":            frozenset({
        "fallthrough",
    }),
}


def _classify_match(
    v1_tool:   str,
    v1_handled: bool,
    v2_decision: Optional[SemanticDecisionV2],
    v2_policy:   Optional[PolicyResultV2],
) -> str:
    """Return one of MATCH_CATEGORIES.

    * v2 error → v2_validation_error
    * v1 fallthrough vs v2 fallthrough → intent_equivalent
    * v1 tool ≈ v2 intent per family map → intent_equivalent
    * v2 has focus-only reason but shadow can't build focus →
      insufficient_shadow_context
    * else → different_semantics
    """
    if v2_decision is None or v2_decision.error:
        return MATCH_V2_VALIDATION_ERROR

    intent = v2_decision.intent

    # Reasons that indicate v2 lacks context that would only exist
    # in `on` mode (e.g., persisted focus records).
    if v2_policy is not None:
        insufficient_reasons = {
            "INSUFFICIENT_CONTEXT",
            "TARGET_NOT_FOCUSED",
            "EXPIRED_FOCUS",
        }
        if v2_policy.reason_code in insufficient_reasons \
                and v2_policy.outcome == OUTCOME_CLARIFY:
            return MATCH_INSUFFICIENT_CONTEXT

    # v1 fallthrough vs v2 fallthrough
    if not v1_handled and intent == "fallthrough":
        return MATCH_INTENT_EQUIVALENT

    # Map v1 tool to v2 intent family
    family = _V1_TOOL_TO_V2_INTENT_FAMILY.get(v1_tool, frozenset())
    if intent in family:
        return MATCH_INTENT_EQUIVALENT

    return MATCH_DIFFERENT_SEMANTICS


# =====================================================================
# Public entry point
# =====================================================================

def build_and_log_diff(
    *,
    vault_id:        str,
    session_id:      Optional[str],
    turn_id:         str,
    v1_tool:         str,
    v1_handled:      bool,
    v2_decision:     Optional[SemanticDecisionV2],
    v2_policy:       Optional[PolicyResultV2],
    note:            str = "",
) -> ShadowDiffRecordV2:
    """Build a diff record and emit it to the standard logger.

    Returns the record so tests can inspect the derived fields
    (fingerprint, HMAC-8 correlations, match category).
    """
    if v2_decision is not None:
        target_id = v2_decision.target.id or ""
        v2_target_kind = v2_decision.target.kind
        v2_intent = v2_decision.intent
        v2_conf_bucket = _confidence_bucket(v2_decision.confidence)
    else:
        target_id = ""
        v2_target_kind = "-"
        v2_intent = "-"
        v2_conf_bucket = "-"

    if v2_policy is not None:
        v2_outcome = v2_policy.outcome
        v2_reason = v2_policy.reason_code
    else:
        v2_outcome = "-"
        v2_reason = "-"

    fp = fingerprint(
        intent=v2_intent,
        target_kind=v2_target_kind,
        target_id=target_id,
        reason_code=v2_reason,
        outcome=v2_outcome,
    )
    target_hmac = target_id_fingerprint(vault_id, target_id)

    record = ShadowDiffRecordV2(
        vault_hmac8=_short_correlation(vault_id),
        session_hmac8=_short_correlation(session_id or ""),
        turn_hmac8=_short_correlation(turn_id),
        v1_tool=v1_tool or "-",
        v1_handled=bool(v1_handled),
        v2_intent=v2_intent,
        v2_target_kind=v2_target_kind,
        v2_target_id_hmac8=target_hmac,
        v2_outcome=v2_outcome,
        v2_reason_code=v2_reason,
        v2_confidence_bucket=v2_conf_bucket,
        v2_fingerprint=fp,
        match=_classify_match(v1_tool, v1_handled, v2_decision, v2_policy),
        note=note,
    )
    logger.info("[SHADOW_V2] %s", record.to_log_line())
    return record


__all__ = [
    "MATCH_INTENT_EQUIVALENT",
    "MATCH_DIFFERENT_SEMANTICS",
    "MATCH_INSUFFICIENT_CONTEXT",
    "MATCH_V2_VALIDATION_ERROR",
    "MATCH_CATEGORIES",
    "fingerprint",
    "target_id_fingerprint",
    "ShadowDiffRecordV2",
    "build_and_log_diff",
]
