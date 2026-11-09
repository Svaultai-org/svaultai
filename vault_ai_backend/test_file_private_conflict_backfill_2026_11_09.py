"""Default-off owner file-index backfill checks on isolated PostgreSQL."""

from __future__ import annotations

import base64
import os
import secrets
from uuid import uuid4

from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from legacy_source_snapshot import source_snapshot
from routes import file_private_conflict_backfill_routes as route
from routes import legacy_ciphertext_migration_routes as migration


def test_disabled_route_does_not_open_database(monkeypatch):
    monkeypatch.delenv(route.FLAG_NAME, raising=False)
    monkeypatch.setattr(route, "get_db", lambda: pytest.fail("database opened"))
    payload = route.IndexLegacyFile(
        file_id="legacy-synthetic", source_snapshot="A" * 43,
        readback_receipt="synthetic-receipt",
        content_token="B" * 43, name_tokens=["C" * 43],
        zk_proof_token="synthetic-proof", client_verified_exact_bytes=True,
    )
    with pytest.raises(HTTPException) as disabled:
        route.index_legacy_file(payload, {"vault_id": str(uuid4())})
    assert disabled.value.status_code == 404


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_owner_receipt_and_source_snapshot_bind_private_tokens(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("port") == "55432"
    assert parsed.get("dbname") == "svault_file_conflict_backfill_qa"
    assert dsn == os.environ["DATABASE_URL"]
    monkeypatch.setenv(route.FLAG_NAME, "true")
    monkeypatch.setattr(route, "get_db", lambda: psycopg2.connect(dsn))
    actual_owner_guard = route._require_live_owner
    monkeypatch.setattr(route, "_require_live_owner", lambda *_: None)
    monkeypatch.setattr(migration, "_get_secret", lambda: b"synthetic-secret" * 3)
    consumed = []
    monkeypatch.setattr(
        route, "consume_recent_zk_proof_on_cursor",
        lambda proof, _principal, _cur: consumed.append(proof),
    )
    vault_id = str(uuid4())
    file_id = f"legacy-{uuid4()}"
    principal = {
        "vault_id": vault_id, "token_id": str(uuid4()),
        "device_id": "synthetic-device", "file_v2_reader_capable": True,
    }
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            cur.execute(
                "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
                "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
                (vault_id, f"vault-{vault_id.replace('-', '')}",
                 secrets.token_bytes(15), secrets.token_bytes(32),
                 secrets.token_bytes(48)),
            )
            cur.execute(
                "INSERT INTO uploaded_files(id,vault_id,file_name,file_size,"
                "encrypted_file_data,storage_mode,upload_status) "
                "VALUES (%s,%s,'photo.png',5,'synthetic-ciphertext',"
                "'inline','complete')", (file_id, vault_id),
            )
            cur.execute(
                "INSERT INTO file_v2_records "
                "(file_id,vault_id,crypto_version,manifest_ciphertext,"
                "total_bytes,chunk_size,chunk_count,migrating_legacy) "
                "VALUES (%s,%s,'client_mvk_v2',%s,5,1024,1,TRUE)",
                (file_id, vault_id, b"synthetic-manifest"),
            )
            cur.execute(
                "INSERT INTO file_v2_chunks(file_id,chunk_index,ciphertext) "
                "VALUES (%s,0,%s)", (file_id, b"synthetic-chunk"),
            )
            row = migration._load_file_pair(cur, vault_id, file_id, locked=False)
            digest, _ = migration._file_digest_and_v2_hash(
                cur, file_id, row, locked=False,
            )
            snapshot = source_snapshot(
                "file", row, vault_id=vault_id, record_id=file_id,
            )
            with pytest.raises(HTTPException) as old_client:
                actual_owner_guard(cur, {
                    **principal, "file_v2_reader_capable": False,
                })
            assert old_client.value.status_code == 426
            with pytest.raises(HTTPException) as revoked:
                actual_owner_guard(cur, principal)
            assert revoked.value.status_code == 401
        receipt, _ = migration._new_receipt("f", principal, file_id, digest)
        encoded = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
        payload = route.IndexLegacyFile(
            file_id=file_id, source_snapshot=snapshot,
            readback_receipt=receipt,
            content_token=encoded(b"c" * 32),
            name_tokens=[encoded(b"n" * 32)],
            zk_proof_token="synthetic-proof",
            client_verified_exact_bytes=True,
        )
        assert route.index_legacy_file(payload, principal) == {
            "file_id": file_id, "source_snapshot": snapshot,
            "indexed": True,
        }
        assert consumed == ["synthetic-proof"]
        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            cur.execute(
                "SELECT content_token,file_size FROM file_private_conflict_index "
                "WHERE vault_id=%s AND file_id=%s", (vault_id, file_id),
            )
            indexed = cur.fetchone()
            assert bytes(indexed["content_token"]) == b"c" * 32
            assert indexed["file_size"] == 5

        complete = route.complete_index(
            route.FinishIndex(zk_proof_token="second-proof"), principal,
        )
        assert complete["indexed"] is True
        assert complete["private_upload_enabled"] is False
        assert consumed[-1] == "second-proof"

        with pytest.raises(HTTPException) as wrong_receipt:
            route.index_legacy_file(
                payload.model_copy(update={"readback_receipt": "invalid"}),
                principal,
            )
        assert wrong_receipt.value.detail == "readback_required"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE uploaded_files SET file_name='changed.png' "
                "WHERE vault_id=%s AND id=%s", (vault_id, file_id),
            )
        with pytest.raises(HTTPException) as changed:
            route.index_legacy_file(payload, principal)
        assert changed.value.detail == "legacy_source_changed"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM file_private_conflict_index "
                "WHERE vault_id=%s", (vault_id,),
            )
            assert cur.fetchone()[0] == 0
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
