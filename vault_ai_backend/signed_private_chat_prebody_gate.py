"""Reject replaced PIN routes before reading an offered session's body.

The signed v4 bearer MAC is checked without a database lookup or ASGI receive.
Other sessions retain their existing routes. This gate does not stop bytes from
reaching the reverse proxy; it prevents the API from parsing those bodies.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from starlette.responses import JSONResponse

from auth_local import PIN_FREE_PRIVATE_CHAT_OFFER, _parse_token_claims


_DEEP_JOB = re.compile(r"^/vault-analysis/deep-answer/[^/]+/(?:poll|debug)$")
_RELATED_FILE = re.compile(r"^/files/[^/]+/related$")


def _replaced_private_chat_path(path: str) -> bool:
    path = path.rstrip("/")
    return (path in ("/chat", "/vault-analysis/deep-answer") or
            _DEEP_JOB.fullmatch(path) is not None or
            _RELATED_FILE.fullmatch(path) is not None)


def _has_signed_private_chat_offer(headers: list[tuple[bytes, bytes]]) -> bool:
    # Inspect every Authorization field: a duplicate header must not turn an
    # offered bearer into a legacy-compatible request at this boundary.
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
        if claims is not None and claims[1] & PIN_FREE_PRIVATE_CHAT_OFFER:
            return True
    return False


class SignedPrivateChatPreBodyGate:
    """Keep an issued private-chat offer PIN-free even if issuance is disabled."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if (scope.get("type") == "http" and scope.get("method") == "POST" and
                _replaced_private_chat_path(scope.get("path", "")) and
                _has_signed_private_chat_offer(scope.get("headers", []))):
            response = JSONResponse(
                status_code=409,
                content={"detail": "pin_free_private_chat_required"},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
