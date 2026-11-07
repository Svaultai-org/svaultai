"""Reject replaced PIN routes before reading an offered session's body.

The signed v3/v4 bearer MAC is checked without a database lookup or ASGI receive.
Other sessions retain their existing routes. This gate does not stop bytes from
reaching the reverse proxy; it prevents the API from parsing those bodies.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from starlette.responses import JSONResponse

from auth_local import (
    PIN_FREE_BENEFICIARY_OFFER,
    PIN_FREE_FILE_CREATE_OFFER,
    PIN_FREE_FILE_DOWNLOAD_OFFER,
    PIN_FREE_FILE_LIST_OFFER,
    PIN_FREE_PASSWORD_ANALYSIS_OFFER,
    PIN_FREE_PRIVATE_CHAT_OFFER,
    _parse_token_claims,
)


_DEEP_JOB = re.compile(r"^/vault-analysis/deep-answer/[^/]+/(?:poll|debug)$")
_RELATED_FILE = re.compile(r"^/files/[^/]+/related$")


def _replaced_private_chat_path(path: str) -> bool:
    path = path.rstrip("/")
    return (path in ("/chat", "/vault-analysis/deep-answer") or
            _DEEP_JOB.fullmatch(path) is not None or
            _RELATED_FILE.fullmatch(path) is not None)


def _signed_offer_bits(headers: list[tuple[bytes, bytes]]) -> int:
    # Inspect every Authorization field: a duplicate header must not turn an
    # offered bearer into a legacy-compatible request at this boundary.
    offers = 0
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
            offers |= claims[1]
    return offers


def _replaced_pin_route(path: str, offers: int) -> str | None:
    path = path.rstrip("/")
    if (offers & PIN_FREE_BENEFICIARY_OFFER and
            path in ("/beneficiary/create", "/beneficiary/link",
                     "/beneficiary/request-transfer",
                     "/beneficiary/claim-transfer")):
        return "pin_free_beneficiary_required"
    if (offers & PIN_FREE_PASSWORD_ANALYSIS_OFFER and
            path == "/security-center/analyze-passwords"):
        return "pin_free_password_analysis_required"
    if (offers & PIN_FREE_PRIVATE_CHAT_OFFER and
            _replaced_private_chat_path(path)):
        return "pin_free_private_chat_required"
    if (offers & PIN_FREE_FILE_LIST_OFFER and
            (path == "/list-files" or _RELATED_FILE.fullmatch(path))):
        return "pin_free_read_required"
    if (offers & PIN_FREE_FILE_DOWNLOAD_OFFER and
            (path in ("/download-file", "/download-file/manifest") or
             _RELATED_FILE.fullmatch(path))):
        return "pin_free_read_required"
    if (offers & PIN_FREE_FILE_CREATE_OFFER and
            path in ("/upload-file", "/upload-file/init",
                     "/upload-file/finalize", "/upload-file/abort")):
        return "pin_free_file_create_required"
    return None


def _candidate_pin_path(path: str) -> bool:
    path = path.rstrip("/")
    return (_replaced_private_chat_path(path) or
            path in ("/beneficiary/create", "/beneficiary/link",
                     "/beneficiary/request-transfer",
                     "/beneficiary/claim-transfer") or
            path == "/security-center/analyze-passwords" or
            path in ("/list-files", "/download-file", "/download-file/manifest",
                     "/upload-file", "/upload-file/init",
                     "/upload-file/finalize", "/upload-file/abort"))


class SignedPrivateChatPreBodyGate:
    """Keep issued file and chat offers PIN-free despite later flag changes."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        reason = None
        if (scope.get("type") == "http" and scope.get("method") == "POST" and
                _candidate_pin_path(scope.get("path", ""))):
            offers = _signed_offer_bits(scope.get("headers", []))
            reason = _replaced_pin_route(scope.get("path", ""), offers)
        if reason is not None:
            response = JSONResponse(
                status_code=409,
                content={"detail": reason},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
