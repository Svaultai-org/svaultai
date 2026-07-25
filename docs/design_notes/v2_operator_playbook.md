# VaultAI Chat Brain v2 — Operator Playbook

Version stamp: `b1.p1.r1.s1.q1.i1` (see `vault_chat_v2_versions.py`)

Audience: operations engineers managing shadow-mode observation
and eventual mode-on activation.

## What v2 is

v2 replaces the v1 chat brain's keyword/heuristic intent parser
with an LLM-driven semantic decider fronted by:

    snapshot -> semantic decider -> policy -> router -> integration

Each layer is independently versioned. The feature flag
`VAULTAI_CHAT_BRAIN_MODE` gates activation.

## Modes

| `VAULTAI_CHAT_BRAIN_MODE` | Behavior |
|---|---|
| `off` (default) | v1 legacy brain runs. v2 code path never invoked. |
| `shadow` | v1 remains authoritative; v2 runs the full read-only decision stack alongside; a `[SHADOW_V2]` log record is emitted per turn. Zero writes from v2. |
| `on` | v2 is authoritative. v1 does not run inside brain. Refused at startup by the readiness gate if the executor registry is incomplete or health thresholds are unmet. |

## Rollout sequence (do not skip stages)

```
OFF
  ↓  (baseline production)

SHADOW (staging)
  ↓  (staging-only; verify configuration, self-test, parity, and behavioral thresholds)

SHADOW (small internal production population)
  ↓  (5–10 % traffic; observe disagreement source attribution; investigate SEMANTIC/POLICY/ROUTER disagreements independently)

SHADOW (full production observation)
  ↓  (100 % traffic in shadow; reach CONFIDENCE_HIGH ≥10 000 diffs; behavior status must be PASS)

ON (staging)
  ↓  (staging-only; is_v2_authoritative_ready() must return ready=True)

ON (small internal production)
  ↓  (5–10 % traffic; monitor pipeline exceptions and controlled-error rate)

ON (full production)
```

At **every transition**, all of the following must hold:

1. `validate_shadow_configuration()` — no `ERROR`-level findings.
2. `run_startup_self_test()` — every stage `ok=True`.
3. `assert_shadow_authoritative_parity(registry)` — parity holds.
4. `shadow_health_summary(...)` — overall `READY` (or, for the
   OFF→SHADOW-staging transition, at least no `UNREADY`).
5. `is_v2_authoritative_ready(registry, require_confidence=HIGH)`
   — required only for the two ON transitions.

## Enabling shadow mode

1. Set the fingerprint secret (required — validator errors if
   missing):

   ```bash
   export VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET="<≥32-byte random string>"
   ```

   This secret keys the HMAC-SHA256 correlation hashes in shadow
   log records. It is process-local, never logged, never
   forwarded.

2. Verify configuration:

   ```python
   from vault_chat_v2_diagnostics import validate_shadow_configuration
   report = validate_shadow_configuration()
   assert report.ok, report.as_dict()
   ```

3. Run the startup self-test:

   ```python
   from vault_chat_v2_diagnostics import run_startup_self_test
   assert run_startup_self_test().ok
   ```

4. Flip the mode:

   ```bash
   export VAULTAI_CHAT_BRAIN_MODE=shadow
   ```

   Restart the workers. v1 remains authoritative from the user's
   perspective; v2 begins emitting `[SHADOW_V2]` log records.

## Observing shadow rollout

Every shadow log line carries closed-set fields only:

```
[SHADOW_V2] turn=<hmac64> vault=<hmac64> sess=<hmac64>
  v1_tool=<name> v1_handled=<0|1>
  v2_intent=<intent> v2_target_kind=<kind>
  v2_target_hmac64=<hmac64> v2_outcome=<allow|clarify|reject>
  v2_reason=<REASON_CODE> v2_conf_bucket=<lt85|85to90|90to95|gte95>
  v2_fp=<hmac64> fp_available=<0|1>
  match=<intent_equivalent|different_semantics|insufficient_shadow_context|v2_validation_error>
  disagreement_source=<NONE|SEMANTIC|POLICY|ROUTER|INSUFFICIENT_CONTEXT|V2_ERROR|UNKNOWN>
  v2_rev=<b1.p1.r1.s1.q1.i1>
  v2_router_handled=<0|1> v2_router_reply_kind=<...>
  v2_router_next_state=<...> v2_router_action_kind=<...>
```

**No raw user text, no plaintext ids, no PII.** Only HMAC-truncated
correlation tokens.

### Investigating disagreements by source

| `disagreement_source` | What it means | Where to look first |
|---|---|---|
| `NONE` | v1 and v2 agree; no action | — |
| `SEMANTIC` | v2 decider chose a different intent | LLM prompt, decider training examples |
| `POLICY` | Intents agree, but v2 policy rejected/clarified where v1 handled | `vault_chat_policy_v2` reason codes |
| `ROUTER` | Intent + policy agree, router chose incompatible action | `vault_chat_decision_router_v2` ExecutionPlanV2 wiring |
| `INSUFFICIENT_CONTEXT` | Shadow lacked focus state that on-mode would have | Not a v2 defect; expected in shadow |
| `V2_ERROR` | v2 returned malformed decision | `vault_chat_semantic_decision_v2` parser |
| `UNKNOWN` | Could not attribute; defensive fallback | Investigate individually |

## Querying rollup metrics

```python
from vault_chat_shadow_metrics_v2 import get_metrics_snapshot
snap = get_metrics_snapshot()
```

