"""Semantic index writes must never persist a readable content_hash
for a ZK/adopted vault.

`semantic_embedder.upsert_uploaded_file_inline` / `upsert_vault_item_inline`
and their async background siblings must short-circuit before
computing embedding or hash when the vault is ZK-adopted. The
client is expected to compute keyed_content_hash locally (via a
subkey the backend never derives) and POST to
/vault/ciphertext/semantic-index.
"""

from __future__ import annotations

import asyncio
from unittest import mock


class _CursorSpy:
    def __init__(self) -> None:
        self.calls: list = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))


class _ConnSpy:
    def __init__(self) -> None:
        self.cur = _CursorSpy()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_upsert_uploaded_file_inline_short_circuits_for_zk_vault() -> None:
    import semantic_embedder as se
    conn = _ConnSpy()
    fake_embed = mock.AsyncMock(return_value=[0.1, 0.2])
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=True), \
         mock.patch("semantic_embedder.is_enabled",
                    return_value=True), \
         mock.patch("semantic_embedder.embed_text", fake_embed):
        asyncio.run(se.upsert_uploaded_file_inline(
            openai_client=None,
            conn=conn,
            vault_id="00000000-0000-0000-0000-000000000000",
            file_id="fake-file-id",
            kind="file_name",
            text="my_secret_passport.pdf",
        ))
    assert conn.cur.calls == [], (
        "ZK semantic embedding must not INSERT into semantic_index "
        f"— got {conn.cur.calls}"
    )
    assert fake_embed.call_count == 0, (
        "ZK semantic embedding must not even call OpenAI — the "
        "text is user-derived and must not leave the request "
        "unless client-authorized"
    )


def test_upsert_vault_item_inline_short_circuits_for_zk_vault() -> None:
    import semantic_embedder as se
    conn = _ConnSpy()
    fake_embed = mock.AsyncMock(return_value=[0.1])
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=True), \
         mock.patch("semantic_embedder.is_enabled",
                    return_value=True), \
         mock.patch("semantic_embedder.embed_text", fake_embed):
        asyncio.run(se.upsert_vault_item_inline(
            openai_client=None,
            conn=conn,
            vault_id="00000000-0000-0000-0000-000000000001",
            item_id=42,
            kind="item_service",
            text="chase.com",
        ))
    assert conn.cur.calls == []
    assert fake_embed.call_count == 0


def test_legacy_vault_still_indexes_via_plaintext_content_hash() -> None:
    """Non-adopted vaults must keep the plaintext-hash indexing path
    so the product does not regress for un-migrated users."""
    import semantic_embedder as se
    conn = _ConnSpy()
    fake_embed = mock.AsyncMock(return_value=[0.1, 0.2])
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=False), \
         mock.patch("semantic_embedder.is_enabled",
                    return_value=True), \
         mock.patch("semantic_embedder.embed_text", fake_embed):
        asyncio.run(se.upsert_uploaded_file_inline(
            openai_client=None,
            conn=conn,
            vault_id="00000000-0000-0000-0000-000000000002",
            file_id="legacy-file-id",
            kind="file_name",
            text="tax_return_2025.pdf",
        ))
    assert len(conn.cur.calls) == 1, (
        f"Legacy path must still INSERT once — got {conn.cur.calls}"
    )
