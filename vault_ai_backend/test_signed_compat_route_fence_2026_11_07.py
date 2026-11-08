"""Signed-read clients cannot fall back to unused raw-PIN compatibility APIs.

This is a wire fence for capable sessions, not a replacement for these APIs
for older clients. The old routes remain available to unoffered sessions.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi import HTTPException

from auth_local import (
    PIN_FREE_ITEM_READ_OFFER, _format_token, reset_secret_for_tests,
    require_signed_offer_route, sign_opaque_read_offer_token,
)
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


OLD_ROUTES = (
    ("POST", "/delete-login"),
    ("PATCH", "/manage/login"),
    ("DELETE", "/manage/login"),
    ("POST", "/manage/login/delete"),
    ("POST", "/crypto/save-wallet-profile"),
    ("POST", "/crypto/save-sensitive-backup"),
    ("POST", "/crypto/reveal-sensitive-backup"),
    ("POST", "/crypto/save-note"),
    ("POST", "/vault-analysis/coverage"),
    ("POST", "/vault-analysis/drain-text-extraction"),
    ("POST", "/vault-analysis/backfill-chunked-text-extraction"),
    ("POST", "/vault-analysis/backfill-archive-signals"),
    ("POST", "/vault/file/synthetic-file/text"),
)


def _token(monkeypatch, *, offered: bool) -> str:
    monkeypatch.setenv(
        "VAULT_SESSION_SECRET", "synthetic-compat-fence-secret-12345678901234567890",
    )
    reset_secret_for_tests()
    token = _format_token(uuid.uuid4().bytes)
    return sign_opaque_read_offer_token(token, PIN_FREE_ITEM_READ_OFFER) if offered else token


def _probe(method: str, path: str, token: str) -> tuple[bool, int, bytes]:
    read = False
    status = 0
    body = b""

    async def receive():
        nonlocal read
        read = True
        return {"type": "http.request", "body": b'{"pin":"synthetic-secret"}',
                "more_body": False}

    async def send(message):
        nonlocal status, body
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            body += message.get("body", b"")

    async def downstream(_scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"passed"})

    scope = {"type": "http", "method": method, "path": path,
             "headers": [(b"authorization", f"Bearer {token}".encode())]}
    asyncio.run(SignedPrivateChatPreBodyGate(downstream)(scope, receive, send))
    return read, status, body


@pytest.mark.parametrize("method,path", OLD_ROUTES)
def test_signed_client_old_contract_is_rejected_before_body(monkeypatch, method, path):
    token = _token(monkeypatch, offered=True)
    for suffix in ("", "/"):
        read, status, body = _probe(method, path + suffix, token)
        assert not read
        assert status == 409
        assert json.loads(body)["detail"] == "pin_free_client_required"
        assert b"synthetic-secret" not in body
    with pytest.raises(HTTPException) as exc:
        require_signed_offer_route(
            {"pin_free_read_offers": PIN_FREE_ITEM_READ_OFFER}, path=path,
        )
    assert getattr(exc.value, "status_code", None) == 409


@pytest.mark.parametrize("method,path", OLD_ROUTES)
def test_unoffered_client_keeps_old_route(monkeypatch, method, path):
    read, status, body = _probe(method, path, _token(monkeypatch, offered=False))
    assert read and status == 200 and body == b"passed"


def test_only_reviewed_method_and_path_are_fenced(monkeypatch):
    token = _token(monkeypatch, offered=True)
    for method, path in (("GET", "/manage/login"),
                         ("POST", "/manage/login"),
                         ("POST", "/crypto/save-note-extra"),
                         ("GET", "/vault/file/synthetic-file/text"),
                         ("POST", "/vault/file/synthetic-file/text/extra"),
                         ("POST", "/vault-analysis/coverage-extra")):
        read, status, body = _probe(method, path, token)
        assert read and status == 200 and body == b"passed"