Returns a plain dict with:
- `diff_count`
- `matches` and `match_ratios_pct`
- `disagreement_sources` and `disagreement_source_ratios_pct`
- `pipeline_exceptions` (per stage) and `pipeline_exception_types` (histogram)
- `action_kind_counts`
- `revision_stamps` (which v2 revisions have produced records)

## Enabling ON mode

**Do NOT flip `VAULTAI_CHAT_BRAIN_MODE=on` without verifying the
readiness gate.** The gate is a hard STOP:

```python
from vault_chat_v2_diagnostics import is_v2_authoritative_ready, CONFIDENCE_HIGH
from vault_chat_executor_adapters_v2 import build_production_executor_registry

registry = build_production_executor_registry()
gate = is_v2_authoritative_ready(
    registry,
    require_confidence=CONFIDENCE_HIGH,
    require_self_test=True,
)
if not gate.ready:
    for blocker in gate.blockers:
        print("BLOCKER:", blocker)
    raise SystemExit("v2 authoritative activation refused")
```

Gate refuses if any of the following:

- Executor registry missing any `EXECUTOR_REQUIRED_ACTION_KINDS` member
- `configuration` status != `PASS`
- Parity broken between shadow and authoritative inventories
- Startup self-test failed
- Any pipeline exception counter > 0
- `behavior` status != `PASS` (INSUFFICIENT_SAMPLES also refuses)
- `confidence_tier` below `require_confidence` (default HIGH = ≥10 000 diffs)

Also set the fallback env explicitly (default is disabled; the
validator warns if it is unset in mode==on):

```bash
export VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK=off   # or on, chosen deliberately
```

## Rollback procedures

### Immediate rollback from ON to OFF

If v2 authoritative shows harmful behavior in production:

```bash
# In every worker's environment:
export VAULTAI_CHAT_BRAIN_MODE=off
# Restart workers.
```

There is no persistent v2-only state in the vault DB. Every write
v2 performs goes through the same V1 primitives (`save_secret_tool`,
`_execute_pending_delete`, `save_named_uploaded_asset`) — the DB
state is identical to what v1 would have produced. Redis-backed
v2 state (drafts, focus, authorization records) TTLs out on its
own (defaults: draft 300 s, focus 180 s, auth 60 s).

### Emergency v1 fallback from ON

If v2 is failing at pipeline stages but you don't want to flip to
OFF wholesale:

```bash
export VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK=on
```

This only takes effect for exceptions caught in the
`READ_ONLY` phase (snapshot / decider / policy / router). Once
integration has started (`INTEGRATION_STARTED` and later phases),
v1 fallback is refused regardless of the env, because state
mutation may already have landed and a second v1 pass could
duplicate the operation. This is enforced in code, not
documentation — see the phase-boundary tests in
`test_chat_brain_v2_2026_07_25.PhaseAwareFallbackTest`.

### Rollback from SHADOW to OFF

Trivial:

```bash
export VAULTAI_CHAT_BRAIN_MODE=off
# Restart workers.
```

Shadow mode never writes anything. No cleanup required.

### Revision-stamp rollback awareness

Historical shadow log records embed `v2_rev=<stamp>`. If a
layer's revision bumps between runs, older records still parse
under the older stamp — grep by `v2_rev=` when correlating
metrics across releases:

```
grep 'v2_rev=b1.p1.r1.s1.q1.i1' current.log     # records produced by revision 1
grep 'v2_rev=b2.p1.r1.s1.q1.i1' current.log     # records produced after brain-v2 bump
```

Bump only when the layer's observable behavior changes. See
`vault_chat_v2_versions.py` for the per-layer bump rules.

## Persistence footprint

v2 uses no new database tables. Every persistent record is
already governed by an existing store:

| v2 record | Backing store | TTL |
|---|---|---|
| `Draft` | `vault_chat_state_store` (Redis) | 300 s |
| `ConversationalFocus` | `vault_chat_state_store` (Redis) | 180 s |
| `AuthorizationRecord` | `vault_chat_state_store` (Redis) | 60 s |
| Shadow diff logs | stdout / stderr only | none |
| Shadow metrics | in-process memory only | until restart |

A worker restart clears all in-process metrics but preserves
Redis-backed state (until TTL). Shadow metrics are process-local
by design; if you need cross-worker aggregation, tee the
`[SHADOW_V2]` log lines to an external collector.

## Common pitfalls

1. **Do not set `VAULTAI_CHAT_BRAIN_MODE=on` before shadow has
   reached CONFIDENCE_HIGH.** The default readiness gate refuses
   this. Overriding with `require_confidence=MEDIUM` is
   dangerous — 100 to 1 000 diffs is too little sample for a
   production activation decision.

2. **Do not set `VAULTAI_CHAT_BRAIN_MODE=shadow` without also
   setting the fingerprint secret.** The validator errors, but
   the mode still runs — you'll get fingerprint-free diff
   records and rollout correlation will be broken.

3. **Do not modify `main.py` to activate v2.** The
   `_default_v2_executor_registry()` seam in
   `vault_chat_brain.py` is where the switch happens. Wire
   `build_production_executor_registry()` there when — and only
   when — the readiness gate has been ready for several days
   under real traffic.

4. **Never disable the phase-boundary refusal.** Even in an
   emergency, do NOT modify the `_FALLBACK_ELIGIBLE_PHASES` set
   in `vault_chat_brain_v2.py`. State mutation after integration
   starts is the point where fallback risks a duplicate
   operation.
