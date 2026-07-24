# Held Generated Login Passwords — Phase 1 Posture

**Baseline:** commit `e54be1fc6c0f382a7a3451af6987e59fb833c9c9` (Bug C in production).
**Purpose:** describe, factually, how the chat pipeline currently holds a generated login password between the moment the assistant proposes it and the moment the user confirms or cancels the save; and record that phase 1 of the chat-brain semantic-reasoning redesign does not change any of that.
**Non-purpose:** this note is not a change proposal, a threat model, an incident report, or a remediation plan. It documents the pre-existing state so subsequent redesign work has a shared baseline. Remediation is proposed as a separate, later memo (see §7).
**Redaction:** this document contains no passwords, credentials, hostnames, tokens, or any user-identifying value. Line-number references point at the code they describe.

---

## 1. Where the password comes from

The generated login workflow lives in `vault_ai_backend/main.py`, in the `generate_login` branch of the chat handler. Inside that branch, the password is produced in-process by:

- `main.generate_strong_password()` — invoked around `main.py:15015` when the branch has decided to propose a fresh generated password (as opposed to reusing a value already present in the vault).

The generated value is a Python `str` living on the branch's local frame at that point.

---

## 2. Where the password is stored

The branch writes the entire draft (service, username option(s), the generated password, and a small envelope of metadata) into per-vault chat memory:

- Write site: `main.py:15108` — assigns `memory["pending_login_draft"] = {"service": ..., "username_options": ..., "password": <generated>, "policy_email_required": ..., "has_existing_username": ..., "has_existing_email": ..., "existing_username": ..., "existing_email": ..., "ts": <epoch>}`.
- `memory` is a `SavedDict` returned by `vault_chat_memory.get_memory(vault_id)` at [vault_chat_memory.py:279](../../vault_ai_backend/vault_chat_memory.py). `SavedDict` is a subclass of `dict` defined at [vault_chat_memory.py:96](../../vault_ai_backend/vault_chat_memory.py).
- Every mutation on `SavedDict` flushes the *whole* dict payload to the shared state backend via `SavedDict.__setitem__ → _flush()` at [vault_chat_memory.py:140-142](../../vault_ai_backend/vault_chat_memory.py). Under production configuration the backend is `RedisSharedStateBackend` from `vault_chat_state_store`; other environments may use the in-memory backend.
- Serialization is `json.dumps(payload, ensure_ascii=False).encode("utf-8")` at [vault_chat_memory.py:77](../../vault_ai_backend/vault_chat_memory.py). No application-layer encryption is applied to this payload.

Net effect: the generated login password is present, in plaintext, inside the JSON blob that `SavedDict` flushes to Redis on the write at `main.py:15108`.

---

## 3. Redis key family

The shared-state key composition lives in `vault_ai_backend/vault_chat_state_store.py`:

- Bucket: `chat_memory` (set at [vault_chat_memory.py:65](../../vault_ai_backend/vault_chat_memory.py)).
- Composed key: `chatst:v1:chat_memory:<sha16(vault_id)>`, produced by `compose_key(bucket=..., vault_id=...)` at [vault_chat_state_store.py:91](../../vault_ai_backend/vault_chat_state_store.py). `<sha16(vault_id)>` is the first 16 hex characters of a SHA-256 of the vault id (plus a fixed namespace prefix).
- The vault id is hashed for keying, so a Redis operator cannot enumerate vaults by scanning the key namespace directly. However, if the operator knows a specific `vault_id`, computing the corresponding key is trivial (`compose_key` is deterministic and publicly derivable from the code).
- The Redis payload is the plain JSON blob described in §2. It is not encrypted at the application layer. Any encryption-at-rest properties depend on the Redis deployment's own configuration and are outside the application's control.

---

## 4. TTL

- The chat-memory TTL is `CHAT_MEMORY_TTL_SECONDS`, environment-configurable, default **3600 seconds (1 hour)**, set at [vault_chat_memory.py:61](../../vault_ai_backend/vault_chat_memory.py).
- The TTL is applied per-key on every `SavedDict._flush()`, i.e. every mutation refreshes the TTL for the whole `chat_memory` record for that vault. Adjacent chat activity therefore extends the window during which any *previously-written* `pending_login_draft` (and its plaintext password field) remains resident.
- There is no field-level TTL: the plaintext password shares the same TTL as unrelated chat-memory fields such as `last_service`, `pending_action` (a string sentinel used by other flows), or `pending_field`.

---

## 5. Erase paths

### 5.1 Existing erase paths

The following code paths remove the `pending_login_draft` entry (and therefore the plaintext password field inside it) from chat memory:

1. **Successful save via the brain-band router.** `_confirm_save_login_draft` in [vault_chat_decision_router.py](../../vault_ai_backend/vault_chat_decision_router.py) calls `_memory_clear(memory, "pending_login_draft")` after `save_secret_tool` returns success. The dict slot is popped; the `SavedDict._flush()` writes the reduced payload to Redis.
2. **Successful save via the legacy save cascade.** `main.py:13511` and `main.py:13592` similarly `memory.pop("pending_login_draft", None)` after a successful save through the legacy path.
3. **Explicit cancel via the brain-band router.** `_cancel_pending_save` in `vault_chat_decision_router.py` pops the same key when the router sees a cancel decision that matches the login-draft action id.
4. **TTL expiry.** After `CHAT_MEMORY_TTL_SECONDS` of key inactivity, Redis expires the entire `chat_memory` record for the vault. The plaintext password disappears with it. Because §4 notes that adjacent chat activity refreshes the TTL, expiry is not guaranteed within any fixed wall-clock window shorter than the last-mutation timestamp + TTL.

### 5.2 Missing or weak erase paths

The following gaps are present in the current code:

