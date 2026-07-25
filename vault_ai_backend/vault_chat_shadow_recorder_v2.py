"""Shadow-mode diff logger for the chat brain v2.

Called only when ``VAULTAI_CHAT_BRAIN_MODE == "shadow"``:

    * v1 stays authoritative and its BrainResult is what the user sees;
    * v2 runs the full READ-ONLY decision stack alongside
      (snapshot -> decider -> policy -> router);
    * this module produces one structured diff record per turn
      that captures the v2 verdict + a stable fingerprint for
      grouping disagreements without leaking sensitive values.

Disagreement categories (closed set)
------------------------------------
    * ``intent_equivalent`` -- v1 and v2 chose semantically-equivalent
      tools/intents.
    * ``different_semantics`` -- v1 and v2 chose materially different
      outcomes given the same evidence.
    * ``insufficient_shadow_context`` -- v2 lacked focus/state context
      that would only exist in ``on`` mode (e.g., focus records not
      yet stamped). NOT a v2 defect.
    * ``v2_validation_error`` -- v2 returned a malformed decision,
      unknown target, or failed schema/policy validation. This IS
      a v2 defect.

Logging restrictions (commit 5a)
--------------------------------
    * Raw target/vault/session IDs are NEVER emitted -- correlation
      fields carry an HMAC-SHA256 truncated to 16 hex chars
      (64-bit truncation; the field suffix ``hmac64`` names the
      truncation width in bits, not bytes).
    * User message text, raw target labels, model prompt bytes,
      model raw response, authorization contents, password
      references, credential values, tokens, or Redis keys are
      NEVER emitted.
    * Free-form ``reason``/``diagnostic`` text is NEVER emitted
      -- only closed-set reason codes.
    * Usernames and email addresses may enter the decider prompt
      (where a user's own "use my email as the username" edit
      requires it) but MUST NEVER appear in shadow logs,
      fingerprints, or telemetry.

Fingerprint-secret contract (commit 5a)
---------------------------------------
    * Env var ``VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET`` must
      hold a deployment-provided secret at least
      ``MIN_FINGERPRINT_SECRET_LEN`` bytes.
    * No default constant is baked into runtime code.
    * If the secret is absent when shadow mode runs, this module
      emits a fingerprint-free diff record (all correlation
      fields carry the sentinel ``NOFP_SENTINEL``) and logs one
      WARNING per process so operators notice.
    * Tests inject a fixed secret via
      ``configure_fingerprint_secret_for_tests(secret)`` and
      reset with ``reset_fingerprint_secret_for_tests()``.
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
from vault_chat_v2_versions import compute_v2_revision_stamp


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
# Disagreement source attribution (closed set)
#
# For every diff record we attribute the layer at which v1 and v2
# started to diverge. Analysts investigate different sources with
# different playbooks (semantic disagreement -> LLM prompt work;
# router disagreement -> action-kind wiring; policy disagreement
# -> reason-code semantics; etc.).
# =====================================================================

DISAGREEMENT_SOURCE_NONE:                      str = "NONE"
DISAGREEMENT_SOURCE_SEMANTIC:                  str = "SEMANTIC"
DISAGREEMENT_SOURCE_POLICY:                    str = "POLICY"
DISAGREEMENT_SOURCE_ROUTER:                    str = "ROUTER"
DISAGREEMENT_SOURCE_INSUFFICIENT_CONTEXT:      str = "INSUFFICIENT_CONTEXT"
DISAGREEMENT_SOURCE_V2_ERROR:                  str = "V2_ERROR"
DISAGREEMENT_SOURCE_UNKNOWN:                   str = "UNKNOWN"

DISAGREEMENT_SOURCES: frozenset[str] = frozenset({
    DISAGREEMENT_SOURCE_NONE,
    DISAGREEMENT_SOURCE_SEMANTIC,
    DISAGREEMENT_SOURCE_POLICY,
    DISAGREEMENT_SOURCE_ROUTER,
    DISAGREEMENT_SOURCE_INSUFFICIENT_CONTEXT,
    DISAGREEMENT_SOURCE_V2_ERROR,
    DISAGREEMENT_SOURCE_UNKNOWN,
})


# =====================================================================
# Fingerprint secret (no runtime default)
# =====================================================================

_ENV_FINGERPRINT_SECRET: str = "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"

MIN_FINGERPRINT_SECRET_LEN: int = 32
"""Minimum acceptable length (bytes, post-utf8-encode) for the
fingerprint secret. Rejects trivial 'x'/'secret'/'password' values."""

_HMAC_HEX_LEN: int = 16
"""16 hex chars = 8 bytes = 64-bit truncation. Field suffix
``hmac64`` names the bit-width."""

NOFP_SENTINEL: str = "-no-fp-secret-"
"""Value substituted for every fingerprint/correlation field when
no fingerprint secret is available. Reads as clearly-not-a-real-
hash so operators cannot mistake it for a truncation collision."""

# Test-only injection. Never touched by runtime code paths (they
# only ever read ``_process_secret()`` which consults env first).
_TEST_INJECTED_SECRET: Optional[bytes] = None
_MISSING_SECRET_WARNED_ONCE: bool = False


def configure_fingerprint_secret_for_tests(secret: bytes) -> None:
    """TEST-ONLY: inject a fixed secret so tests get stable
    fingerprints without setting a process-wide env var. Must
    be called from setUp; reset in tearDown."""
    global _TEST_INJECTED_SECRET
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 8:
        raise ValueError("test fingerprint secret must be >= 8 bytes")
    _TEST_INJECTED_SECRET = bytes(secret)


def reset_fingerprint_secret_for_tests() -> None:
    global _TEST_INJECTED_SECRET, _MISSING_SECRET_WARNED_ONCE
    _TEST_INJECTED_SECRET = None
    _MISSING_SECRET_WARNED_ONCE = False


def _process_secret() -> Optional[bytes]:
    """Return the fingerprint secret bytes, or ``None`` if no
    valid secret is configured. Never returns a compile-time
    default -- callers MUST handle ``None`` explicitly (either
    emit fingerprint-free records or skip logging)."""
    if _TEST_INJECTED_SECRET is not None:
        return _TEST_INJECTED_SECRET
    raw = (os.environ.get(_ENV_FINGERPRINT_SECRET) or "").strip()
    if not raw:
        return None
    encoded = raw.encode("utf-8")
    if len(encoded) < MIN_FINGERPRINT_SECRET_LEN:
        return None
    return encoded


def _warn_missing_secret_once() -> None:
    global _MISSING_SECRET_WARNED_ONCE
    if _MISSING_SECRET_WARNED_ONCE:
        return
    _MISSING_SECRET_WARNED_ONCE = True
    logger.warning(
        "[BRAIN_V2] shadow fingerprint secret not configured "
        "(env %s unset or too short; min %d bytes). "
        "Emitting fingerprint-free shadow diff records.",
        _ENV_FINGERPRINT_SECRET, MIN_FINGERPRINT_SECRET_LEN,
    )


def fingerprint(
    *,
    intent:         str,
    target_kind:    Optional[str],
    target_id:      Optional[str],
    reason_code:    str,
    outcome:        str,
) -> str:
    """HMAC-SHA256 truncated to 16 hex chars (64-bit truncation)
    over the grouping key. The raw ``target_id`` is folded into
    the HMAC input but never emitted. Returns
    ``NOFP_SENTINEL`` when no fingerprint secret is configured."""
    key = _process_secret()
    if key is None:
        return NOFP_SENTINEL
    msg = (
        f"{intent or '-'}|{target_kind or '-'}|{target_id or '-'}|"
        f"{reason_code or '-'}|{outcome or '-'}"
    ).encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return mac[:_HMAC_HEX_LEN]


def target_id_fingerprint(vault_id: str, target_id: str) -> str:
    """Short correlation for a specific target across records
    without emitting the raw id. Used inside the DiffRecord's
    correlation fields. Returns ``NOFP_SENTINEL`` when no
    fingerprint secret is configured."""
    if not target_id:
        return "-"
    key = _process_secret()
    if key is None:
        return NOFP_SENTINEL
    msg = f"target|{vault_id or '-'}|{target_id}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:_HMAC_HEX_LEN]


def _short_correlation(s: str) -> str:
    """Non-secret short correlation for vault/session/turn ids.
    Uses the process secret so operators can group without
    reconstructing the raw id. Returns ``NOFP_SENTINEL`` when
    no fingerprint secret is configured."""
    if not s:
        return "-"
    key = _process_secret()
    if key is None:
        return NOFP_SENTINEL
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
# Router-summary view (closed-set summary of the shadow router)
# =====================================================================

@dataclass(frozen=True)
class ShadowRouterView:
    """Closed-set summary of a shadow-mode ``RouterResultV2``.
    Carries only closed-set fields (reply_kind, next_state,
    action_kind, handled). NEVER carries reply_text, diagnostic
    text, focus contents, or any raw target id."""
    handled:      bool
    reply_kind:   str
    next_state:   str
    action_kind:  str = ""

    @classmethod
    def from_router(cls, rr) -> "ShadowRouterView":
        plan = getattr(rr, "execution_plan", None)
        action_kind = getattr(plan, "action_kind", "") if plan else ""
        return cls(
            handled=bool(rr.handled),
            reply_kind=rr.reply_kind,
            next_state=rr.next_state,
            action_kind=action_kind or "",
        )


# =====================================================================
# Diff record
# =====================================================================

@dataclass(frozen=True)
class ShadowDiffRecordV2:
    """One shadow-mode observation. Fields are chosen to be safe
    to log to production telemetry without exposing user data.

    All ``*_hmac64`` fields are HMAC-SHA256 truncated to 16 hex
    chars (64-bit truncation). ``target_id_hmac64``'s HMAC input
    is combined with the vault id to prevent cross-vault
    correlation. When the fingerprint secret is not configured,
    every correlation field carries ``NOFP_SENTINEL``.
    """
    vault_hmac64:            str
    session_hmac64:          str
    turn_hmac64:             str
    v1_tool:                 str            # v1 legacy tool name if handled
    v1_handled:              bool
    v2_intent:               str
    v2_target_kind:          str
    v2_target_id_hmac64:     str
    v2_outcome:              str
    v2_reason_code:          str
    v2_confidence_bucket:    str
    v2_fingerprint:          str
    match:                   str            # one of MATCH_CATEGORIES
    router_view:             Optional[ShadowRouterView] = None
    fp_available:            bool = True
    # commit 8: closed-set enum naming the layer at which v1 and
    # v2 diverged. NONE for equivalent turns.
    disagreement_source:     str = DISAGREEMENT_SOURCE_NONE
    # commit 8: multi-layer revision stamp. Historical shadow
    # logs remain interpretable after later architectural changes.
    v2_revision_stamp:       str = ""
    note:                    str = ""

    def __post_init__(self) -> None:
        if self.disagreement_source not in DISAGREEMENT_SOURCES:
            raise ValueError(
                f"unknown disagreement_source {self.disagreement_source!r}"
            )
        if self.match not in MATCH_CATEGORIES:
            raise ValueError(f"unknown match category {self.match!r}")

    def to_log_line(self) -> str:
        rv = self.router_view
        router_part = ""
        if rv is not None:
            router_part = (
                f" v2_router_handled={int(rv.handled)}"
                f" v2_router_reply_kind={rv.reply_kind}"
                f" v2_router_next_state={rv.next_state}"
                f" v2_router_action_kind={rv.action_kind or '-'}"
            )
        return (
            f"turn={self.turn_hmac64} vault={self.vault_hmac64} "
            f"sess={self.session_hmac64} "
            f"v1_tool={self.v1_tool or '-'} v1_handled={int(self.v1_handled)} "
            f"v2_intent={self.v2_intent} "
            f"v2_target_kind={self.v2_target_kind or '-'} "
            f"v2_target_hmac64={self.v2_target_id_hmac64} "
            f"v2_outcome={self.v2_outcome} "
            f"v2_reason={self.v2_reason_code} "
            f"v2_conf_bucket={self.v2_confidence_bucket} "
            f"v2_fp={self.v2_fingerprint} "
            f"fp_available={int(self.fp_available)} "
            f"match={self.match} "
            f"disagreement_source={self.disagreement_source} "
            f"v2_rev={self.v2_revision_stamp or '-'}"
            + router_part
            + (f" note={self.note}" if self.note else "")
        )


# =====================================================================
# Category classifier
# =====================================================================

# Map a v1 tool name -> its normalized-intent equivalent for
# match-vs-different classification. v1 uses tool names like
# "confirm_pending_delete"; v2 uses intent names like
# "confirm_pending_action". This mapping is intentional and is
# checked at test time.
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
    """Return one of MATCH_CATEGORIES."""
    if v2_decision is None or v2_decision.error:
        return MATCH_V2_VALIDATION_ERROR

    intent = v2_decision.intent

    if v2_policy is not None:
        insufficient_reasons = {
            "INSUFFICIENT_CONTEXT",
            "TARGET_NOT_FOCUSED",
            "EXPIRED_FOCUS",
        }
        if v2_policy.reason_code in insufficient_reasons \
                and v2_policy.outcome == OUTCOME_CLARIFY:
            return MATCH_INSUFFICIENT_CONTEXT

    if not v1_handled and intent == "fallthrough":
        return MATCH_INTENT_EQUIVALENT

    family = _V1_TOOL_TO_V2_INTENT_FAMILY.get(v1_tool, frozenset())
    if intent in family:
        return MATCH_INTENT_EQUIVALENT

    return MATCH_DIFFERENT_SEMANTICS


def _attribute_disagreement_source(
    match:        str,
    v1_tool:      str,
    v1_handled:   bool,
    v2_decision:  Optional[SemanticDecisionV2],
    v2_policy:    Optional[PolicyResultV2],
    v2_router:    Optional[object],
) -> str:
    """Attribute the layer at which v1 and v2 started to diverge.

    Attribution rules (in evaluation order):

        * match category is intent_equivalent -> NONE.
        * match category is v2_validation_error -> V2_ERROR.
        * match category is insufficient_shadow_context ->
          INSUFFICIENT_CONTEXT (a real POLICY-side reason but
          shadow-mode specific; NOT counted as a v2 defect).
        * v2 intent is not in v1's tool family -> SEMANTIC (the
          semantic decider chose a materially different intent).
        * v2 intent matches v1's family but v2 policy did NOT
          allow (outcome != allow) -> POLICY (policy layer
          rejected/clarified where v1 handled).
        * v2 intent + policy allow but the router chose an
          action_kind or reply_kind incompatible with v1's
          dispatch -> ROUTER.
        * fallback -> UNKNOWN (defensive; should be rare).

    The attribution never inspects reply text, user-facing
    content, or raw target ids. Only the layer verdict shapes.
    """
    if match == MATCH_V2_VALIDATION_ERROR:
        return DISAGREEMENT_SOURCE_V2_ERROR
    if match == MATCH_INSUFFICIENT_CONTEXT:
        return DISAGREEMENT_SOURCE_INSUFFICIENT_CONTEXT

    if match == MATCH_INTENT_EQUIVALENT:
        # Intent family agrees. But v1 handled and v2's policy
        # would have rejected/clarified? That's a POLICY-layer
        # disagreement even though the intents look equivalent.
        if (
            v1_handled
            and v2_policy is not None
            and v2_policy.outcome != OUTCOME_ALLOW
        ):
            return DISAGREEMENT_SOURCE_POLICY
        return DISAGREEMENT_SOURCE_NONE

    # match == MATCH_DIFFERENT_SEMANTICS: figure out which layer.
    if v2_decision is None:
        return DISAGREEMENT_SOURCE_UNKNOWN
    intent = v2_decision.intent
    family = _V1_TOOL_TO_V2_INTENT_FAMILY.get(v1_tool, frozenset())

    # Special case: v1 didn't handle (fallthrough) but v2 chose a
    # concrete intent. That's a semantic-level disagreement --
    # v2's decider is claiming coverage where v1 handed off.
    if not v1_handled and intent != "fallthrough":
        return DISAGREEMENT_SOURCE_SEMANTIC

    if intent not in family:
        return DISAGREEMENT_SOURCE_SEMANTIC

    # From here, intents agree at the family level.
    if v2_policy is not None and v2_policy.outcome != OUTCOME_ALLOW:
        return DISAGREEMENT_SOURCE_POLICY

    # v2 router disagreed on action shape despite intent + policy
    # agreement. Requires a shadow_router summary to attribute
    # confidently; without it we fall through to UNKNOWN.
    if v2_router is not None:
        handled = getattr(v2_router, "handled", None)
        if handled is False and v1_handled:
            return DISAGREEMENT_SOURCE_ROUTER
        if handled is True and not v1_handled:
            return DISAGREEMENT_SOURCE_ROUTER

    return DISAGREEMENT_SOURCE_UNKNOWN


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
    v2_router:       Optional[object] = None,
    note:            str = "",
) -> ShadowDiffRecordV2:
    """Build a diff record and emit it to the standard logger.

    ``v2_router`` (a ``RouterResultV2`` or ``None``) is summarized
    into a closed-set ``ShadowRouterView`` when present -- raw
    reply_text/diagnostic/focus contents are never carried.
    """
    fp_key_present = _process_secret() is not None
    if not fp_key_present:
        _warn_missing_secret_once()

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

    router_view: Optional[ShadowRouterView] = None
    if v2_router is not None:
        try:
            router_view = ShadowRouterView.from_router(v2_router)
        except Exception:
            logger.exception("[SHADOW_V2] router_view_build_failed")
            router_view = None

    match_category = _classify_match(
        v1_tool, v1_handled, v2_decision, v2_policy,
    )
    disagreement_source = _attribute_disagreement_source(
        match=match_category, v1_tool=v1_tool, v1_handled=v1_handled,
        v2_decision=v2_decision, v2_policy=v2_policy,
        v2_router=router_view,
    )
    record = ShadowDiffRecordV2(
        vault_hmac64=_short_correlation(vault_id),
        session_hmac64=_short_correlation(session_id or ""),
        turn_hmac64=_short_correlation(turn_id),
        v1_tool=v1_tool or "-",
        v1_handled=bool(v1_handled),
        v2_intent=v2_intent,
        v2_target_kind=v2_target_kind,
        v2_target_id_hmac64=target_hmac,
        v2_outcome=v2_outcome,
        v2_reason_code=v2_reason,
        v2_confidence_bucket=v2_conf_bucket,
        v2_fingerprint=fp,
        match=match_category,
        router_view=router_view,
        fp_available=fp_key_present,
        disagreement_source=disagreement_source,
        v2_revision_stamp=compute_v2_revision_stamp(),
        note=note,
    )
    logger.info("[SHADOW_V2] %s", record.to_log_line())
    # Increment the in-process aggregator. Never fatal on failure
    # -- metrics degrading is preferable to shadow-mode failing.
    try:
        from vault_chat_shadow_metrics_v2 import record_shadow_diff
        record_shadow_diff(record)
    except Exception:
        logger.exception("[SHADOW_V2] metrics_dispatch_failed")
    return record


__all__ = [
    "MATCH_INTENT_EQUIVALENT",
    "MATCH_DIFFERENT_SEMANTICS",
    "MATCH_INSUFFICIENT_CONTEXT",
    "MATCH_V2_VALIDATION_ERROR",
    "MATCH_CATEGORIES",
    "DISAGREEMENT_SOURCE_NONE",
    "DISAGREEMENT_SOURCE_SEMANTIC",
    "DISAGREEMENT_SOURCE_POLICY",
    "DISAGREEMENT_SOURCE_ROUTER",
    "DISAGREEMENT_SOURCE_INSUFFICIENT_CONTEXT",
    "DISAGREEMENT_SOURCE_V2_ERROR",
    "DISAGREEMENT_SOURCE_UNKNOWN",
    "DISAGREEMENT_SOURCES",
    "MIN_FINGERPRINT_SECRET_LEN",
    "NOFP_SENTINEL",
    "configure_fingerprint_secret_for_tests",
    "reset_fingerprint_secret_for_tests",
    "fingerprint",
    "target_id_fingerprint",
    "ShadowRouterView",
    "ShadowDiffRecordV2",
    "build_and_log_diff",
]
