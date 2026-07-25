"""In-process metrics aggregator for shadow-mode v2 (commit 7).

Shadow mode emits one ``ShadowDiffRecordV2`` per turn. This module
aggregates those records into thread-safe counters that an
operator can snapshot at any point to answer:

    * how many turns has shadow observed?
    * what percentage of those matched v1 semantically?
    * what percentage disagreed materially (different_semantics)?
    * what percentage were v2 validation errors (a v2 defect)?
    * what percentage were insufficient-context artifacts (not a
      v2 defect -- shadow lacks focus state that on-mode has)?
    * what percentage produced fingerprints vs degraded records?
    * how many v2-side exceptions did shadow catch, broken down
      by pipeline stage (snapshot / decider / policy / router)?
    * how many turns did each router-observable action_kind
      produce (rate-of-use for each action)?

Design choices:

    * Pure Python, no external metrics dependency.
    * Thread-safe via a single lock guarding a plain-dict shape.
    * ``snapshot()`` returns a deep copy so callers can iterate
      without holding the lock.
    * ``reset_for_tests()`` clears every counter. Never called
      from production code paths.
    * NEVER stores or forwards raw user text, target ids,
      usernames, or vault ids -- only the closed-set match
      categories, closed-set stage names, and closed-set
      action_kinds.
    * NEVER writes to Redis, disk, or any external store; every
      counter is process-local. Operators query the metrics via
      ``get_metrics_snapshot()`` and export them however they
      wish.

Usage:

    from vault_chat_shadow_metrics_v2 import (
        record_shadow_diff, record_pipeline_exception,
        get_metrics_snapshot, reset_metrics_for_tests,
    )

The shadow recorder is wired to call ``record_shadow_diff(record)``
after every ``build_and_log_diff``; the brain-v2 shadow path
calls ``record_pipeline_exception(stage, exc_type_name)`` at each
try/except boundary that would otherwise swallow the exception.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Mapping, Optional

from vault_chat_decision_router_v2 import ACTION_KINDS
from vault_chat_shadow_recorder_v2 import (
    DISAGREEMENT_SOURCES,
    MATCH_CATEGORIES,
    ShadowDiffRecordV2,
)


logger = logging.getLogger(__name__)


# Closed set of pipeline stages a shadow-mode exception may occur
# at. Any string reported to record_pipeline_exception outside
# this set is rejected (raises ValueError in strict mode; logs a
# warning and drops in permissive/production mode).
SHADOW_PIPELINE_STAGES: frozenset[str] = frozenset({
    "snapshot",
    "decider",
    "policy",
    "router",
    "log",       # build_and_log_diff itself raising
    "metrics",   # this aggregator itself raising (self-report)
})


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
        # commit 8: per-source disagreement attribution counts
        # so operators can prioritize which layer to investigate.
        self._disagreement_sources: dict[str, int] = {
            src: 0 for src in DISAGREEMENT_SOURCES
        }
        # commit 8: revision-stamp histogram so an operator can
        # see when historical records were produced against a
        # different layer revision than the running process.
        self._revision_stamps: dict[str, int] = {}

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
            # Bound the histogram to prevent an untrusted stamp
            # source from bloating the dict (defense in depth --
            # stamps come from compute_v2_revision_stamp() which
            # produces a bounded shape).
            if len(self._revision_stamps) < 32 or stamp in self._revision_stamps:
                self._revision_stamps[stamp] = (
                    self._revision_stamps.get(stamp, 0) + 1
                )

    def record_pipeline_exception(
        self, stage: str, exc_type_name: str,
    ) -> None:
        # Strict on stage; permissive on exception type name (still
        # a bounded string).
        if stage not in SHADOW_PIPELINE_STAGES:
            logger.warning(
                "[SHADOW_METRICS] unknown pipeline stage %r; dropping",
                stage,
            )
            return
        # Bound the type name length so a pathological exception
        # class name cannot bloat the dict.
        safe_name = (exc_type_name or "unknown")[:64]
        with self._lock:
            self._pipeline_exceptions[stage] += 1
            m = self._pipeline_exception_types[stage]
            m[safe_name] = m.get(safe_name, 0) + 1

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
            return {
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
    call at any time from any thread."""
    return _METRICS.snapshot()


def reset_metrics_for_tests() -> None:
    """TEST-ONLY: clear every counter. Never called from
    production paths."""
    _METRICS.reset()


__all__ = [
    "SHADOW_PIPELINE_STAGES",
    "record_shadow_diff",
    "record_pipeline_exception",
    "get_metrics_snapshot",
    "reset_metrics_for_tests",
]
