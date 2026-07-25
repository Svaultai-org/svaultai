"""PROCESS-LOCAL metrics aggregator for shadow-mode v2 (commits 7 + 8a).

This module is PROCESS-LOCAL by design. Its counters:

    * reset every process restart;
    * are isolated per worker / server / container;
    * are unavailable to a newly-started authoritative process;
    * are NOT durable rollout evidence and MUST NOT be used to
      approve production activation.

For fleet-wide rollout approval use
``vault_chat_v2_rollout_evidence`` -- a signed, immutable
evidence artifact produced by an externally-run aggregation
pipeline. The authoritative readiness gate consumes evidence,
not local counters.

What this module IS useful for:

    * debugging and per-worker diagnostics;
    * immediate exception detection while shadow is enabled;
    * verifying zero-write invariants during staging;
    * populating the process-local dimension of health reports.

The snapshot dataclass ``ProcessShadowMetricsSnapshotV2`` labels
its output with process correlation fields (an HMAC of pid +
start time, the worker start timestamp, the sample-window start
timestamp) so a naive fleet-wide sum cannot accidentally
double-count or elide observations.

Bounded histograms
------------------

Every long-running counter uses a bounded map:

    * ``pipeline_exception_types``: type names truncated to 64
      chars, keyed per stage;
    * ``revision_stamps``: at most 32 distinct stamps stored;
    * ``recent_decisions_window``: deque bounded to
      ``EXCEPTION_WINDOW_SIZE = 10 000``.

Adversarial input cannot bloat memory beyond these caps.

Never stores raw user content, target ids, usernames, or vault
ids -- only the closed-set match categories, stage names,
action_kinds, and disagreement sources.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from vault_chat_decision_router_v2 import ACTION_KINDS
from vault_chat_shadow_recorder_v2 import (
    DISAGREEMENT_SOURCES,
    MATCH_CATEGORIES,
    ShadowDiffRecordV2,
    _process_secret,
)


logger = logging.getLogger(__name__)


# Closed set of pipeline stages a shadow-mode exception may occur
# at.
SHADOW_PIPELINE_STAGES: frozenset[str] = frozenset({
    "snapshot",
    "decider",
    "policy",
    "router",
    "log",       # build_and_log_diff itself raising
    "metrics",   # this aggregator itself raising (self-report)
})


# Exception windowing (commit 8a). The rate view uses the last
# ``EXCEPTION_WINDOW_SIZE`` shadow events (diffs + exceptions).
# Bounded via ``collections.deque(maxlen=...)`` so memory stays
# capped regardless of traffic volume.
EXCEPTION_WINDOW_SIZE: int = 10_000

# Bound distinct exception-type histograms + revision-stamp
# histogram to prevent adversarial input from bloating the map.
_MAX_DISTINCT_EXCEPTION_TYPES_PER_STAGE: int = 32
_MAX_DISTINCT_REVISION_STAMPS:           int = 32
_EXCEPTION_TYPE_NAME_MAX_LEN:            int = 64


# =====================================================================
# Process correlation
# =====================================================================

def _compute_process_id_hmac() -> str:
    """HMAC of (pid, worker_started_at). Uses the shadow
    fingerprint secret when available so cross-process aggregation
    can safely correlate replays without exposing raw ids. Returns
    ``'-'`` when no secret is configured (process-local snapshot
    still labels itself as such).
    """
    secret = _process_secret()
    if secret is None:
        return "-"
    material = f"{os.getpid()}|{_WORKER_STARTED_AT}".encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()[:16]


_WORKER_STARTED_AT: float = time.time()


@dataclass(frozen=True)
class ProcessShadowMetricsSnapshotV2:
    """A single worker's shadow-metrics view AT A POINT IN TIME.

    Explicitly labeled ``process-local``. Every consumer MUST
    treat this as one worker's private view, NOT as fleet-wide
    evidence. See ``vault_chat_v2_rollout_evidence`` for the
    fleet-wide aggregation contract.

    Fields:
        process_id_hmac:            HMAC-64 of (pid, start_ts).
                                    "-" if no fingerprint secret.
        worker_started_at:          epoch seconds when the worker
                                    booted.
        sample_window_started_at:   epoch seconds when the current
                                    metrics window started (reset
                                    to ``time.time()`` on
                                    ``reset_metrics_for_tests``).
        snapshot_at:                epoch seconds when this
                                    snapshot was taken.
        data:                       the plain-dict metrics view
                                    (backward-compatible with
                                    ``get_metrics_snapshot()``).
    """
    process_id_hmac:           str
    worker_started_at:         float
    sample_window_started_at:  float
    snapshot_at:               float
    data:                      dict

    def as_dict(self) -> dict:
        return {
            "scope":                    "process-local",
            "process_id_hmac":          self.process_id_hmac,
            "worker_started_at":        self.worker_started_at,
            "sample_window_started_at": self.sample_window_started_at,
            "snapshot_at":              self.snapshot_at,
            "data":                     dict(self.data),
        }


class _Metrics:
    """Guarded mutable state. Only accessed through the module
    functions -- do not instantiate directly."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_time: float = time.time()
        self._reset_locked()

    def _reset_locked(self) -> None:
        self._start_time = time.time()
        self._diff_count: int = 0
        self._matches: dict[str, int] = {
            cat: 0 for cat in MATCH_CATEGORIES
        }
        self._fp_available_count: int = 0
        self._fp_unavailable_count: int = 0
        self._pipeline_exceptions: dict[str, int] = {
            stage: 0 for stage in SHADOW_PIPELINE_STAGES
        }
        self._pipeline_exception_types: dict[str, dict[str, int]] = {
            stage: {} for stage in SHADOW_PIPELINE_STAGES
        }
        self._action_kind_counts: dict[str, int] = {
            k: 0 for k in ACTION_KINDS
        }
        self._router_handled_count: int = 0
        self._router_fallthrough_count: int = 0
        self._v1_handled_count: int = 0
        self._v1_fallthrough_count: int = 0
        self._disagreement_sources: dict[str, int] = {
            src: 0 for src in DISAGREEMENT_SOURCES
        }
        self._revision_stamps: dict[str, int] = {}
        # commit 8a: exception rate is meaningless as a lifetime
        # counter for a long-running process. Track the last
        # EXCEPTION_WINDOW_SIZE shadow events (each entry is 1
        # for exception, 0 for normal diff) so a rolling rate
        # can be computed.
        self._recent_window: collections.deque[int] = collections.deque(
            maxlen=EXCEPTION_WINDOW_SIZE,
        )
        self._exceptions_total: int = 0
        self._last_exception_at: float = 0.0

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def record_diff(self, record: ShadowDiffRecordV2) -> None:
        with self._lock:
            self._diff_count += 1
            cat = record.match
            if cat in self._matches:
                self._matches[cat] += 1
            if record.fp_available:
                self._fp_available_count += 1
            else:
                self._fp_unavailable_count += 1
            if record.v1_handled:
                self._v1_handled_count += 1
            else:
                self._v1_fallthrough_count += 1
            if record.router_view is not None:
                if record.router_view.handled:
                    self._router_handled_count += 1
                else:
                    self._router_fallthrough_count += 1
                action_kind = record.router_view.action_kind
                if action_kind and action_kind in self._action_kind_counts:
                    self._action_kind_counts[action_kind] += 1
            src = record.disagreement_source
            if src in self._disagreement_sources:
                self._disagreement_sources[src] += 1
            stamp = record.v2_revision_stamp or "-"
            if len(self._revision_stamps) < _MAX_DISTINCT_REVISION_STAMPS \
                    or stamp in self._revision_stamps:
                self._revision_stamps[stamp] = (
                    self._revision_stamps.get(stamp, 0) + 1
                )
            self._recent_window.append(0)  # 0 = normal diff

    def record_pipeline_exception(
        self, stage: str, exc_type_name: str,
    ) -> None:
        if stage not in SHADOW_PIPELINE_STAGES:
            logger.warning(
                "[SHADOW_METRICS] unknown pipeline stage %r; dropping",
                stage,
            )
            return
        safe_name = (exc_type_name or "unknown")[:_EXCEPTION_TYPE_NAME_MAX_LEN]
        with self._lock:
            self._pipeline_exceptions[stage] += 1
            self._exceptions_total += 1
            self._last_exception_at = time.time()
            m = self._pipeline_exception_types[stage]
            # Bounded histogram: cap distinct type names per
            # stage. If cap reached, fold further into a
            # sentinel bucket -- never grow.
            if safe_name in m or len(m) < _MAX_DISTINCT_EXCEPTION_TYPES_PER_STAGE:
                m[safe_name] = m.get(safe_name, 0) + 1
            else:
                m["__other__"] = m.get("__other__", 0) + 1
            self._recent_window.append(1)  # 1 = exception

    def snapshot(self) -> dict:
        """Return a plain-dict deep copy of the current counters.
        Never returns a live reference to internal state.
        """
        with self._lock:
            uptime = max(0.0, time.time() - self._start_time)
            total = self._diff_count
            def pct(numerator: int) -> float:
                if total == 0:
                    return 0.0
                return round(100.0 * numerator / total, 3)
            window_size = len(self._recent_window)
            exceptions_in_window = sum(self._recent_window)
            if window_size > 0:
                exception_rate_pct = round(
                    100.0 * exceptions_in_window / window_size, 3,
                )
            else:
                exception_rate_pct = 0.0
            return {
                "scope":                       "process-local",
                "uptime_seconds":              round(uptime, 3),
                "diff_count":                  self._diff_count,
                "matches":                     dict(self._matches),
                "match_ratios_pct": {
                    cat: pct(v) for cat, v in self._matches.items()
                },
                "fp_available_count":          self._fp_available_count,
                "fp_unavailable_count":        self._fp_unavailable_count,
                "fp_available_ratio_pct":      pct(self._fp_available_count),
                "pipeline_exceptions":         dict(self._pipeline_exceptions),
                "pipeline_exception_types": {
                    stage: dict(types)
                    for stage, types
                    in self._pipeline_exception_types.items()
                },
                "action_kind_counts":          dict(self._action_kind_counts),
                "router_handled_count":        self._router_handled_count,
                "router_fallthrough_count":    self._router_fallthrough_count,
                "v1_handled_count":            self._v1_handled_count,
                "v1_fallthrough_count":        self._v1_fallthrough_count,
                "disagreement_sources":        dict(self._disagreement_sources),
                "disagreement_source_ratios_pct": {
                    src: pct(v)
                    for src, v in self._disagreement_sources.items()
                },
                "revision_stamps":             dict(self._revision_stamps),
                "exceptions_total":            self._exceptions_total,
                "exceptions_in_current_window": exceptions_in_window,
                "exception_window_size":       window_size,
                "exception_rate_pct":          exception_rate_pct,
                "last_exception_at":           self._last_exception_at,
                "sample_window_started_at":    self._start_time,
            }


