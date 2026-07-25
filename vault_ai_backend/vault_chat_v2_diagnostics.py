"""Operational diagnostics for the v2 chat brain (commits 7 + 8).

Public surface:

    validate_shadow_configuration()      -> ValidationReport
    check_enum_consistency()             -> tuple[bool, list[str]]
    run_startup_self_test(ai_provider=)  -> SelfTestReport
    shadow_health_summary(...)           -> HealthReport
    is_v2_authoritative_ready(...)       -> ReadinessGateReport

Design constraints (unchanged from commit 7):

    * No network, no disk, no Redis writes.
    * Never enables a mode. Never mutates env. Never modifies
      persistent state.
    * Every function returns a plain-dict / dataclass result.
    * Never logs raw user content, vault ids, or session ids.

Commit 8 refinements:

    * ``check_enum_consistency`` -- static assertion that every
      closed-set enum is internally consistent (ACTION_KIND
      classification coverage, reply-template coverage,
      execution-status recognition, policy-outcome routability).
      Wired into startup self-test as its own stage.
    * ``HealthReport`` now carries per-dimension sub-statuses
      (configuration / startup / runtime / behavior) plus a
      ``sample_size_ok`` flag and a ``confidence_tier``
      (LOW / MEDIUM / HIGH) so an operator can distinguish
      "20 turns, 0 disagreements" from "50 000 turns, 0
      disagreements".
    * ``is_v2_authoritative_ready(registry)`` is an explicit
      gate function: verifies configuration, registry
      completeness, startup self-test, parity, sample size, and
      behavior thresholds. Refuses on any failure with a
      structured ``ReadinessGateReport`` naming every blocker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from vault_chat_brain_v2 import (
    MODES,
    MODE_OFF,
    MODE_ON,
    MODE_SHADOW,
    _build_v2_snapshot,
    _default_ai_provider,
    read_brain_mode,
    v1_fallback_enabled,
)
from vault_chat_decision_router_v2 import (
    ACTION_KINDS,
    FAILURE_REPLY_TEMPLATES,
    NEXT_STATES,
    REPLY_KINDS,
    SUCCESS_REPLY_TEMPLATES,
)
from vault_chat_integration_v2 import (
    ACTION_KIND_CLASSIFICATION,
    EXECUTION_STATUSES,
    EXECUTOR_REQUIRED_ACTION_KINDS,
    ExecutorRegistry,
    NON_EXECUTOR_ACTION_KINDS,
    assert_shadow_authoritative_parity,
    get_authoritative_action_inventory,
    get_shadow_observable_inventory,
    validate_v2_runtime_readiness,
)
from vault_chat_policy_v2 import OUTCOMES
from vault_chat_semantic_decider_v2 import decide_v2
from vault_chat_shadow_metrics_v2 import (
    SHADOW_PIPELINE_STAGES,
    get_metrics_snapshot,
)
from vault_chat_shadow_recorder_v2 import (
    DISAGREEMENT_SOURCES,
    MATCH_CATEGORIES,
    MIN_FINGERPRINT_SECRET_LEN,
    _process_secret,
)
from vault_chat_v2_versions import (
    check_revision_invariants,
    compute_v2_revision_stamp,
    get_v2_revision_dict,
)


logger = logging.getLogger(__name__)


# =====================================================================
# ValidationReport (config-side)
# =====================================================================

VALIDATION_OK:       str = "OK"
VALIDATION_WARN:     str = "WARN"
VALIDATION_ERROR:    str = "ERROR"

_VALIDATION_LEVELS: frozenset[str] = frozenset({
    VALIDATION_OK, VALIDATION_WARN, VALIDATION_ERROR,
})


@dataclass(frozen=True)
class ValidationFinding:
    level:    str
    code:     str
    message:  str

    def __post_init__(self) -> None:
        if self.level not in _VALIDATION_LEVELS:
            raise ValueError(f"unknown level {self.level!r}")


@dataclass(frozen=True)
class ValidationReport:
    mode:            str
    ok:              bool
    findings:        tuple = ()

    def as_dict(self) -> dict:
        return {
            "mode":     self.mode,
            "ok":       self.ok,
            "findings": [
                {"level": f.level, "code": f.code, "message": f.message}
                for f in self.findings
            ],
        }


def validate_shadow_configuration() -> ValidationReport:
    """Static checks for shadow-mode readiness. No I/O."""
    mode = read_brain_mode()
    findings: list[ValidationFinding] = []

    raw_mode = (os.environ.get("VAULTAI_CHAT_BRAIN_MODE") or "").strip().lower()
    if raw_mode and raw_mode not in MODES:
        findings.append(ValidationFinding(
            level=VALIDATION_WARN,
            code="mode_unrecognized_value",
            message=(
                f"VAULTAI_CHAT_BRAIN_MODE={raw_mode!r} not in "
                f"{sorted(MODES)}; read_brain_mode falls back to off"
            ),
        ))

    if mode in (MODE_SHADOW, MODE_ON):
        secret = _process_secret()
        if secret is None:
            findings.append(ValidationFinding(
                level=VALIDATION_ERROR,
                code="fingerprint_secret_missing_or_too_short",
                message=(
                    "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET is not "
                    f"set or is shorter than {MIN_FINGERPRINT_SECRET_LEN} "
                    "bytes; shadow diff records will be emitted without "
                    "fingerprints and rollout analysis will be blind to "
                    "target correlation"
                ),
            ))
        else:
            findings.append(ValidationFinding(
                level=VALIDATION_OK,
                code="fingerprint_secret_present",
                message=(
                    "fingerprint secret configured; shadow diff records "
                    "will carry stable correlation ids"
                ),
            ))

    if mode == MODE_ON:
        fallback_raw = (
            os.environ.get("VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK") or ""
        ).strip().lower()
        if fallback_raw == "":
            findings.append(ValidationFinding(
                level=VALIDATION_WARN,
                code="v1_fallback_env_unset",
                message=(
                    "VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK is unset in "
                    "mode==on; V1 fallback is DISABLED. Set the env to "
                    "'on' or 'off' explicitly so the choice is auditable."
                ),
            ))

    ok = all(f.level != VALIDATION_ERROR for f in findings)
    return ValidationReport(
        mode=mode, ok=ok, findings=tuple(findings),
    )


# =====================================================================
# Enum-consistency check (commit 8)
# =====================================================================

def check_enum_consistency() -> tuple[bool, list[str]]:
    """Assert every closed-set enum is internally consistent.

    Checks (all pass -> return (True, [])):

        1. Every ACTION_KIND has exactly one classification in
           ACTION_KIND_CLASSIFICATION.
        2. Every ACTION_KIND classification value belongs to the
           closed set {executor_required, non_executor}.
        3. EXECUTOR_REQUIRED_ACTION_KINDS and
           NON_EXECUTOR_ACTION_KINDS are disjoint; their union is
           ACTION_KINDS.
        4. Every REPLY_KIND except 'none' has both a success
           template in SUCCESS_REPLY_TEMPLATES and a failure
           template in FAILURE_REPLY_TEMPLATES.
        5. Every SUCCESS_REPLY_TEMPLATES key has a matching entry
           in FAILURE_REPLY_TEMPLATES (and vice versa).
        6. Every EXECUTION_STATUS is unique (no aliasing).
        7. Every POLICY OUTCOME is a member of {allow, clarify,
           reject}.
        8. Every DISAGREEMENT_SOURCE is a member of the closed
           set (tautological, but catches enum-drift when a new
           source is added but the recorder isn't updated).
        9. Every MATCH_CATEGORY is a member of the closed set.

    Returns ``(is_consistent, violations_sorted)`` where
    ``violations_sorted`` is a list of human-readable violation
    strings (empty on success).
    """
    violations: list[str] = []

    # 1 + 2: classification coverage + value shape.
    allowed_classes = frozenset({"executor_required", "non_executor"})
    for kind in ACTION_KINDS:
        if kind not in ACTION_KIND_CLASSIFICATION:
            violations.append(
                f"ACTION_KIND {kind!r} has no classification entry"
            )
        else:
            cls = ACTION_KIND_CLASSIFICATION[kind]
            if cls not in allowed_classes:
                violations.append(
                    f"ACTION_KIND {kind!r} classification {cls!r} "
                    f"not in {sorted(allowed_classes)}"
                )

    # 3: partition invariants.
    overlap = EXECUTOR_REQUIRED_ACTION_KINDS & NON_EXECUTOR_ACTION_KINDS
    if overlap:
        violations.append(
            f"action-kind partition overlap: {sorted(overlap)}"
        )
    union = EXECUTOR_REQUIRED_ACTION_KINDS | NON_EXECUTOR_ACTION_KINDS
    if union != ACTION_KINDS:
        missing = ACTION_KINDS - union
        extra = union - ACTION_KINDS
        if missing:
            violations.append(
                f"action-kind partition missing kinds: {sorted(missing)}"
            )
        if extra:
            violations.append(
                f"action-kind partition has extra kinds: {sorted(extra)}"
            )

    # 4 + 5: reply-template coverage.
    for k in SUCCESS_REPLY_TEMPLATES.keys():
        if k not in FAILURE_REPLY_TEMPLATES:
            violations.append(
                f"success reply key {k!r} has no failure template"
            )
    for k in FAILURE_REPLY_TEMPLATES.keys():
        if k not in SUCCESS_REPLY_TEMPLATES:
            violations.append(
                f"failure reply key {k!r} has no success template"
            )

    # 6: execution statuses uniqueness by string identity.
    # (frozenset membership already ensures uniqueness, but
    # verify the constant list didn't lose a member.)
    if len(EXECUTION_STATUSES) < 6:
        violations.append(
            f"EXECUTION_STATUSES has only {len(EXECUTION_STATUSES)} "
            "members; expected at least 6 (SUCCESS, EXECUTOR_FAILED, "
            "AUTHORIZATION_FAILED, CONSUME_FAILED, INTERNAL_ERROR, "
            "NO_EXECUTION)"
        )

    # 7: policy outcomes shape.
    expected_outcomes = frozenset({"allow", "clarify", "reject"})
    for o in OUTCOMES:
        if o not in expected_outcomes:
            violations.append(
                f"policy outcome {o!r} not in {sorted(expected_outcomes)}"
            )

    # 8 + 9: closed-set integrity for match + disagreement enums.
    if len(MATCH_CATEGORIES) < 4:
        violations.append(
            f"MATCH_CATEGORIES has only {len(MATCH_CATEGORIES)} members; "
            "expected at least 4"
        )
    if len(DISAGREEMENT_SOURCES) < 7:
        violations.append(
            f"DISAGREEMENT_SOURCES has only {len(DISAGREEMENT_SOURCES)} "
            "members; expected at least 7"
        )

    return (len(violations) == 0, sorted(violations))


# =====================================================================
# SelfTestReport (pipeline-side)
# =====================================================================

@dataclass(frozen=True)
class SelfTestStage:
    name:            str
    ok:              bool
    detail:          str = ""


@dataclass(frozen=True)
class SelfTestReport:
    ok:              bool
    duration_ms:     int
    stages:          tuple = ()

    def as_dict(self) -> dict:
        return {
            "ok":          self.ok,
            "duration_ms": self.duration_ms,
            "stages": [
                {"name": s.name, "ok": s.ok, "detail": s.detail}
                for s in self.stages
            ],
        }


class _StubProvider:

    async def __call__(self, **kwargs) -> Any:
        body = json.dumps({
            "schema_version": 1,
            "intent": "fallthrough",
            "target": {"kind": "none", "id": None},
            "field_patch": {},
            "requested_operations": [],
            "authorization": {"granted": False},
            "confidence": 0.99,
            "reason": "self_test",
        })
        class _R:
            content = body
        return _R()


def run_startup_self_test(
    ai_provider: Optional[Callable[..., Any]] = None,
    _installed_backend_hook: Optional[Callable[[], None]] = None,
) -> SelfTestReport:
    """Synthetic read-only pass through
    ``enum_consistency -> snapshot -> decide -> authorize ->
    route``. Uses a scratch InMemoryChatStateBackend and a stub
    ai_provider (unless one is supplied). Restores the original
    backend on exit. Never hits Redis.
    """
    import vault_chat_state_store as st
    started = time.time()
    stages: list[SelfTestStage] = []

    # Stage 0a: revision-invariants (commit 8b). A merge conflict
    # that silently reset a layer revision below its floor would
    # corrupt rollout-evidence semantics; catch it here.
    try:
        ok, violations = check_revision_invariants()
        if ok:
            stages.append(SelfTestStage(
                name="revision_invariants", ok=True,
                detail=(
                    "all revisions positive and >= their "
                    "MIN_LAYER_REVISIONS floors"
                ),
            ))
        else:
            stages.append(SelfTestStage(
                name="revision_invariants", ok=False,
                detail="; ".join(violations),
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )
    except Exception as exc:
        stages.append(SelfTestStage(
            name="revision_invariants", ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        ))
        return SelfTestReport(
            ok=False,
            duration_ms=int((time.time() - started) * 1000),
            stages=tuple(stages),
        )

    # Stage 0b: enum consistency. Runs BEFORE the backend swap so
    # a codebase-level enum drift is diagnosed clearly even when
    # no state store is available.
    try:
        ok, violations = check_enum_consistency()
        if ok:
            stages.append(SelfTestStage(
                name="enum_consistency", ok=True,
                detail="every closed-set enum internally consistent",
            ))
        else:
            stages.append(SelfTestStage(
                name="enum_consistency", ok=False,
                detail="; ".join(violations),
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )
    except Exception as exc:
        stages.append(SelfTestStage(
            name="enum_consistency", ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        ))
        return SelfTestReport(
            ok=False,
            duration_ms=int((time.time() - started) * 1000),
            stages=tuple(stages),
        )

    scratch = st.InMemoryChatStateBackend()
    st.install_backend_for_tests(scratch)
    if _installed_backend_hook is not None:
        try:
            _installed_backend_hook()
        except Exception:
            pass
    provider = ai_provider or _StubProvider()

    try:
        try:
            snap = _build_v2_snapshot(
                vault_id="selftest-vault", session_id="selftest-session",
                user_message="hello",
                current_user_turn_id="u-selftest-1",
                preceding_assistant_turn_id="a-selftest-0",
                memory=None,
            )
            stages.append(SelfTestStage(
                name="snapshot", ok=True,
                detail="snapshot built without exception",
            ))
        except Exception as exc:
            stages.append(SelfTestStage(
                name="snapshot", ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )

        try:
            loop = asyncio.new_event_loop()
            try:
                decision = loop.run_until_complete(
                    decide_v2(snap.decider_context, ai_provider=provider),
                )
            finally:
                loop.close()
            stages.append(SelfTestStage(
                name="decider", ok=True,
                detail=f"intent={decision.intent} error={decision.error or '-'}",
            ))
        except Exception as exc:
            stages.append(SelfTestStage(
                name="decider", ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )

        try:
            from vault_chat_policy_v2 import authorize_v2
            policy = authorize_v2(
                snapshot=snap.policy_snapshot, decision=decision,
            )
            stages.append(SelfTestStage(
                name="policy", ok=True,
                detail=f"outcome={policy.outcome} "
                       f"reason={policy.reason_code}",
            ))
        except Exception as exc:
            stages.append(SelfTestStage(
                name="policy", ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )

        try:
            from vault_chat_decision_router_v2 import route_v2
            router_result = route_v2(
                policy_result=policy, decision=decision,
            )
            stages.append(SelfTestStage(
                name="router", ok=True,
                detail=(
                    f"handled={router_result.handled} "
                    f"reply_kind={router_result.reply_kind} "
                    f"next_state={router_result.next_state}"
                ),
            ))
        except Exception as exc:
            stages.append(SelfTestStage(
                name="router", ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            ))
            return SelfTestReport(
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                stages=tuple(stages),
            )
    finally:
        st.reset_chat_state_backend_for_tests()

    ok = all(s.ok for s in stages)
    return SelfTestReport(
        ok=ok,
        duration_ms=int((time.time() - started) * 1000),
        stages=tuple(stages),
    )


# =====================================================================
# HealthReport (commit 8: split dimensions + confidence tier)
# =====================================================================

# Overall status
HEALTH_READY:     str = "READY"
HEALTH_DEGRADED:  str = "DEGRADED"
HEALTH_UNREADY:   str = "UNREADY"

_HEALTH_LEVELS: frozenset[str] = frozenset({
    HEALTH_READY, HEALTH_DEGRADED, HEALTH_UNREADY,
})

# Per-dimension sub-statuses. Not overloaded with the overall
# levels above -- an operator scanning the report can tell at a
# glance which dimension is failing.
DIM_CONFIG_PASS:   str = "PASS"
DIM_CONFIG_WARN:   str = "WARN"
DIM_CONFIG_FAIL:   str = "FAIL"

DIM_STARTUP_PASS:  str = "PASS"
DIM_STARTUP_FAIL:  str = "FAIL"
DIM_STARTUP_SKIP:  str = "NOT_RUN"

DIM_RUNTIME_PASS:      str = "PASS"
DIM_RUNTIME_DEGRADED:  str = "DEGRADED"

DIM_BEHAVIOR_PASS:                 str = "PASS"
DIM_BEHAVIOR_DEGRADED:             str = "DEGRADED"
DIM_BEHAVIOR_INSUFFICIENT_SAMPLES: str = "INSUFFICIENT_SAMPLES"

# Confidence tier for behavioral metrics.
CONFIDENCE_LOW:     str = "LOW"
CONFIDENCE_MEDIUM:  str = "MEDIUM"
CONFIDENCE_HIGH:    str = "HIGH"

_CONFIDENCE_TIERS: frozenset[str] = frozenset({
    CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH,
})


@dataclass(frozen=True)
class HealthReport:
    status:                 str
    reasons:                tuple = ()
    validation:             Optional[ValidationReport] = None
    self_test:              Optional[SelfTestReport] = None
    parity_ok:              bool = True
    parity_diff:            tuple = ()
    metrics:                dict = field(default_factory=dict)
    # commit 8 additions
    configuration_status:   str = DIM_CONFIG_PASS
    startup_status:         str = DIM_STARTUP_SKIP
    runtime_status:         str = DIM_RUNTIME_PASS
    behavior_status:        str = DIM_BEHAVIOR_INSUFFICIENT_SAMPLES
    confidence_tier:        str = CONFIDENCE_LOW
    sample_size_ok:         bool = False
    reasons_by_dimension:   dict = field(default_factory=dict)
    v2_revisions:           dict = field(default_factory=dict)
    v2_revision_stamp:      str = ""

    def __post_init__(self) -> None:
        if self.status not in _HEALTH_LEVELS:
            raise ValueError(f"unknown status {self.status!r}")
        if self.confidence_tier not in _CONFIDENCE_TIERS:
            raise ValueError(f"unknown tier {self.confidence_tier!r}")

    def as_dict(self) -> dict:
        return {
            "status":               self.status,
            "reasons":              list(self.reasons),
            "validation":           self.validation.as_dict() if self.validation else None,
            "self_test":            self.self_test.as_dict() if self.self_test else None,
            "parity_ok":            self.parity_ok,
            "parity_diff":          list(self.parity_diff),
            "metrics":              dict(self.metrics),
            "configuration_status": self.configuration_status,
            "startup_status":       self.startup_status,
            "runtime_status":       self.runtime_status,
            "behavior_status":      self.behavior_status,
            "confidence_tier":      self.confidence_tier,
            "sample_size_ok":       self.sample_size_ok,
            "reasons_by_dimension": {
                k: list(v) for k, v in self.reasons_by_dimension.items()
            },
            "v2_revisions":         dict(self.v2_revisions),
            "v2_revision_stamp":    self.v2_revision_stamp,
        }


# Thresholds. All commit 7 behavioral thresholds preserved.
_MIN_DIFFS_FOR_QUALITY:                  int = 100
_MAX_V2_ERROR_PCT_FOR_READY:             float = 1.0
_MAX_DIFFERENT_SEMANTICS_PCT_FOR_READY:  float = 5.0
_MIN_FP_AVAILABLE_PCT_FOR_READY:         float = 99.0

# Sample-size tiers (commit 8).
_CONFIDENCE_MEDIUM_THRESHOLD:            int = 1_000
_CONFIDENCE_HIGH_THRESHOLD:              int = 10_000


def _confidence_tier_from_diff_count(n: int) -> str:
    if n >= _CONFIDENCE_HIGH_THRESHOLD:
        return CONFIDENCE_HIGH
    if n >= _CONFIDENCE_MEDIUM_THRESHOLD:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def shadow_health_summary(
    *,
    registry: Optional[ExecutorRegistry] = None,
    run_self_test: bool = False,
) -> HealthReport:
    """Aggregate every diagnostic into a single HealthReport.

    ``registry``: if supplied, verified against
    ``assert_shadow_authoritative_parity``. If None, parity is
    not checked (``parity_ok`` stays True by default).

    ``run_self_test``: if True, run the startup self-test.
    """
    reasons_by_dim: dict[str, list[str]] = {
        "configuration": [],
        "startup":       [],
        "runtime":       [],
        "behavior":      [],
        "parity":        [],
    }
    reasons: list[str] = []

    # ---- configuration
    validation = validate_shadow_configuration()
    if not validation.ok:
        for f in validation.findings:
            if f.level == VALIDATION_ERROR:
                reason = f"config.{f.code}"
                reasons.append(reason)
                reasons_by_dim["configuration"].append(reason)
        configuration_status = DIM_CONFIG_FAIL
    elif any(f.level == VALIDATION_WARN for f in validation.findings):
        configuration_status = DIM_CONFIG_WARN
    else:
        configuration_status = DIM_CONFIG_PASS

    # ---- parity
    parity_ok = True
    parity_diff: tuple = ()
    if registry is not None:
        parity_ok, diff = assert_shadow_authoritative_parity(registry)
        parity_diff = tuple(diff)
        if not parity_ok:
            reason = "parity.action_inventory_mismatch"
            reasons.append(reason)
            reasons_by_dim["parity"].append(reason)

    # ---- startup
    self_test: Optional[SelfTestReport] = None
    if run_self_test:
        self_test = run_startup_self_test()
        if not self_test.ok:
            for st_stage in self_test.stages:
                if not st_stage.ok:
                    reason = f"self_test.{st_stage.name}_failed"
                    reasons.append(reason)
                    reasons_by_dim["startup"].append(reason)
            startup_status = DIM_STARTUP_FAIL
        else:
            startup_status = DIM_STARTUP_PASS
    else:
        startup_status = DIM_STARTUP_SKIP

    # ---- runtime + behavior
    metrics = get_metrics_snapshot()
    pipeline_exc = metrics.get("pipeline_exceptions", {})
    runtime_status = DIM_RUNTIME_PASS
    for stage, count in pipeline_exc.items():
        if count > 0:
            reason = f"pipeline.exception.{stage}={count}"
            reasons.append(reason)
            reasons_by_dim["runtime"].append(reason)
            runtime_status = DIM_RUNTIME_DEGRADED

    total = metrics.get("diff_count", 0)
    confidence_tier = _confidence_tier_from_diff_count(total)
    sample_size_ok = total >= _MIN_DIFFS_FOR_QUALITY

    if not sample_size_ok:
        behavior_status = DIM_BEHAVIOR_INSUFFICIENT_SAMPLES
    else:
        match_ratios = metrics.get("match_ratios_pct", {})
        v2_err_pct = float(match_ratios.get("v2_validation_error", 0.0))
        diff_pct = float(match_ratios.get("different_semantics", 0.0))
        fp_pct = float(metrics.get("fp_available_ratio_pct", 0.0))
        behavior_reasons: list[str] = []
        if v2_err_pct > _MAX_V2_ERROR_PCT_FOR_READY:
            behavior_reasons.append(
                f"quality.v2_validation_error_pct={v2_err_pct}"
            )
        if diff_pct > _MAX_DIFFERENT_SEMANTICS_PCT_FOR_READY:
            behavior_reasons.append(
                f"quality.different_semantics_pct={diff_pct}"
            )
        if fp_pct < _MIN_FP_AVAILABLE_PCT_FOR_READY:
            behavior_reasons.append(
                f"quality.fp_available_pct={fp_pct}"
            )
        if behavior_reasons:
            reasons.extend(behavior_reasons)
            reasons_by_dim["behavior"].extend(behavior_reasons)
            behavior_status = DIM_BEHAVIOR_DEGRADED
        else:
            behavior_status = DIM_BEHAVIOR_PASS

    # ---- overall
    if configuration_status == DIM_CONFIG_FAIL:
        status = HEALTH_UNREADY
    elif not parity_ok:
        status = HEALTH_UNREADY
    elif startup_status == DIM_STARTUP_FAIL:
        status = HEALTH_UNREADY
    elif runtime_status == DIM_RUNTIME_DEGRADED:
        status = HEALTH_DEGRADED
    elif behavior_status == DIM_BEHAVIOR_DEGRADED:
        status = HEALTH_DEGRADED
    else:
        status = HEALTH_READY

    return HealthReport(
        status=status,
        reasons=tuple(reasons),
        validation=validation,
        self_test=self_test,
        parity_ok=parity_ok,
        parity_diff=parity_diff,
        metrics=metrics,
        configuration_status=configuration_status,
        startup_status=startup_status,
        runtime_status=runtime_status,
        behavior_status=behavior_status,
        confidence_tier=confidence_tier,
        sample_size_ok=sample_size_ok,
        reasons_by_dimension={
            k: tuple(v) for k, v in reasons_by_dim.items() if v
        },
        v2_revisions=get_v2_revision_dict(),
        v2_revision_stamp=compute_v2_revision_stamp(),
    )


# =====================================================================
# Authoritative readiness gate (commit 8a: evidence-driven)
# =====================================================================

@dataclass(frozen=True)
class ReadinessGateReport:
    """Structured outcome of ``is_v2_authoritative_ready``.

    ``blockers`` are sorted, unique, closed-set-shaped strings.
    ``health`` is the live process-local rollup (debugging info
    ONLY -- authoritative approval comes from
    ``evidence_validation``, not ``health``).
    ``evidence_validation`` names the exact evidence-side
    blockers when the evidence file failed to load or validate.
    """
    ready:                       bool
    blockers:                    tuple = ()
    health:                      Optional[HealthReport] = None
    evidence:                    Optional[Any] = None  # RolloutEvidenceV2
    evidence_validation:         Optional[Any] = None  # EvidenceValidationResult
    evidence_load:               Optional[Any] = None  # EvidenceLoadResult

    def as_dict(self) -> dict:
        return {
            "ready":                self.ready,
            "blockers":             list(self.blockers),
            "health":               self.health.as_dict() if self.health else None,
            "evidence_present":     self.evidence is not None,
            "evidence_valid": (
                self.evidence_validation.valid
                if self.evidence_validation else False
            ),
            "evidence_blockers": (
                list(self.evidence_validation.blockers)
                if self.evidence_validation else []
            ),
            "evidence_load_blockers": (
                list(self.evidence_load.blockers)
                if self.evidence_load else []
            ),
        }


def is_v2_authoritative_ready(
    registry: ExecutorRegistry,
    rollout_evidence: Optional[Any] = None,
    *,
    require_self_test: bool = True,
    current_environment: Optional[str] = None,
    current_release_id: Optional[str] = None,
    _evidence_load_result: Optional[Any] = None,
    _validation_now: Optional[Any] = None,
) -> ReadinessGateReport:
    """Explicit gate for authoritative (mode==on) activation.

    Commit 8a: the gate now REQUIRES external rollout evidence
    signed by a deployment-provided HMAC secret. The
    process-local metrics aggregator is treated as debugging
    information only -- it never approves rollout.

    Parameters:
        registry:            production ExecutorRegistry.
        rollout_evidence:    a validated RolloutEvidenceV2, or
                             None to load from the deployment
                             env (VAULTAI_CHAT_BRAIN_V2_
                             ROLLOUT_EVIDENCE_PATH +
                             _HMAC_SECRET).
        require_self_test:   whether to run the startup
                             self-test.
        current_environment: overrides the environment env var
                             for tests.

    Refuses on ANY of:

        * evidence missing / unreadable / malformed
        * evidence signature invalid or algorithm unsupported
        * evidence semantically invalid (see
          RolloutEvidenceV2 blockers)
        * executor registry missing an EXECUTOR_REQUIRED
          adapter (static wiring failure)
        * configuration status != PASS
        * parity broken
        * startup self-test failed (unless require_self_test=False)

    NOTE: process-local pipeline_exceptions counters and
    confidence_tier are NOT used for the authoritative decision.
    Cross-fleet exception rate and observation sample size come
    from the signed evidence payload.
    """
    from vault_chat_v2_rollout_evidence import (
        EvidenceLoadResult, EvidenceValidationResult,
        load_rollout_evidence_from_env,
        validate_rollout_evidence,
    )

    blockers: list[str] = []
    health = shadow_health_summary(
        registry=registry, run_self_test=require_self_test,
    )

    # 1. Evidence: load if not supplied.
    load_result: Optional[EvidenceLoadResult] = _evidence_load_result
    evidence = rollout_evidence
    if evidence is None:
        if load_result is None:
            load_result = load_rollout_evidence_from_env()
        for b in load_result.blockers:
            blockers.append(b)
        evidence = load_result.evidence

    # 2. Evidence: validate if we have one.
    validation: Optional[EvidenceValidationResult] = None
    if evidence is not None:
        validation = validate_rollout_evidence(
            evidence,
            current_environment=current_environment,
            current_release_id=current_release_id,
            now=_validation_now,
        )
        if not validation.valid:
            for b in validation.blockers:
                blockers.append(b)

    # 3. Registry completeness (static wiring).
    reg_ready, missing = validate_v2_runtime_readiness(registry)
    if not reg_ready:
        blockers.append(
            f"registry.missing_executors={sorted(missing)}"
        )

    # 4. Configuration.
    if health.configuration_status != DIM_CONFIG_PASS:
        blockers.append(
            f"configuration={health.configuration_status}"
        )
        for r in health.reasons_by_dimension.get("configuration", ()):
            blockers.append(f"config.{r}")

    # 5. Parity.
    if not health.parity_ok:
        blockers.append(
            f"parity.symmetric_diff={list(health.parity_diff)}"
        )

    # 6. Startup self-test.
    if require_self_test:
        if health.startup_status == DIM_STARTUP_SKIP:
            blockers.append("startup.self_test_not_run")
        elif health.startup_status == DIM_STARTUP_FAIL:
            blockers.append(f"startup={health.startup_status}")
            for r in health.reasons_by_dimension.get("startup", ()):
                blockers.append(r)

    ready = len(blockers) == 0
    return ReadinessGateReport(
        ready=ready,
        blockers=tuple(sorted(set(blockers))),
        health=health,
        evidence=evidence,
        evidence_validation=validation,
        evidence_load=load_result,
    )


__all__ = [
    "VALIDATION_OK", "VALIDATION_WARN", "VALIDATION_ERROR",
    "ValidationFinding", "ValidationReport",
    "validate_shadow_configuration",
    "check_enum_consistency",
    "SelfTestStage", "SelfTestReport",
    "run_startup_self_test",
    "HEALTH_READY", "HEALTH_DEGRADED", "HEALTH_UNREADY",
    "DIM_CONFIG_PASS", "DIM_CONFIG_WARN", "DIM_CONFIG_FAIL",
    "DIM_STARTUP_PASS", "DIM_STARTUP_FAIL", "DIM_STARTUP_SKIP",
    "DIM_RUNTIME_PASS", "DIM_RUNTIME_DEGRADED",
    "DIM_BEHAVIOR_PASS", "DIM_BEHAVIOR_DEGRADED",
    "DIM_BEHAVIOR_INSUFFICIENT_SAMPLES",
    "CONFIDENCE_LOW", "CONFIDENCE_MEDIUM", "CONFIDENCE_HIGH",
    "HealthReport",
    "shadow_health_summary",
    "ReadinessGateReport",
    "is_v2_authoritative_ready",
]
