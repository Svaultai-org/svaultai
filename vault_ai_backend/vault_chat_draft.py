"""First-class Draft state for the chat-brain v2 semantic reasoning path.

A ``Draft`` is a tentative artifact the assistant is helping the
user build across multiple turns (currently: only login drafts).
Distinct from ``PendingAction``:

    * A ``Draft`` is editable — subsequent turns can patch
      individual fields via a merge operation
      (``vault_chat_draft_merge.merge``).
    * A ``PendingAction`` is a proposed sensitive operation that
      surfaces to the arbiter after a Draft transitions to
      ``STATUS_PRESENTED_FOR_CONFIRMATION``.

Phase 1 scope
-------------
Only ``DRAFT_LOGIN`` is implemented. Other draft kinds are
deliberately not supported yet; adding them requires (a)
declaring a closed field schema and (b) tests for the new kind.

Per-field provenance
--------------------
Every field carries a ``DraftField(value, source, turn_id, at)``.
The merge function uses ``source`` (SOURCE_USER_EXPLICIT >
SOURCE_VAULT_LOOKUP > SOURCE_INFERRED > SOURCE_GENERATED) plus
turn ordering to determine which value survives a patch. The
merge rules themselves live in ``vault_chat_draft_merge``.

Secret-holding boundary
-----------------------
A ``Draft`` NEVER contains a plaintext password, token, or other
raw secret. Login drafts carry a ``password_ref`` — an opaque
handle whose format-validator rejects strings that could
plausibly be a raw password. The plaintext generated password
lives elsewhere (see docs/design_notes/held_secrets_phase1.md);
the Draft only points at it.

Field states (four-way, deliberately distinguished)
---------------------------------------------------
    * absent              — field key not in ``Draft.fields``
    * present             — DraftField with a real value
    * cleared             — DraftField with value == CLEARED
    * requested-generate  — DraftField with value == PENDING_GENERATION

``None`` is never a legal value; if a field is unset the key is
absent from the mapping entirely.

Storage
-------
Redis-backed via ``vault_chat_state_store``. Bucket: ``draft``.
Default TTL: 600 s (`DRAFT_TTL_SECONDS`), refreshed on every
meaningful mutation (create, edit-patch, explicit confirm/cancel).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping, Optional

from vault_chat_state_store import (
    compose_key,
    compose_index_key,
    get_chat_state_backend,
)


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Draft kinds (closed set — phase 1 supports only DRAFT_LOGIN)
# -------------------------------------------------------------------

DRAFT_LOGIN: str = "login"

DRAFT_KINDS: frozenset[str] = frozenset({DRAFT_LOGIN})


# -------------------------------------------------------------------
# Lifecycle statuses
# -------------------------------------------------------------------

STATUS_EDITABLE:                  str = "editable"
STATUS_PRESENTED_FOR_CONFIRMATION: str = "presented_for_confirmation"
STATUS_AUTHORIZED_ONCE:           str = "authorized_once"
STATUS_EXECUTING:                 str = "executing"
STATUS_CONSUMED:                  str = "consumed"
STATUS_CANCELLED:                 str = "cancelled"

DRAFT_STATUSES: frozenset[str] = frozenset({
    STATUS_EDITABLE,
    STATUS_PRESENTED_FOR_CONFIRMATION,
    STATUS_AUTHORIZED_ONCE,
    STATUS_EXECUTING,
    STATUS_CONSUMED,
    STATUS_CANCELLED,
})

_LIVE_STATUSES: frozenset[str] = frozenset({
    STATUS_EDITABLE,
    STATUS_PRESENTED_FOR_CONFIRMATION,
    STATUS_AUTHORIZED_ONCE,
    STATUS_EXECUTING,
})


# -------------------------------------------------------------------
# Field-value provenance
# -------------------------------------------------------------------

SOURCE_USER_EXPLICIT: str = "user_explicit"
SOURCE_VAULT_LOOKUP:  str = "vault_lookup"
SOURCE_INFERRED:      str = "inferred"
SOURCE_GENERATED:     str = "generated"

FIELD_SOURCES: frozenset[str] = frozenset({
    SOURCE_USER_EXPLICIT,
    SOURCE_VAULT_LOOKUP,
    SOURCE_INFERRED,
    SOURCE_GENERATED,
})

# Higher wins (used by merge as a residual tiebreaker; see
# vault_chat_draft_merge for the full rule set).
FIELD_SOURCE_PRIORITY: Mapping[str, int] = MappingProxyType({
    SOURCE_USER_EXPLICIT: 4,
    SOURCE_VAULT_LOOKUP:  3,
    SOURCE_INFERRED:      2,
    SOURCE_GENERATED:     1,
})


# -------------------------------------------------------------------
# Field-state sentinels
# -------------------------------------------------------------------

# String markers so they survive JSON round-trip. Chosen with
# distinctive prefixes so they cannot collide with user text or
# with any valid opaque_ref pattern.
CLEARED:             str = "__CLEARED__"
PENDING_GENERATION:  str = "__PENDING_GENERATION__"


# -------------------------------------------------------------------
# Patch ops (used by merge)
# -------------------------------------------------------------------

OP_REPLACE:    str = "replace"
OP_CLEAR:      str = "clear"
OP_REGENERATE: str = "regenerate"
OP_UNCHANGED:  str = "unchanged"

PATCH_OPS: frozenset[str] = frozenset({
    OP_REPLACE, OP_CLEAR, OP_REGENERATE, OP_UNCHANGED,
})


# -------------------------------------------------------------------
# TTL
# -------------------------------------------------------------------

DRAFT_TTL_SECONDS: int = 600


# -------------------------------------------------------------------
# Field-format validators
# -------------------------------------------------------------------

_SERVICE_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9 ._+\-]{0,127}$"
)

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62})"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}))+$"
)

_HANDLE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$"
)

_OPAQUE_REF_RE = re.compile(
    r"^[a-z][a-z_0-9]{1,32}(?::[a-z][a-z_0-9]{0,32}){1,3}$"
)

_URL_RE = re.compile(
    r"^https?://[A-Za-z0-9._\-]{1,253}(?::[0-9]{1,5})?(?:/[^\s]{0,2000})?$"
)


class FieldFormatError(ValueError):
    """Raised when a field value fails its format check."""


def _validate_service_name(value: str) -> str:
    if not isinstance(value, str):
        raise FieldFormatError("service must be a string")
    stripped = value.strip()
    if not _SERVICE_NAME_RE.match(stripped):
        raise FieldFormatError("invalid service name format")
    return stripped


def _validate_email_or_handle(value: str) -> str:
    if not isinstance(value, str):
        raise FieldFormatError("username must be a string")
    stripped = value.strip()
    if _EMAIL_RE.match(stripped):
        return stripped
    if _HANDLE_RE.match(stripped):
        return stripped
    raise FieldFormatError("invalid username format")


def _validate_opaque_ref(value: str) -> str:
    """Reject raw passwords being stored as a ``password_ref``.

    An opaque reference is a colon-delimited identifier path like
    ``memory:pending_login_draft:password``. Anything with
    whitespace, mixed case, punctuation-heavy content, or leading
    digits is refused."""
    if not isinstance(value, str):
        raise FieldFormatError("password_ref must be a string")
    if not _OPAQUE_REF_RE.match(value):
        raise FieldFormatError(
            "password_ref must be a colon-delimited lowercase "
            "identifier path (e.g. 'memory:pending_login_draft:password')"
        )
    return value


def _validate_url(value: str) -> str:
    if not isinstance(value, str):
        raise FieldFormatError("url must be a string")
    stripped = value.strip()
    if not _URL_RE.match(stripped):
        raise FieldFormatError("invalid url format")
    return stripped


def _validate_free_text(value: str, *, max_len: int) -> str:
    if not isinstance(value, str):
        raise FieldFormatError("value must be a string")
    if "\x00" in value:
        raise FieldFormatError("value contains null byte")
    if len(value) > max_len:
        raise FieldFormatError(f"value longer than {max_len} chars")
    return value


# -------------------------------------------------------------------
# Field schemas — closed per draft_kind
# -------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    name:         str
    required:     bool
    max_len:      int
    formatter:    Any                # Callable[[str], str]
    allows_regenerate: bool = False


_LOGIN_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("service",      required=True,  max_len=128,
              formatter=_validate_service_name),
    FieldSpec("username",     required=True,  max_len=320,
              formatter=_validate_email_or_handle),
    FieldSpec("password_ref", required=True,  max_len=256,
              formatter=_validate_opaque_ref,
              allows_regenerate=True),
    FieldSpec("url",          required=False, max_len=2048,
              formatter=_validate_url),
    FieldSpec("notes",        required=False, max_len=2000,
              formatter=lambda v: _validate_free_text(v, max_len=2000)),
)

_LOGIN_FIELD_INDEX: Mapping[str, FieldSpec] = MappingProxyType(
    {f.name: f for f in _LOGIN_FIELDS}
)


_KIND_SCHEMA: Mapping[str, Mapping[str, FieldSpec]] = MappingProxyType({
    DRAFT_LOGIN: _LOGIN_FIELD_INDEX,
})


def schema_for(draft_kind: str) -> Mapping[str, FieldSpec]:
    if draft_kind not in _KIND_SCHEMA:
        raise ValueError(f"unknown draft_kind {draft_kind!r}")
    return _KIND_SCHEMA[draft_kind]


def is_allowed_field(draft_kind: str, field_name: str) -> bool:
    return field_name in schema_for(draft_kind)


def validate_field_value(
    draft_kind: str, field_name: str, raw_value: Any,
) -> Any:
    """Format-validate ``raw_value`` against the field's schema.

    Sentinels (CLEARED, PENDING_GENERATION) pass through
    unchanged — they are not user data.

    On format failure raises ``FieldFormatError``.
    """
    if raw_value in (CLEARED, PENDING_GENERATION):
        return raw_value
    schema = schema_for(draft_kind)
    spec = schema.get(field_name)
    if spec is None:
        raise FieldFormatError(
            f"unknown field {field_name!r} for {draft_kind!r}"
        )
    return spec.formatter(raw_value)


# -------------------------------------------------------------------
# Dataclasses
# -------------------------------------------------------------------

@dataclass(frozen=True)
class DraftField:
    value:    Any                 # str | CLEARED | PENDING_GENERATION
    source:   str                 # one of FIELD_SOURCES
    turn_id:  str
    at:       float

    def __post_init__(self) -> None:
        if self.source not in FIELD_SOURCES:
            raise ValueError(f"unknown source {self.source!r}")
        if not isinstance(self.turn_id, str):
            raise TypeError("turn_id must be a string")
        if not isinstance(self.at, (int, float)):
            raise TypeError("at must be numeric")


@dataclass(frozen=True)
class Draft:
    draft_id:            str
    vault_id:            str
    session_id:          Optional[str]
    draft_kind:          str
    fields:              Mapping[str, DraftField]
    created_at:          float
    updated_at:          float
    expires_at:          float
    origin_turn_id:      str
    last_touch_turn_id:  str
    status:              str
    schema_version:      int = 1

    def __post_init__(self) -> None:
        if self.draft_kind not in DRAFT_KINDS:
            raise ValueError(f"unknown draft_kind {self.draft_kind!r}")
        if self.status not in DRAFT_STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        # Freeze the fields mapping so consumers cannot mutate a
        # frozen dataclass by side effect through the field.
        if not isinstance(self.fields, MappingProxyType):
            object.__setattr__(
                self, "fields", MappingProxyType(dict(self.fields)),
            )
        # Reject any field name not in the schema. Merge does the
        # same check earlier; this is defense in depth.
        schema = schema_for(self.draft_kind)
        for k in self.fields:
            if k not in schema:
                raise ValueError(
                    f"draft {self.draft_kind!r} has unknown field {k!r}"
                )

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def is_live(self, now: Optional[float] = None) -> bool:
        return self.status in _LIVE_STATUSES and not self.is_expired(now)

    def get(self, field_name: str) -> Optional[DraftField]:
        return self.fields.get(field_name)

    def to_prompt_dict(self, *, redact_secrets: bool = True) -> dict:
        """Redacted view for the semantic decider's prompt.

        Password-shaped fields (currently only ``password_ref``)
        expose only ``{present, source}`` — never their value.
        Non-secret fields expose ``{value, source}``.
        """
        out_fields: dict[str, dict] = {}
        for name, spec in schema_for(self.draft_kind).items():
            f = self.fields.get(name)
            if f is None:
                continue
            is_secret_shaped = (name == "password_ref")
            if is_secret_shaped and redact_secrets:
                out_fields[name] = {
                    "present": f.value not in (CLEARED, PENDING_GENERATION),
                    "source":  f.source,
                }
            else:
                out_fields[name] = {
                    "value":  f.value,
                    "source": f.source,
                }
        return {
            "draft_id":       self.draft_id,
            "draft_kind":     self.draft_kind,
            "status":         self.status,
            "fields":         out_fields,
        }

    def to_json(self) -> str:
        payload = {
            "draft_id":           self.draft_id,
            "vault_id":           self.vault_id,
            "session_id":         self.session_id,
            "draft_kind":         self.draft_kind,
            "fields": {
                name: {
                    "value":   df.value,
                    "source":  df.source,
                    "turn_id": df.turn_id,
                    "at":      df.at,
                }
                for name, df in self.fields.items()
            },
            "created_at":         self.created_at,
            "updated_at":         self.updated_at,
            "expires_at":         self.expires_at,
            "origin_turn_id":     self.origin_turn_id,
            "last_touch_turn_id": self.last_touch_turn_id,
            "status":             self.status,
            "schema_version":     self.schema_version,
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Draft":
        payload = json.loads(raw)
        fields = {
            name: DraftField(
                value=meta["value"],
                source=meta["source"],
                turn_id=meta["turn_id"],
                at=float(meta["at"]),
            )
            for name, meta in (payload.get("fields") or {}).items()
        }
        return cls(
            draft_id=str(payload["draft_id"]),
            vault_id=str(payload["vault_id"]),
            session_id=payload.get("session_id"),
            draft_kind=str(payload["draft_kind"]),
            fields=fields,
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
            expires_at=float(payload["expires_at"]),
            origin_turn_id=str(payload["origin_turn_id"]),
            last_touch_turn_id=str(payload["last_touch_turn_id"]),
            status=str(payload["status"]),
            schema_version=int(payload.get("schema_version") or 1),
        )


# -------------------------------------------------------------------
# ID generation
# -------------------------------------------------------------------

def new_draft_id() -> str:
    """Random opaque id. 128 bits of entropy hex-encoded (32 chars)."""
    return secrets.token_hex(16)


# -------------------------------------------------------------------
# Constructors
# -------------------------------------------------------------------

def new_draft(
    *,
    vault_id:       str,
    session_id:     Optional[str],
    draft_kind:     str,
    initial_fields: Mapping[str, DraftField],
    origin_turn_id: str,
    now:            Optional[float] = None,
    draft_id:       Optional[str] = None,
    ttl_seconds:    Optional[int] = None,
) -> Draft:
    """Build a fresh Draft with the initial field set.

    All ``initial_fields`` values are format-validated. Unknown
    fields raise ``FieldFormatError``. This is a pure constructor;
    it does not persist to Redis (use ``store_draft`` for that).
    """
    if not vault_id:
        raise ValueError("vault_id required")
    if draft_kind not in DRAFT_KINDS:
        raise ValueError(f"unknown draft_kind {draft_kind!r}")
    when = float(now) if now is not None else time.time()
    ttl = int(ttl_seconds if ttl_seconds is not None else DRAFT_TTL_SECONDS)
    validated: dict[str, DraftField] = {}
    for name, df in initial_fields.items():
        if not isinstance(df, DraftField):
            raise TypeError(f"initial_fields[{name!r}] must be a DraftField")
        validate_field_value(draft_kind, name, df.value)
        validated[name] = df
    return Draft(
        draft_id=draft_id or new_draft_id(),
        vault_id=str(vault_id),
        session_id=session_id,
        draft_kind=draft_kind,
        fields=validated,
        created_at=when,
        updated_at=when,
        expires_at=when + ttl,
        origin_turn_id=origin_turn_id,
        last_touch_turn_id=origin_turn_id,
        status=STATUS_EDITABLE,
        schema_version=1,
    )


def with_status(
    draft: Draft, new_status: str, *,
    touch_turn_id: str,
    now: Optional[float] = None,
    refresh_ttl: bool = True,
    ttl_seconds: Optional[int] = None,
) -> Draft:
    """Return a copy of ``draft`` with an updated status.

    ``refresh_ttl`` controls whether the expiry is bumped.
    """
    if new_status not in DRAFT_STATUSES:
        raise ValueError(f"unknown status {new_status!r}")
    when = float(now) if now is not None else time.time()
    ttl = int(ttl_seconds if ttl_seconds is not None else DRAFT_TTL_SECONDS)
    expires = when + ttl if refresh_ttl else draft.expires_at
    return replace(
        draft,
        status=new_status,
        updated_at=when,
        last_touch_turn_id=touch_turn_id,
        expires_at=expires,
    )


# -------------------------------------------------------------------
# Storage — Redis via vault_chat_state_store
# -------------------------------------------------------------------

_BUCKET: str = "draft"


def _draft_key(vault_id: str, draft_id: str) -> str:
    return compose_key(bucket=_BUCKET, vault_id=vault_id, sub=draft_id)


def _draft_index_key(vault_id: str) -> str:
    return compose_index_key(bucket=_BUCKET, vault_id=vault_id)


def store_draft(draft: Draft) -> None:
    """Persist a Draft, refreshing its TTL to match ``expires_at``.

    Only meaningful user interactions should call this — never
    background reads, prompt builds, or shadow evaluations
    (per the design memo §9).
    """
    backend = get_chat_state_backend()
    now = time.time()
    ttl = max(1, int(draft.expires_at - now))
    key = _draft_key(draft.vault_id, draft.draft_id)
    backend.set(key, draft.to_json().encode("utf-8"), ttl)
    try:
        backend.sadd(_draft_index_key(draft.vault_id), draft.draft_id, ttl)
    except Exception:
        logger.exception("[DRAFT] index_add_failed vault=%s",
                         (draft.vault_id or "")[:8] + "…")


def get_draft(
    vault_id: str, draft_id: str,
    *, now: Optional[float] = None,
) -> Optional[Draft]:
    """Read a Draft. Returns None if absent, malformed, or expired."""
    if not vault_id or not draft_id:
        return None
    backend = get_chat_state_backend()
    try:
        raw = backend.get(_draft_key(vault_id, draft_id))
    except Exception:
        logger.exception("[DRAFT] read_failed vault=%s",
                         (vault_id or "")[:8] + "…")
        return None
    if not raw:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        draft = Draft.from_json(text)
    except Exception:
        logger.warning(
            "[DRAFT] deserialize_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if draft.is_expired(now):
        return None
    return draft


def list_live_drafts(
    vault_id: str, *,
    session_id: Optional[str] = None,
    draft_kind: Optional[str] = None,
    now: Optional[float] = None,
    limit: int = 5,
) -> list[Draft]:
    """Return live drafts, newest-first, up to ``limit``.

    ``session_id=None`` returns drafts for any session (matches
    the visibility rule used elsewhere: a session-stamped record
    is visible only to that session; an unstamped record is
    visible to any reader). See ``_visible_to_session``.
    """
    if not vault_id:
        return []
    backend = get_chat_state_backend()
    try:
        ids = backend.smembers(_draft_index_key(vault_id)) or []
    except Exception:
        logger.exception("[DRAFT] index_read_failed vault=%s",
                         (vault_id or "")[:8] + "…")
        ids = []
    when = float(now) if now is not None else time.time()
    hits: list[Draft] = []
    for raw_id in ids:
        did = raw_id.decode("utf-8") if isinstance(raw_id, (bytes, bytearray)) else str(raw_id)
        d = get_draft(vault_id, did, now=when)
        if d is None:
            continue
        if not d.is_live(when):
            continue
        if draft_kind is not None and d.draft_kind != draft_kind:
            continue
        if not _visible_to_session(d.session_id, session_id):
            continue
        hits.append(d)
    hits.sort(key=lambda d: d.updated_at, reverse=True)
    return hits[: max(0, int(limit))]


def _visible_to_session(
    stored_session_id: Optional[str],
    reader_session_id: Optional[str],
) -> bool:
    if stored_session_id is None:
        return True
    if reader_session_id is None:
        return False
    return stored_session_id == reader_session_id


def cancel_draft(vault_id: str, draft_id: str) -> bool:
    """Delete the draft record (transitions status to CANCELLED
    from the caller's perspective — the record itself is removed
    from the store, so no live reader will see it again).

    Returns True if a record was removed, False if nothing was
    there to remove.
    """
    if not vault_id or not draft_id:
        return False
    backend = get_chat_state_backend()
    key = _draft_key(vault_id, draft_id)
    try:
        raw = backend.get(key)
    except Exception:
        logger.exception("[DRAFT] cancel_read_failed vault=%s",
                         (vault_id or "")[:8] + "…")
        raw = None
    had = raw is not None
    try:
        backend.delete(key)
    except Exception:
        logger.exception("[DRAFT] cancel_delete_failed vault=%s",
                         (vault_id or "")[:8] + "…")
        return False
    try:
        backend.srem(_draft_index_key(vault_id), draft_id)
    except Exception:
        # non-fatal
        logger.debug("[DRAFT] cancel_index_srem_failed vault=%s",
                     (vault_id or "")[:8] + "…")
    return had


def consume_draft(vault_id: str, draft_id: str) -> Optional[Draft]:
    """Read-and-delete a Draft — used after a successful save.

    Returns the last-known Draft value if one was present,
    otherwise None. The record is deleted from the store even
    if the caller drops the returned value.
    """
    if not vault_id or not draft_id:
        return None
    d = get_draft(vault_id, draft_id)
    cancel_draft(vault_id, draft_id)
    return d


__all__ = [
    "DRAFT_LOGIN",
    "DRAFT_KINDS",
    "STATUS_EDITABLE",
    "STATUS_PRESENTED_FOR_CONFIRMATION",
    "STATUS_AUTHORIZED_ONCE",
    "STATUS_EXECUTING",
    "STATUS_CONSUMED",
    "STATUS_CANCELLED",
    "DRAFT_STATUSES",
    "SOURCE_USER_EXPLICIT",
    "SOURCE_VAULT_LOOKUP",
    "SOURCE_INFERRED",
    "SOURCE_GENERATED",
    "FIELD_SOURCES",
    "FIELD_SOURCE_PRIORITY",
    "CLEARED",
    "PENDING_GENERATION",
    "OP_REPLACE",
    "OP_CLEAR",
    "OP_REGENERATE",
    "OP_UNCHANGED",
    "PATCH_OPS",
    "DRAFT_TTL_SECONDS",
    "FieldFormatError",
    "FieldSpec",
    "schema_for",
    "is_allowed_field",
    "validate_field_value",
    "DraftField",
    "Draft",
    "new_draft_id",
    "new_draft",
    "with_status",
    "store_draft",
    "get_draft",
    "list_live_drafts",
    "cancel_draft",
    "consume_draft",
]
