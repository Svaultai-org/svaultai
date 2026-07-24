"""Single-use, atomic-consume AuthorizationRecord for the chat-brain
v2 semantic reasoning path.

An ``AuthorizationRecord`` is minted by the policy layer when it
accepts a ``confirm_draft`` or ``confirm_pending_action``
decision. It is a small record separate from the Draft or
PendingAction; the router acquires it and atomically CAS-deletes
it before invoking any executor. That atomic step is the
non-replay guarantee: a duplicate HTTP retry (or a concurrent
worker) observes ``NoSuchAuth`` and does NOT execute a second
time.

Atomic-consume contract
-----------------------
The consume operation MUST validate target, action, session,
vault, expiry, and the required authorizing-turn binding
*within* the atomic operation. This module provides two
implementations that meet that contract:

    * Redis path: a Lua script (``_LUA_ATOMIC_CONSUME``) that
      reads the record, applies every validation branch, and
      deletes iff all validations pass — in one atomic Redis
      command from the client's perspective.

    * In-memory path: a module-level ``threading.Lock`` that
      wraps read-validate-delete for the in-memory backend
      used by tests. This simulates the same single-consumer
      semantics under concurrent test threads.

The path is selected automatically: if the backend has a
Redis-shaped ``_client`` attribute, the Lua path is used; else
the lock path is used. If the Lua path raises for any reason,
the code falls back to the lock path with a WARNING log.

Never exposes the plaintext of a consumed record to a caller
who did not pass every ``expected_*`` check.

Storage
-------
Redis-backed via ``vault_chat_state_store``. Bucket: ``auth``.
Default TTL: 60 s (``AUTH_TTL_SECONDS``).
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from vault_chat_state_store import compose_key, get_chat_state_backend


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Target kinds & actions (closed sets)
# -------------------------------------------------------------------

AUTH_TARGET_DRAFT:          str = "draft"
AUTH_TARGET_PENDING_ACTION: str = "pending_action"

AUTH_TARGETS: frozenset[str] = frozenset({
    AUTH_TARGET_DRAFT, AUTH_TARGET_PENDING_ACTION,
})


AUTH_ACTION_SAVE:            str = "save"
AUTH_ACTION_DELETE:          str = "delete"
AUTH_ACTION_SAVE_ATTACHMENT: str = "save_attachment"

AUTH_ACTIONS: frozenset[str] = frozenset({
    AUTH_ACTION_SAVE, AUTH_ACTION_DELETE, AUTH_ACTION_SAVE_ATTACHMENT,
})

# Action-target compatibility (rule 9 of design memo §6).
_COMPATIBLE_TARGET_KINDS: dict[str, frozenset[str]] = {
    AUTH_ACTION_SAVE:            frozenset({AUTH_TARGET_DRAFT, AUTH_TARGET_PENDING_ACTION}),
    AUTH_ACTION_DELETE:          frozenset({AUTH_TARGET_PENDING_ACTION}),
    AUTH_ACTION_SAVE_ATTACHMENT: frozenset({AUTH_TARGET_PENDING_ACTION}),
}


def is_action_compatible_with_target(
    action: str, target_kind: str,
) -> bool:
    return target_kind in _COMPATIBLE_TARGET_KINDS.get(action, frozenset())


# -------------------------------------------------------------------
# Consume-result reasons (closed set)
# -------------------------------------------------------------------

REASON_CONSUMED:            str = "consumed"
REASON_NOT_FOUND:           str = "not_found"
REASON_MALFORMED:           str = "malformed"
REASON_EXPIRED:             str = "expired"
REASON_VAULT_MISMATCH:      str = "vault_mismatch"
REASON_SESSION_MISMATCH:    str = "session_mismatch"
REASON_TARGET_KIND_MISMATCH: str = "target_kind_mismatch"
REASON_TARGET_ID_MISMATCH:  str = "target_id_mismatch"
REASON_ACTION_MISMATCH:     str = "action_mismatch"
REASON_TURN_MISMATCH:       str = "turn_mismatch"
REASON_BACKEND_ERROR:       str = "backend_error"

CONSUME_REASONS: frozenset[str] = frozenset({
    REASON_CONSUMED, REASON_NOT_FOUND, REASON_MALFORMED, REASON_EXPIRED,
    REASON_VAULT_MISMATCH, REASON_SESSION_MISMATCH,
    REASON_TARGET_KIND_MISMATCH, REASON_TARGET_ID_MISMATCH,
    REASON_ACTION_MISMATCH, REASON_TURN_MISMATCH,
    REASON_BACKEND_ERROR,
})


# -------------------------------------------------------------------
# TTL
# -------------------------------------------------------------------

AUTH_TTL_SECONDS: int = 60


# -------------------------------------------------------------------
# Payload schema version — strict discipline per design memo rev 4.
# Redis JSON payloads MUST carry this exact version; deserializers
# (both the Python from_json and the Lua atomic-consume script)
# reject any other value. Bumping this constant requires an
# explicit forward-migration path (or dropping in-flight
# authorization records — acceptable, they are single-use with
# 60s TTL).
# -------------------------------------------------------------------

AUTH_SCHEMA_VERSION: int = 1


# -------------------------------------------------------------------
# Dataclasses
# -------------------------------------------------------------------

@dataclass(frozen=True)
class AuthorizationRecord:
    auth_id:                        str
    vault_id:                       str
    session_id:                     Optional[str]
    target_kind:                    str
    target_id:                      str
    action:                         str
    authorizing_user_turn_id:       str
    preceding_assistant_turn_id:    str
    confidence:                     float
    created_at:                     float
    expires_at:                     float
    schema_version:                 int = 1

    def __post_init__(self) -> None:
        if self.schema_version != AUTH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported authorization_record schema_version "
                f"{self.schema_version!r}"
            )
        if not self.auth_id:
            raise ValueError("auth_id required")
        if not self.vault_id:
            raise ValueError("vault_id required")
        if self.target_kind not in AUTH_TARGETS:
            raise ValueError(f"unknown target_kind {self.target_kind!r}")
        if not self.target_id:
            raise ValueError("target_id required")
        if self.action not in AUTH_ACTIONS:
            raise ValueError(f"unknown action {self.action!r}")
        if not is_action_compatible_with_target(self.action, self.target_kind):
            raise ValueError(
                f"action {self.action!r} is not compatible with "
                f"target_kind {self.target_kind!r}"
            )
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if not isinstance(self.authorizing_user_turn_id, str):
            raise TypeError("authorizing_user_turn_id must be a string")
        if not isinstance(self.preceding_assistant_turn_id, str):
            raise TypeError("preceding_assistant_turn_id must be a string")

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def to_json(self) -> str:
        return json.dumps({
            "schema_version":              self.schema_version,
            "auth_id":                     self.auth_id,
            "vault_id":                    self.vault_id,
            "session_id":                  self.session_id or "",
            "target_kind":                 self.target_kind,
            "target_id":                   self.target_id,
            "action":                      self.action,
            "authorizing_user_turn_id":    self.authorizing_user_turn_id,
            "preceding_assistant_turn_id": self.preceding_assistant_turn_id,
            "confidence":                  self.confidence,
            "created_at":                  self.created_at,
            "expires_at":                  self.expires_at,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "AuthorizationRecord":
        p = json.loads(raw)
        # Strict schema-version discipline (design memo rev 4).
        sv = p.get("schema_version")
        if sv != AUTH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported authorization_record schema_version {sv!r}"
            )
        sess = p.get("session_id")
        if sess == "":
            sess = None
        return cls(
            auth_id=str(p["auth_id"]),
            vault_id=str(p["vault_id"]),
            session_id=sess,
            target_kind=str(p["target_kind"]),
            target_id=str(p["target_id"]),
            action=str(p["action"]),
            authorizing_user_turn_id=str(p["authorizing_user_turn_id"]),
            preceding_assistant_turn_id=str(p["preceding_assistant_turn_id"]),
            confidence=float(p["confidence"]),
            created_at=float(p["created_at"]),
            expires_at=float(p["expires_at"]),
            schema_version=int(sv),
        )


@dataclass(frozen=True)
class ConsumeResult:
    consumed: bool
    reason:   str
    record:   Optional[AuthorizationRecord] = None

    def __post_init__(self) -> None:
        if self.reason not in CONSUME_REASONS:
            raise ValueError(f"unknown reason {self.reason!r}")
        if self.consumed and self.reason != REASON_CONSUMED:
            raise ValueError(
                "ConsumeResult(consumed=True) requires reason=consumed"
            )
        if not self.consumed and self.reason == REASON_CONSUMED:
            raise ValueError(
                "reason=consumed requires consumed=True"
            )


# -------------------------------------------------------------------
# ID / mint
# -------------------------------------------------------------------

def new_auth_id() -> str:
    return secrets.token_hex(16)


def mint_authorization(
    *,
    vault_id:                       str,
    session_id:                     Optional[str],
    target_kind:                    str,
    target_id:                      str,
    action:                         str,
    authorizing_user_turn_id:       str,
    preceding_assistant_turn_id:    str,
    confidence:                     float,
    ttl_seconds:                    Optional[int] = None,
    now:                            Optional[float] = None,
    auth_id:                        Optional[str] = None,
) -> AuthorizationRecord:
    """Mint an AuthorizationRecord and persist it.

    Return the record. The caller must present all
    ``expected_*`` values back to ``atomic_consume_authorization``
    to spend it.
    """
    when = float(now) if now is not None else time.time()
    ttl = int(ttl_seconds if ttl_seconds is not None else AUTH_TTL_SECONDS)
    record = AuthorizationRecord(
        auth_id=auth_id or new_auth_id(),
        vault_id=vault_id,
        session_id=session_id,
        target_kind=target_kind,
        target_id=target_id,
        action=action,
        authorizing_user_turn_id=authorizing_user_turn_id,
        preceding_assistant_turn_id=preceding_assistant_turn_id,
        confidence=confidence,
        created_at=when,
        expires_at=when + ttl,
    )
    backend = get_chat_state_backend()
    backend.set(
        _auth_key(vault_id, record.auth_id),
        record.to_json().encode("utf-8"),
        max(1, ttl),
    )
    return record


# -------------------------------------------------------------------
# Read (non-consuming) — for logging/debug only
# -------------------------------------------------------------------

def read_authorization(
    *, auth_id: str, vault_id: str,
    now: Optional[float] = None,
) -> Optional[AuthorizationRecord]:
    """Non-consuming read.

    Callers must NEVER treat a successful read as authorization —
    only ``atomic_consume_authorization`` grants that. This is
    exposed for observability and for the router's pre-consume
    logging path.
    """
    if not auth_id or not vault_id:
        return None
    backend = get_chat_state_backend()
    try:
        raw = backend.get(_auth_key(vault_id, auth_id))
    except Exception:
        logger.exception(
            "[AUTH] read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if not raw:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        record = AuthorizationRecord.from_json(text)
    except Exception:
        logger.warning(
            "[AUTH] read_deserialize_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if record.is_expired(now):
        return None
    return record


# -------------------------------------------------------------------
# Atomic consume — the load-bearing security primitive
# -------------------------------------------------------------------

# Module-level lock used by the in-memory fallback. Redis-backed
# deployments never touch this — the Lua script provides its own
# atomicity. Tests using InMemoryChatStateBackend hit this lock.
_ATOMIC_LOCK = threading.Lock()


# The Lua script that implements read-validate-delete atomically
# for Redis. The script returns a two-element table
# [reason_string, raw_json_or_empty]. On REASON_CONSUMED the
# record is deleted; on REASON_EXPIRED the record is also
# deleted (so subsequent reads never see it); on validation
# failures the record is NOT deleted (a legitimate authorized
# consumer should still be able to claim it if they present
# correct expected_* values).
_LUA_ATOMIC_CONSUME: str = r"""
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expected_vault    = ARGV[2]
local expected_session  = ARGV[3]
local expected_t_kind   = ARGV[4]
local expected_t_id     = ARGV[5]
local expected_action   = ARGV[6]
local expected_turn     = ARGV[7]

