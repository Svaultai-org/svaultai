"""Durable rollout evidence for v2 authoritative activation (commit 8a).

Separates two operational concerns:

    * PROCESS-LOCAL METRICS -- what the current worker has
      observed since it started. See
      ``vault_chat_shadow_metrics_v2``. These are useful for
      debugging, per-worker diagnostics, and immediate-exception
      detection, but they MUST NOT be interpreted as fleet-wide
      rollout approval:

        - reset every process restart;
        - isolated per worker / server / container;
        - unavailable to a newly-started authoritative process;
        - cannot represent the full production fleet.

    * ROLLOUT EVIDENCE -- a signed, immutable payload produced
      by an externally-run aggregation + review pipeline.
      Represents fleet-level shadow observation over a bounded
      window, cryptographically signed by a deployment secret,
      and consumed (never created) by the process that would
      like to enter authoritative mode.

The authoritative readiness gate consumes evidence, not local
counters. This module defines the evidence dataclass, its
canonical serialization, its HMAC-SHA256 signature scheme, and
its validation rules.

Trust model
-----------

Evidence is a deployment artifact. The signing key
(``VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_HMAC_SECRET``) MUST be
provisioned by the deployment pipeline and MUST NOT have a
default. If either the evidence file or the secret is absent,
authoritative activation is refused. If the signature does not
verify (constant-time compare), activation is refused.

Observation and approval MUST remain separate operations. A
process that CONSUMES evidence to authorize its own activation
MUST NOT also PRODUCE evidence. ``sign_rollout_evidence`` is
provided for external tooling and tests only; there is no code
path in production that both signs and immediately consumes.

File format
-----------

An evidence file is a JSON object with three top-level keys::

    {
      "envelope_version": 1,
      "payload":          <RolloutEvidenceV2 fields as JSON>,
      "signature_alg":    "HMAC-SHA256",
      "signature_hex":    <64 hex characters>
    }

The signature is computed over the CANONICAL JSON encoding of
``payload`` -- sorted keys, no whitespace, ISO-8601 UTC 'Z'
datetimes. The canonicalization is defined by
``canonical_payload_bytes()``.

Rejection blockers (closed set)
-------------------------------

Every validator that refuses an evidence file returns a blocker
string from ``EVIDENCE_BLOCKERS`` so operators see the exact
reason.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from vault_chat_v2_versions import compute_v2_revision_stamp


logger = logging.getLogger(__name__)


# =====================================================================
# Envelope + payload version
# =====================================================================

EVIDENCE_ENVELOPE_VERSION:                    int = 1
SUPPORTED_EVIDENCE_VERSIONS: frozenset[int]     = frozenset({1})
SIGNATURE_ALG_HMAC_SHA256:                    str = "HMAC-SHA256"

MIN_HMAC_SECRET_LEN:                          int = 32


# =====================================================================
# Environment / evidence-path env vars
# =====================================================================

ENV_ROLLOUT_EVIDENCE_PATH:      str = "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_PATH"
ENV_ROLLOUT_EVIDENCE_SECRET:    str = "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_HMAC_SECRET"
ENV_ENVIRONMENT:                str = "VAULTAI_CHAT_BRAIN_V2_ENVIRONMENT"


# =====================================================================
# Thresholds -- rollout gate requires evidence at or above these.
# Bump conservatively; a follow-up review can loosen after fleet
# behavior is proven.
# =====================================================================

MIN_TOTAL_DIFFS_FOR_ROLLOUT:      int = 10_000
MIN_WORKERS_OBSERVED:             int = 3
MIN_OBSERVATION_WINDOW_HOURS:     float = 24.0
MAX_EXCEPTION_RATE_PCT:           float = 0.5
MAX_DIFFERENT_SEMANTICS_PCT:      float = 5.0
MAX_VALIDATION_ERROR_PCT:         float = 1.0
MIN_FINGERPRINT_AVAILABLE_PCT:    float = 99.0


# =====================================================================
# Blocker codes (closed set)
# =====================================================================

BLOCKER_EVIDENCE_MISSING:              str = "evidence.missing"
BLOCKER_EVIDENCE_PATH_UNREADABLE:      str = "evidence.path_unreadable"
BLOCKER_EVIDENCE_MALFORMED:            str = "evidence.malformed"
BLOCKER_EVIDENCE_ENVELOPE_VERSION:     str = "evidence.envelope_version_unsupported"
BLOCKER_EVIDENCE_SECRET_MISSING:       str = "evidence.hmac_secret_missing"
BLOCKER_EVIDENCE_SECRET_TOO_SHORT:     str = "evidence.hmac_secret_too_short"
BLOCKER_EVIDENCE_SIGNATURE_ALG:        str = "evidence.signature_alg_unsupported"
BLOCKER_EVIDENCE_SIGNATURE_INVALID:    str = "evidence.signature_invalid"
BLOCKER_EVIDENCE_SIGNATURE_MISSING:    str = "evidence.signature_missing"
BLOCKER_EVIDENCE_VERSION:              str = "evidence.payload_version_unsupported"
BLOCKER_REVISION_MISMATCH:             str = "evidence.revision_stamp_mismatch"
BLOCKER_ENVIRONMENT_MISMATCH:          str = "evidence.environment_mismatch"
BLOCKER_ENVIRONMENT_UNSET:             str = "evidence.environment_env_unset"
BLOCKER_APPROVED_IN_FUTURE:            str = "evidence.approved_at_in_future"
BLOCKER_OBSERVATION_IN_FUTURE:         str = "evidence.observation_window_in_future"
BLOCKER_OBSERVATION_WINDOW_INVERTED:   str = "evidence.observation_window_inverted"
BLOCKER_OBSERVATION_WINDOW_TOO_SHORT:  str = "evidence.observation_window_too_short"
BLOCKER_EVIDENCE_EXPIRED:              str = "evidence.expired"
BLOCKER_INSUFFICIENT_DIFFS:            str = "evidence.total_diffs_below_threshold"
BLOCKER_INSUFFICIENT_WORKERS:          str = "evidence.workers_observed_below_threshold"
BLOCKER_EXCESS_EXCEPTION_RATE:         str = "evidence.exception_rate_above_threshold"
BLOCKER_EXCESS_SEMANTIC_DISAGREEMENT:  str = "evidence.different_semantics_above_threshold"
BLOCKER_EXCESS_VALIDATION_ERRORS:      str = "evidence.validation_errors_above_threshold"
BLOCKER_LOW_FINGERPRINT_AVAILABILITY:  str = "evidence.fingerprint_availability_below_threshold"
BLOCKER_APPROVAL_ID_MISSING:           str = "evidence.approval_id_missing"

EVIDENCE_BLOCKERS: frozenset[str] = frozenset({
    BLOCKER_EVIDENCE_MISSING,
    BLOCKER_EVIDENCE_PATH_UNREADABLE,
    BLOCKER_EVIDENCE_MALFORMED,
    BLOCKER_EVIDENCE_ENVELOPE_VERSION,
    BLOCKER_EVIDENCE_SECRET_MISSING,
    BLOCKER_EVIDENCE_SECRET_TOO_SHORT,
    BLOCKER_EVIDENCE_SIGNATURE_ALG,
    BLOCKER_EVIDENCE_SIGNATURE_INVALID,
    BLOCKER_EVIDENCE_SIGNATURE_MISSING,
    BLOCKER_EVIDENCE_VERSION,
    BLOCKER_REVISION_MISMATCH,
    BLOCKER_ENVIRONMENT_MISMATCH,
    BLOCKER_ENVIRONMENT_UNSET,
    BLOCKER_APPROVED_IN_FUTURE,
    BLOCKER_OBSERVATION_IN_FUTURE,
    BLOCKER_OBSERVATION_WINDOW_INVERTED,
    BLOCKER_OBSERVATION_WINDOW_TOO_SHORT,
    BLOCKER_EVIDENCE_EXPIRED,
    BLOCKER_INSUFFICIENT_DIFFS,
    BLOCKER_INSUFFICIENT_WORKERS,
    BLOCKER_EXCESS_EXCEPTION_RATE,
    BLOCKER_EXCESS_SEMANTIC_DISAGREEMENT,
    BLOCKER_EXCESS_VALIDATION_ERRORS,
    BLOCKER_LOW_FINGERPRINT_AVAILABILITY,
    BLOCKER_APPROVAL_ID_MISSING,
})


# =====================================================================
# RolloutEvidenceV2 dataclass
# =====================================================================

@dataclass(frozen=True)
class RolloutEvidenceV2:
    """Signed, immutable rollout evidence. Consumed (never
    created) by the process that would like to enter
    authoritative mode. See module docstring for the trust
    model.

    Fields intentionally exclude ANY user identifiers, target
    identifiers, raw prompts, or conversation content. The
    ``disagreement_source_counts`` map is a closed-set
    aggregation over ``vault_chat_shadow_recorder_v2.DISAGREEMENT_SOURCES``;
    an aggregator that surfaces raw content in this field is
    off-contract.
    """
    evidence_version:               int
    v2_revision_stamp:              str
    environment:                    str
    observation_started_at:         datetime
    observation_ended_at:           datetime
    total_diffs:                    int
    workers_observed:               int
    pipeline_exception_count:       int
    different_semantics_pct:        float
    validation_error_pct:           float
    fingerprint_available_pct:      float
    disagreement_source_counts:     Mapping[str, int]
    approved_at:                    datetime
    expires_at:                     datetime
    approval_id:                    str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_version, int):
            raise TypeError("evidence_version must be int")
        for name in ("observation_started_at", "observation_ended_at",
                      "approved_at", "expires_at"):
            v = getattr(self, name)
            if not isinstance(v, datetime):
                raise TypeError(f"{name} must be datetime")
            if v.tzinfo is None:
                raise ValueError(
                    f"{name} must carry a timezone (UTC required)"
                )


# =====================================================================
# Canonicalization
# =====================================================================

def _dt_to_iso_z(dt: datetime) -> str:
    """UTC ISO-8601 with trailing 'Z'. Deterministic."""
    if dt.tzinfo is None:
        raise ValueError("datetime must carry tzinfo")
    utc = dt.astimezone(timezone.utc)
    # Drop microseconds to keep canonical form stable across
    # producers that vary sub-second precision.
    utc = utc.replace(microsecond=0)
    s = utc.isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _iso_z_to_dt(s: str) -> datetime:
    if not isinstance(s, str):
        raise TypeError("iso datetime must be string")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"iso datetime {s!r} missing tz")
    return dt


def evidence_to_payload_dict(evidence: RolloutEvidenceV2) -> dict:
    """Turn an evidence dataclass into a plain dict suitable for
    canonical JSON serialization. Every field is present; no
    optional keys."""
    return {
        "approval_id":                 evidence.approval_id,
        "approved_at":                 _dt_to_iso_z(evidence.approved_at),
        "different_semantics_pct":     float(evidence.different_semantics_pct),
        "disagreement_source_counts":  {
            k: int(v) for k, v in evidence.disagreement_source_counts.items()
        },
        "environment":                 evidence.environment,
        "evidence_version":            int(evidence.evidence_version),
        "expires_at":                  _dt_to_iso_z(evidence.expires_at),
        "fingerprint_available_pct":   float(evidence.fingerprint_available_pct),
        "observation_ended_at":        _dt_to_iso_z(evidence.observation_ended_at),
        "observation_started_at":      _dt_to_iso_z(evidence.observation_started_at),
        "pipeline_exception_count":    int(evidence.pipeline_exception_count),
        "total_diffs":                 int(evidence.total_diffs),
        "v2_revision_stamp":           evidence.v2_revision_stamp,
        "validation_error_pct":        float(evidence.validation_error_pct),
        "workers_observed":            int(evidence.workers_observed),
    }


def payload_dict_to_evidence(d: Mapping[str, Any]) -> RolloutEvidenceV2:
    """Inverse of ``evidence_to_payload_dict``. Raises
    ``ValueError`` on missing / malformed fields."""
    required = {
        "approval_id", "approved_at", "different_semantics_pct",
        "disagreement_source_counts", "environment", "evidence_version",
        "expires_at", "fingerprint_available_pct",
        "observation_ended_at", "observation_started_at",
        "pipeline_exception_count", "total_diffs",
        "v2_revision_stamp", "validation_error_pct", "workers_observed",
    }
    missing = required - set(d.keys())
    if missing:
        raise ValueError(f"payload missing keys: {sorted(missing)}")
    extra = set(d.keys()) - required
    if extra:
        raise ValueError(f"payload has unknown keys: {sorted(extra)}")
    dsc_raw = d["disagreement_source_counts"]
    if not isinstance(dsc_raw, Mapping):
        raise ValueError("disagreement_source_counts must be an object")
    dsc = {str(k): int(v) for k, v in dsc_raw.items()}
    return RolloutEvidenceV2(
        evidence_version=int(d["evidence_version"]),
        v2_revision_stamp=str(d["v2_revision_stamp"]),
        environment=str(d["environment"]),
        observation_started_at=_iso_z_to_dt(d["observation_started_at"]),
        observation_ended_at=_iso_z_to_dt(d["observation_ended_at"]),
        total_diffs=int(d["total_diffs"]),
        workers_observed=int(d["workers_observed"]),
        pipeline_exception_count=int(d["pipeline_exception_count"]),
        different_semantics_pct=float(d["different_semantics_pct"]),
        validation_error_pct=float(d["validation_error_pct"]),
        fingerprint_available_pct=float(d["fingerprint_available_pct"]),
        disagreement_source_counts=dsc,
        approved_at=_iso_z_to_dt(d["approved_at"]),
        expires_at=_iso_z_to_dt(d["expires_at"]),
        approval_id=str(d["approval_id"]),
    )


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return the canonical JSON encoding of ``payload`` --
    sorted keys, no whitespace, UTF-8. Every producer + verifier
    MUST agree on this exact encoding for signatures to match.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# =====================================================================
# HMAC sign / verify
# =====================================================================

def sign_rollout_evidence(
    evidence: RolloutEvidenceV2, *, secret: bytes,
) -> str:
    """External tooling / tests only. Returns the hex-encoded
    HMAC-SHA256 signature over the canonical payload bytes.

    Production readers use ``verify_signature`` -- NOT this. A
    process that both signs and immediately consumes evidence is
    off-contract (observation + approval must remain separate).
    """
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_HMAC_SECRET_LEN:
        raise ValueError(
            f"HMAC secret must be >= {MIN_HMAC_SECRET_LEN} bytes"
        )
    payload = evidence_to_payload_dict(evidence)
    return hmac.new(
        bytes(secret), canonical_payload_bytes(payload), hashlib.sha256,
    ).hexdigest()


def verify_signature(
    payload: Mapping[str, Any],
    signature_hex: str,
    *,
    secret: bytes,
) -> bool:
    """Constant-time HMAC verification. Returns True iff the
    signature matches the canonical payload bytes under
    ``secret``. NEVER raises on mismatch; NEVER logs the
    signature or the secret."""
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_HMAC_SECRET_LEN:
        return False
    if not isinstance(signature_hex, str) or len(signature_hex) != 64:
        return False
    try:
        expected = hmac.new(
            bytes(secret), canonical_payload_bytes(payload), hashlib.sha256,
        ).hexdigest()
    except Exception:
        return False
    # Constant-time compare -- both sides same length by now.
    return hmac.compare_digest(expected, signature_hex.lower())


# =====================================================================
# Loading
# =====================================================================

def _read_hmac_secret_from_env() -> Optional[bytes]:
    raw = (os.environ.get(ENV_ROLLOUT_EVIDENCE_SECRET) or "").strip()
    if not raw:
        return None
    encoded = raw.encode("utf-8")
    if len(encoded) < MIN_HMAC_SECRET_LEN:
        return None
    return encoded


def _read_environment_name() -> Optional[str]:
    raw = (os.environ.get(ENV_ENVIRONMENT) or "").strip()
    return raw or None


@dataclass(frozen=True)
class EvidenceLoadResult:
    """Outcome of attempting to load evidence from a file.
    ``evidence`` is set on success; ``blockers`` names every
    reason the load failed."""
    evidence:   Optional[RolloutEvidenceV2] = None
    blockers:   tuple = ()


def load_rollout_evidence_from_path(
    path: str, *, secret: bytes,
) -> EvidenceLoadResult:
    """Load and cryptographically verify an evidence file.

    Fail-closed semantics:
        * unreadable file -> BLOCKER_EVIDENCE_PATH_UNREADABLE
        * malformed JSON / structure -> BLOCKER_EVIDENCE_MALFORMED
        * unknown envelope version -> BLOCKER_EVIDENCE_ENVELOPE_VERSION
        * missing signature -> BLOCKER_EVIDENCE_SIGNATURE_MISSING
        * signature alg not supported -> BLOCKER_EVIDENCE_SIGNATURE_ALG
        * signature bytes do not verify -> BLOCKER_EVIDENCE_SIGNATURE_INVALID
        * payload version not supported -> BLOCKER_EVIDENCE_VERSION

    On success, ``evidence`` is populated; ``blockers`` is empty.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except Exception as exc:
        logger.warning(
            "[ROLLOUT_EVIDENCE] path_unreadable: %r",
            type(exc).__name__,
        )
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_PATH_UNREADABLE,),
        )

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except Exception:
        return EvidenceLoadResult(blockers=(BLOCKER_EVIDENCE_MALFORMED,))

    if not isinstance(envelope, Mapping):
        return EvidenceLoadResult(blockers=(BLOCKER_EVIDENCE_MALFORMED,))

    envelope_version = envelope.get("envelope_version")
    if envelope_version != EVIDENCE_ENVELOPE_VERSION:
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_ENVELOPE_VERSION,),
        )

    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return EvidenceLoadResult(blockers=(BLOCKER_EVIDENCE_MALFORMED,))

    sig_alg = envelope.get("signature_alg")
    if sig_alg != SIGNATURE_ALG_HMAC_SHA256:
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_SIGNATURE_ALG,),
        )

    sig_hex = envelope.get("signature_hex")
    if not isinstance(sig_hex, str) or not sig_hex:
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_SIGNATURE_MISSING,),
        )

    if not verify_signature(payload, sig_hex, secret=secret):
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_SIGNATURE_INVALID,),
        )

    try:
        evidence = payload_dict_to_evidence(payload)
    except Exception as exc:
        logger.warning(
            "[ROLLOUT_EVIDENCE] payload_decode_failed: %r",
            type(exc).__name__,
        )
        return EvidenceLoadResult(blockers=(BLOCKER_EVIDENCE_MALFORMED,))

    if evidence.evidence_version not in SUPPORTED_EVIDENCE_VERSIONS:
        return EvidenceLoadResult(
            evidence=evidence,
            blockers=(BLOCKER_EVIDENCE_VERSION,),
        )

    return EvidenceLoadResult(evidence=evidence)


