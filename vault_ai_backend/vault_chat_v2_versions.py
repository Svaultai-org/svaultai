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


__all__ = [
    "BRAIN_V2_REVISION",
    "POLICY_V2_REVISION",
    "ROUTER_V2_REVISION",
    "SEMANTIC_DECIDER_REVISION",
    "PROMPT_REVISION",
    "INTEGRATION_V2_REVISION",
    "compute_v2_revision_stamp",
    "get_v2_revision_dict",
]
