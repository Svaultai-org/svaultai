"""A private item editor gets a distinct, body-free old-route fence."""

import asyncio
import os

import pytest
from fastapi import HTTPException, Request

os.environ.setdefault("DATABASE_URL", "postgresql://synthetic.invalid/test")

import auth_local
from routes import auth_zk_routes
from routes import legacy_ciphertext_export_routes as export_routes
from routes import legacy_ciphertext_migration_routes as migration_routes
from routes import zk_metadata_inventory_routes as metadata_routes
from signed_offer_prebody_pin_fence import SignedOfferPrebodyPinFence


def _request(offered=True):
    headers = [(b"x-svaultai-file-v2-reader", b"1")]
    if offered:
        headers.append((b"x-svaultai-pin-free-saved-item-mutation", b"1"))
    return Request({"type": "http", "method": "POST",
                    "path": "/auth/zk-login-finalize", "headers": headers})


def test_negotiation_needs_complete_private_edit_and_delete(monkeypatch):
    negotiate = auth_zk_routes._signed_saved_item_mutation_negotiation
    assert not negotiate(_request(False), signed_reads=True)
    flags = (
        "VAULTAI_SIGNED_SAVED_ITEM_MUTATION_ENABLED",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE",
        "VAULTAI_ZK_METADATA_INVENTORY_ENABLED",
        "VAULTAI_ZK_LEGACY_EXPORT_ENABLED",
    )
    for flag in flags:
        with pytest.raises(HTTPException) as denied:
            negotiate(_request(), signed_reads=True)
        assert denied.value.detail == "signed_saved_item_mutation_unavailable"
        monkeypatch.setenv(flag, "true")
    assert negotiate(_request(), signed_reads=True)
    with pytest.raises(HTTPException) as denied:
        negotiate(_request(), signed_reads=False)
    assert denied.value.detail == "signed_read_offers_required"


def test_signed_claim_fences_both_old_item_routes_before_body(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/test")
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-item-offer-secret-2026")
    monkeypatch.setenv("VAULTAI_SIGNED_OFFER_PREBODY_PIN_FENCE_ENABLED", "true")
    auth_local.reset_secret_for_tests()
    old = auth_local._format_token(bytes(range(16)))
    signed = auth_local.sign_opaque_read_offer_token(
        old, auth_local.PIN_FREE_ITEM_READ_OFFER |
        auth_local.PIN_FREE_SAVED_ITEM_MUTATION_OFFER,
    )
    assert auth_local._parse_token_claims(signed)[1] == 2049
    with pytest.raises(ValueError):
        auth_local.sign_opaque_read_offer_token(old, 2048)

    async def exercise(path, bearer):
        read = False
        status = None

        async def receive():
            nonlocal read
            read = True
            return {"type": "http.request", "body": b'{"pin":"synthetic"}'}

        async def send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]

        async def downstream(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        await SignedOfferPrebodyPinFence(downstream)(
            {"type": "http", "method": "POST", "path": path,
             "headers": [(b"authorization", f"Bearer {bearer}".encode())]},
            receive, send,
        )
        return read, status

    for path in ("/update-secure-item", "/delete-secure-item"):
        assert asyncio.run(exercise(path, signed)) == (False, 409)
        assert asyncio.run(exercise(path, old)) == (True, 200)


def test_signed_item_routes_survive_issuance_flag_change(monkeypatch):
    principal = {"vault_id": "synthetic-vault", "pin_free_read_offers": 2049}
    unoffered = {"vault_id": "synthetic-vault", "pin_free_read_offers": 0}
    monkeypatch.setattr(metadata_routes, "is_vault_zk_adopted", lambda _: True)
    for flag in (
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE",
        "VAULTAI_ZK_LEGACY_EXPORT_ENABLED",
        "VAULTAI_ZK_METADATA_INVENTORY_ENABLED",
    ):
        monkeypatch.setenv(flag, "false")
    for flag in (
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME",
        "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE",
    ):
        migration_routes._require_flag(flag, principal)
        with pytest.raises(HTTPException):
            migration_routes._require_flag(flag, unoffered)
    export_routes._require_enabled(principal)
    metadata_routes._require_inventory("synthetic-vault", principal)
    with pytest.raises(HTTPException):
        export_routes._require_enabled(unoffered)
    with pytest.raises(HTTPException):
        metadata_routes._require_inventory("synthetic-vault", unoffered)
