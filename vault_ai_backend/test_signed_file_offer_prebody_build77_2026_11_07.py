"""A signed file offer rejects replaced PIN routes before body parsing."""

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
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-file-offer-secret-" * 3)
    auth_local.reset_secret_for_tests()
    yield
    auth_local.reset_secret_for_tests()


async def _probe(path: str, headers: list[tuple[bytes, bytes]],
                 method: str = "POST") -> tuple[int, int, object]:
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
                "headers": headers}, receive, send)
    body = sent[1]["body"]
    return len(reads), sent[0]["status"], (
        json.loads(body) if sent[0]["status"] == 409 else body
    )


def _header(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode("ascii"))]


@pytest.mark.parametrize("path", ["/list-secure-items", "/get-secure-item"])
def test_signed_item_read_offer_rejects_pin_body_before_receive(path):
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, 1)
    for candidate in (path, path + "/"):
        assert asyncio.run(_probe(candidate, _header(offered))) == (
            0, 409, {"detail": "pin_free_read_required"},
        )
    # Clients that did not negotiate a signed item offer retain their route.
    for token in (old, auth_local.sign_opaque_read_offer_token(old, 6)):
        assert asyncio.run(_probe(path, _header(token))) == (1, 200, b"ok")
    # An extra legacy bearer cannot conceal the signed offer.
    assert asyncio.run(_probe(path, _header(old) + _header(offered))) == (
        0, 409, {"detail": "pin_free_read_required"},
    )
    # Only the two replaced POST contracts are fenced.
    assert asyncio.run(_probe(path, _header(offered), "OPTIONS")) == (
        1, 200, b"ok",
    )
    assert asyncio.run(_probe("/list-login-names", _header(offered))) == (
        1, 200, b"ok",
    )


@pytest.mark.parametrize("bits,path,reason", [
    (2, "/list-files", "pin_free_read_required"),
    (2, "/files/synthetic/related", "pin_free_read_required"),
    (6, "/download-file", "pin_free_read_required"),
    (6, "/download-file/manifest", "pin_free_read_required"),
    (8, "/upload-file", "pin_free_file_create_required"),
    (8, "/upload-file/init", "pin_free_file_create_required"),
    (8, "/upload-file/finalize", "pin_free_file_create_required"),
    (8, "/upload-file/abort", "pin_free_file_create_required"),
    (16, "/security-center/analyze-passwords",
     "pin_free_password_analysis_required"),
    (519, "/files/synthetic/related", "pin_free_private_chat_required"),
    (535, "/security-center/analyze-passwords",
     "pin_free_password_analysis_required"),
])
def test_signed_offer_blocks_replaced_file_post_before_receive(bits, path, reason):
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, bits)
    for candidate in (path, path + "/"):
        reads, status, body = asyncio.run(_probe(candidate, _header(offered)))
        assert (reads, status, body) == (0, 409, {"detail": reason})
    # An ordinary legacy bearer still follows its unchanged route.
    assert asyncio.run(_probe(path, _header(old))) == (1, 200, b"ok")
    # A second Authorization header cannot hide an issued offer.
    assert asyncio.run(_probe(path, _header(old) + _header(offered))) == (
        0, 409, {"detail": reason},
    )


@pytest.mark.parametrize("method,path", [
    ("POST", "/name-file"),
    ("PATCH", "/manage/file"),
    ("DELETE", "/manage/file"),
    ("POST", "/manage/file/delete"),
    ("DELETE", "/delete-file"),
])
@pytest.mark.parametrize("bits", [39, 551])
def test_signed_file_mutation_offer_blocks_old_routes_before_body(
    method, path, bits,
):
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, bits)
    for candidate in (path, path + "/"):
        assert asyncio.run(_probe(candidate, _header(offered), method)) == (
            0, 409, {"detail": "pin_free_file_mutation_required"},
        )
    assert asyncio.run(_probe(path, _header(old), method)) == (1, 200, b"ok")
    assert asyncio.run(_probe(path, _header(old) + _header(offered), method)) == (
        0, 409, {"detail": "pin_free_file_mutation_required"},
    )
    assert asyncio.run(_probe("/manage/file/delete-proof", _header(offered))) == (
        1, 200, b"ok",
    )
    assert asyncio.run(_probe(path, _header(offered), "OPTIONS")) == (
        1, 200, b"ok",
    )
    with pytest.raises(HTTPException) as blocked:
        auth_local.require_signed_offer_route(
            {"pin_free_read_offers": bits}, path=path,
        )
    assert blocked.value.detail == "pin_free_file_mutation_required"


def test_file_mutation_offer_needs_explicit_client_and_server_flags(monkeypatch):
    def request(*, offered: bool, reader: bool) -> Request:
        headers = []
        if offered:
            headers.append((b"x-svaultai-pin-free-file-mutation", b"1"))
        if reader:
            headers.append((b"x-svaultai-file-v2-reader", b"1"))
        return Request({"type": "http", "method": "POST",
                        "path": "/auth/zk-login-finalize", "headers": headers})

    negotiate = auth_zk_routes._signed_file_mutation_negotiation
    assert negotiate(request(offered=False, reader=False),
                     signed_reads=False) is False
    with pytest.raises(HTTPException) as disabled:
        negotiate(request(offered=True, reader=True), signed_reads=True)
    assert disabled.value.detail == "signed_file_mutation_unavailable"
    for flag in ("VAULTAI_SIGNED_FILE_MUTATION_ENABLED",
                 "VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED",
                 "VAULTAI_ZK_FILE_V2_RENAME_ENABLED"):
        monkeypatch.setenv(flag, "true")
    for signed_reads, reader in ((False, True), (True, False)):
        with pytest.raises(HTTPException) as missing:
            negotiate(request(offered=True, reader=reader),
                      signed_reads=signed_reads)
        assert missing.value.detail == "signed_read_offers_required"
    assert negotiate(request(offered=True, reader=True), signed_reads=True)
    old = auth_local._format_token(bytes(range(16)))
    issued = auth_zk_routes._signed_offer_token(
        old, signed_reads=True, item_read=True, file_list=True,
        file_download=True, file_create=False, file_mutation=True,
    )
    assert auth_local._parse_token_claims(issued) == (bytes(range(16)), 39)


