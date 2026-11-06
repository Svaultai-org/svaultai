"""Signed OPAQUE offers on the deployed schema-0056 session shape.

All tokens, account IDs, and rows here are synthetic. No database is opened.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException, Request

import auth_local
from routes import auth_zk_routes as routes


TOKEN_ID = bytes(range(16))


def request(token="", path="/list-files", *, signed=False, create=False,
            reader=False):
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if signed:
        headers.append((b"x-svaultai-pin-free-read-offers", b"1"))
    if create:
        headers.append((b"x-svaultai-pin-free-file-create", b"1"))
    if reader:
        headers.append((b"x-svaultai-file-v2-reader", b"1"))
    return Request({"type": "http", "method": "POST", "path": path,
                    "headers": headers, "client": ("192.0.2.4", 12345)})


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-signed-offer-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


def test_live_legacy_bearer_unchanged_and_v3_bits_authenticated():
    old = auth_local._format_token(TOKEN_ID)
    assert len(auth_local._b64url_decode(old)) == 48
    assert auth_local._parse_token_claims(old) == (TOKEN_ID, 0)
    signed = auth_local.sign_opaque_read_offer_token(old, 15)
    assert len(auth_local._b64url_decode(signed)) == 50
    assert auth_local._parse_token_claims(signed) == (TOKEN_ID, 15)
    assert auth_local._parse_token(signed) == TOKEN_ID
    wire = auth_local._b64url_decode(signed)
    assert auth_local._parse_token_claims(
        auth_local._b64url_encode(wire[:1] + b"\x00" + wire[2:])
    ) is None
    assert auth_local._parse_token_claims(
        auth_local._b64url_encode(wire[:1] + b"\x10" + wire[2:])
    ) is None
    assert auth_local._parse_token_claims(
        auth_local._b64url_encode(b"\x02" + wire[1:])
    ) is None
    with pytest.raises(ValueError):
        auth_local.sign_opaque_read_offer_token(signed, 0)
    with pytest.raises(ValueError):
        auth_local.sign_opaque_read_offer_token(old, 16)


def test_signed_routes_block_only_offered_reads_and_new_upload_starts():
    for bit, blocked in (
        (1, {"/list-secure-items", "/get-secure-item"}),
        (2, {"/list-files", "/files/synthetic/related"}),
        (4, {"/download-file", "/download-file/manifest",
             "/files/synthetic/related"}),
        (8, {"/upload-file", "/upload-file/init"}),
    ):
        principal = {"pin_free_read_offers": bit}
        for path in ("/list-secure-items", "/get-secure-item", "/list-files",
                     "/download-file", "/download-file/manifest",
                     "/files/synthetic/related", "/upload-file",
                     "/upload-file/init", "/upload-file/finalize",
                     "/upload-file/abort", "/name-file"):
            if path in blocked:
                with pytest.raises(HTTPException) as exc:
                    auth_local.require_signed_offer_route(principal, path=path)
                assert exc.value.status_code == 409
            else:
                auth_local.require_signed_offer_route(principal, path=path)
    for path in ("/upload-file", "/upload-file/init", "/list-files"):
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": 0}, path=path,
        )


def test_verifier_enforces_signed_bit_despite_issuance_flag_off(monkeypatch):
    monkeypatch.setenv("VAULTAI_SIGNED_READ_OFFERS_ENABLED", "false")
    monkeypatch.setenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", "false")
    old = auth_local._format_token(TOKEN_ID)
    signed = auth_local.sign_opaque_read_offer_token(old, 8)
    principal = {"vault_id": "synthetic-vault", "vault_name": "",
                 "token_id": "00010203-0405-0607-0809-0a0b0c0d0e0f",
                 "device_id": "synthetic-device"}
    with mock.patch.object(auth_local, "_load_principal",
                           return_value=(principal, None)), \
         mock.patch("device_monitor.monitor_best_effort"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth_local.verify_session_token(
                request(signed, "/upload-file"),
            ))
        assert exc.value.status_code == 409
        assert exc.value.detail == "pin_free_file_create_required"
        assert asyncio.run(auth_local.verify_session_token(
            request(signed, "/upload-file/finalize"),
        ))["pin_free_read_offers"] == 8
        assert asyncio.run(auth_local.verify_session_token(
            request(old, "/upload-file"),
        ))["pin_free_read_offers"] == 0
    with mock.patch.object(auth_local, "_load_principal",
                           return_value=(None, "session_superseded")):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth_local.verify_session_token(
                request(signed, "/upload-file/finalize"),
            ))
        assert exc.value.status_code == 401


def test_negotiation_is_explicit_default_off_and_old_clients_unchanged(
    monkeypatch,
):
    monkeypatch.delenv("VAULTAI_SIGNED_READ_OFFERS_ENABLED", raising=False)
    monkeypatch.delenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", raising=False)
    assert routes._signed_read_offer_negotiation(request()) is False
    assert routes._signed_file_create_negotiation(
        request(), signed_reads=False,
    ) is False
    with pytest.raises(HTTPException):
        routes._signed_read_offer_negotiation(
            request(signed=True, reader=True),
        )
    monkeypatch.setenv("VAULTAI_SIGNED_READ_OFFERS_ENABLED", "true")
    with pytest.raises(HTTPException):
        routes._signed_read_offer_negotiation(request(signed=True))
    assert routes._signed_read_offer_negotiation(
        request(signed=True, reader=True),
    ) is True
    with pytest.raises(HTTPException):
        routes._signed_file_create_negotiation(
            request(create=True, reader=True), signed_reads=True,
        )
    monkeypatch.setenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", "true")
    assert routes._signed_file_create_negotiation(
        request(create=True, reader=True), signed_reads=True,
    ) is True


def test_live_v2_write_offer_requires_both_file_flags_and_new_route(monkeypatch):
    for key in ("FILE_V2_READ_ENABLED", "FILE_V2_WRITE_ENABLED",
                "VAULTAI_ZK_NEW_FILE_V2_ENABLED"):
        monkeypatch.setenv(key, "true")
    assert routes.pin_free_v2_file_upload_server_enabled() is True
    monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "false")
    assert routes.pin_free_v2_file_upload_server_enabled() is False
    monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "true")
    monkeypatch.setenv("FILE_V2_WRITE_ENABLED", "false")
    assert routes.pin_free_v2_file_upload_server_enabled() is False
