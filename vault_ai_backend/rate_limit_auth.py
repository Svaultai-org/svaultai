

from __future__ import annotations

import os
import ipaddress
from typing import Optional

from fastapi import HTTPException, Request, status

from rate_limit_backend import (
    RateLimitBackend, RateLimitCheck, RateLimitDecision, get_rate_limit_backend,
)
from vault_handle import VAULT_HANDLE_BYTES


BUCKET_SIGNUP = "auth_signup"
BUCKET_LOGIN  = "auth_login"
BUCKET_LOGIN_CREDENTIAL = "auth_login_credential"
BUCKET_LOGIN_VAULT = "auth_login_vault"
BUCKET_LOGIN_FINALIZE = "auth_login_finalize"


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
LOGIN_LIMIT_PER_WINDOW  = _env_int("VAULTAI_AUTH_LOGIN_LIMIT",  10,  lo=1, hi=10_000)
WINDOW_SECONDS          = _env_int("VAULTAI_AUTH_WINDOW_SECONDS", 3600, lo=60, hi=86_400)
LOGIN_WINDOW_SECONDS = _env_int(
    "VAULTAI_AUTH_LOGIN_WINDOW_SECONDS", 60, lo=60, hi=600,
)
LOGIN_CREDENTIAL_LIMIT = _env_int("VAULTAI_AUTH_CREDENTIAL_LIMIT", 6, lo=2, hi=100)
LOGIN_CREDENTIAL_WINDOW_SECONDS = _env_int(
    "VAULTAI_AUTH_CREDENTIAL_WINDOW_SECONDS", 60, lo=30, hi=600,
)
LOGIN_VAULT_LIMIT = _env_int("VAULTAI_AUTH_VAULT_LIMIT", 10, lo=2, hi=100)
LOGIN_VAULT_WINDOW_SECONDS = 60
LOGIN_FINALIZE_LIMIT = _env_int("VAULTAI_AUTH_FINALIZE_LIMIT", 30, lo=2, hi=100)


def _client_ip(request: Request) -> str:
    # ASGI's client must be established by the server's configured, trusted
    # proxy boundary. Never independently trust caller-supplied forwarding
    # headers here: doing so lets an attacker choose a fresh budget per try.
    boundary = os.getenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", "").strip().lower()
    if boundary == "nginx_single_hop":
        # Enable ONLY after proving public ingress terminates at the single
        # Nginx hop, overwrites X-Real-IP with $remote_addr, appends it to XFF,
        # and the backend port is loopback/private. The inherited Uvicorn
        # trusted-all middleware may already have rewritten ASGI's client
        # from a forged LEFTMOST XFF value, so it is not used in this mode.
        real = request.headers.get("x-real-ip", "")
        forwarded = request.headers.get("x-forwarded-for", "")
        if not real or len(real) > 64 or not forwarded or len(forwarded) > 1024:
            return "unknown"
        hops = forwarded.split(",")
        if len(hops) > 16:
            return "unknown"
        try:
            actual = _normalized_ip(real.strip())
            appended = _normalized_ip(hops[-1].strip())
        except (ValueError, TypeError):
            return "unknown"
        return actual if actual == appended else "unknown"
    if boundary not in {"", "none"}:
        # A misspelled security setting must not silently enable a weaker
        # interpretation of an untrusted forwarding header.
        raise HTTPException(
            status_code=503,
            detail={"code": "auth_temporarily_unavailable", "message": "Sign-in is temporarily unavailable. Please try again shortly."},
        )
    raw = request.client.host if request.client else ""
    try:
        return _normalized_ip(raw)
    except (ValueError, TypeError):
        return "unknown"


def _normalized_ip(raw: str) -> str:
    if not isinstance(raw, str) or "%" in raw:
        raise ValueError("invalid rate-limit IP")
    return str(ipaddress.ip_address(raw))


def _check(
    request: Request, *, bucket: str, limit: int, window_seconds: int,
) -> RateLimitDecision:
    backend = get_rate_limit_backend()
    ip = _client_ip(request)
    return backend.check_and_increment(
        user_id=f"ip:{ip}",
        bucket=bucket,
        limit_per_window=limit,
        window_seconds=window_seconds,
    )


def _deny_login(decision: RateLimitDecision) -> None:
    if decision.allowed:
        return
    retry = max(1, int(decision.reset_in_seconds))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limited",
            "message": f"Too many sign-in attempts. Try again in {retry} seconds.",
            "reset_in_seconds": retry,
        },
        headers={"Retry-After": str(retry)},
    )


