"""ConversationalFocus — what the assistant most recently invited
the user to respond to.

Focus is a short-lived, per-(vault_id, session_id) record stamped
by the router immediately after any turn where the assistant
either:

    * presented a Draft or PendingAction for confirmation
      (``assistant_act = FOCUS_ACT_PRESENTED_FOR_CONFIRMATION``);
    * asked a clarification about a specific target
      (``FOCUS_ACT_ASKED_CLARIFICATION``);
    * described a specific entity in a way that establishes it as
      the local subject
      (``FOCUS_ACT_DESCRIBED``).

The policy layer consults focus for authorization decisions. A
short/generic user confirmation ("yes", "ok") is required to
target the current focus; a decision that targets a different
live pending action requires higher confidence (see design memo
§6 rule 6).

This module implements storage primitives, validation, TTL
behavior, and clearing semantics ONLY. It does NOT wire itself
into any router — that wiring lands in a later commit
(specifically the router-v2 commit).

Shadow-mode note
----------------
In shadow mode the v2 evaluation does NOT persist focus (that
would be a write and would violate the shadow-mode zero-side-
effects contract). Instead it synthesizes an ephemeral
``ConversationalFocus`` from v1 output + turn context and marks
it ``synthetic_shadow=True``. That synthesis lives in the shadow
recorder module (later commit); this module here is only for
genuine, persisted focus.

Storage
-------
Redis-backed via ``vault_chat_state_store``. Bucket: ``focus``.
Default TTL: 180 s (``FOCUS_TTL_SECONDS``). Refreshed on every
``stamp_focus`` call (this is a meaningful assistant-side event).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from vault_chat_state_store import compose_key, get_chat_state_backend


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Focus kinds
# -------------------------------------------------------------------

FOCUS_KIND_DRAFT:          str = "draft"
FOCUS_KIND_PENDING_ACTION: str = "pending_action"
FOCUS_KIND_ACTIVE_ENTITY:  str = "active_entity"
FOCUS_KIND_NONE:           str = "none"

FOCUS_KINDS: frozenset[str] = frozenset({
    FOCUS_KIND_DRAFT,
    FOCUS_KIND_PENDING_ACTION,
    FOCUS_KIND_ACTIVE_ENTITY,
    FOCUS_KIND_NONE,
})


# -------------------------------------------------------------------
# Assistant acts
# -------------------------------------------------------------------

FOCUS_ACT_PRESENTED_FOR_CONFIRMATION: str = "presented_for_confirmation"
FOCUS_ACT_ASKED_CLARIFICATION:        str = "asked_clarification"
FOCUS_ACT_DESCRIBED:                  str = "described"
FOCUS_ACT_NONE:                       str = "none"

FOCUS_ACTS: frozenset[str] = frozenset({
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_ACT_ASKED_CLARIFICATION,
    FOCUS_ACT_DESCRIBED,
    FOCUS_ACT_NONE,
})


# -------------------------------------------------------------------
# TTL
# -------------------------------------------------------------------

FOCUS_TTL_SECONDS: int = 180


# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------

@dataclass(frozen=True)
class ConversationalFocus:
    kind:               str
    id:                 Optional[str]
    assistant_act:      str
    assistant_turn_id:  str
    vault_id:           str
    session_id:         Optional[str]
    at:                 float
    expires_at:         float

    def __post_init__(self) -> None:
        if self.kind not in FOCUS_KINDS:
            raise ValueError(f"unknown focus kind {self.kind!r}")
        if self.assistant_act not in FOCUS_ACTS:
            raise ValueError(
                f"unknown assistant_act {self.assistant_act!r}"
            )
        if self.kind != FOCUS_KIND_NONE and not self.id:
            raise ValueError(
                f"focus with kind={self.kind!r} requires a non-empty id"
            )
        if self.kind == FOCUS_KIND_NONE and self.id:
            raise ValueError(
                "focus with kind=none must not carry an id"
            )
        if not isinstance(self.assistant_turn_id, str):
            raise TypeError("assistant_turn_id must be a string")
        if not self.vault_id:
            raise ValueError("vault_id required")

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def targets(self, kind: str, id_: str) -> bool:
        """True iff this focus points at exactly ``(kind, id_)``."""
        return (
            self.kind == kind
            and self.id is not None
            and self.id == id_
        )

    def to_json(self) -> str:
        return json.dumps({
            "kind":              self.kind,
            "id":                self.id,
            "assistant_act":     self.assistant_act,
            "assistant_turn_id": self.assistant_turn_id,
            "vault_id":          self.vault_id,
            "session_id":        self.session_id,
            "at":                self.at,
            "expires_at":        self.expires_at,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "ConversationalFocus":
        p = json.loads(raw)
        return cls(
            kind=str(p["kind"]),
            id=p.get("id"),
            assistant_act=str(p["assistant_act"]),
            assistant_turn_id=str(p["assistant_turn_id"]),
            vault_id=str(p["vault_id"]),
            session_id=p.get("session_id"),
            at=float(p["at"]),
            expires_at=float(p["expires_at"]),
        )


NONE_FOCUS_SINGLETON = None  # sentinel; use read_focus() → Optional[Focus]


# -------------------------------------------------------------------
# Storage
# -------------------------------------------------------------------

_BUCKET: str = "focus"


def _focus_key(vault_id: str, session_id: Optional[str]) -> str:
    sub = session_id or ""
    return compose_key(bucket=_BUCKET, vault_id=vault_id, sub=sub)


def stamp_focus(
    *,
    vault_id:          str,
    session_id:        Optional[str],
    kind:              str,
    id:                Optional[str],
    assistant_act:     str,
    assistant_turn_id: str,
    ttl_seconds:       Optional[int] = None,
    now:               Optional[float] = None,
) -> ConversationalFocus:
    """Create-or-refresh the focus for (vault_id, session_id).

    Writes to Redis with a fresh TTL. Returns the new
    ``ConversationalFocus`` value.
    """
    when = float(now) if now is not None else time.time()
    ttl = int(ttl_seconds if ttl_seconds is not None else FOCUS_TTL_SECONDS)
    focus = ConversationalFocus(
        kind=kind,
        id=id,
        assistant_act=assistant_act,
        assistant_turn_id=assistant_turn_id,
        vault_id=vault_id,
        session_id=session_id,
        at=when,
        expires_at=when + ttl,
    )
    backend = get_chat_state_backend()
    try:
        backend.set(
            _focus_key(vault_id, session_id),
            focus.to_json().encode("utf-8"),
            max(1, ttl),
        )
    except Exception:
        logger.exception(
            "[FOCUS] write_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
    return focus


def read_focus(
    *,
    vault_id:   str,
    session_id: Optional[str] = None,
    now:        Optional[float] = None,
) -> Optional[ConversationalFocus]:
    """Read the current focus for (vault_id, session_id).

    Returns None if none stamped, if expired, or if the stored
    value is malformed.
    """
    if not vault_id:
        return None
    backend = get_chat_state_backend()
    try:
        raw = backend.get(_focus_key(vault_id, session_id))
    except Exception:
        logger.exception(
            "[FOCUS] read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if not raw:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        focus = ConversationalFocus.from_json(text)
    except Exception:
        logger.warning(
            "[FOCUS] deserialize_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return None
    if focus.is_expired(now):
        return None
    return focus


def clear_focus(
    *,
    vault_id:   str,
    session_id: Optional[str] = None,
) -> bool:
    """Delete the focus record.

    Returns True if a record was present and removed, False
    otherwise.
    """
    if not vault_id:
        return False
    backend = get_chat_state_backend()
    key = _focus_key(vault_id, session_id)
    try:
        had = backend.get(key) is not None
    except Exception:
        logger.exception(
            "[FOCUS] clear_read_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        had = False
    try:
        backend.delete(key)
    except Exception:
        logger.exception(
            "[FOCUS] clear_delete_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return False
    return had


def clear_focus_if_matches(
    *,
    vault_id:   str,
    session_id: Optional[str] = None,
    kind:       str,
    id:         str,
    now:        Optional[float] = None,
) -> bool:
    """Delete the focus iff it targets exactly ``(kind, id)``.

    Used by callers that consumed or cancelled the exact target
    the assistant just presented — clears stale focus without
    stomping a subsequent, unrelated focus that a concurrent
    turn may have already stamped. Best-effort; not
    cross-process atomic in in-memory backends.
    """
    focus = read_focus(
        vault_id=vault_id, session_id=session_id, now=now,
    )
    if focus is None:
        return False
    if not focus.targets(kind, id):
        return False
    return clear_focus(vault_id=vault_id, session_id=session_id)


__all__ = [
    "FOCUS_KIND_DRAFT",
    "FOCUS_KIND_PENDING_ACTION",
    "FOCUS_KIND_ACTIVE_ENTITY",
    "FOCUS_KIND_NONE",
    "FOCUS_KINDS",
    "FOCUS_ACT_PRESENTED_FOR_CONFIRMATION",
    "FOCUS_ACT_ASKED_CLARIFICATION",
    "FOCUS_ACT_DESCRIBED",
    "FOCUS_ACT_NONE",
    "FOCUS_ACTS",
    "FOCUS_TTL_SECONDS",
    "ConversationalFocus",
    "stamp_focus",
    "read_focus",
    "clear_focus",
    "clear_focus_if_matches",
]