1. **No explicit wipe on draft replacement.** If a subsequent `generate_login` turn overwrites `memory["pending_login_draft"]` with a fresh dict, the previous password value is replaced in place. This is not a lingering-copy leak (the old dict is garbage-collected in-process, and the Redis blob is replaced), but the *new* password now inherits the same TTL and same store; there is no explicit "old draft wiped" signal.
2. **No wipe on session logout.** `chat_memory` is keyed by `vault_id`, not by `session_id`. Ending a session does not remove the `chat_memory` record. A `pending_login_draft` created in the ended session remains readable to any subsequent session on the same vault until it is consumed, cancelled, or expires.
3. **No wipe on chat-brain error paths.** If the brain runs, presents the draft, and then a subsequent turn crashes before the router reaches consume or cancel, the `pending_login_draft` — including the password — lingers for the full remaining TTL.
4. **No wipe on user abandonment.** If the user simply stops replying, the `pending_login_draft` is not proactively pruned; it survives until TTL expiry.
5. **No process-memory scrubbing.** Python `str` values are immutable and released to the garbage collector without an explicit zeroing step. This is a Python language property, not a defect specific to this code, but is noted here because a `bytearray`-based secret holder would allow explicit overwrite prior to release.
6. **Payload width.** The full `pending_login_draft` dict is flushed on every mutation to any *other* key in the `SavedDict` (because `SavedDict._flush` serializes the whole dict). The plaintext password therefore travels the write path on unrelated chat-memory writes for the same vault while the draft is live. This does not enlarge the exposure surface at rest (same key, same TTL), but it does mean the plaintext password crosses the app-Redis link more often than the number of `pending_login_draft` writes suggests.

---

## 6. Redaction posture (what the password does *not* appear in)

For completeness, the code paths that were checked to confirm the plaintext password is *not* exposed elsewhere:

- **Application logs.** `main.generate_login` logs a small set of scalars (service, boolean flags, counts). The password itself is not passed to a logger. This was confirmed by inspecting the `logger.info` / `logger.warning` calls in the branch at commit `e54be1f`.
- **Semantic-decider prompt.** `PendingAction.to_prompt_dict()` at [vault_chat_pending_action.py:127](../../vault_ai_backend/vault_chat_pending_action.py) does not include a `password` key; it exposes only `action_id`, `kind`, `target_label`, `is_destructive`, and `age_seconds`. The decider therefore never sees the password.
- **Turn snapshot.** `TurnSnapshot.to_prompt_dict()` uses the same `PendingAction.to_prompt_dict()` view; no other snapshot field carries the password.
- **HTTP responses.** After a successful save, `save_secret_tool` returns a reply that references the login but does not include the password value. The plaintext password is not sent back to the client on the confirm turn (the user already saw it on the propose turn, when the assistant rendered the draft text).

The one place the plaintext password *does* appear is inside the JSON blob at `chatst:v1:chat_memory:<sha16(vault_id)>`, for the duration described in §4.

---

## 7. Phase 1 posture

The phase 1 redesign (chat-brain semantic-reasoning v2, tracked separately in the design memo) does not change any behavior described in §1 through §6.

Specifically, in phase 1:

- No new Redis bucket or key family is introduced for the generated login password.
- The new first-class `Draft` record introduced in phase 1 holds only an opaque `password_ref` string that points at `memory:pending_login_draft:password` — the same slot that today's code already writes and today's `_confirm_save_login_draft` already consumes. The Draft record itself never contains the plaintext.
- Consume and cancel paths in the phase 1 router continue to `memory.pop("pending_login_draft", None)` — the same wipe behavior as today.
- Shadow-mode evaluation (a phase 1 rollout mechanism) is constrained by contract to perform zero writes; it does not create, touch, refresh, or copy the `pending_login_draft` key.
- The phase 1 design deliberately does not attempt to shorten the 1-hour default TTL, encrypt the payload at the application layer, or add erase paths for session logout or brain-band failure.

Phase 1 is therefore neutral with respect to the storage posture described here. It does not improve it and it does not regress it.

---

## 8. Proposed follow-up (phase 2, separate memo)

The plaintext-password-in-Redis exposure described in §2 through §5 warrants a purpose-built secret-holding mechanism. That work is proposed as a separate memo, out of scope for the phase 1 redesign. A phase 2 design should cover at minimum:

- Application-layer encryption of held generated secrets under a vault-derived key or per-session ephemeral key, so a Redis operator cannot recover the plaintext without additional material outside Redis.
- A short TTL matched to the actual save window (for example, on the order of tens of seconds after `PRESENTED_FOR_CONFIRMATION` from the phase 1 lifecycle), decoupled from the general 1-hour chat-memory TTL.
- Explicit, atomic erase on each of: consume, cancel, replacement, expiry, session logout, brain-band failure. The failure-mode wipe is the largest gap called out in §5.2.
- Explicit exclusion from prompts, snapshots, shadow diffs, telemetry, and process-level exposure beyond the immediate use site.
- Failure-mode design for backend degradation (Redis unavailable or errored) that fails toward re-generation rather than toward serving stale material.

This document does not commit the project to any specific mechanism; it only records that the current mechanism is chat memory that happens to hold a secret, that phase 1 preserves this, and that a proper mechanism deserves its own design cycle.

---

## Appendix A — Baseline & scope

- This note describes the state of `vault_ai_backend/` at commit `e54be1fc6c0f382a7a3451af6987e59fb833c9c9` (Bug C in production, current baseline for the semantic-reasoning redesign).
- It does not reference commit `c752ca9b2d3472c4b0ec19c920c6a706d9b35a4b` (Bug B, local-only, unpushed) — Bug B does not change any of the storage or erase behavior described here.
- No production behavior is being changed by this document. It is documentation only.
