"""Synthetic checks for per-vault Memory cutover; no real vault rows or network."""

import asyncio

import pytest
from fastapi import HTTPException, Request

import auth_local
from routes import auth_zk_routes
from routes import vault_ciphertext_write_routes as ciphertext_routes
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-memory-offer-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


def _request(with_offer: bool) -> Request:
    headers = [(b"x-svaultai-pin-free-memory", b"1")] if with_offer else []
    return Request({"type": "http", "method": "POST",
                    "path": "/auth/zk-login-finalize", "headers": headers})


def test_memory_negotiation_requires_both_private_routes_and_server_opt_in(
    monkeypatch,
):
    negotiate = auth_zk_routes._signed_memory_negotiation
    assert negotiate(_request(False), signed_reads=True) is False
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(True), signed_reads=True)
    assert denied.value.detail == "signed_memory_unavailable"
    monkeypatch.setenv("MEMORY_V2_READ_ENABLED", "true")
    monkeypatch.setenv("MEMORY_V2_WRITE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_SIGNED_MEMORY_OFFER_ENABLED", "true")
    with pytest.raises(HTTPException):
        negotiate(_request(True), signed_reads=False)
    assert negotiate(_request(True), signed_reads=True) is True


def test_memory_readiness_rejects_any_active_row_without_private_copy():
    class Cursor:
        def __init__(self, ready):
            self.ready = ready

        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def fetchone(self):
            return (self.ready,)

    class Conn:
        def __init__(self, ready):
            self.cur = Cursor(ready)

        def cursor(self):
            return self.cur

    for ready in (True, False):
        conn = Conn(ready)
        assert auth_zk_routes._memory_v2_offer_ready(conn, "owned-vault") is ready
        assert conn.cur.params == ("owned-vault",)
        for safety_check in ("superseded_at IS NULL", "memory_record_id IS NULL",
                             "payload_ciphertext IS NULL", "GET_BYTE"):
            assert safety_check in conn.cur.sql


def test_memory_signed_v4_claim_and_prebody_fence():
    original = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(original, 1024)
    combined = auth_local.sign_opaque_read_offer_token(original, 519 | 1024)
    all_offers = auth_local.sign_opaque_read_offer_token(original, 2047)
    assert auth_local._parse_token_claims(offered) == (bytes(range(16)), 1024)
    assert auth_local._parse_token_claims(combined) == (bytes(range(16)), 1543)
    assert auth_local._parse_token_claims(all_offers) == (bytes(range(16)), 2047)
    assert auth_local._b64url_decode(offered)[0] == 4

    async def probe(path, token):
        reads = []
        statuses = []

        async def receive():
            reads.append(True)
            return {"type": "http.request", "body": b'{"pin":"synthetic"}',
                    "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                statuses.append(message["status"])

        async def inner(scope, receive_inner, send_inner):
            await receive_inner()
            await send_inner({"type": "http.response.start", "status": 200,
                              "headers": []})
            await send_inner({"type": "http.response.body", "body": b"ok"})

        scope = {"type": "http", "method": "POST", "path": path,
                 "headers": [(b"authorization", f"Bearer {token}".encode())]}
        await SignedPrivateChatPreBodyGate(inner)(scope, receive, send)
        return len(reads), statuses[0]

    for path in ("/memory/list", "/memory/create", "/memory/update",
                 "/memory/delete", "/memory/list/"):
        assert asyncio.run(probe(path, offered)) == (0, 409)
        assert asyncio.run(probe(path, combined)) == (0, 409)
        assert asyncio.run(probe(path, original)) == (1, 200)
        with pytest.raises(HTTPException) as denied:
            auth_local.require_signed_offer_route(
                {"pin_free_read_offers": 1024}, path=path,
            )
        assert denied.value.detail == "pin_free_memory_required"


def test_memory_offer_is_not_signed_when_vault_is_not_ready():
    original = auth_local._format_token(bytes(range(16)))
    signed = auth_zk_routes._signed_offer_token(
        original, signed_reads=True, item_read=False, file_list=False,
        file_download=False, file_create=False, memory=False,
    )
    assert auth_local._parse_token_claims(signed) == (bytes(range(16)), 0)
    assert auth_local._b64url_decode(signed)[0] == 3


def test_offered_private_memory_routes_survive_flag_change(monkeypatch):
    monkeypatch.setenv("MEMORY_V2_READ_ENABLED", "false")
    monkeypatch.setenv("MEMORY_V2_WRITE_ENABLED", "false")
    principal = {"vault_id": "synthetic-vault", "pin_free_read_offers": 1024}
    assert ciphertext_routes._memory_v2_route_enabled(principal, write=False)
    assert ciphertext_routes._memory_v2_route_enabled(principal, write=True)
    principal["pin_free_read_offers"] = 0
    assert not ciphertext_routes._memory_v2_route_enabled(principal, write=False)
    assert not ciphertext_routes._memory_v2_route_enabled(principal, write=True)
