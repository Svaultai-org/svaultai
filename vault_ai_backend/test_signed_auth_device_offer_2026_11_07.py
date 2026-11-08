"""PIN-free metadata and device approval are scoped to a signed OPAQUE offer."""

import asyncio

import pytest
from fastapi import HTTPException, Request

import auth_local
from routes import auth_zk_routes
from signed_private_chat_prebody_gate import SignedPrivateChatPreBodyGate


OLD_ROUTES = (
    "/get-or-create-vault-meta", "/verify-pin", "/rotate-vault-kdf",
    "/vault-stats", "/devices/request-self-approval",
    "/devices/finalize-self-approval",
)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-auth-device-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


def _request(*, offer=False, reader=True):
    headers = []
    if offer:
        headers.append((b"x-svaultai-pin-free-auth-device", b"1"))
    if reader:
        headers.append((b"x-svaultai-file-v2-reader", b"1"))
    return Request({"type": "http", "method": "POST",
                    "path": "/auth/zk-login-finalize", "headers": headers})


def test_offer_is_explicit_and_requires_pending_proof(monkeypatch):
    negotiate = auth_zk_routes._signed_auth_device_negotiation
    assert negotiate(_request(), signed_reads=False) is False
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(offer=True), signed_reads=False)
    assert denied.value.detail == "signed_read_offers_required"
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(offer=True, reader=False), signed_reads=True)
    assert denied.value.detail == "signed_read_offers_required"
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(offer=True), signed_reads=True)
    assert denied.value.detail == "signed_auth_device_unavailable"
    monkeypatch.setenv("VAULTAI_SIGNED_AUTH_DEVICE_OFFER_ENABLED", "true")
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(offer=True), signed_reads=True)
    assert denied.value.detail == "signed_auth_device_unavailable"
    monkeypatch.setenv("VAULTAI_ZK_PENDING_DEVICE_PROOF_ENABLED", "true")
    assert negotiate(_request(offer=True), signed_reads=True) is True


def test_only_signed_offered_sessions_fence_six_old_routes():
    fresh = auth_local._format_token(bytes(range(16)))
    token = auth_zk_routes._signed_offer_token(
        fresh, signed_reads=True, item_read=False, file_list=False,
        file_download=False, file_create=False, auth_device=True,
    )
    assert auth_local._parse_token_claims(token) == (bytes(range(16)), 128)
    for path in OLD_ROUTES:
        with pytest.raises(HTTPException) as denied:
            auth_local.require_signed_offer_route(
                {"pin_free_read_offers": 128}, path=path)
        assert (denied.value.status_code, denied.value.detail) == (
            409, "pin_free_auth_device_required")
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": 0}, path=path)
    for path in ("/auth/login", "/auth/zk-pending-verify-init",
                 "/auth/zk-pending-verify-finalize",
                 "/devices/request-self-approval-proof",
                 "/devices/finalize-self-approval-proof", "/vault-meta",
                 "/vault-stats/zk"):
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": 128}, path=path)


@pytest.mark.parametrize("path", OLD_ROUTES)
def test_offered_route_rejected_before_receiving_pin_body(path):
    fresh = auth_local._format_token(bytes(range(16)))
    signed = auth_local.sign_opaque_read_offer_token(fresh, 128)

    async def probe(token):
        reads = []
        starts = []

        async def receive():
            reads.append(True)
            return {"type": "http.request", "body": b'{"pin":"123456"}',
                    "more_body": False}

        async def app(scope, receive, send):
            starts.append(True)

        async def send(message):
            if message["type"] == "http.response.start":
                starts.append(message["status"])

        scope = {"type": "http", "method": "POST", "path": path,
                 "headers": [(b"authorization", f"Bearer {token}".encode())]}
        await SignedPrivateChatPreBodyGate(app)(scope, receive, send)
        return reads, starts

    assert asyncio.run(probe(signed)) == ([], [409])
    assert asyncio.run(probe(fresh)) == ([], [True])
