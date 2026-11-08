"""Import offers fence exactly the three old PIN actions before body reads."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException, Request

import auth_local
from routes import auth_zk_routes
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-import-offer-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


async def _probe(path: str, token: str, method: str = "POST"):
    reads = []
    sent = []

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b'{"pin":"synthetic"}',
                "more_body": False}

    async def send(message):
        sent.append(message)

    async def inner(scope, read, write):
        await read()
        await write({"type": "http.response.start", "status": 200,
                     "headers": []})
        await write({"type": "http.response.body", "body": b"ok"})

    gate = SignedPrivateChatPreBodyGate(inner)
    await gate({"type": "http", "method": method, "path": path,
                "headers": [(b"authorization", f"Bearer {token}".encode())]},
               receive, send)
    return len(reads), sent[0]["status"], (
        json.loads(sent[1]["body"]) if sent[0]["status"] == 409 else None
    )


@pytest.mark.parametrize("path", [
    "/imports/start", "/imports/synthetic-id/cancel",
    "/imports/synthetic-id/complete",
])
def test_signed_import_fences_old_routes_before_body(path):
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(
        old, auth_local.PIN_FREE_IMPORT_OFFER | 7,
    )
    assert auth_local._parse_token_claims(offered)[1] == 263
    for candidate in (path, path + "/"):
        assert asyncio.run(_probe(candidate, offered)) == (
            0, 409, {"detail": "pin_free_import_required"},
        )
    assert asyncio.run(_probe(path, old)) == (1, 200, None)
    assert asyncio.run(_probe(path, offered, "OPTIONS")) == (1, 200, None)
    with pytest.raises(HTTPException) as blocked:
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": 263}, path=path,
        )
    assert blocked.value.detail == "pin_free_import_required"


def test_import_offer_does_not_fence_private_session_actions():
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, 263)
    for path in ("/imports/session/start",
                 "/imports/session/id/cancel", "/imports/session/id/complete"):
        assert asyncio.run(_probe(path, offered)) == (1, 200, None)
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": 263}, path=path,
        )


def test_combined_auth_import_chat_offer_keeps_every_bit():
    old = auth_local._format_token(bytes(range(16)))
    bits = (auth_local.PIN_FREE_AUTH_DEVICE_OFFER |
            auth_local.PIN_FREE_IMPORT_OFFER |
            auth_local.PIN_FREE_PRIVATE_CHAT_OFFER | 7)
    offered = auth_local.sign_opaque_read_offer_token(old, bits)
    assert auth_local._parse_token_claims(offered)[1] == bits
    for path, reason in (("/vault-stats", "pin_free_auth_device_required"),
                         ("/imports/start", "pin_free_import_required"),
                         ("/chat", "pin_free_private_chat_required")):
        assert asyncio.run(_probe(path, offered)) == (
            0, 409, {"detail": reason},
        )


def test_import_offer_needs_explicit_client_and_server_flags(monkeypatch):
    def request(offered: bool, reader: bool = True) -> Request:
        headers = []
        if offered:
            headers.append((b"x-svaultai-pin-free-import", b"1"))
        if reader:
            headers.append((b"x-svaultai-file-v2-reader", b"1"))
        return Request({"type": "http", "method": "POST",
                        "path": "/auth/zk-login-finalize", "headers": headers})

    negotiate = auth_zk_routes._signed_import_negotiation
    assert negotiate(request(False), signed_reads=True) is False
    with pytest.raises(HTTPException) as unavailable:
        negotiate(request(True), signed_reads=True)
    assert unavailable.value.detail == "signed_import_unavailable"
    monkeypatch.setenv("VAULTAI_SIGNED_IMPORT_OFFER_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "true")
    assert negotiate(request(True), signed_reads=True) is True
    for signed_reads, reader in ((False, True), (True, False)):
        with pytest.raises(HTTPException) as missing:
            negotiate(request(True, reader), signed_reads=signed_reads)
        assert missing.value.detail == "signed_read_offers_required"
