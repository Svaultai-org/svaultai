"""Closed-set security event logger.

Every audit-relevant security event is emitted through this module so
we have ONE place to review what gets logged and can prove no secret
material leaks. Reasons are a closed set validated at emit-time; a
typo in a reason becomes a test failure, not silent corruption.

Log lines are structured strings prefixed with `[SEC-EVENT]` so they
can be grepped in production log aggregation.

STRICT NO-LOG rules:
  * NEVER accept a raw PIN, seed, mnemonic, private key, spend key,
    view key, encrypted wallet secret, auth token, API key, or a
    Stripe secret in any field. All identifiers are pre-hashed by the
    caller (use `security_event_log.short_hash`).
  * NEVER accept raw request/response bodies.
  * NEVER accept raw chat prompts, file contents, or item values.
  * Free-form `note` is capped at 200 chars and MUST NOT include
    user-provided text.

Callers pass:
  * `reason`  — one of REASONS (closed set)
  * `route`   — one of ROUTE_GROUPS (closed set)
  * `subject` — optional short-hashed vault id / IP / device id
  * `note`    — optional constant strings only (kwarg-free literal)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger(__name__)


LOG_PREFIX: str = "[SEC-EVENT]"


REASON_RATE_LIMITED_AUTH:         str = "rate_limited_auth"
REASON_RATE_LIMITED_PIN_VERIFY:   str = "rate_limited_pin_verify"
REASON_RATE_LIMITED_CHAT:         str = "rate_limited_chat"
REASON_RATE_LIMITED_DELETE_VAULT: str = "rate_limited_delete_vault"
REASON_RATE_LIMITED_UPLOAD:       str = "rate_limited_upload_burst"
REASON_RATE_LIMITED_DELETE_BURST: str = "rate_limited_delete_burst"
REASON_RATE_LIMITED_EXPORT:       str = "rate_limited_export"
REASON_PIN_ATTEMPT_FAIL:          str = "pin_attempt_fail"
REASON_PIN_LOCKOUT_TRIGGERED:     str = "pin_lockout_triggered"
REASON_TRUSTED_DEVICE_REJECTED:   str = "trusted_device_rejected"
REASON_DELETE_VAULT_REQUESTED:    str = "delete_vault_requested"
REASON_DELETE_VAULT_CONFIRMED:    str = "delete_vault_confirmed"
REASON_INACTIVE_UNPAID_DELETED:   str = "inactive_unpaid_deleted"
REASON_UPLOAD_BURST_DETECTED:     str = "upload_burst_detected"
REASON_DELETE_BURST_DETECTED:     str = "delete_burst_detected"
REASON_WEBHOOK_SIGNATURE_FAIL:    str = "webhook_signature_fail"
REASON_AUTH_FAILURE_BURST:        str = "auth_failure_burst"
REASON_INVALID_ORIGIN:            str = "invalid_origin_rejected"
REASON_OVERSIZED_REQUEST:         str = "oversized_request_rejected"


REASONS: frozenset[str] = frozenset({
    REASON_RATE_LIMITED_AUTH,
    REASON_RATE_LIMITED_PIN_VERIFY,
    REASON_RATE_LIMITED_CHAT,
    REASON_RATE_LIMITED_DELETE_VAULT,
    REASON_RATE_LIMITED_UPLOAD,
    REASON_RATE_LIMITED_DELETE_BURST,
    REASON_RATE_LIMITED_EXPORT,
    REASON_PIN_ATTEMPT_FAIL,
    REASON_PIN_LOCKOUT_TRIGGERED,
    REASON_TRUSTED_DEVICE_REJECTED,
    REASON_DELETE_VAULT_REQUESTED,
    REASON_DELETE_VAULT_CONFIRMED,
    REASON_INACTIVE_UNPAID_DELETED,
    REASON_UPLOAD_BURST_DETECTED,
    REASON_DELETE_BURST_DETECTED,
    REASON_WEBHOOK_SIGNATURE_FAIL,
    REASON_AUTH_FAILURE_BURST,
    REASON_INVALID_ORIGIN,
    REASON_OVERSIZED_REQUEST,
})


ROUTE_GROUP_AUTH:         str = "auth"
ROUTE_GROUP_PIN:          str = "pin"
ROUTE_GROUP_CHAT:         str = "chat"
ROUTE_GROUP_DELETE_VAULT: str = "delete_vault"
ROUTE_GROUP_UPLOAD:       str = "upload"
ROUTE_GROUP_SECURE_ITEM:  str = "secure_item"
ROUTE_GROUP_CRYPTO:       str = "crypto"
ROUTE_GROUP_WEBHOOK:      str = "webhook"
ROUTE_GROUP_EXPORT:       str = "export"
ROUTE_GROUP_INACTIVE_JOB: str = "inactive_unpaid_cleanup"


ROUTE_GROUPS: frozenset[str] = frozenset({
    ROUTE_GROUP_AUTH,
    ROUTE_GROUP_PIN,
    ROUTE_GROUP_CHAT,
    ROUTE_GROUP_DELETE_VAULT,
    ROUTE_GROUP_UPLOAD,
    ROUTE_GROUP_SECURE_ITEM,
    ROUTE_GROUP_CRYPTO,
    ROUTE_GROUP_WEBHOOK,
    ROUTE_GROUP_EXPORT,
    ROUTE_GROUP_INACTIVE_JOB,
})


_NOTE_MAX_CHARS: int = 200


_BANNED_IN_NOTE = (
    "pin=",
    "pin ",
    "seed",
    "mnemonic",
    "private_key",
    "private key",
    "spend_key",
    "spend key",
    "view_key",
    "view key",
    "api_key",
    "api key",
    "auth_token",
    "bearer ",
    "password",
    "encrypted_data",
    "pin_verifier",
    "pin_salt",
    "stripe_sk_",
)


def short_hash(raw: str) -> str:
    """SHA-256 hex, first 12 chars. Use for vault id, account id,
    device id, IP address in security event fields."""
    if not raw:
        return "anon"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _validate_note(note: Optional[str]) -> str:
    if note is None:
        return ""
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if len(note) > _NOTE_MAX_CHARS:
        raise ValueError(
            f"note exceeds {_NOTE_MAX_CHARS} chars — "
            "security events must not carry user-provided text"
        )
    lower = note.lower()
    for banned in _BANNED_IN_NOTE:
        if banned in lower:
            raise ValueError(
                f"note contains banned token {banned!r} — refusing "
                "to log potentially sensitive material"
            )
    return note


def emit(
    *,
    reason: str,
    route: str,
    subject: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Emit a security event. Raises ValueError on any invariant
    violation so a typo becomes a hard test failure rather than a
    silent log corruption.
    """
    if reason not in REASONS:
        raise ValueError(f"unknown security event reason: {reason!r}")
    if route not in ROUTE_GROUPS:
        raise ValueError(f"unknown security event route: {route!r}")
    if subject is not None:
        if not isinstance(subject, str):
            raise ValueError("subject must be a string")
        if len(subject) > 32:
            raise ValueError(
                "subject is too long — pass a short_hash(...) prefix"
            )
    safe_note = _validate_note(note)

    ts = datetime.now(timezone.utc).isoformat()
    parts = [
        LOG_PREFIX,
        f"ts={ts}",
        f"reason={reason}",
        f"route={route}",
    ]
    if subject:
        parts.append(f"subject={subject}")
    if safe_note:
        parts.append(f"note={safe_note}")

    logger.warning(" ".join(parts))


