"""Private file conflict index tests on a disposable loopback database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import secrets
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from file_private_conflict_index import (
    index_existing_file, inspect_and_reserve_new_file,
    mark_index_complete,
)
from legacy_source_snapshot import FILE_SOURCE_FIELDS, source_snapshot


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_private_conflicts_are_atomic_and_legacy_writers_are_fenced():
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("port") == "55432"
    assert parsed.get("dbname") == "svault_file_conflict_qa2"
    assert dsn == os.environ["DATABASE_URL"]
    vault_id = str(uuid4())
    old_file_id = f"legacy-{uuid4()}"
    old_content_token = b"c" * 32
    old_name_token = b"n" * 32
    new_content_token = b"d" * 32
    new_name_token = b"p" * 32

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
                "'inline','complete')",
                (old_file_id, vault_id),
            )

        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            with pytest.raises(HTTPException) as incomplete:
                mark_index_complete(cur, vault_id=vault_id)
            assert incomplete.value.detail == "private_file_index_incomplete"
            cur.execute(
                f"SELECT {', '.join(FILE_SOURCE_FIELDS)} FROM uploaded_files "
                "WHERE vault_id=%s AND id=%s",
                (vault_id, old_file_id),
            )
            snapshot = source_snapshot(
                "file", cur.fetchone(), vault_id=vault_id,
                record_id=old_file_id,
            )
            with pytest.raises(HTTPException) as stale:
                index_existing_file(
                    cur, vault_id=vault_id, file_id=old_file_id,
                    file_size=5, content_token=old_content_token,
                    name_tokens=(old_name_token,),
                    expected_source_snapshot="A" * 43,
                )
            assert stale.value.detail == "private_file_source_changed"
            index_existing_file(
                cur, vault_id=vault_id, file_id=old_file_id,
                file_size=5, content_token=old_content_token,
                name_tokens=(old_name_token,),
                expected_source_snapshot=snapshot,
            )
            generation = mark_index_complete(cur, vault_id=vault_id)
            assert generation >= 1
            cur.execute(
                "SELECT enforced FROM file_private_conflict_state "
                "WHERE vault_id=%s", (vault_id,),
            )
            assert cur.fetchone()["enforced"] is False
            with pytest.raises(HTTPException) as inactive:
                inspect_and_reserve_new_file(
                    cur, vault_id=vault_id, file_id="v2-inactive",
                    file_size=5, content_token=new_content_token,
                    name_tokens=(new_name_token,),
                )
            assert inactive.value.detail == "private_file_conflict_index_unavailable"
            cur.execute(
                "UPDATE uploaded_files SET file_name='renamed.png' "
                "WHERE vault_id=%s AND id=%s",
                (vault_id, old_file_id),
            )
            cur.execute(
                "SELECT indexed_generation FROM file_private_conflict_state "
                "WHERE vault_id=%s", (vault_id,),
            )
            assert cur.fetchone()["indexed_generation"] is None
            with pytest.raises(HTTPException) as changed:
                mark_index_complete(cur, vault_id=vault_id)
            assert changed.value.detail == "private_file_index_incomplete"
            cur.execute(
                f"SELECT {', '.join(FILE_SOURCE_FIELDS)} FROM uploaded_files "
                "WHERE vault_id=%s AND id=%s",
                (vault_id, old_file_id),
            )
            renamed_snapshot = source_snapshot(
                "file", cur.fetchone(), vault_id=vault_id,
                record_id=old_file_id,
            )
            index_existing_file(
                cur, vault_id=vault_id, file_id=old_file_id,
                file_size=5, content_token=old_content_token,
                name_tokens=(old_name_token,),
                expected_source_snapshot=renamed_snapshot,
            )
            assert mark_index_complete(cur, vault_id=vault_id) > generation
            # This synthetic-only activation is intentionally absent from the
            # HTTP API. A release cannot turn it on without full client parity.
            cur.execute(
                "UPDATE file_private_conflict_state SET enforced=TRUE "
                "WHERE vault_id=%s", (vault_id,),
            )
            duplicate = inspect_and_reserve_new_file(
                cur, vault_id=vault_id, file_id="v2-duplicate",
                file_size=5, content_token=old_content_token,
                name_tokens=(b"z" * 32,),
            )
            assert (duplicate.kind, duplicate.existing_file_id) == (
                "duplicate", old_file_id,
            )
            name = inspect_and_reserve_new_file(
                cur, vault_id=vault_id, file_id="v2-name",
                file_size=6, content_token=b"e" * 32,
                name_tokens=(old_name_token,),
            )
            assert (name.kind, name.existing_file_id) == (
                "name_conflict", old_file_id,
            )

        barrier = Barrier(2)

        def publish(index: int):
            file_id = f"v2-race-{index}-{uuid4()}"
            with psycopg2.connect(dsn) as conn, conn.cursor(
                cursor_factory=RealDictCursor,
            ) as cur:
                barrier.wait(timeout=5)
                decision = inspect_and_reserve_new_file(
                    cur, vault_id=vault_id, file_id=file_id,
                    file_size=6, content_token=new_content_token,
                    name_tokens=(new_name_token,),
                )
                if decision.kind == "available":
                    cur.execute(
                        "INSERT INTO file_v2_records "
                        "(file_id,vault_id,crypto_version,manifest_ciphertext,"
                        "total_bytes,chunk_size,chunk_count,migrating_legacy) "
                        "VALUES (%s,%s,'client_mvk_v2',%s,6,1024,1,FALSE)",
                        (file_id, vault_id, b"synthetic-manifest"),
                    )
                    cur.execute(
                        "INSERT INTO uploaded_files "
                        "(id,vault_id,file_name,file_size,encrypted_file_data,"
                        "storage_mode,upload_status) "
                        "VALUES (%s,%s,NULL,6,NULL,'inline','complete')",
                        (file_id, vault_id),
                    )
                return decision

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, (1, 2)))
        assert sorted(result.kind for result in results) == [
            "available", "duplicate",
        ]

        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO uploaded_files(id,vault_id,file_name,file_size,"
                    "encrypted_file_data) VALUES (%s,%s,'older-client.txt',1,'x')",
                    (f"legacy-{uuid4()}", vault_id),
                )
            conn.rollback()

        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM uploaded_files WHERE vault_id=%s",
                (vault_id,),
            )
            assert cur.fetchone()["n"] == 2
    finally:
        # A synthetic fixture owns these rows; removing this fixture checks
        # cascading vault deletion does not resurrect a conflict state row.
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
