"""Optional pre-body fence for old PIN routes superseded by signed offers.

The current auth dependency rejects these routes after FastAPI has parsed the
request body. This ASGI middleware makes the same route decision from the MAC
on an OPAQUE offer bearer before the body reaches a parser. It is scoped to
offered sessions; older bearers keep their existing access. It cannot stop a
network peer from sending bytes to the web server in the first place.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from fastapi import HTTPException
from starlette.responses import JSONResponse


FLAG_NAME = "VAULTAI_SIGNED_OFFER_PREBODY_PIN_FENCE_ENABLED"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def enabled() -> bool:
    value = os.getenv(FLAG_NAME, "false").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    # A typo in an enabled security fence must fail closed.
    raise RuntimeError("Invalid signed-offer pre-body PIN fence configuration")


def _signed_offer_bits(headers) -> int:
    from auth_local import _parse_token_claims

    # Inspect every Authorization header. A duplicate valid signed bearer
    # cannot be hidden behind a second old or malformed bearer.
    bits = 0
    for name, value in headers:
        if name.lower() != b"authorization":
            continue
        try:
            scheme, token = value.decode("ascii").strip().split(None, 1)
        except (UnicodeDecodeError, ValueError):
            continue
        if scheme.lower() != "bearer":
            continue
        claims = _parse_token_claims(token.strip())
        if claims is not None:
            bits |= claims[1]
    return bits


class SignedOfferPrebodyPinFence:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if (scope.get("type") != "http" or
                scope.get("method") not in ("POST", "PATCH", "DELETE") or
                not enabled()):
            await self.app(scope, receive, send)
            return
        bits = _signed_offer_bits(scope.get("headers", ()))
        if bits:
            from auth_local import require_signed_offer_route

            path = scope.get("path", "").rstrip("/")
            try:
                require_signed_offer_route(
                    {"pin_free_read_offers": bits}, path=path,
                )
            except HTTPException as exc:
                response = JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
