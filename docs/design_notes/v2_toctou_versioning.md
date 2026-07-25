# TOC/TOU: object-identity versioning (future enhancement)

Status: **future enhancement**, not required for phase 1 shadow
rollout.

## What the adapters check today (commit 6 + 6a)

Every executor adapter re-loads the live target immediately
before calling the underlying V1 primitive. The current identity
invariants are:

* **`vault_id` match** — the live target must belong to the same
  vault the caller authorized against.
* **`session_id` match** (soft) — the pending-action arbiter is
  session-scoped; passing `ctx.session_id` when re-reading
  surfaces a mid-request session change as absence.
* **`action_id` / `draft_id` match** — pending-action ids and
  draft ids are opaque UUID-scale strings that are never re-used
  across different intents. Same id implies same conceptual slot.
* **`kind` match** — pending actions carry a closed-set `kind`;
  the adapter refuses to proceed if the live pending's kind does
  not match the expected action kind (e.g. a delete pending
  showing up where a save was authorized).

## What is NOT yet checked

* **Object generation / version.** The current data model does
  not carry a monotonically-increasing `version` (or `updated_at`
  clock) on pending actions, delete intents, credential drafts,
  or upload bindings. If a live target were REPLACED between
  policy time and execution time — same id slot, different
  content — the identity check today would not catch it.

## Why this is safe for phase 1

The pending-action stores are effectively **append-only from the
caller's perspective**. Every mint of a fresh intent (delete
intent, credential draft, upload binding, secure-item draft)
generates a new opaque id. The same id is never re-used. So the
"same id slot, different content" case cannot happen in the
current architecture.

The one exception is the memory-backed login draft
(`memory["pending_login_draft"]`) which is a single fixed key.
Its `action_id` shape is `memlogin:<service>` and could
conceivably collide across sessions. The pending-action arbiter
scopes memory reads to the current session's `SavedDict`
instance, so cross-session collision is not possible in practice.

## Future work

When any of the underlying stores gains a versioned record type
(a `version` or `updated_at` column), extend the identity check
in `vault_chat_executor_adapters_v2._find_pending_by_id` and the
draft-loading adapters to verify:

```
live.version == plan.expected_version
```

Add `expected_version` to `ExecutionPlanV2` and thread it through
`AuthorizationIntent` so policy captures the version it observed.
Mismatch resolves to `RESULT_TARGET_STALE` (not
`AUTHORIZATION_CONTEXT_INVALID`) because the *authorization
context* is still valid — it is the *target itself* that has
changed.

Do not add a synthetic version field just for v2; wait for the
underlying store to gain one so we do not maintain a parallel
version tag.
