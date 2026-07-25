"""Operational diagnostics for the v2 chat brain (commit 7).

Three deliverables:

    validate_shadow_configuration()
        Static check of environment configuration that shadow (or
        on) mode requires. Reads env vars; performs no I/O; returns
        a structured ``ValidationReport``. Safe to call at boot,
        or before flipping the mode env var.

    run_startup_self_test(ai_provider=None)
        Synthetic end-to-end pass through the read-only v2 stack
        (snapshot -> decider -> policy -> router) with a stub
        ai_provider. Confirms every component imports, constructs,
        and returns a well-formed result. Does not touch Redis or
        any persistent store; uses a scratch InMemoryChatStateBackend
        installed for the duration of the test only. Returns
        ``SelfTestReport``.

    shadow_health_summary()
        Rolls up ``get_metrics_snapshot()`` into a human-friendly
        ``HealthReport``: overall READY / DEGRADED / UNREADY with
        the reasons that pushed it there. Consumed by operators
        deciding whether to promote from shadow to on.

Design constraints:

    * No network, no disk, no Redis writes.
    * Never enables a mode. Never mutates env. Never modifies
      persistent state.
    * Every function returns a plain-dict / dataclass result --
      no side effects, no exceptions escape.
    * Never logs raw user content, vault ids, or session ids.
    * Every diagnostic can be exposed to operators (log line,
      admin HTTP endpoint, CLI tool) without leaking user data.
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
from vault_chat_integration_v2 import (
    ExecutorRegistry,
    assert_shadow_authoritative_parity,
    get_authoritative_action_inventory,
    get_shadow_observable_inventory,
    validate_v2_runtime_readiness,
)
from vault_chat_semantic_decider_v2 import decide_v2
from vault_chat_shadow_metrics_v2 import (
    SHADOW_PIPELINE_STAGES,
    get_metrics_snapshot,
)
from vault_chat_shadow_recorder_v2 import (
    MIN_FINGERPRINT_SECRET_LEN,
    _process_secret,
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
    """Static checks for shadow-mode readiness. Performs no I/O.
    Safe to call at boot and again before any operator action.

    Checks:
        * VAULTAI_CHAT_BRAIN_MODE is one of {off, shadow, on} or
          unset (defaults to off).
        * If mode is shadow or on:
              - VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET is set
                and >= MIN_FINGERPRINT_SECRET_LEN bytes.
        * If mode is on:
              - VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK is set
                explicitly (either "on" or something else) --
                mode==on with implicit fallback default is
                warn-worthy: operators should have made an
                explicit choice.
    """
    mode = read_brain_mode()  # Already validated / normalized.
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
                    "mode==on; V1 fallback is DISABLED (READ_ONLY-phase "
                    "v2 exceptions become controlled errors, not v1 "
                    "fallthroughs). Set the env to 'on' or 'off' "
                    "explicitly so the choice is auditable."
                ),
            ))

    ok = all(f.level != VALIDATION_ERROR for f in findings)
    return ValidationReport(
        mode=mode, ok=ok, findings=tuple(findings),
    )


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
    """Deterministic ai_provider stub for the self-test. Returns
    a well-formed fallthrough decision so the decider never
    fabricates any state that requires a real snapshot."""

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
    """Run a synthetic read-only pass through
    ``snapshot -> decide -> authorize -> route`` against a scratch
    in-memory backend and a stub ai_provider. Confirms every
    component imports and constructs without exception.

    Does NOT hit Redis; installs a scratch
    ``InMemoryChatStateBackend`` for the duration of the test and
    restores the original backend afterward.

    ``ai_provider`` overrides the stub for tests that want to
    verify the wiring accepts an alternate provider.
    """
    import vault_chat_state_store as st
    from vault_chat_authorization_record import atomic_consume_authorization  # noqa: F401
    started = time.time()
    stages: list[SelfTestStage] = []

    # Install a scratch backend. Restore on exit.
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
# HealthReport (rollup)
# =====================================================================

HEALTH_READY:     str = "READY"
HEALTH_DEGRADED:  str = "DEGRADED"
HEALTH_UNREADY:   str = "UNREADY"

_HEALTH_LEVELS: frozenset[str] = frozenset({
    HEALTH_READY, HEALTH_DEGRADED, HEALTH_UNREADY,
})


@dataclass(frozen=True)
class HealthReport:
    status:           str
    reasons:          tuple = ()
    validation:       Optional[ValidationReport] = None
    self_test:        Optional[SelfTestReport] = None
    parity_ok:        bool = True
    parity_diff:      tuple = ()
    metrics:          dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _HEALTH_LEVELS:
            raise ValueError(f"unknown status {self.status!r}")

    def as_dict(self) -> dict:
        return {
            "status":     self.status,
            "reasons":    list(self.reasons),
            "validation": self.validation.as_dict() if self.validation else None,
            "self_test":  self.self_test.as_dict() if self.self_test else None,
            "parity_ok":  self.parity_ok,
            "parity_diff": list(self.parity_diff),
            "metrics":    dict(self.metrics),
        }


# Thresholds for DEGRADED classification. Tuned conservatively:
# a rollout should not enter mode==on if these thresholds trip in
# shadow mode over a meaningful sample.
_MIN_DIFFS_FOR_QUALITY: int = 100
_MAX_V2_ERROR_PCT_FOR_READY: float = 1.0
_MAX_DIFFERENT_SEMANTICS_PCT_FOR_READY: float = 5.0
_MIN_FP_AVAILABLE_PCT_FOR_READY: float = 99.0


def shadow_health_summary(
    *,
    registry: Optional[ExecutorRegistry] = None,
    run_self_test: bool = False,
) -> HealthReport:
    """Aggregate every diagnostic into a single HealthReport.

    Parameters:
        registry:       if supplied, verified against
                        assert_shadow_authoritative_parity. If None,
                        parity is not checked (parity_ok stays True
                        by default).
        run_self_test:  if True, run the startup self-test. Costs
                        one synthetic decide_v2 call. Default False
                        so the summary is cheap to poll.
    """
    reasons: list[str] = []

    validation = validate_shadow_configuration()
    if not validation.ok:
        for f in validation.findings:
            if f.level == VALIDATION_ERROR:
                reasons.append(f"config.{f.code}")

    parity_ok = True
    parity_diff: tuple = ()
    if registry is not None:
        parity_ok, diff = assert_shadow_authoritative_parity(registry)
        parity_diff = tuple(diff)
        if not parity_ok:
            reasons.append("parity.action_inventory_mismatch")

    self_test: Optional[SelfTestReport] = None
    if run_self_test:
        self_test = run_startup_self_test()
        if not self_test.ok:
            for st_stage in self_test.stages:
                if not st_stage.ok:
                    reasons.append(f"self_test.{st_stage.name}_failed")

    metrics = get_metrics_snapshot()

    total = metrics.get("diff_count", 0)
    if total >= _MIN_DIFFS_FOR_QUALITY:
        match_ratios = metrics.get("match_ratios_pct", {})
        v2_err_pct = float(match_ratios.get("v2_validation_error", 0.0))
        diff_pct = float(match_ratios.get("different_semantics", 0.0))
        fp_pct = float(metrics.get("fp_available_ratio_pct", 0.0))
        if v2_err_pct > _MAX_V2_ERROR_PCT_FOR_READY:
            reasons.append(
                f"quality.v2_validation_error_pct={v2_err_pct}"
            )
        if diff_pct > _MAX_DIFFERENT_SEMANTICS_PCT_FOR_READY:
            reasons.append(
                f"quality.different_semantics_pct={diff_pct}"
            )
        if fp_pct < _MIN_FP_AVAILABLE_PCT_FOR_READY:
            reasons.append(
                f"quality.fp_available_pct={fp_pct}"
            )

    pipeline_exc = metrics.get("pipeline_exceptions", {})
    for stage, count in pipeline_exc.items():
        if count > 0:
            reasons.append(f"pipeline.exception.{stage}={count}")

    if not reasons:
        status = HEALTH_READY
    else:
        has_config_error = any(
            r.startswith("config.") or r.startswith("parity.")
            or r.startswith("self_test.")
            for r in reasons
        )
        status = HEALTH_UNREADY if has_config_error else HEALTH_DEGRADED

    return HealthReport(
        status=status,
        reasons=tuple(reasons),
        validation=validation,
        self_test=self_test,
        parity_ok=parity_ok,
        parity_diff=parity_diff,
        metrics=metrics,
    )


__all__ = [
    "VALIDATION_OK", "VALIDATION_WARN", "VALIDATION_ERROR",
    "ValidationFinding", "ValidationReport",
    "validate_shadow_configuration",
    "SelfTestStage", "SelfTestReport",
    "run_startup_self_test",
    "HEALTH_READY", "HEALTH_DEGRADED", "HEALTH_UNREADY",
    "HealthReport",
    "shadow_health_summary",
]