def _credential_checks(
    *, ip: str, credential_id: bytes, kind: str,
) -> list[RateLimitCheck]:
    expected_length = {"handle": VAULT_HANDLE_BYTES, "lookup": 32}.get(kind)
    if expected_length is None or not isinstance(credential_id, bytes) or len(credential_id) != expected_length:
        raise ValueError("invalid opaque authentication rate-limit identifier")
    opaque_id = credential_id.hex()
    return [
        RateLimitCheck(
            user_id=f"ip:{ip}:{kind}:{opaque_id}",
            bucket=BUCKET_LOGIN_CREDENTIAL,
            limit_per_window=LOGIN_CREDENTIAL_LIMIT,
            window_seconds=LOGIN_CREDENTIAL_WINDOW_SECONDS,
        ),
        RateLimitCheck(
            user_id=f"{kind}:{opaque_id}",
            bucket=BUCKET_LOGIN_VAULT,
            limit_per_window=LOGIN_VAULT_LIMIT,
            window_seconds=LOGIN_VAULT_WINDOW_SECONDS,
        ),
    ]


def _enforce_login_checks(checks: list[RateLimitCheck]) -> None:
    backend = get_rate_limit_backend()
    # Duck-typed legacy test/custom backends may implement only the original
    # single-check method; do not mistake a Mock's synthesized attributes for
    # support for the ordered batch interface.
    if issubclass(type(backend), RateLimitBackend):
        decisions = backend.check_and_increment_many(checks)
        if not decisions or len(decisions) > len(checks):
            _deny_login(RateLimitDecision(
                allowed=False, remaining=0,
                reset_in_seconds=checks[0].window_seconds,
            ))
        for decision in decisions:
            _deny_login(decision)
        if len(decisions) != len(checks):
            _deny_login(RateLimitDecision(
                allowed=False, remaining=0,
                reset_in_seconds=checks[0].window_seconds,
            ))
    else:
        for check in checks:
            _deny_login(backend.check_and_increment(
                user_id=check.user_id, bucket=check.bucket,
                limit_per_window=check.limit_per_window,
                window_seconds=check.window_seconds,
            ))


def enforce_login_init_rate_limits(
    request: Request, *, handle_bytes: bytes, lookup_bytes: Optional[bytes],
) -> None:
    """One ordered init check after cheap syntax decoding, before DB/OPAQUE.

    Malformed wire values must still call enforce_login_rate_limit before
    returning their validation error. This valid-ID helper consumes IP once,
    then the same handle and lookup budgets used by the single-check helpers.
    """
    ip = _client_ip(request)
    checks = [RateLimitCheck(
        user_id=f"ip:{ip}", bucket=BUCKET_LOGIN,
        limit_per_window=LOGIN_LIMIT_PER_WINDOW,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )]
    checks.extend(_credential_checks(ip=ip, credential_id=handle_bytes, kind="handle"))
    if lookup_bytes is not None:
        checks.extend(_credential_checks(ip=ip, credential_id=lookup_bytes, kind="lookup"))
    _enforce_login_checks(checks)


def enforce_login_credential_rate_limit(
    request: Request, *, credential_id: bytes, kind: str,
) -> None:
    """Short budget scoped to source AND an opaque client identifier.

    The limiter is consulted before account lookup for known/unknown IDs
    alike. Source and vault budgets expire automatically; no persistent
    account lock is changed, and PINs never enter limiter keys. Each
    wrong modern OPAQUE PIN may use two exchanges for old-record
    compatibility, so the default six exchanges permits three such tries.
    """
    # Bound distributed attempts at this opaque vault identifier as well.
    # Modern and legacy exchanges using the same lookup share this key.
    # Rejected global checks do not refresh the global window; each source
    # attempt still counts against its own budget before this shared check.
    _enforce_login_checks(_credential_checks(
        ip=_client_ip(request), credential_id=credential_id, kind=kind,
    ))


def enforce_login_finalize_rate_limit(request: Request) -> None:
    # Finalize does not consume the init budget a second time. A separate
    # source budget also bounds forged slot/proof submissions before DB/OPAQUE.
    decision = get_rate_limit_backend().check_and_increment(
        user_id=f"ip:{_client_ip(request)}",
        bucket=BUCKET_LOGIN_FINALIZE,
        limit_per_window=LOGIN_FINALIZE_LIMIT,
        window_seconds=LOGIN_CREDENTIAL_WINDOW_SECONDS,
    )
    _deny_login(decision)


def enforce_signup_rate_limit(request: Request) -> None:

    decision = _check(
        request, bucket=BUCKET_SIGNUP, limit=SIGNUP_LIMIT_PER_WINDOW,
        window_seconds=WINDOW_SECONDS,
    )
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
    decision = _check(
        request, bucket=BUCKET_LOGIN, limit=LOGIN_LIMIT_PER_WINDOW,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )
    _deny_login(decision)


__all__ = [
    "BUCKET_SIGNUP",
    "BUCKET_LOGIN",
    "BUCKET_LOGIN_VAULT",
    "SIGNUP_LIMIT_PER_WINDOW",
    "LOGIN_LIMIT_PER_WINDOW",
    "LOGIN_WINDOW_SECONDS",
    "WINDOW_SECONDS",
    "enforce_signup_rate_limit",
    "enforce_login_rate_limit",
    "enforce_login_credential_rate_limit",
    "enforce_login_init_rate_limits",
    "enforce_login_finalize_rate_limit",
]