def test_existing_signed_clients_keep_old_mutations_without_new_bit():
    old = auth_local._format_token(bytes(range(16)))
    for bits in (15, 519, 543):
        offered = auth_local.sign_opaque_read_offer_token(old, bits)
        for method, path in (
            ("POST", "/name-file"),
            ("PATCH", "/manage/file"),
            ("DELETE", "/manage/file"),
            ("POST", "/manage/file/delete"),
            ("DELETE", "/delete-file"),
        ):
            assert asyncio.run(_probe(path, _header(offered), method)) == (
                1, 200, b"ok",
            )


def test_pin_free_successors_and_unoffered_routes_remain_available():
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, 15)
    for path in (
        "/vault/files/metadata", "/vault/legacy-ciphertext/export/start",
        "/vault/legacy-ciphertext/export/page",
        "/vault/legacy-file/chunked/manifest", "/download-file/chunk",
        "/vault/file-v2/manifest", "/vault/file-v2/chunk",
        "/vault/file-v2/synthetic/publish-new", "/vault/file-v2/synthetic",
        "/upload-file/chunk", "/upload-file/finalize-token",
        "/upload-file/abort-token",
    ):
        assert asyncio.run(_probe(path, _header(offered))) == (1, 200, b"ok")
    assert asyncio.run(_probe("/download-file", _header(offered),
                              method="OPTIONS")) == (1, 200, b"ok")


def test_tampered_offer_is_not_treated_as_an_issued_offer():
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, 6)
    wire = bytearray(auth_local._b64url_decode(offered))
    wire[-1] ^= 1
    forged = auth_local._b64url_encode(wire)
    assert auth_local._parse_token_claims(forged) is None
    # The ordinary authentication dependency rejects this invalid bearer.
    # The pre-body fence must never trust unauthenticated offer bits.
    assert asyncio.run(_probe("/download-file", _header(forged))) == (
        1, 200, b"ok",
    )


def test_password_analysis_offer_requires_explicit_capable_client(monkeypatch):
    def request(*, password_analysis: bool, signed_reads: bool,
                reader: bool) -> Request:
        headers = []
        if password_analysis:
            headers.append((b"x-svaultai-pin-free-password-analysis", b"1"))
        if reader:
            headers.append((b"x-svaultai-file-v2-reader", b"1"))
        return Request({"type": "http", "method": "POST",
                        "path": "/auth/zk-login-finalize", "headers": headers})

    monkeypatch.delenv("VAULTAI_SIGNED_PASSWORD_ANALYSIS_ENABLED", raising=False)
    negotiate = auth_zk_routes._signed_password_analysis_negotiation
    assert negotiate(request(password_analysis=False, signed_reads=False,
                             reader=False), signed_reads=False) is False
    with pytest.raises(HTTPException) as disabled:
        negotiate(request(password_analysis=True, signed_reads=True,
                          reader=True), signed_reads=True)
    assert disabled.value.detail == "signed_password_analysis_unavailable"
    monkeypatch.setenv("VAULTAI_SIGNED_PASSWORD_ANALYSIS_ENABLED", "true")
    for signed_reads, reader in ((False, True), (True, False)):
        with pytest.raises(HTTPException) as missing:
            negotiate(request(password_analysis=True, signed_reads=signed_reads,
                              reader=reader), signed_reads=signed_reads)
        assert missing.value.detail == "signed_read_offers_required"
    assert negotiate(request(password_analysis=True, signed_reads=True,
                             reader=True), signed_reads=True) is True


def test_password_analysis_offer_is_mac_bound_and_legacy_route_scoped():
    old = auth_local._format_token(bytes(range(16)))
    for bits in (16, 535):
        offered = auth_local.sign_opaque_read_offer_token(old, bits)
        assert auth_local._parse_token_claims(offered) == (bytes(range(16)), bits)
        with pytest.raises(HTTPException) as blocked:
            auth_local.require_signed_offer_route(
                {"pin_free_read_offers": bits},
                path="/security-center/analyze-passwords",
            )
        assert blocked.value.detail == "pin_free_password_analysis_required"
        assert asyncio.run(_probe(
            "/security-center/analyze-passwords", _header(offered),
        )) == (0, 409, {"detail": "pin_free_password_analysis_required"})
    # Item-read alone does not imply a local analyzer and remains compatible.
    auth_local.require_signed_offer_route(
        {"pin_free_read_offers": 1},
        path="/security-center/analyze-passwords",
    )
    bit_one = auth_local.sign_opaque_read_offer_token(old, 1)
    assert asyncio.run(_probe(
        "/security-center/analyze-passwords", _header(bit_one),
    )) == (1, 200, b"ok")
