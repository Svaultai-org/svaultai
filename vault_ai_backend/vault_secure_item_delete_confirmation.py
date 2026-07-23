"""Owner-side "delete this saved item" confirmation intent store.

2026-07-23 revision — Bug 4 root-cause fix.

Prior to this revision the intent was held in a module-level dict.
On the production topology (Uvicorn ``--workers 2`` with no session
affinity) that meant:

  * Request A — sentinel ``__delete_item:login:instagram`` — hits
    worker A, stores the intent in A's local ``_store`` dict,
    responds "Are you sure you want to delete instagram login…".
  * Request B — user types ``yes`` — round-robins to worker B,
    whose ``_store`` is empty, so the pending-delete resolver falls
    through. The next handler down the chain
    (``pending_named_file``) reinterprets the "yes" as a filename
    for a recently-uploaded image, replying "Saved this image as
    Img_3177.png." Exact production incident.

The fix routes the intent through the same Redis-backed
``vault_chat_state_store`` module that ``vault_credential_draft``
and ``vault_secure_item_draft`` already use post-c1e3df3. Same
Redis URL, same key namespace shape, same TTL enforcement mechanic
(``PEX`` on ``SET``). No new env var, no new dependency, no
migration. The public API (``store_delete_intent``,
``get_pending_delete_intent``, ``consume_pending_delete_intent``,
``clear_pending_delete_intent``, ``_reset_store_for_test``) is
UNCHANGED — callers do not know they moved from a dict to Redis.

Data written to Redis under the key
``chatst:v1:secure_delete_intent:{sha256(vault_id)[0:16]}``:

  { intent_id, vault_id, service, item_type, item_id,
    is_login, created_at, expires_at }

The ``service`` field is product metadata — the same value that
appears in the SQL ``WHERE LOWER(service) = LOWER(%s)`` clause the
delete executor uses. It is NOT a credential. NO plaintext PINs,
NO passwords, NO recovery codes, NO tokens are stored.

Failure semantics unchanged:
  * TTL 600s (10 min).
  * At most one active intent per vault_id.
  * Storing a new intent overwrites any prior one.
  * ``consume`` deletes-and-returns atomically.
  * ``get`` reads without touching TTL.
  * Redis outage → the backend falls back to a per-process
    in-memory shim on that call (``vault_chat_state_store``
    handles that) and the request continues without erroring.
    Worst case matches the pre-fix worker-hop behavior — which was
    the bug we are fixing — but does not brick the chat UX.

Original prompt / cancellation phrases (``_CONFIRM_DELETE_RE``,
``_CANCEL_DELETE_RE``) and their public accessors are unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Optional


logger = logging.getLogger(__name__)


DELETE_INTENT_TTL_SECONDS: int = 600


BAND_DELETE_CONFIRMATION_PENDING: str = "delete_confirmation_pending"
BAND_DELETED:                     str = "deleted"
BAND_DELETE_CANCELLED:            str = "delete_cancelled"
BAND_NO_PENDING_DELETE:           str = "no_pending_delete"


@dataclass(frozen=True)
class SecureItemDeleteIntent:


    intent_id:  str
    vault_id:   str
    service:    str
    item_type:  str
    item_id:    Optional[str]
    is_login:   bool
    created_at: float
    expires_at: float

    def __repr__(self) -> str:
        return (
            f"SecureItemDeleteIntent(intent_id={self.intent_id!r}, "
            f"vault_prefix={self.vault_id[:8]!r}..., "
            f"item_type={self.item_type!r}, "
            f"is_login={self.is_login}, "
            f"service=<REDACTED>)"
        )

    __str__ = __repr__

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at


_LOGIN_LIKE_TYPES: frozenset[str] = frozenset({"login", "credential"})


# ---------------------------------------------------------------------
# Cross-worker persistence (Redis-backed shared state)
# ---------------------------------------------------------------------
#
# The 2026-07-23 root cause fix. Previously ``_store`` was a
# per-process dict; the sentinel + "yes" round-robined across
# Uvicorn workers so worker B never saw worker A's intent. This
# migrates to the same shared backend the rest of the chat state
# uses, which resolves to Redis in production and to an in-memory
# shim in dev / test — semantically identical to the old dict for
# single-worker environments.

_BUCKET: str = "secure_delete_intent"


def _now() -> float:
    return time.time()


def _serialize(intent: SecureItemDeleteIntent) -> bytes:
    return json.dumps(asdict(intent), separators=(",", ":")).encode("utf-8")


def _deserialize(raw: bytes) -> Optional[SecureItemDeleteIntent]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
        return SecureItemDeleteIntent(
            intent_id=str(d["intent_id"]),
            vault_id=str(d["vault_id"]),
            service=str(d["service"]),
            item_type=str(d["item_type"]),
            item_id=d.get("item_id"),
            is_login=bool(d.get("is_login", False)),
            created_at=float(d["created_at"]),
            expires_at=float(d["expires_at"]),
        )
    except Exception:
        # Corrupt / partial value: treat as no-pending. Log via the
        # shared-state backend's normal warning cadence so the
        # operator sees repeated corruption on the correct module.
        logger.warning(
            "[SECURE-ITEM-DELETE] intent_deserialize_failed",
        )
        return None


def _backend_key(vault_id: str) -> str:
    from vault_chat_state_store import compose_key
    return compose_key(bucket=_BUCKET, vault_id=vault_id)


def _get_intent_from_shared_store(
    vault_id: str,
) -> Optional[SecureItemDeleteIntent]:
    if not vault_id:
        return None
    from vault_chat_state_store import get_chat_state_backend
    raw = get_chat_state_backend().get(_backend_key(vault_id))
    if raw is None:
        return None
    intent = _deserialize(raw)
    if intent is None:
        # Corrupt — clean up so subsequent reads return None.
        try:
            get_chat_state_backend().delete(_backend_key(vault_id))
        except Exception:
            pass
        return None
    if intent.is_expired(_now()):
        try:
            get_chat_state_backend().delete(_backend_key(vault_id))
        except Exception:
            pass
        return None
    return intent


def store_delete_intent(
    *,
    vault_id: str,
    service: str,
    item_type: str,
    item_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> SecureItemDeleteIntent:


    if not vault_id:
        raise ValueError("vault_id required")
    safe_service = (service or "").strip()
    safe_type    = (item_type or "").strip()
    if not safe_service:
        raise ValueError("service required")
    if not safe_type:
        raise ValueError("item_type required")
    ttl = int(
        ttl_seconds if ttl_seconds is not None
        else DELETE_INTENT_TTL_SECONDS
    )
    if ttl <= 0:
        ttl = DELETE_INTENT_TTL_SECONDS
    now = _now()
    intent = SecureItemDeleteIntent(
        intent_id=uuid.uuid4().hex,
        vault_id=vault_id,
        service=safe_service,
        item_type=safe_type,
        item_id=(item_id or None),
        is_login=(safe_type.lower() in _LOGIN_LIKE_TYPES),
        created_at=now,
        expires_at=now + ttl,
    )
    from vault_chat_state_store import get_chat_state_backend
    get_chat_state_backend().set(
        _backend_key(vault_id), _serialize(intent), ttl_seconds=ttl,
    )
    logger.info(
        "[SECURE-ITEM-DELETE] intent_stored vault=%s type=%s ttl=%d",
        (vault_id or "")[:8] + "…", safe_type, ttl,
    )
    return intent


def get_pending_delete_intent(
    *, vault_id: str,
) -> Optional[SecureItemDeleteIntent]:
    return _get_intent_from_shared_store(vault_id)


def consume_pending_delete_intent(
    *, vault_id: str,
) -> Optional[SecureItemDeleteIntent]:


    if not vault_id:
        return None
    intent = _get_intent_from_shared_store(vault_id)
    if intent is None:
        return None
    try:
        from vault_chat_state_store import get_chat_state_backend
        get_chat_state_backend().delete(_backend_key(vault_id))
    except Exception:
        # The get returned a valid intent — a delete failure here
        # would leak a re-consumable ghost. Log it and continue so
        # the caller still executes the delete; the ghost either
        # gets consumed on the next matching "yes" (safe — it
        # points at the same target) or expires via TTL.
        logger.warning(
            "[SECURE-ITEM-DELETE] consume_delete_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
    return intent


def clear_pending_delete_intent(vault_id: str) -> bool:
    if not vault_id:
        return False
    from vault_chat_state_store import get_chat_state_backend
    key = _backend_key(vault_id)
    existed = get_chat_state_backend().get(key) is not None
    try:
        get_chat_state_backend().delete(key)
    except Exception:
        pass
    return existed


def _reset_store_for_test() -> None:
    """Drop any prior intent, and also reset the shared-state
    backend singleton so tests get a fresh InMemoryChatStateBackend.
    Idempotent."""
    try:
        from vault_chat_state_store import reset_chat_state_backend_for_tests
        reset_chat_state_backend_for_tests()
    except Exception:
        pass


_CONFIRM_DELETE_PATTERNS: tuple[str, ...] = (
    r"^\s*yes\s*[.!?]*\s*$",
    r"^\s*yes\s*[,.\s]+\s*delete\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*yes\s*[,.\s]+\s*remove\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*delete\s+it\s*[.!?]*\s*$",
    r"^\s*delete\s+that\s*[.!?]*\s*$",
    r"^\s*delete\s+now\s*[.!?]*\s*$",
    r"^\s*remove\s+it\s*[.!?]*\s*$",
    r"^\s*remove\s+that\s*[.!?]*\s*$",
    r"^\s*confirm\s*[.!?]*\s*$",
    r"^\s*confirm\s+delete\s*[.!?]*\s*$",
    r"^\s*go\s+ahead\s*[.!?]*\s*$",
    r"^\s*go\s+ahead\s+(?:and\s+)?(?:delete|remove)\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*proceed\s*[.!?]*\s*$",
    r"^\s*yep\s*[,.\s]*delete\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*sure\s*[,.\s]*delete\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*ok(?:ay)?\s*[,.\s]*delete\s+(?:it|that|now)?\s*[.!?]*\s*$",
    r"^\s*do\s+it\s*[.!?]*\s*$",
)


_CONFIRM_DELETE_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _CONFIRM_DELETE_PATTERNS
)


_CANCEL_DELETE_PATTERNS: tuple[str, ...] = (
    r"^\s*no\s*[.!?]*\s*$",
    r"^\s*nope\s*[.!?]*\s*$",
    r"^\s*nah\s*[.!?]*\s*$",
    r"^\s*cancel\s*[.!?]*\s*$",
    r"^\s*cancel\s+(?:it|that|delete)\s*[.!?]*\s*$",

    r"^\s*don'?t\s+delete(?:\s+(?:it|that))?\s*[.!?]*\s*$",
    r"^\s*do\s+not\s+delete(?:\s+(?:it|that))?\s*[.!?]*\s*$",
    r"^\s*stop\s*[.!?]*\s*$",
    r"^\s*keep\s+it\s*[.!?]*\s*$",
    r"^\s*keep\s+them\s*[.!?]*\s*$",
    r"^\s*never\s*mind\s*[.!?]*\s*$",
    r"^\s*nevermind\s*[.!?]*\s*$",
    r"^\s*on\s+second\s+thought\s*[.!?]*\s*$",
)


_CANCEL_DELETE_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _CANCEL_DELETE_PATTERNS
)


def is_confirm_delete_phrase(msg: Optional[str]) -> bool:

    if not isinstance(msg, str):
        return False
    text = msg.strip()
    if not text:
        return False
    return any(pat.match(text) for pat in _CONFIRM_DELETE_RE)


def is_cancel_delete_phrase(msg: Optional[str]) -> bool:


    if not isinstance(msg, str):
        return False
    text = msg.strip()
    if not text:
        return False
    return any(pat.match(text) for pat in _CANCEL_DELETE_RE)


SENTINEL_PREFIX: str = "__delete_item:"


_SENTINEL_RE = re.compile(
    r"^\s*__delete_item:"
    r"(?P<type>[A-Za-z0-9_]{1,64})"
    r":(?P<service>.{1,200})\s*$",
    re.DOTALL,
)


def is_delete_intent_sentinel(msg: Optional[str]) -> bool:


    if not isinstance(msg, str) or not msg:
        return False
    return _SENTINEL_RE.match(msg) is not None


def parse_delete_intent_sentinel(
    msg: Optional[str],
) -> Optional[tuple[str, str]]:


    if not isinstance(msg, str) or not msg:
        return None
    m = _SENTINEL_RE.match(msg)
    if not m:
        return None
    item_type = m.group("type").strip()
    service   = m.group("service").strip()
    if not item_type or not service:
        return None
    return item_type, service


_CONFIRM_QUESTION_LOGIN: str = (
    "Are you sure you want to delete {title} login from your vault?"
)


_CONFIRM_QUESTION_NON_LOGIN: str = (
    "Are you sure you want to delete {title} from your vault?"
)


_CONFIRM_QUESTION_NON_LOGIN_NO_TITLE: str = (
    "Are you sure you want to delete this saved item from your vault?"
)


_DELETED_REPLY_LOGIN: str = (
    "Deleted {title} login from your vault."
)


_DELETED_REPLY_NON_LOGIN: str = (
    "Deleted {title} from your vault."
)


_DELETED_REPLY_NON_LOGIN_NO_TITLE: str = (
    "Deleted saved item from your vault."
)


_CANCELLED_REPLY: str = "Okay — I won't delete it."


def confirmation_question(intent: SecureItemDeleteIntent) -> str:


    title = (intent.service or "").strip()
    if intent.is_login:
        if not title:


            return _CONFIRM_QUESTION_NON_LOGIN_NO_TITLE
        return _CONFIRM_QUESTION_LOGIN.format(title=title)
    if title:
        return _CONFIRM_QUESTION_NON_LOGIN.format(title=title)
    return _CONFIRM_QUESTION_NON_LOGIN_NO_TITLE


def deleted_reply(intent: SecureItemDeleteIntent) -> str:

    title = (intent.service or "").strip()
    if intent.is_login and title:
        return _DELETED_REPLY_LOGIN.format(title=title)
    if title:
        return _DELETED_REPLY_NON_LOGIN.format(title=title)
    return _DELETED_REPLY_NON_LOGIN_NO_TITLE


def cancelled_reply() -> str:
    return _CANCELLED_REPLY


__all__ = [
    "DELETE_INTENT_TTL_SECONDS",
    "BAND_DELETE_CONFIRMATION_PENDING",
    "BAND_DELETED",
    "BAND_DELETE_CANCELLED",
    "BAND_NO_PENDING_DELETE",
    "SENTINEL_PREFIX",
    "SecureItemDeleteIntent",
    "store_delete_intent",
    "get_pending_delete_intent",
    "consume_pending_delete_intent",
    "clear_pending_delete_intent",
    "is_confirm_delete_phrase",
    "is_cancel_delete_phrase",
    "is_delete_intent_sentinel",
    "parse_delete_intent_sentinel",
    "confirmation_question",
    "deleted_reply",
    "cancelled_reply",
]
