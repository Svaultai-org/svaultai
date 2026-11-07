"""A signed file offer rejects replaced PIN routes before body parsing."""

from __future__ import annotations

import asyncio
import json

import pytest

import auth_local
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


@pytest.mark.parametrize("bits,path,reason", [
    (2, "/list-files", "pin_free_read_required"),
    (2, "/files/synthetic/related", "pin_free_read_required"),
    (6, "/download-file", "pin_free_read_required"),
    (6, "/download-file/manifest", "pin_free_read_required"),
    (8, "/upload-file", "pin_free_file_create_required"),
    (8, "/upload-file/init", "pin_free_file_create_required"),
    (519, "/files/synthetic/related", "pin_free_private_chat_required"),
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


def test_pin_free_successors_and_unoffered_routes_remain_available():
    old = auth_local._format_token(bytes(range(16)))
    offered = auth_local.sign_opaque_read_offer_token(old, 15)
    for path in (
        "/vault/files/metadata", "/vault/legacy-ciphertext/export/start",
        "/vault/legacy-ciphertext/export/page",
        "/vault/legacy-file/chunked/manifest", "/download-file/chunk",
        "/vault/file-v2/manifest", "/vault/file-v2/chunk",
        "/vault/file-v2/synthetic/publish-new", "/vault/file-v2/synthetic",
        "/upload-file/chunk", "/upload-file/finalize", "/upload-file/abort",
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
