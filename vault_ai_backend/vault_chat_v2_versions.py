"""Version stamps for the v2 chat brain (commit 8).

Every architectural layer has an independent integer revision.
Bump the revision when the layer's behavior changes in a way
that a historical shadow log record would misinterpret.

Guidelines for bumping:

    BRAIN_V2_REVISION
        * flag semantics change (mode dispatch, fallback rules)
        * failure-invariant / phase-boundary contract change

    POLICY_V2_REVISION
        * a REASON_CODE or OUTCOME added, renamed, or removed
        * a decision-authorization rule changes

    ROUTER_V2_REVISION
        * an ACTION_KIND or REPLY_KIND added, renamed, or removed
        * ExecutionPlanV2 or RouterResultV2 field shape changes
        * a next_state transition rule changes

    SEMANTIC_DECIDER_REVISION
        * async decider wiring / retry / timeout logic change

    PROMPT_REVISION
        * the LLM system prompt is edited in
          vault_chat_semantic_decider_v2._SYSTEM_PROMPT_V2

    INTEGRATION_V2_REVISION
        * apply_router_result_v2 pipeline stages change order
        * ExecutorRegistry / IntegrationResultV2 shape changes

Do NOT bump for:

    * bug fixes that preserve observable behavior;
    * test-only changes;
    * comment or docstring updates;
    * refactors that keep the closed-set outputs identical.

Every shadow diff record embeds ``compute_v2_revision_stamp()``.
Operators grep shadow logs by stamp to know exactly which
combination of layer versions produced a given record.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


# =====================================================================
# Per-layer revisions
# =====================================================================

BRAIN_V2_REVISION:           int = 1
POLICY_V2_REVISION:          int = 1
ROUTER_V2_REVISION:          int = 1
SEMANTIC_DECIDER_REVISION:   int = 1
PROMPT_REVISION:             int = 1
INTEGRATION_V2_REVISION:     int = 1


# =====================================================================
# Revision-invariants floor (commit 8b)
#
# Each entry is the MINIMUM acceptable value for the matching
# revision constant above. When you bump a constant per the
# bump-policy comment at the top of this module, bump the
# matching floor too. A merge conflict that accidentally resets
# a constant BELOW its floor fails ``check_revision_invariants``
# at startup rather than silently downgrading historical
# evidence.
#
# Monotonicity policy: revisions are append-only per repo
# history. Do NOT decrement. Never re-use a stamp for a
# different observable behavior.
# =====================================================================

MIN_LAYER_REVISIONS: Mapping[str, int] = MappingProxyType({
    "brain":              1,
    "policy":             1,
    "router":             1,
    "semantic_decider":   1,
    "prompt":             1,
    "integration":        1,
})


# =====================================================================
# Combined stamp
# =====================================================================

def compute_v2_revision_stamp() -> str:
    """Return a compact multi-layer stamp for embedding in shadow
    records and diagnostic reports. Format:

        b<N>.p<N>.r<N>.s<N>.q<N>.i<N>

    where:
        b -> brain
        p -> policy
        r -> router
        s -> semantic decider
        q -> prompt
        i -> integration

    Stable ordering. Grep-friendly. Never carries user data.
    """
    return (
        f"b{BRAIN_V2_REVISION}"
        f".p{POLICY_V2_REVISION}"
        f".r{ROUTER_V2_REVISION}"
        f".s{SEMANTIC_DECIDER_REVISION}"
        f".q{PROMPT_REVISION}"
        f".i{INTEGRATION_V2_REVISION}"
    )


def get_v2_revision_dict() -> dict[str, int]:
    """Return the per-layer revision map for structured
    diagnostic export. Callers should NOT mutate the return
    value (dict comprehension makes a fresh copy)."""
    return {
        "brain":              BRAIN_V2_REVISION,
        "policy":             POLICY_V2_REVISION,
        "router":             ROUTER_V2_REVISION,
        "semantic_decider":   SEMANTIC_DECIDER_REVISION,
        "prompt":             PROMPT_REVISION,
        "integration":        INTEGRATION_V2_REVISION,
    }


def check_revision_invariants() -> tuple[bool, list[str]]:
    """Verify every revision constant satisfies the invariants
    documented in this module:

        * strictly positive integer (>= 1);
        * >= its entry in ``MIN_LAYER_REVISIONS`` (defends
          against a merge conflict silently resetting a
          revision below its historical floor).

    Returns ``(is_valid, sorted_violations)``. Wired into the
    startup self-test so a downgrade fails startup rather than
    corrupting rollout evidence semantics.
    """
    violations: list[str] = []
    revisions = get_v2_revision_dict()
    for name, value in revisions.items():
        if not isinstance(value, int) or value < 1:
            violations.append(
                f"revision {name!r} must be a positive int, got {value!r}"
            )
            continue
        floor = MIN_LAYER_REVISIONS.get(name)
        if floor is None:
            violations.append(
                f"MIN_LAYER_REVISIONS is missing an entry for {name!r}"
            )
            continue
        if value < floor:
            violations.append(
                f"revision {name!r}={value} is below its floor "
                f"MIN_LAYER_REVISIONS[{name!r}]={floor}; monotonic "
                "bump policy forbids downgrade"
            )
    # Every MIN entry must correspond to a real revision.
    for name in MIN_LAYER_REVISIONS.keys():
        if name not in revisions:
            violations.append(
                f"MIN_LAYER_REVISIONS[{name!r}] has no matching "
                "revision constant"
            )
    return (len(violations) == 0, sorted(violations))


__all__ = [
    "BRAIN_V2_REVISION",
    "POLICY_V2_REVISION",
    "ROUTER_V2_REVISION",
    "SEMANTIC_DECIDER_REVISION",
    "PROMPT_REVISION",
    "INTEGRATION_V2_REVISION",
    "MIN_LAYER_REVISIONS",
    "compute_v2_revision_stamp",
    "get_v2_revision_dict",
    "check_revision_invariants",
]