local raw = redis.call('GET', key)
if not raw then
    return {'not_found', ''}
end

local ok, record = pcall(cjson.decode, raw)
if not ok or type(record) ~= 'table' then
    return {'malformed', raw}
end

-- Strict schema-version discipline: refuse (without consuming)
-- any record whose version we do not understand. See design memo
-- rev 4. The specific version constant is passed as ARGV[8] so
-- Python and Lua stay in sync automatically.
if tonumber(record.schema_version) ~= tonumber(ARGV[8]) then
    return {'malformed', raw}
end

if tonumber(record.expires_at) == nil then
    return {'malformed', raw}
end
if tonumber(record.expires_at) <= now then
    redis.call('DEL', key)
    return {'expired', raw}
end

if record.vault_id ~= expected_vault then
    return {'vault_mismatch', raw}
end

local rec_session = record.session_id
if rec_session == nil or rec_session == cjson.null then
    rec_session = ''
end
if rec_session ~= expected_session then
    return {'session_mismatch', raw}
end

if record.target_kind ~= expected_t_kind then
    return {'target_kind_mismatch', raw}
end
if record.target_id ~= expected_t_id then
    return {'target_id_mismatch', raw}
end
if record.action ~= expected_action then
    return {'action_mismatch', raw}
end
if record.authorizing_user_turn_id ~= expected_turn then
    return {'turn_mismatch', raw}
