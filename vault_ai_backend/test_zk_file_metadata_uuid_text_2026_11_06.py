"""Real-PostgreSQL regression for the UUID/text file inventory join.

Set TEST_DATABASE_URL to a disposable database. No production connection is
accepted by the test runner. Tables are temporary and disappear on close.
"""

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest
from fastapi import HTTPException, Request

from routes import auth_zk_routes, zk_metadata_inventory_routes


def test_private_folder_offer_requires_new_client_and_server_gate(monkeypatch):
    def request(*, capability=None, reader=True):
        headers = [(b"x-svaultai-file-v2-reader", b"1")] if reader else []
        if capability is not None:
            headers.append((b"x-svaultai-private-local-folders",
                            capability.encode("ascii")))
        return Request({"type": "http", "method": "POST",
                        "path": "/auth/zk-login-finalize", "headers": headers})

    negotiate = auth_zk_routes._private_local_folder_negotiation
    monkeypatch.setenv("VAULTAI_ZK_SIGNED_FOLDER_METADATA_ENABLED", "true")
    assert not negotiate(request(), signed_reads=True)
    assert negotiate(request(capability="1"), signed_reads=True)
    for kwargs, signed_reads, expected in (
        ({"capability": "bad"}, True, "invalid_private_folder_capability"),
        ({"capability": "1"}, False, "signed_read_offers_required"),
        ({"capability": "1", "reader": False}, True,
         "signed_read_offers_required"),
    ):
        with pytest.raises(HTTPException) as denied:
            negotiate(request(**kwargs), signed_reads=signed_reads)
        assert denied.value.detail == expected
    monkeypatch.setenv("VAULTAI_ZK_SIGNED_FOLDER_METADATA_ENABLED", "false")
    with pytest.raises(HTTPException) as denied:
        negotiate(request(capability="1"), signed_reads=True)
    assert denied.value.detail == "private_folder_inventory_unavailable"