_METRICS = _Metrics()


def record_shadow_diff(record: ShadowDiffRecordV2) -> None:
    """Increment counters for one shadow diff record. Called by
    the shadow recorder after every ``build_and_log_diff``."""
    try:
        _METRICS.record_diff(record)
    except Exception:
        logger.exception("[SHADOW_METRICS] record_diff_failed")


def record_pipeline_exception(stage: str, exc_type_name: str) -> None:
    """Increment counters for a caught v2 pipeline exception in
    shadow mode. ``stage`` must be in
    ``SHADOW_PIPELINE_STAGES``. Called from
    ``vault_chat_brain_v2.run_v2_shadow`` at each try/except
    boundary that swallows the exception."""
    try:
        _METRICS.record_pipeline_exception(stage, exc_type_name)
    except Exception:
        logger.exception("[SHADOW_METRICS] record_exception_failed")


def get_metrics_snapshot() -> dict:
    """Return a plain-dict snapshot of every counter. Safe to
    call at any time from any thread. The snapshot is labeled
    ``scope=process-local`` -- callers MUST NOT interpret it as
    fleet-wide evidence."""
    return _METRICS.snapshot()


def get_process_local_snapshot() -> ProcessShadowMetricsSnapshotV2:
    """Return the same data as ``get_metrics_snapshot`` wrapped
    in a labeled ``ProcessShadowMetricsSnapshotV2`` dataclass.
    Callers that build fleet-level views MUST label each
    observation with the ``process_id_hmac`` +
    ``worker_started_at`` so aggregation cannot accidentally
    double-count or elide observations."""
    data = _METRICS.snapshot()
    return ProcessShadowMetricsSnapshotV2(
        process_id_hmac=_compute_process_id_hmac(),
        worker_started_at=_WORKER_STARTED_AT,
        sample_window_started_at=data.get(
            "sample_window_started_at", _WORKER_STARTED_AT,
        ),
        snapshot_at=time.time(),
        data=data,
    )


def reset_metrics_for_tests() -> None:
    """TEST-ONLY: clear every counter. Never called from
    production paths."""
    _METRICS.reset()


__all__ = [
    "SHADOW_PIPELINE_STAGES",
    "EXCEPTION_WINDOW_SIZE",
    "ProcessShadowMetricsSnapshotV2",
    "record_shadow_diff",
    "record_pipeline_exception",
    "get_metrics_snapshot",
    "get_process_local_snapshot",
    "reset_metrics_for_tests",
]
