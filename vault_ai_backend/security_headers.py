"""HTTP security-header middleware for VaultAI.

Adds a conservative set of response headers to every non-preflight
response. Enabled by default; can be disabled per env for local
debugging via VAULTAI_SECURITY_HEADERS_ENABLED=false.

Headers set:
  * X-Content-Type-Options: nosniff
  * Referrer-Policy: no-referrer
  * Permissions-Policy: neutered set (no geolocation, mic, cam, etc.)
  * X-Frame-Options: DENY
  * Content-Security-Policy: strict default that permits only self,
    disallows inline scripts, and denies eval and framing.
  * Strict-Transport-Security: preload+includeSubDomains+2y max-age,
    ONLY in production (never for dev/local).
  * Cross-Origin-Opener-Policy: same-origin
  * Cross-Origin-Resource-Policy: same-origin

Sensitive responses (auth, PIN, delete, secure item reveal, etc.)
also get a strict Cache-Control:
    Cache-Control: no-store, no-cache, must-revalidate, private
    Pragma: no-cache
    Expires: 0

The header set is intentionally static (no per-request branching)
so a bug can't downgrade an individual response's protection.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


CSP_STRICT: str = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' https:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


PERMISSIONS_POLICY: str = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(self), geolocation=(), "
    "gyroscope=(), magnetometer=(), microphone=(), midi=(), "
    "payment=(), picture-in-picture=(), publickey-credentials-get=(), "
    "screen-wake-lock=(), sync-xhr=(), usb=(), xr-spatial-tracking=()"
)


HSTS_VALUE: str = "max-age=63072000; includeSubDomains; preload"


# 2026-07-26 diagnostic build headers. Non-sensitive by design — they
# expose only the currently-running backend release and, for /chat,
# the exit-path enum chat_endpoint took. Purpose: give the operator a
# per-response ground-truth signal about which build actually handled
# the request. Even if logs are being silenced or routed elsewhere,
# a `curl -I` (or the browser dev-tools Network tab) reveals the
# release SHA and the exact chat path.
#
# Values are drawn from environment variables set at container start
# so a rebuild is not required to update them:
#   VAULTAI_RELEASE_SHA — short git SHA of the currently-running
#                        image. Defaults to "dev" when unset.
_RELEASE_HEADER: str = "X-VaultAI-Backend-Release"
_CHAT_PATH_HEADER: str = "X-VaultAI-Chat-Path"

# Fixed enum of chat-path values a request can be tagged with. Kept
# small and stable so operators can build monitors around them.
CHAT_PATH_STATE_MACHINE_UPDATED   = "state_machine_updated"
CHAT_PATH_STATE_MACHINE_SHOWN     = "state_machine_shown"
CHAT_PATH_STATE_MACHINE_CANCELLED = "state_machine_cancelled"
CHAT_PATH_STATE_MACHINE_REPLACED  = "state_machine_replaced"
CHAT_PATH_STATE_MACHINE_SAVED     = "state_machine_saved"
CHAT_PATH_AI_PLANNER_DIRECT       = "ai_planner_direct"
CHAT_PATH_AI_PLANNER_FALLBACK     = "ai_planner_fallback"
CHAT_PATH_ENCRYPTED_REPLY         = "encrypted_reply"
CHAT_PATH_UNKNOWN                 = "unknown"
# 2026-07-27 deterministic-router chat paths. Emitted by
# vault_chat_deterministic_router when it fully resolves a chat turn
# before the OpenAI planner runs. The four values are a closed set;
# any router branch that does not fit falls through with no header
# change and the existing planner tags it.
CHAT_PATH_DETERMINISTIC_FOLLOWUP          = "deterministic_followup"
CHAT_PATH_DETERMINISTIC_NAMED_OBJECT      = "deterministic_named_object"
CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS   = "deterministic_named_ambiguous"
CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE = "deterministic_credential_create"


def _release_sha() -> str:
    return os.getenv("VAULTAI_RELEASE_SHA", "dev").strip()[:16] or "dev"


SENSITIVE_PATH_PREFIXES: tuple[str, ...] = (
    "/auth/",
    "/verify-pin",
    "/vault/delete/",
    "/logins/",
    "/secure-items/",
    "/ids/",
    "/crypto/reveal",
    "/crypto/save-sensitive",
    "/billing/",
    "/manage/",
    "/get-login",
    "/reveal-",
    # 2026-07-21 root-cause fix for the "first chat forces PIN"
    # production incident. /vault-meta is the authoritative source of
    # (pin_salt, kdf_iterations) that the client uses to derive the
    # per-session PBKDF2 vault key. Without a strict no-store, the
    # browser (and any intermediate cache) is free to serve a
    # previous response body from disk after a rotation has moved
    # the DB to a new salt — the client re-derives from the STALE
    # cached salt while the server derives from the CURRENT salt,
    # decrypt fails at vault_core.decrypt_message with 400
    # "Invalid PIN or corrupted data", InvalidVaultUnlockException
    # trips on the client, and the user is forced back to /pin even
    # though they entered the correct PIN. The route is
    # session-authenticated, per-user, and MUST always reflect the
    # current row — never a cached one.
    "/vault-meta",
)


NO_STORE_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _headers_enabled() -> bool:
    raw = os.getenv(
        "VAULTAI_SECURITY_HEADERS_ENABLED", "true",
    ).strip().lower()
    return raw != "false"


def _is_production() -> bool:
    env_tokens = ("prod", "production", "live")
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        if os.getenv(var, "").strip().lower() in env_tokens:
            return True
    return False


def _is_sensitive_path(path: str) -> bool:
    if not path:
        return False
    for prefix in SENSITIVE_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def apply_security_headers(response: Response, path: str) -> None:
    """Public helper — mutates `response.headers` in place. Exposed
    for tests and for callers that want to add headers to a
    response they construct directly (not via the middleware)."""

    response.headers.setdefault(
        "X-Content-Type-Options", "nosniff",
    )
    response.headers.setdefault(
        "Referrer-Policy", "no-referrer",
    )
    response.headers.setdefault(
        "Permissions-Policy", PERMISSIONS_POLICY,
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy", CSP_STRICT,
    )
    response.headers.setdefault(
        "Cross-Origin-Opener-Policy", "same-origin",
    )
    response.headers.setdefault(
        "Cross-Origin-Resource-Policy", "same-origin",
    )

    if _is_production():
        response.headers.setdefault(
            "Strict-Transport-Security", HSTS_VALUE,
        )

    if _is_sensitive_path(path):
        for k, v in NO_STORE_CACHE_HEADERS.items():
            response.headers[k] = v

    # 2026-07-26 diagnostic — always tag every response with the
    # running backend release SHA. Non-sensitive; the value is chosen
    # per deploy and does not depend on the request.
    response.headers.setdefault(_RELEASE_HEADER, _release_sha())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        response: Response = await call_next(request)
        if not _headers_enabled():
            return response
        if request.method == "OPTIONS":

            return response
        apply_security_headers(response, request.url.path or "")

        # 2026-07-26 diagnostic — if chat_endpoint tagged the request
        # with a chat_path enum, surface it as a response header. Read
        # via getattr because Starlette's request.state is a lazy
        # SimpleNamespace and may not have the attribute for non-chat
        # requests. Never touches sensitive content — the value is a
        # closed-set enum from security_headers.CHAT_PATH_*.
        try:
            _chat_path = getattr(
                request.state, "chat_path",
                CHAT_PATH_UNKNOWN,
            )
        except Exception:
            _chat_path = CHAT_PATH_UNKNOWN
        if isinstance(_chat_path, str) and _chat_path:
            response.headers.setdefault(_CHAT_PATH_HEADER, _chat_path)

        return response


__all__ = [
    "CSP_STRICT",
    "PERMISSIONS_POLICY",
    "HSTS_VALUE",
    "SENSITIVE_PATH_PREFIXES",
    "NO_STORE_CACHE_HEADERS",
    "apply_security_headers",
    "SecurityHeadersMiddleware",
    "CHAT_PATH_STATE_MACHINE_UPDATED",
    "CHAT_PATH_STATE_MACHINE_SHOWN",
    "CHAT_PATH_STATE_MACHINE_CANCELLED",
    "CHAT_PATH_STATE_MACHINE_REPLACED",
    "CHAT_PATH_STATE_MACHINE_SAVED",
    "CHAT_PATH_AI_PLANNER_DIRECT",
    "CHAT_PATH_AI_PLANNER_FALLBACK",
    "CHAT_PATH_ENCRYPTED_REPLY",
    "CHAT_PATH_UNKNOWN",
    "CHAT_PATH_DETERMINISTIC_FOLLOWUP",
    "CHAT_PATH_DETERMINISTIC_NAMED_OBJECT",
    "CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS",
    "CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE",
]
