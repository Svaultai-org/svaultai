

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


DELETE_INTENT_TTL_SECONDS: int = 600


_lock = threading.Lock()
_store: dict[str, "SecureItemDeleteIntent"] = {}


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


def _now() -> float:
    return time.time()


def _gc_expired(vault_id: str, now: float) -> None:

    entry = _store.get(vault_id)
    if entry is None:
        return
    if entry.is_expired(now):
        _store.pop(vault_id, None)


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
    with _lock:
        _store[vault_id] = intent
    logger.info(
        "[SECURE-ITEM-DELETE] intent_stored vault=%s type=%s ttl=%d",
        (vault_id or "")[:8] + "…", safe_type, ttl,
    )
    return intent


def get_pending_delete_intent(
    *, vault_id: str,
) -> Optional[SecureItemDeleteIntent]:
    if not vault_id:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        return _store.get(vault_id)


def consume_pending_delete_intent(
    *, vault_id: str,
) -> Optional[SecureItemDeleteIntent]:


    if not vault_id:
        return None
    now = _now()
    with _lock:
        _gc_expired(vault_id, now)
        return _store.pop(vault_id, None)


def clear_pending_delete_intent(vault_id: str) -> bool:
    if not vault_id:
        return False
    with _lock:
        return _store.pop(vault_id, None) is not None


def _reset_store_for_test() -> None:
    with _lock:
        _store.clear()


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