def load_rollout_evidence_from_env() -> EvidenceLoadResult:
    """Convenience loader: reads
    ``VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_PATH`` +
    ``VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_HMAC_SECRET`` and
    dispatches to ``load_rollout_evidence_from_path``. If either
    env var is unset, returns a blocker-only result."""
    path = (os.environ.get(ENV_ROLLOUT_EVIDENCE_PATH) or "").strip()
    if not path:
        return EvidenceLoadResult(blockers=(BLOCKER_EVIDENCE_MISSING,))
    secret = _read_hmac_secret_from_env()
    if secret is None:
        # Distinguish absent vs too-short by re-reading raw.
        raw = (os.environ.get(ENV_ROLLOUT_EVIDENCE_SECRET) or "").strip()
        if not raw:
            return EvidenceLoadResult(
                blockers=(BLOCKER_EVIDENCE_SECRET_MISSING,),
            )
        return EvidenceLoadResult(
            blockers=(BLOCKER_EVIDENCE_SECRET_TOO_SHORT,),
        )
    return load_rollout_evidence_from_path(path, secret=secret)


# =====================================================================
# Validation
# =====================================================================

@dataclass(frozen=True)
class EvidenceValidationResult:
    valid:      bool
    blockers:   tuple = ()
    warnings:   tuple = ()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def validate_rollout_evidence(
    evidence: RolloutEvidenceV2,
    *,
    current_environment: Optional[str] = None,
    now: Optional[datetime] = None,
) -> EvidenceValidationResult:
    """Verify semantic invariants of loaded evidence.

    Callers who already ran ``load_rollout_evidence_from_env``
    have a valid signature; this function checks the fields
    themselves. Any single-line blocker refuses activation.

    ``current_environment`` overrides the env-var lookup for
    tests; production callers should pass None so the env is
    read.
    """
    now_ts = now if now is not None else _now_utc()
    blockers: list[str] = []
    warnings: list[str] = []

    # Revision stamp must match the running code EXACTLY.
    running_stamp = compute_v2_revision_stamp()
    if evidence.v2_revision_stamp != running_stamp:
        blockers.append(BLOCKER_REVISION_MISMATCH)

    # Environment name.
    env_expected = (
        current_environment if current_environment is not None
        else _read_environment_name()
    )
    if env_expected is None:
        blockers.append(BLOCKER_ENVIRONMENT_UNSET)
    elif evidence.environment != env_expected:
        blockers.append(BLOCKER_ENVIRONMENT_MISMATCH)

    # Temporal.
    if evidence.approved_at > now_ts:
        blockers.append(BLOCKER_APPROVED_IN_FUTURE)
    if evidence.observation_started_at > now_ts:
        blockers.append(BLOCKER_OBSERVATION_IN_FUTURE)
    if evidence.observation_ended_at > now_ts:
        blockers.append(BLOCKER_OBSERVATION_IN_FUTURE)
    if evidence.observation_ended_at < evidence.observation_started_at:
        blockers.append(BLOCKER_OBSERVATION_WINDOW_INVERTED)
    if evidence.expires_at < now_ts:
        blockers.append(BLOCKER_EVIDENCE_EXPIRED)

    window_seconds = (
        evidence.observation_ended_at - evidence.observation_started_at
    ).total_seconds()
    if window_seconds < MIN_OBSERVATION_WINDOW_HOURS * 3600.0:
        blockers.append(BLOCKER_OBSERVATION_WINDOW_TOO_SHORT)

    # Quantitative thresholds.
    if evidence.total_diffs < MIN_TOTAL_DIFFS_FOR_ROLLOUT:
        blockers.append(BLOCKER_INSUFFICIENT_DIFFS)
    if evidence.workers_observed < MIN_WORKERS_OBSERVED:
        blockers.append(BLOCKER_INSUFFICIENT_WORKERS)

    exception_rate_pct = 0.0
    if evidence.total_diffs > 0:
        exception_rate_pct = (
            100.0 * evidence.pipeline_exception_count / evidence.total_diffs
        )
    if exception_rate_pct > MAX_EXCEPTION_RATE_PCT:
        blockers.append(BLOCKER_EXCESS_EXCEPTION_RATE)

    if evidence.different_semantics_pct > MAX_DIFFERENT_SEMANTICS_PCT:
        blockers.append(BLOCKER_EXCESS_SEMANTIC_DISAGREEMENT)
    if evidence.validation_error_pct > MAX_VALIDATION_ERROR_PCT:
        blockers.append(BLOCKER_EXCESS_VALIDATION_ERRORS)
    if evidence.fingerprint_available_pct < MIN_FINGERPRINT_AVAILABLE_PCT:
        blockers.append(BLOCKER_LOW_FINGERPRINT_AVAILABILITY)

    # Approval id.
    if not evidence.approval_id or not evidence.approval_id.strip():
        blockers.append(BLOCKER_APPROVAL_ID_MISSING)

    return EvidenceValidationResult(
        valid=(len(blockers) == 0),
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(warnings),
    )


