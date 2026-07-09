

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Request, status

from rate_limit_backend import RateLimitDecision, get_rate_limit_backend


BUCKET_SIGNUP = "auth_signup"
BUCKET_LOGIN  = "auth_login"


def _env_int(key: str, default: int, *, lo: int = 1, hi: int = 100_000) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


SIGNUP_LIMIT_PER_WINDOW = _env_int("VAULTAI_AUTH_SIGNUP_LIMIT", 20,  lo=1, hi=10_000)
LOGIN_LIMIT_PER_WINDOW  = _env_int("VAULTAI_AUTH_LOGIN_LIMIT",  30,  lo=1, hi=10_000)
WINDOW_SECONDS          = _env_int("VAULTAI_AUTH_WINDOW_SECONDS", 3600, lo=60, hi=86_400)


def _client_ip(request: Request) -> str:


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


def _check(request: Request, *, bucket: str, limit: int) -> RateLimitDecision:
    backend = get_rate_limit_backend()
    ip = _client_ip(request)
    return backend.check_and_increment(
        user_id=f"ip:{ip}",
        bucket=bucket,
        limit_per_window=limit,
        window_seconds=WINDOW_SECONDS,
    )


def enforce_signup_rate_limit(request: Request) -> None:

    decision = _check(request, bucket=BUCKET_SIGNUP, limit=SIGNUP_LIMIT_PER_WINDOW)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code":             "rate_limited",
                "message":          "Too many signup attempts. Try again later.",
                "reset_in_seconds": decision.reset_in_seconds,
            },
            headers={"Retry-After": str(decision.reset_in_seconds)},
        )


def enforce_login_rate_limit(request: Request) -> None:

    decision = _check(request, bucket=BUCKET_LOGIN, limit=LOGIN_LIMIT_PER_WINDOW)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code":             "rate_limited",
                "message":          "Too many login attempts. Try again later.",
                "reset_in_seconds": decision.reset_in_seconds,
            },
            headers={"Retry-After": str(decision.reset_in_seconds)},
        )


__all__ = [
    "BUCKET_SIGNUP",
    "BUCKET_LOGIN",
    "SIGNUP_LIMIT_PER_WINDOW",
    "LOGIN_LIMIT_PER_WINDOW",
    "WINDOW_SECONDS",
    "enforce_signup_rate_limit",
    "enforce_login_rate_limit",
]