end

redis.call('DEL', key)
return {'consumed', raw}
"""


def atomic_consume_authorization(
    *,
    auth_id:                        str,
    expected_vault_id:              str,
    expected_session_id:            Optional[str],
    expected_target_kind:           str,
    expected_target_id:             str,
    expected_action:                str,
    expected_authorizing_user_turn_id: str,
    now:                            Optional[float] = None,
) -> ConsumeResult:
    """Atomically read, validate, and delete an AuthorizationRecord.

    All validation happens *inside* the atomic operation:
    target_kind, target_id, action, session_id, vault_id,
    expires_at, and authorizing_user_turn_id. Returns a
    ``ConsumeResult`` naming the outcome.

    Concurrency: on Redis, the Lua script runs as a single
    atomic command from the client's perspective. On the
    in-memory backend used by tests, a module-level
    ``threading.Lock`` serializes concurrent consumers.
    """
    if not auth_id or not expected_vault_id:
        return ConsumeResult(consumed=False, reason=REASON_NOT_FOUND)
    when = float(now) if now is not None else time.time()
    backend = get_chat_state_backend()
    key = _auth_key(expected_vault_id, auth_id)
    session_str = expected_session_id if expected_session_id is not None else ""

    # Try Lua fast path.
    client = getattr(backend, "_client", None)
    if client is not None and hasattr(client, "eval"):
        try:
            return _consume_via_lua(
                client, key, when,
                expected_vault_id, session_str,
                expected_target_kind, expected_target_id,
                expected_action, expected_authorizing_user_turn_id,
            )
        except Exception:
            logger.exception(
                "[AUTH] lua_consume_failed_falling_back auth=%s",
                _short(auth_id),
            )
            # fall through to the lock path

    return _consume_via_lock(
        backend, key, when,
        expected_vault_id, session_str,
        expected_target_kind, expected_target_id,
        expected_action, expected_authorizing_user_turn_id,
    )


def _consume_via_lua(
    client: Any,
    key: str,
    now: float,
    expected_vault_id: str,
    expected_session_id: str,
    expected_target_kind: str,
    expected_target_id: str,
    expected_action: str,
    expected_turn: str,
) -> ConsumeResult:
    result = client.eval(
        _LUA_ATOMIC_CONSUME,
        1,
        key,
        str(now),
        expected_vault_id,
        expected_session_id,
        expected_target_kind,
        expected_target_id,
        expected_action,
        expected_turn,
        str(AUTH_SCHEMA_VERSION),
    )
    reason_raw = result[0] if result else b""
    raw_value  = result[1] if len(result) > 1 else b""
    reason = _decode(reason_raw)
    if reason == REASON_CONSUMED:
        try:
            record = AuthorizationRecord.from_json(_decode(raw_value))
        except Exception:
            logger.exception("[AUTH] consumed_but_parse_failed")
            return ConsumeResult(
                consumed=False, reason=REASON_MALFORMED,
            )
        return ConsumeResult(
            consumed=True, reason=REASON_CONSUMED, record=record,
        )
    if reason not in CONSUME_REASONS:
        logger.warning("[AUTH] unknown_lua_reason=%r", reason)
        return ConsumeResult(consumed=False, reason=REASON_BACKEND_ERROR)
    return ConsumeResult(consumed=False, reason=reason)


def _consume_via_lock(
    backend: Any,
    key: str,
    now: float,
    expected_vault_id: str,
    expected_session_id: str,
    expected_target_kind: str,
    expected_target_id: str,
    expected_action: str,
    expected_turn: str,
) -> ConsumeResult:
    """In-memory fallback. The lock guards the entire
    read-validate-delete sequence.
    """
    with _ATOMIC_LOCK:
        try:
            raw = backend.get(key)
        except Exception:
            logger.exception("[AUTH] lock_get_failed")
            return ConsumeResult(consumed=False, reason=REASON_BACKEND_ERROR)
        if not raw:
            return ConsumeResult(consumed=False, reason=REASON_NOT_FOUND)
        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            record = AuthorizationRecord.from_json(text)
        except Exception:
            logger.warning("[AUTH] lock_parse_failed")
            return ConsumeResult(consumed=False, reason=REASON_MALFORMED)
        if record.is_expired(now):
            try:
                backend.delete(key)
            except Exception:
                logger.exception("[AUTH] expired_delete_failed")
            return ConsumeResult(consumed=False, reason=REASON_EXPIRED)
        if record.vault_id != expected_vault_id:
            return ConsumeResult(consumed=False, reason=REASON_VAULT_MISMATCH)
        rec_session = record.session_id or ""
        if rec_session != expected_session_id:
            return ConsumeResult(consumed=False, reason=REASON_SESSION_MISMATCH)
        if record.target_kind != expected_target_kind:
            return ConsumeResult(consumed=False, reason=REASON_TARGET_KIND_MISMATCH)
        if record.target_id != expected_target_id:
            return ConsumeResult(consumed=False, reason=REASON_TARGET_ID_MISMATCH)
        if record.action != expected_action:
            return ConsumeResult(consumed=False, reason=REASON_ACTION_MISMATCH)
        if record.authorizing_user_turn_id != expected_turn:
            return ConsumeResult(consumed=False, reason=REASON_TURN_MISMATCH)
        try:
            backend.delete(key)
        except Exception:
            logger.exception("[AUTH] delete_failed_after_validation")
            return ConsumeResult(consumed=False, reason=REASON_BACKEND_ERROR)
        return ConsumeResult(
            consumed=True, reason=REASON_CONSUMED, record=record,
        )


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

_BUCKET: str = "auth"


def _auth_key(vault_id: str, auth_id: str) -> str:
    return compose_key(bucket=_BUCKET, vault_id=vault_id, sub=auth_id)


def _decode(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:
            return ""
    if isinstance(value, str):
        return value
    return ""


def _short(s: str) -> str:
    return (s or "")[:8] + "…"


__all__ = [
    "AUTH_TARGET_DRAFT",
    "AUTH_TARGET_PENDING_ACTION",
    "AUTH_TARGETS",
    "AUTH_ACTION_SAVE",
    "AUTH_ACTION_DELETE",
    "AUTH_ACTION_SAVE_ATTACHMENT",
    "AUTH_ACTIONS",
    "AUTH_TTL_SECONDS",
    "AUTH_SCHEMA_VERSION",
    "REASON_CONSUMED",
    "REASON_NOT_FOUND",
    "REASON_MALFORMED",
    "REASON_EXPIRED",
    "REASON_VAULT_MISMATCH",
    "REASON_SESSION_MISMATCH",
    "REASON_TARGET_KIND_MISMATCH",
    "REASON_TARGET_ID_MISMATCH",
    "REASON_ACTION_MISMATCH",
    "REASON_TURN_MISMATCH",
    "REASON_BACKEND_ERROR",
    "CONSUME_REASONS",
    "AuthorizationRecord",
    "ConsumeResult",
    "is_action_compatible_with_target",
    "new_auth_id",
    "mint_authorization",
    "read_authorization",
    "atomic_consume_authorization",
]
