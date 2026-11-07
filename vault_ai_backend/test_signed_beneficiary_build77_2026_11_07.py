"""Default-off signed beneficiary offer and pre-body PIN fence."""

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException, Request

import auth_local
import main
from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER
from routes import auth_zk_routes
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-beneficiary-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


def _request(*, beneficiary: bool, reader: bool = True) -> Request:
    headers = []
    if beneficiary:
        headers.append((b"x-svaultai-pin-free-beneficiary", b"1"))
    if reader:
        headers.append((b"x-svaultai-file-v2-reader", b"1"))
    return Request({"type": "http", "method": "POST",
                    "path": "/auth/zk-login-finalize", "headers": headers})


def test_negotiation_is_default_off_and_requires_v2_pairing(monkeypatch):
    assert "X-SVaultAI-Pin-Free-Beneficiary" in main.CORS_ALLOWED_HEADERS
    negotiate = auth_zk_routes._signed_beneficiary_negotiation
    assert negotiate(_request(beneficiary=False), signed_reads=False) is False
    with pytest.raises(HTTPException) as exc:
        negotiate(_request(beneficiary=True), signed_reads=False)
    assert exc.value.detail == "signed_read_offers_required"
    with pytest.raises(HTTPException) as exc:
        negotiate(_request(beneficiary=True, reader=False), signed_reads=True)
    assert exc.value.detail == "signed_read_offers_required"
    with pytest.raises(HTTPException) as exc:
        negotiate(_request(beneficiary=True), signed_reads=True)
    assert exc.value.detail == "signed_beneficiary_unavailable"
    monkeypatch.setenv("VAULTAI_SIGNED_BENEFICIARY_OFFER_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        negotiate(_request(beneficiary=True), signed_reads=True)
    assert exc.value.detail == "beneficiary_v2_pairing_unavailable"
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    assert negotiate(_request(beneficiary=True), signed_reads=True) is True


def test_v3_v4_bits_keep_password_and_chat_distinct():
    original = auth_local._format_token(bytes(range(16)))
    beneficiary_only = auth_zk_routes._signed_offer_token(
        original, signed_reads=True, item_read=False, file_list=False,
        file_download=False, file_create=False, beneficiary=True,
    )
    assert auth_local._parse_token_claims(beneficiary_only) == (
        bytes(range(16)), 64)
    for bits, version in ((7 | 16 | 64, 3), (519 | 16 | 64, 4)):
        token = auth_local.sign_opaque_read_offer_token(original, bits)
        assert auth_local._parse_token_claims(token) == (bytes(range(16)), bits)
        assert auth_local._b64url_decode(token)[0] == version
        assert auth_zk_routes._signed_offer_token(
            original, signed_reads=True, item_read=True, file_list=True,
            file_download=True, file_create=False, password_analysis=True,
            beneficiary=True, private_chat=(version == 4),
        ) == token
    for bits, version in ((7 | 16 | 32 | 64, 3),
                          (519 | 16 | 32 | 64, 4)):
        token = auth_local.sign_opaque_read_offer_token(original, bits)
        assert auth_local._parse_token_claims(token) == (bytes(range(16)), bits)
        assert auth_local._b64url_decode(token)[0] == version
        assert auth_zk_routes._signed_offer_token(
            original, signed_reads=True, item_read=True, file_list=True,
            file_download=True, file_create=False, file_mutation=True,
            password_analysis=True, beneficiary=True,
            private_chat=(version == 4),
        ) == token
    with pytest.raises(ValueError, match="negotiated"):
        auth_zk_routes._signed_offer_token(
            original, signed_reads=False, item_read=False, file_list=False,
            file_download=False, file_create=False, beneficiary=True,
        )
    for path in ("/beneficiary/create", "/beneficiary/link",
                 "/beneficiary/request-transfer",
                 "/beneficiary/claim-transfer", "/beneficiary/create/"):
        with pytest.raises(HTTPException) as exc:
            auth_local.require_signed_offer_route(
                {"pin_free_read_offers": 64}, path=path)
        assert exc.value.detail == "pin_free_beneficiary_required"


def test_offered_legacy_actions_are_rejected_before_request_body():
    original = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(original, 7 | 16 | 64)
    combined = auth_local.sign_opaque_read_offer_token(original, 519 | 16 | 64)

    async def probe(path, token):
        reads = []
        starts = []

        async def receive():
            reads.append(True)
            return {"type": "http.request", "body": b'{"pin":"synthetic"}',
                    "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                starts.append(message["status"])

        async def inner(scope, receive_inner, send_inner):
            await receive_inner()
            await send_inner({"type": "http.response.start", "status": 200,
                              "headers": []})
            await send_inner({"type": "http.response.body", "body": b"ok"})

        scope = {"type": "http", "method": "POST", "path": path,
                 "headers": [(b"authorization", f"Bearer {token}".encode())]}
        await SignedPrivateChatPreBodyGate(inner)(scope, receive, send)
        return len(reads), starts[0]

    for token in (offered, combined):
        for path in ("/beneficiary/create", "/beneficiary/link",
                     "/beneficiary/request-transfer",
                     "/beneficiary/claim-transfer", "/beneficiary/create/"):
            assert asyncio.run(probe(path, token)) == (0, 409)
    assert asyncio.run(probe("/beneficiary/create", original)) == (1, 200)
    assert asyncio.run(probe("/security-center/analyze-passwords", offered)) == (0, 409)
    assert asyncio.run(probe("/chat", combined)) == (0, 409)


def test_offered_beneficiary_action_consumes_proof_without_pin_check():
    principal = {"vault_id": "11111111-1111-1111-1111-111111111111",
                 "pin_free_read_offers": 64}
    with mock.patch.object(main, "verify_vault_pin") as pin_check, \
         mock.patch.object(auth_zk_routes, "consume_recent_zk_proof") as consume:
        main._verify_beneficiary_action(
            principal, pin=None, proof_token="synthetic-proof")
        consume.assert_called_once_with("synthetic-proof", principal)
        with pytest.raises(HTTPException) as exc:
            main._verify_beneficiary_action(
                principal, pin="synthetic-pin", proof_token=None)
        assert exc.value.detail == "pin_free_beneficiary_required"
        with pytest.raises(HTTPException) as exc:
            main._verify_beneficiary_action(
                principal, pin=None, proof_token=None)
        assert exc.value.detail == "zk_proof_token_required"
        pin_check.assert_not_called()


def test_existing_older_links_prevent_offer():
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
        assert auth_zk_routes._beneficiary_v2_offer_ready(
            conn, "synthetic-vault") is ready
        assert "passer_vault_id" in conn.cur.sql
        assert "beneficiary_vault_id" in conn.cur.sql
        assert conn.cur.params == (
            "synthetic-vault", "synthetic-vault",
            ZK_BENEFICIARY_V2_MARKER,
        )
