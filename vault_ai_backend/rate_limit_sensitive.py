"""Rate limits for sensitive/expensive routes.

Sits on top of rate_limit_backend so it uses the same backend (in-
memory dev / Redis prod). Buckets are separate from the auth ones
in rate_limit_auth so a burst on one route doesn't drain another's
budget.

Buckets:
  * pin_verify   — /verify-pin and PIN checks against a specific vault
  * chat         — /chat expensive completions
  * delete_vault — /vault/delete/* endpoints
  * upload_burst — mass-upload anomaly rate limit
  * delete_burst — mass-delete anomaly rate limit
  * export       — vault export / large read

Error shape mirrors rate_limit_auth: HTTPException(429) with a
"code": "rate_limited" body and Retry-After. Message NEVER reveals
whether the account/vault exists.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException, Request, status

from rate_limit_backend import (
    RateLimitDecision,
    get_rate_limit_backend,
)


logger = logging.getLogger(__name__)


BUCKET_PIN_VERIFY:    str = "pin_verify"
BUCKET_CHAT:          str = "chat"
BUCKET_DELETE_VAULT:  str = "delete_vault"
BUCKET_UPLOAD_BURST:  str = "upload_burst"
BUCKET_DELETE_BURST:  str = "delete_burst"
BUCKET_EXPORT:        str = "export"


ALL_BUCKETS: frozenset[str] = frozenset({
    BUCKET_PIN_VERIFY,
    BUCKET_CHAT,
    BUCKET_DELETE_VAULT,
    BUCKET_UPLOAD_BURST,
    BUCKET_DELETE_BURST,
    BUCKET_EXPORT,
})


def _env_int(key: str, default: int, *, lo: int = 1, hi: int = 100_000) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


PIN_VERIFY_LIMIT_PER_WINDOW:   int = _env_int(
    "VAULTAI_RL_PIN_VERIFY_LIMIT", 30, lo=1, hi=10_000,
)
PIN_VERIFY_WINDOW_SECONDS:     int = _env_int(
    "VAULTAI_RL_PIN_VERIFY_WINDOW_SECONDS", 3600, lo=60, hi=86_400,
)


CHAT_LIMIT_PER_WINDOW:         int = _env_int(
    "VAULTAI_RL_CHAT_LIMIT", 120, lo=1, hi=100_000,
)
CHAT_WINDOW_SECONDS:           int = _env_int(
    "VAULTAI_RL_CHAT_WINDOW_SECONDS", 600, lo=30, hi=86_400,
)


DELETE_VAULT_LIMIT_PER_WINDOW: int = _env_int(
    "VAULTAI_RL_DELETE_VAULT_LIMIT", 10, lo=1, hi=1_000,
)
DELETE_VAULT_WINDOW_SECONDS:   int = _env_int(
    "VAULTAI_RL_DELETE_VAULT_WINDOW_SECONDS", 3600, lo=60, hi=86_400,
)


UPLOAD_BURST_LIMIT_PER_WINDOW: int = _env_int(
    "VAULTAI_RL_UPLOAD_BURST_LIMIT", 100, lo=1, hi=100_000,
)
UPLOAD_BURST_WINDOW_SECONDS:   int = _env_int(
    "VAULTAI_RL_UPLOAD_BURST_WINDOW_SECONDS", 60, lo=5, hi=3_600,
)


DELETE_BURST_LIMIT_PER_WINDOW: int = _env_int(
    "VAULTAI_RL_DELETE_BURST_LIMIT", 50, lo=1, hi=10_000,
)
DELETE_BURST_WINDOW_SECONDS:   int = _env_int(
    "VAULTAI_RL_DELETE_BURST_WINDOW_SECONDS", 60, lo=5, hi=3_600,
)


EXPORT_LIMIT_PER_WINDOW:       int = _env_int(
    "VAULTAI_RL_EXPORT_LIMIT", 5, lo=1, hi=1_000,
)
EXPORT_WINDOW_SECONDS:         int = _env_int(
    "VAULTAI_RL_EXPORT_WINDOW_SECONDS", 3600, lo=60, hi=86_400,
)


_GENERIC_429_MESSAGE = "Too many requests. Please wait and try again."


def client_ip(request: Request) -> str:

    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip")
    if real:
        real = real.strip()
        if real:
            return real
    return (request.client.host if request.client else "unknown") or "unknown"


def _hashed_id(raw: str) -> str:
    import hashlib
    if not raw:
        return "anon"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _enforce(
    *,
    key_id: str,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:

    backend = get_rate_limit_backend()
    decision = backend.check_and_increment(
        user_id=key_id,
        bucket=bucket,
        limit_per_window=limit,
        window_seconds=window_seconds,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code":             "rate_limited",
                "message":          _GENERIC_429_MESSAGE,
                "reset_in_seconds": decision.reset_in_seconds,
            },
            headers={"Retry-After": str(decision.reset_in_seconds)},
        )
    return decision


def enforce_pin_verify_rate_limit(
    request: Request,
    *,
    vault_id: str,
) -> RateLimitDecision:
    """Per-vault + per-IP rate limit on PIN verification. Composes
    with the vault's own failed_pin_attempts lockout — this limit
    protects against distributed guesses across multiple vaults
    from the same IP."""

    ip = client_ip(request)
    return _enforce(
        key_id=f"pin:{_hashed_id(vault_id)}:{ip}",
        bucket=BUCKET_PIN_VERIFY,
        limit=PIN_VERIFY_LIMIT_PER_WINDOW,
        window_seconds=PIN_VERIFY_WINDOW_SECONDS,
    )


def enforce_chat_rate_limit(
    request: Request,
    *,
    vault_id: str,
) -> RateLimitDecision:
    """Per-vault rate limit on /chat. Expensive completion calls
    are the most abusable route in the app — a small window
    keeps token cost bounded per user."""

    ip = client_ip(request)
    return _enforce(
        key_id=f"chat:{_hashed_id(vault_id)}:{ip}",
        bucket=BUCKET_CHAT,
        limit=CHAT_LIMIT_PER_WINDOW,
        window_seconds=CHAT_WINDOW_SECONDS,
    )


def enforce_delete_vault_rate_limit(
    request: Request,
    *,
    vault_id: Optional[str] = None,
) -> RateLimitDecision:
    """Per-IP + optional per-vault rate limit on the delete flow.
    Very tight; a legitimate user needs at most a handful of
    requests across status/request/confirm."""

    ip = client_ip(request)
    key = f"del:{ip}"
    if vault_id:
        key = f"del:{_hashed_id(vault_id)}:{ip}"
    return _enforce(
        key_id=key,
        bucket=BUCKET_DELETE_VAULT,
        limit=DELETE_VAULT_LIMIT_PER_WINDOW,
        window_seconds=DELETE_VAULT_WINDOW_SECONDS,
    )


def enforce_upload_burst_rate_limit(
    *,
    vault_id: str,
) -> RateLimitDecision:
    """Per-vault upload-count-per-minute cap for the mass-upload
    anomaly guard. Legitimate bulk imports use the import batch
    flow, which is exempt."""

    return _enforce(
        key_id=f"up:{_hashed_id(vault_id)}",
        bucket=BUCKET_UPLOAD_BURST,
        limit=UPLOAD_BURST_LIMIT_PER_WINDOW,
        window_seconds=UPLOAD_BURST_WINDOW_SECONDS,
    )


def enforce_delete_burst_rate_limit(
    *,
    vault_id: str,
) -> RateLimitDecision:
    """Per-vault delete-count-per-minute cap. Protects against a
    compromised session mass-deleting items."""

    return _enforce(
        key_id=f"delb:{_hashed_id(vault_id)}",
        bucket=BUCKET_DELETE_BURST,
        limit=DELETE_BURST_LIMIT_PER_WINDOW,
        window_seconds=DELETE_BURST_WINDOW_SECONDS,
    )


def enforce_export_rate_limit(
    *,
    vault_id: str,
) -> RateLimitDecision:
    return _enforce(
        key_id=f"exp:{_hashed_id(vault_id)}",
        bucket=BUCKET_EXPORT,
        limit=EXPORT_LIMIT_PER_WINDOW,
        window_seconds=EXPORT_WINDOW_SECONDS,
    )


__all__ = [
    "BUCKET_PIN_VERIFY",
    "BUCKET_CHAT",
    "BUCKET_DELETE_VAULT",
    "BUCKET_UPLOAD_BURST",
    "BUCKET_DELETE_BURST",
    "BUCKET_EXPORT",
    "ALL_BUCKETS",
    "PIN_VERIFY_LIMIT_PER_WINDOW",
    "PIN_VERIFY_WINDOW_SECONDS",
    "CHAT_LIMIT_PER_WINDOW",
    "CHAT_WINDOW_SECONDS",
    "DELETE_VAULT_LIMIT_PER_WINDOW",
    "DELETE_VAULT_WINDOW_SECONDS",
    "UPLOAD_BURST_LIMIT_PER_WINDOW",
    "UPLOAD_BURST_WINDOW_SECONDS",
    "DELETE_BURST_LIMIT_PER_WINDOW",
    "DELETE_BURST_WINDOW_SECONDS",
    "EXPORT_LIMIT_PER_WINDOW",
    "EXPORT_WINDOW_SECONDS",
    "client_ip",
    "enforce_pin_verify_rate_limit",
    "enforce_chat_rate_limit",
    "enforce_delete_vault_rate_limit",
    "enforce_upload_burst_rate_limit",
    "enforce_delete_burst_rate_limit",
    "enforce_export_rate_limit",
]
