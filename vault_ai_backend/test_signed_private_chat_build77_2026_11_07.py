"""Synthetic tests for the default-off, signed private-chat offer."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request

import auth_local
from routes import auth_zk_routes
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


TOKEN_ID = bytes(range(16))


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-private-chat-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


def _request(*, chat: bool, reader: bool = True) -> Request:
    headers = []
    if chat:
        headers.append((b"x-svaultai-pin-free-private-chat", b"1"))
    if reader:
        headers.append((b"x-svaultai-file-v2-reader", b"1"))
    return Request({"type": "http", "method": "POST",
                    "path": "/auth/zk-login-finalize", "headers": headers})


def test_wide_chat_bearer_is_mac_bound_and_requires_all_read_offers():
    legacy = auth_local._format_token(TOKEN_ID)
    assert auth_local._parse_token_claims(legacy) == (TOKEN_ID, 0)
    signed = auth_local.sign_opaque_read_offer_token(legacy, 519)
    assert len(auth_local._b64url_decode(signed)) == 51
    assert auth_local._parse_token_claims(signed) == (TOKEN_ID, 519)
    wire = auth_local._b64url_decode(signed)
    tampered = auth_local._b64url_encode(wire[:2] + bytes([wire[2] ^ 1]) + wire[3:])
    assert auth_local._parse_token_claims(tampered) is None
    with pytest.raises(ValueError, match="complete read offers"):
        auth_local.sign_opaque_read_offer_token(legacy, 512)
    # The existing 50-byte v3 bearer remains valid and unchanged.
    assert len(auth_local._b64url_decode(
        auth_local.sign_opaque_read_offer_token(legacy, 15))) == 50


def test_negotiation_is_default_off_and_requires_local_reader_dependencies(monkeypatch):
    assert auth_zk_routes._signed_private_chat_negotiation(
        _request(chat=False), signed_reads=False) is False
    with pytest.raises(HTTPException) as exc:
        auth_zk_routes._signed_private_chat_negotiation(
            _request(chat=True), signed_reads=True)
    assert exc.value.status_code == 409
    monkeypatch.setenv("VAULTAI_SIGNED_PRIVATE_CHAT_ENABLED", "true")
    with pytest.raises(HTTPException):
        auth_zk_routes._signed_private_chat_negotiation(
            _request(chat=True), signed_reads=False)
    with pytest.raises(HTTPException):
        auth_zk_routes._signed_private_chat_negotiation(
            _request(chat=True, reader=False), signed_reads=True)
    with pytest.raises(HTTPException) as exc:
        auth_zk_routes._signed_private_chat_negotiation(
            _request(chat=True), signed_reads=True)
    assert exc.value.detail == "signed_private_chat_dependencies_unavailable"
    for name in ("VAULTAI_ZK_GENERAL_CHAT_ENABLED",
                 "VAULTAI_ZK_PRIVATE_MEDIA_ENABLED",
                 "VAULTAI_ZK_PRIVATE_LEGACY_MEDIA_ENABLED",
                 "VAULTAI_ZK_LEGACY_EXPORT_ENABLED"):
        monkeypatch.setenv(name, "true")
    assert auth_zk_routes._signed_private_chat_negotiation(
        _request(chat=True), signed_reads=True) is True


def test_signed_chat_routes_are_fenced_even_after_issuance_switch_is_off(monkeypatch):
    monkeypatch.setenv("VAULTAI_SIGNED_PRIVATE_CHAT_ENABLED", "false")
    old = auth_local._format_token(TOKEN_ID)
    signed = auth_local.sign_opaque_read_offer_token(old, 519)
    for path in ("/chat", "/vault-analysis/deep-answer",
                 "/vault-analysis/deep-answer/job/poll",
                 "/vault-analysis/deep-answer/job/debug",
                 "/files/file-id/related"):
        with pytest.raises(HTTPException) as exc:
            auth_local.require_signed_offer_route(
                {"pin_free_read_offers": 519}, path=path)
        assert exc.value.status_code == 409
        assert exc.value.detail == "pin_free_private_chat_required"
    auth_local.require_signed_offer_route(
        {"pin_free_read_offers": 0}, path="/chat")

    async def probe(path: str, headers: list[tuple[bytes, bytes]]):
        reads = []
        sent = []

        async def receive():
            reads.append(True)
            return {"type": "http.request", "body": b'{"pin":"synthetic"}',
                    "more_body": False}

        async def send(message):
            sent.append(message)

        async def inner(scope, receive_inner, send_inner):
            await receive_inner()
            await send_inner({"type": "http.response.start", "status": 200,
                              "headers": []})
            await send_inner({"type": "http.response.body", "body": b"ok"})

        gate = SignedPrivateChatPreBodyGate(inner)
        scope = {"type": "http", "method": "POST", "path": path,
                 "headers": headers}
        await gate(scope, receive, send)
        return len(reads), sent[0]["status"]

    offered = [(b"authorization", f"Bearer {signed}".encode())]
    for path in ("/chat", "/chat/", "/vault-analysis/deep-answer",
                 "/vault-analysis/deep-answer/job/poll",
                 "/files/file-id/related"):
        assert asyncio.run(probe(path, offered)) == (0, 409)
    legacy_header = [(b"authorization", f"Bearer {old}".encode())]
    assert asyncio.run(probe("/chat", legacy_header)) == (1, 200)
    # A duplicate legacy Authorization field cannot hide the valid offer.
    assert asyncio.run(probe("/chat", legacy_header + offered)) == (0, 409)
