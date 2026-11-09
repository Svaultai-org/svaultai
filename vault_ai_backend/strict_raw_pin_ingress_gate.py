"""Default-off, body-free cutover fences for the old authentication PIN API.

The login-only switch blocks pre-OPAQUE sign-in. The route-only switch blocks
every inventoried legacy route while leaving OPAQUE finalize available. The
original strict switch also rejects incompatible OPAQUE finalize calls.
All modes decide from ASGI scope alone and never call ``receive`` for a
blocked request. The proxy and transport can still have received bytes;
client-side network tests remain necessary.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.routing import compile_path


FLAG_NAME = "VAULTAI_STRICT_RAW_PIN_INGRESS_ENABLED"
LEGACY_ROUTES_FLAG_NAME = "VAULTAI_LEGACY_PIN_ROUTES_DISABLED"
LEGACY_LOGIN_FLAG_NAME = "VAULTAI_LEGACY_PIN_LOGIN_DISABLED"
STRICT_CLIENT_CAPABILITY_HEADER = b"x-svaultai-strict-pin-free-client"
UPGRADE_DETAIL = {
    "code": "client_upgrade_required",
    "message": "Update SVaultAI to continue with private access.",
}

# Reviewed method/path inventory from the registered FastAPI body models.
# Include optional PINs, router prefixes, aliases, and the three routes
# registered only when VAULTAI_CHUNKED_UPLOADS=true. A test compares this
# manifest to the live route models, so new PIN fields cannot go unnoticed.
LEGACY_PIN_ROUTES: frozenset[tuple[str, str]] = frozenset({
    # Authentication and vault metadata.
    ("POST", "/auth/login"),
    ("POST", "/get-or-create-vault-meta"),
    ("POST", "/verify-pin"),
    ("POST", "/rotate-vault-kdf"),
    ("POST", "/vault-stats"),
    # Saved items and legacy crypto records.
    ("POST", "/list-login-names"),
    ("POST", "/get-login"),
    ("POST", "/delete-login"),
    ("POST", "/login-count"),
    ("POST", "/update-secure-item"),
    ("POST", "/get-secure-item"),
    ("POST", "/delete-secure-item"),
    ("POST", "/list-secure-items"),
    ("POST", "/crypto/save-wallet-profile"),
    ("POST", "/crypto/save-sensitive-backup"),
    ("POST", "/crypto/reveal-sensitive-backup"),
    ("POST", "/crypto/save-note"),
    # Vault management aliases.
    ("POST", "/manage/list-login-names"),
    ("POST", "/manage/list-secure-items"),
    ("POST", "/manage/logins-full"),
    ("PATCH", "/manage/login"),
    ("DELETE", "/manage/login"),
    ("POST", "/manage/login/delete"),
    ("PATCH", "/manage/file"),
    ("DELETE", "/manage/file"),
    ("POST", "/manage/file/delete"),
    # Device approval and Security Center.
    ("POST", "/devices/request-self-approval"),
    ("POST", "/devices/finalize-self-approval"),
    ("POST", "/security-center/analyze-passwords"),
    # Memory.
    ("POST", "/memory/list"),
    ("POST", "/memory/create"),
    ("POST", "/memory/update"),
    ("POST", "/memory/delete"),
    # Files and related lookup.
    ("POST", "/download-file/manifest"),
    ("POST", "/vault/file/{file_id}/text"),
    ("POST", "/files/{file_id}/related"),
    ("POST", "/upload-file"),
    ("POST", "/name-file"),
    ("POST", "/list-files"),
    ("POST", "/download-file"),
    ("DELETE", "/delete-file"),
    ("POST", "/upload-file/init"),
    ("POST", "/upload-file/finalize"),
    ("POST", "/upload-file/abort"),
    # Imports and analysis.
    ("POST", "/imports/start"),
    ("POST", "/imports/{import_id}/cancel"),
    ("POST", "/imports/{import_id}/complete"),
    ("POST", "/vault-analysis/coverage"),
    ("POST", "/vault-analysis/drain-text-extraction"),
    ("POST", "/vault-analysis/backfill-chunked-text-extraction"),
    ("POST", "/vault-analysis/backfill-archive-signals"),
    ("POST", "/vault-analysis/deep-answer"),
    ("POST", "/vault-analysis/deep-answer/{job_id}/poll"),
    ("POST", "/vault-analysis/deep-answer/{job_id}/debug"),
    # Chat, inheritance and vault deletion.
    ("POST", "/chat"),
    ("POST", "/beneficiary/create"),
    ("POST", "/beneficiary/link"),
    ("POST", "/beneficiary/list-mine"),
    ("POST", "/beneficiary/list-inheritances"),
    ("POST", "/beneficiary/request-transfer"),
    ("POST", "/beneficiary/cancel-transfer"),
    ("POST", "/beneficiary/claim-transfer"),
    ("POST", "/beneficiary/delete"),
    ("POST", "/vault/delete/confirm"),
})

# This retired endpoint no longer declares a request body, so it is absent
# from the registered-body-model inventory above. Older clients still send a
# PIN on its wire contract; strict mode must reject it before any app read.
RETIRED_PIN_SENDING_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/auth/signup"),
})

_ROUTE_PATTERNS = tuple(
    (method, compile_path(path)[0])
    for method, path in sorted(LEGACY_PIN_ROUTES | RETIRED_PIN_SENDING_ROUTES)
)


def strict_raw_pin_ingress_enabled() -> bool:
    return os.getenv(FLAG_NAME, "false").strip().lower() == "true"


def legacy_pin_routes_disabled() -> bool:
    """Block old PIN routes without changing OPAQUE finalize compatibility."""
    return os.getenv(LEGACY_ROUTES_FLAG_NAME, "false").strip().lower() == "true"


def legacy_pin_login_disabled() -> bool:
    """Block the pre-OPAQUE login route without affecting other requests."""
    return os.getenv(LEGACY_LOGIN_FLAG_NAME, "false").strip().lower() == "true"


def _has_strict_private_client_signal(headers) -> bool:
    values = [value.strip() for name, value in headers
              if name.lower() == STRICT_CLIENT_CAPABILITY_HEADER]
    return values == [b"v1"]


def require_strict_private_client(request: Request) -> None:
    """Reject older OPAQUE finalize calls before slot/session mutation.

    The exact header is a compatibility signal, not client attestation or
    permission for sensitive routes. OPAQUE, server-signed offers, and route
    authorization remain independent requirements.
    """
    if not strict_raw_pin_ingress_enabled():
        return
    if not _has_strict_private_client_signal(
        request.scope.get("headers", ()),
    ):
        raise HTTPException(
            status_code=426, detail=UPGRADE_DETAIL,
            headers={"Cache-Control": "no-store"},
        )


def is_legacy_pin_route(method: str, path: str) -> bool:
    canonical_path = path.rstrip("/") or "/"
    return any(
        method == candidate_method and pattern.match(canonical_path)
        for candidate_method, pattern in _ROUTE_PATTERNS
    )


class StrictRawPinIngressGate:
    """Reject selected old PIN routes before the app reads their body."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            strict = strict_raw_pin_ingress_enabled()
            block_routes = strict or legacy_pin_routes_disabled()
            block_login = legacy_pin_login_disabled()
            old_finalize = (
                strict and
                method == "POST" and
                path.rstrip("/") in {
                    "/auth/zk-login-finalize",
                    "/auth/zk-register-finalize",
                } and
                not _has_strict_private_client_signal(scope.get("headers", ()))
            )
            old_login = (
                block_login and method == "POST" and
                path.rstrip("/") == "/auth/login"
            )
            if not (
                old_finalize or old_login or
                (block_routes and is_legacy_pin_route(method, path))
            ):
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                status_code=426,
                content={"detail": UPGRADE_DETAIL},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