__all__ = [
    "EVIDENCE_ENVELOPE_VERSION",
    "SUPPORTED_EVIDENCE_VERSIONS",
    "SIGNATURE_ALG_HMAC_SHA256",
    "MIN_HMAC_SECRET_LEN",
    "ENV_ROLLOUT_EVIDENCE_PATH",
    "ENV_ROLLOUT_EVIDENCE_SECRET",
    "ENV_ENVIRONMENT",
    "MIN_TOTAL_DIFFS_FOR_ROLLOUT",
    "MIN_WORKERS_OBSERVED",
    "MIN_OBSERVATION_WINDOW_HOURS",
    "MAX_EXCEPTION_RATE_PCT",
    "MAX_DIFFERENT_SEMANTICS_PCT",
    "MAX_VALIDATION_ERROR_PCT",
    "MIN_FINGERPRINT_AVAILABLE_PCT",
    "EVIDENCE_BLOCKERS",
    # blocker codes
    "BLOCKER_EVIDENCE_MISSING",
    "BLOCKER_EVIDENCE_PATH_UNREADABLE",
    "BLOCKER_EVIDENCE_MALFORMED",
    "BLOCKER_EVIDENCE_ENVELOPE_VERSION",
    "BLOCKER_EVIDENCE_SECRET_MISSING",
    "BLOCKER_EVIDENCE_SECRET_TOO_SHORT",
    "BLOCKER_EVIDENCE_SIGNATURE_ALG",
    "BLOCKER_EVIDENCE_SIGNATURE_INVALID",
    "BLOCKER_EVIDENCE_SIGNATURE_MISSING",
    "BLOCKER_EVIDENCE_VERSION",
    "BLOCKER_REVISION_MISMATCH",
    "BLOCKER_ENVIRONMENT_MISMATCH",
    "BLOCKER_ENVIRONMENT_UNSET",
    "BLOCKER_APPROVED_IN_FUTURE",
    "BLOCKER_OBSERVATION_IN_FUTURE",
    "BLOCKER_OBSERVATION_WINDOW_INVERTED",
    "BLOCKER_OBSERVATION_WINDOW_TOO_SHORT",
    "BLOCKER_EVIDENCE_EXPIRED",
    "BLOCKER_INSUFFICIENT_DIFFS",
    "BLOCKER_INSUFFICIENT_WORKERS",
    "BLOCKER_EXCESS_EXCEPTION_RATE",
    "BLOCKER_EXCESS_SEMANTIC_DISAGREEMENT",
    "BLOCKER_EXCESS_VALIDATION_ERRORS",
    "BLOCKER_LOW_FINGERPRINT_AVAILABILITY",
    "BLOCKER_APPROVAL_ID_MISSING",
    # types + functions
    "RolloutEvidenceV2",
    "EvidenceLoadResult",
    "EvidenceValidationResult",
    "evidence_to_payload_dict",
    "payload_dict_to_evidence",
    "canonical_payload_bytes",
    "sign_rollout_evidence",
    "verify_signature",
    "load_rollout_evidence_from_path",
    "load_rollout_evidence_from_env",
    "validate_rollout_evidence",
]