__all__ = [
    "LOG_PREFIX",
    "REASONS",
    "ROUTE_GROUPS",
    "REASON_RATE_LIMITED_AUTH",
    "REASON_RATE_LIMITED_PIN_VERIFY",
    "REASON_RATE_LIMITED_CHAT",
    "REASON_RATE_LIMITED_DELETE_VAULT",
    "REASON_RATE_LIMITED_UPLOAD",
    "REASON_RATE_LIMITED_DELETE_BURST",
    "REASON_RATE_LIMITED_EXPORT",
    "REASON_PIN_ATTEMPT_FAIL",
    "REASON_PIN_LOCKOUT_TRIGGERED",
    "REASON_TRUSTED_DEVICE_REJECTED",
    "REASON_DELETE_VAULT_REQUESTED",
    "REASON_DELETE_VAULT_CONFIRMED",
    "REASON_INACTIVE_UNPAID_DELETED",
    "REASON_UPLOAD_BURST_DETECTED",
    "REASON_DELETE_BURST_DETECTED",
    "REASON_WEBHOOK_SIGNATURE_FAIL",
    "REASON_AUTH_FAILURE_BURST",
    "REASON_INVALID_ORIGIN",
    "REASON_OVERSIZED_REQUEST",
    "ROUTE_GROUP_AUTH",
    "ROUTE_GROUP_PIN",
    "ROUTE_GROUP_CHAT",
    "ROUTE_GROUP_DELETE_VAULT",
    "ROUTE_GROUP_UPLOAD",
    "ROUTE_GROUP_SECURE_ITEM",
    "ROUTE_GROUP_CRYPTO",
    "ROUTE_GROUP_WEBHOOK",
    "ROUTE_GROUP_EXPORT",
    "ROUTE_GROUP_INACTIVE_JOB",
    "short_hash",
    "emit",
]
