

from __future__ import annotations

import os

from fastapi import HTTPException, status

from rate_limit_backend import get_rate_limit_backend


BUCKET_CRYPTO_REVEAL = "crypto_reveal_sensitive_backup"


def _env_int(key: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


CRYPTO_REVEAL_LIMIT_PER_WINDOW = _env_int(
    "VAULTAI_CRYPTO_REVEAL_LIMIT",
    default=5, lo=1, hi=10_000,
)
CRYPTO_REVEAL_WINDOW_SECONDS = _env_int(
    "VAULTAI_CRYPTO_REVEAL_WINDOW_SECONDS",
    default=60, lo=5, hi=3600,
)


def enforce_crypto_reveal_rate_limit(vault_id: str) -> None:


    backend = get_rate_limit_backend()
    decision = backend.check_and_increment(
        user_id=str(vault_id),
        bucket=BUCKET_CRYPTO_REVEAL,
        limit_per_window=CRYPTO_REVEAL_LIMIT_PER_WINDOW,
        window_seconds=CRYPTO_REVEAL_WINDOW_SECONDS,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "reveal_error":     "rate_limited",
                "reset_in_seconds": decision.reset_in_seconds,
            },
            headers={"Retry-After": str(decision.reset_in_seconds)},
        )


__all__ = [
    "BUCKET_CRYPTO_REVEAL",
    "CRYPTO_REVEAL_LIMIT_PER_WINDOW",
    "CRYPTO_REVEAL_WINDOW_SECONDS",
    "enforce_crypto_reveal_rate_limit",
]
