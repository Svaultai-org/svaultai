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
    PIN_FREE_FILE_MUTATION_OFFER,
    PIN_FREE_ITEM_READ_OFFER,
    PIN_FREE_PASSWORD_ANALYSIS_OFFER,
    PIN_FREE_PRIVATE_CHAT_OFFER,
    _parse_token_claims,
)


_DEEP_JOB = re.compile(r"^/vault-analysis/deep-answer/[^/]+/(?:poll|debug)$")
_RELATED_FILE = re.compile(r"^/files/[^/]+/related$")
_OLD_FILE_MUTATIONS = {
    ("POST", "/name-file"),
    ("PATCH", "/manage/file"),
    ("DELETE", "/manage/file"),
    ("POST", "/manage/file/delete"),
    ("DELETE", "/delete-file"),
}
_OLD_ITEM_READS = {
    "/list-secure-items", "/get-secure-item", "/list-login-names",
    "/get-login", "/login-count", "/manage/list-login-names",
    "/manage/list-secure-items", "/manage/logins-full",
}


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


def _replaced_pin_route(path: str, offers: int, method: str = "POST") -> str | None:
    path = path.rstrip("/")
    if offers & PIN_FREE_ITEM_READ_OFFER and path in _OLD_ITEM_READS:
        return "pin_free_read_required"
    if (offers & PIN_FREE_FILE_MUTATION_OFFER and
            (method, path) in _OLD_FILE_MUTATIONS):
        return "pin_free_file_mutation_required"
    if (offers & PIN_FREE_BENEFICIARY_OFFER and
            path in ("/beneficiary/create", "/beneficiary/link",
                     "/beneficiary/list-mine", "/beneficiary/list-inheritances",
                     "/beneficiary/request-transfer",
                     "/beneficiary/cancel-transfer",
                     "/beneficiary/claim-transfer", "/beneficiary/delete")):
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


def _candidate_pin_path(path: str, method: str = "POST") -> bool:
    path = path.rstrip("/")
    if (method, path) in _OLD_FILE_MUTATIONS:
        return True
    if method != "POST":
        return False
    return (_replaced_private_chat_path(path) or
            path in _OLD_ITEM_READS or
            path in ("/beneficiary/create", "/beneficiary/link",
                     "/beneficiary/list-mine", "/beneficiary/list-inheritances",
                     "/beneficiary/request-transfer",
                     "/beneficiary/cancel-transfer",
                     "/beneficiary/claim-transfer", "/beneficiary/delete") or
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
        method = scope.get("method", "")
        if (scope.get("type") == "http" and
                _candidate_pin_path(scope.get("path", ""), method)):
            offers = _signed_offer_bits(scope.get("headers", []))
            reason = _replaced_pin_route(scope.get("path", ""), offers, method)
        if reason is not None:
            response = JSONResponse(
                status_code=409,
                content={"detail": reason},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