def test_folder_path_metadata_is_returned_only_with_explicit_gate(monkeypatch):
    class Cursor:
        def execute(self, statement, params):
            assert "u.relative_path" in statement
            assert params == ("synthetic-vault", "", 101)

        def fetchall(self):
            return [{
                "id": "synthetic-file", "file_size": 5,
                "storage_mode": "inline", "chunk_size": None,
                "chunk_count": None, "upload_status": "complete",
                "needs_naming": False, "autosaved_secret": False,
                "file_name_ciphertext": b"encrypted-name",
                "saved_name_ciphertext": None,
                "content_type_ciphertext": None,
                "detected_type_ciphertext": None,
                "detected_service_ciphertext": None,
                "asset_type_ciphertext": None,
                "has_inline_ciphertext": True,
                "relative_path": "Folder/synthetic-file.txt",
                "created_at": None, "lifecycle_state": None,
                "verification_state": None, "name_version": None,
            }]

    class Connection:
        def cursor(self, **_kwargs):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setenv("VAULTAI_ZK_METADATA_INVENTORY_ENABLED", "true")
    monkeypatch.setattr(zk_metadata_inventory_routes,
                        "is_vault_zk_adopted", lambda _vault_id: True)
    monkeypatch.setattr(zk_metadata_inventory_routes,
                        "get_db", lambda: Connection())
    kwargs = {"after_file_id": "", "limit": 100,
              "principal": {"vault_id": "synthetic-vault"}}
    without_gate = zk_metadata_inventory_routes.file_metadata_inventory(**kwargs)
    assert without_gate["records"][0]["relative_path"] is None
    monkeypatch.setenv("VAULTAI_ZK_SIGNED_FOLDER_METADATA_ENABLED", "true")
    with_gate = zk_metadata_inventory_routes.file_metadata_inventory(**kwargs)
    assert with_gate["records"][0]["relative_path"] == (
        "Folder/synthetic-file.txt"
    )


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="disposable PostgreSQL required",
)
def test_file_list_offer_and_inventory_match_schema_0056_types(monkeypatch):
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    vault_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE uploaded_files (
                id text PRIMARY KEY, vault_id uuid NOT NULL,
                file_size bigint, storage_mode text, upload_status text,
                chunk_size integer, chunk_count integer,
                needs_naming boolean, autosaved_secret boolean,
                file_name_ciphertext bytea, saved_name_ciphertext bytea,
                content_type_ciphertext bytea, detected_type_ciphertext bytea,
                detected_service_ciphertext bytea, asset_type_ciphertext bytea,
                encrypted_file_data text, created_at timestamptz,
                file_name text, saved_name text, content_type text, detected_type text,
                detected_service text, asset_type text, relative_path text
            )
        """)
        cur.execute("""
            CREATE TEMP TABLE file_v2_records (
                file_id text, vault_id text,
                saved_name_override_ciphertext bytea,
                lifecycle_state text, verification_state text,
                name_version integer, migrating_legacy boolean
            )
        """)
        cur.execute("""
            INSERT INTO uploaded_files (
                id, vault_id, file_size, storage_mode, upload_status,
                needs_naming, autosaved_secret, file_name_ciphertext,
                encrypted_file_data, created_at, relative_path
            ) VALUES (%s, %s::uuid, 14, 'inline', 'complete',
                      true, false, %s, 'ciphertext', NOW(),
                      'Folder/synthetic-file.txt')
        """, ("synthetic-file", vault_id, b"synthetic-encrypted-label"))
        cur.execute("""
            INSERT INTO uploaded_files (
                id, vault_id, file_size, storage_mode, upload_status,
                needs_naming, autosaved_secret, file_name_ciphertext,
                encrypted_file_data, created_at
            ) VALUES (%s, %s::uuid, 14, 'inline', 'incomplete',
                      false, false, NULL, 'ciphertext', NOW())
        """, ("unfinished-file", vault_id))
        cur.execute("""
            INSERT INTO file_v2_records (
                file_id, vault_id, lifecycle_state, verification_state,
                migrating_legacy
            ) VALUES (%s, %s, 'file_v2_written', 'not_verified', true)
        """, ("synthetic-file", vault_id))
    conn.commit()

    try:
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id, allow_old_folders=True,
        ) is True
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id,
        ) is True
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id, chunked_route_enabled=False,
        ) is True
        monkeypatch.setenv("VAULTAI_ZK_METADATA_INVENTORY_ENABLED", "true")
        monkeypatch.setenv("VAULTAI_ZK_SIGNED_FOLDER_METADATA_ENABLED", "true")
        monkeypatch.setattr(
            zk_metadata_inventory_routes, "is_vault_zk_adopted",
            lambda candidate: candidate == vault_id,
        )
        monkeypatch.setattr(
            zk_metadata_inventory_routes, "get_db", lambda: conn,
        )
        result = zk_metadata_inventory_routes.file_metadata_inventory(
            after_file_id="", limit=100,
            principal={"vault_id": vault_id},
        )
        assert len(result["records"]) == 1
        assert result["records"][0]["file_id"] == "synthetic-file"
        assert result["records"][0]["relative_path"] == (
            "Folder/synthetic-file.txt"
        )
        assert result["records"][0]["needs_naming"] is True
        assert result["records"][0]["lifecycle_state"] == "file_v2_written"
    finally:
        if not conn.closed:
            conn.close()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="disposable PostgreSQL required",
)
def test_file_list_offer_rejects_missing_labels_and_new_v2(monkeypatch):
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    vault_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TEMP TABLE uploaded_files (
                    id text, vault_id uuid, upload_status text, file_size bigint,
                    storage_mode text, encrypted_file_data text,
                    chunk_size integer, chunk_count integer,
                    file_name text, file_name_ciphertext bytea, saved_name text,
                    saved_name_ciphertext bytea, content_type text,
                    content_type_ciphertext bytea, detected_type text,
                    detected_type_ciphertext bytea, detected_service text,
                    detected_service_ciphertext bytea, asset_type text,
                    asset_type_ciphertext bytea, relative_path text
                )
            """)
            cur.execute("""
                CREATE TEMP TABLE file_v2_records (
                    file_id text, vault_id text, lifecycle_state text,
                    verification_state text,
                    migrating_legacy boolean,
                    saved_name_override_ciphertext bytea
                )
            """)
            cur.execute("""
                INSERT INTO uploaded_files
                    (id, vault_id, upload_status, file_size, storage_mode,
                     encrypted_file_data)
                VALUES ('synthetic-file', %s::uuid, 'complete', 14, 'inline', 'ciphertext')
            """, (vault_id,))
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id,
        ) is True
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id, chunked_route_enabled=False,
        ) is True
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE uploaded_files
                   SET storage_mode='chunked', file_size=3,
                       chunk_size=16777216, chunk_count=1,
                       encrypted_file_data=NULL
            """)
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id,
        ) is True
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id, chunked_route_enabled=False,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET chunk_size=16777217")
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE uploaded_files
                   SET storage_mode='inline', file_size=14,
                       encrypted_file_data='ciphertext'
            """)
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_name_ciphertext=%s",
                        (b"synthetic-label",))
            cur.execute("UPDATE uploaded_files SET relative_path='Folder/file.txt'")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id, allow_old_folders=True,
        ) is True
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET relative_path='Folder/../file.txt'")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id, allow_old_folders=True,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET relative_path=NULL")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is True
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET saved_name='AI name'")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET saved_name_ciphertext=%s",
                        (b"synthetic-encrypted-ai-name",))
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET saved_name=NULL")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is True
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_name='old-client-name'")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_name=NULL")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is True
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_name_ciphertext=%s",
                        (b"x" * 4097,))
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_name_ciphertext=%s",
                        (b"synthetic-label",))
            cur.execute("UPDATE uploaded_files SET id=%s", ("x" * 129,))
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET id='synthetic-file'")
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is True
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO file_v2_records
                    (vault_id, verification_state, migrating_legacy)
                VALUES (%s, 'not_verified', false)
            """, (vault_id,))
        assert auth_zk_routes._pin_free_legacy_file_list_ready(
            conn, vault_id,
        ) is False
        assert auth_zk_routes._pin_free_legacy_file_download_ready(
            conn, vault_id,
        ) is False
    finally:
        conn.close()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="disposable PostgreSQL required",
)
def test_mixed_legacy_and_ready_v2_files_get_signed_read_offer():
    """A ready V2 marker is covered by its manifest, never a legacy PIN read."""
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    vault_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TEMP TABLE uploaded_files (
                    id text, vault_id uuid, upload_status text,
                    file_size bigint, storage_mode text,
                    encrypted_file_data text, chunk_size integer,
                    chunk_count integer, file_name text,
                    file_name_ciphertext bytea, saved_name text,
                    saved_name_ciphertext bytea, content_type text,
                    content_type_ciphertext bytea, detected_type text,
                    detected_type_ciphertext bytea, detected_service text,
                    detected_service_ciphertext bytea, asset_type text,
                    asset_type_ciphertext bytea, relative_path text
                )
            """)
            cur.execute("""
                CREATE TEMP TABLE file_v2_records (
                    file_id text, vault_id text, crypto_version text,
                    total_bytes bigint, chunk_size integer,
                    chunk_count integer, lifecycle_state text,
                    verification_state text, migrating_legacy boolean,
                    saved_name_override_ciphertext bytea
                )
            """)
            cur.execute("""
                INSERT INTO uploaded_files
                  (id, vault_id, upload_status, file_size, storage_mode,
                   encrypted_file_data, file_name_ciphertext)
                VALUES ('old-file', %s::uuid, 'complete', 12, 'inline',
                        'opaque-frame', %s),
                       ('new-file', %s::uuid, 'complete', 8, 'inline',
                        NULL, NULL)
            """, (vault_id, b"encrypted-name", vault_id))
            cur.execute("""
                INSERT INTO file_v2_records
                  (file_id, vault_id, crypto_version, total_bytes,
                   chunk_size, chunk_count, lifecycle_state,
                   verification_state, migrating_legacy)
                VALUES ('new-file', %s, 'client_mvk_v2', 8, 8, 1,
                        'client_v2_ready', 'client_verified', false)
            """, (vault_id,))
        list_ready = auth_zk_routes._pin_free_legacy_file_list_ready
        download_ready = auth_zk_routes._pin_free_legacy_file_download_ready
        assert not list_ready(conn, vault_id)
        assert not download_ready(conn, vault_id)
        assert list_ready(conn, vault_id, allow_ready_v2=True)
        assert download_ready(conn, vault_id, allow_ready_v2=True)

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE file_v2_records SET saved_name_override_ciphertext=%s
                WHERE file_id='new-file'
            """, (b"encrypted-renamed-label",))
        assert list_ready(conn, vault_id, allow_ready_v2=True)
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_size=9 WHERE id='new-file'")
        assert not list_ready(conn, vault_id, allow_ready_v2=True)
        assert not download_ready(conn, vault_id, allow_ready_v2=True)
        with conn.cursor() as cur:
            cur.execute("UPDATE uploaded_files SET file_size=8 WHERE id='new-file'")
            cur.execute("DELETE FROM uploaded_files WHERE id='new-file'")
        assert not list_ready(conn, vault_id, allow_ready_v2=True)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO uploaded_files
                  (id, vault_id, upload_status, file_size, storage_mode)
                VALUES ('new-file', %s::uuid, 'complete', 8, 'inline')
            """, (vault_id,))
            cur.execute("""
                UPDATE file_v2_records
                   SET verification_state='not_verified'
                 WHERE file_id='new-file'
            """)
        assert not list_ready(conn, vault_id, allow_ready_v2=True)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE file_v2_records
                   SET lifecycle_state='legacy_migration_retired',
                       verification_state='client_verified',
                       migrating_legacy=true
                 WHERE file_id='new-file'
            """)
        assert list_ready(conn, vault_id, allow_ready_v2=True)
        assert download_ready(conn, vault_id, allow_ready_v2=True)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO file_v2_records
                  (file_id, vault_id, crypto_version, total_bytes,
                   chunk_size, chunk_count, lifecycle_state,
                   verification_state, migrating_legacy)
                VALUES ('unfinished-new', %s, 'client_mvk_v2', 1, 1, 1,
                        'file_v2_written', 'not_verified', false)
            """, (vault_id,))
        assert not list_ready(conn, vault_id, allow_ready_v2=True)
    finally:
        conn.close()
