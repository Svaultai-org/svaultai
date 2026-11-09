"""Default-off atomic private file publish against disposable PostgreSQL."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import os
import secrets
from uuid import uuid4

from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from file_private_conflict_index import index_existing_file, mark_index_complete
from legacy_source_snapshot import FILE_SOURCE_FIELDS, source_snapshot
from routes import file_v2_new_upload_routes as route


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _new_id() -> str:
    return "v2-" + _encoded(secrets.token_bytes(20))


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="explicit disposable loopback PostgreSQL required",
)
def test_publish_atomically_handles_duplicate_name_skip_and_keep_both(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("port") == "55432"
    assert parsed.get("dbname") == "svault_file_qa_1109"
    assert dsn == os.environ["DATABASE_URL"]
    vault_id, token_id = str(uuid4()), str(uuid4())
    legacy_id = f"old-{uuid4()}"
    content, name, other = b"c" * 32, b"n" * 32, b"o" * 32

    # The release gate remains false in production. This test exercises the
    # decision only with an explicitly synthetic vault and a patched gate.
    monkeypatch.setattr(
        "file_create_conflict_gate.new_file_conflict_parity_ready",
        lambda: True,
    )
    monkeypatch.setattr(route, "_new_upload_enabled", lambda: None)
    monkeypatch.setattr(route, "require_content_write", lambda _principal: None)
    monkeypatch.setattr(route, "is_vault_zk_adopted", lambda _vault: True)
    monkeypatch.setattr(route, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(route, "_account_quota", lambda _cur, _account, used:
                        (1024, used))
    principal = {"vault_id": vault_id, "token_id": token_id,
                 "file_v2_reader_capable": True}

    def stage(file_id: str, size: int = 5) -> None:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO file_v2_records "
                "(file_id,vault_id,crypto_version,manifest_ciphertext,"
                "total_bytes,chunk_size,chunk_count,migrating_legacy) "
                "VALUES (%s,%s,'client_mvk_v2',%s,%s,%s,1,FALSE)",
                (file_id, vault_id, b"m" * 40, size, size),
            )
            cur.execute(
                "INSERT INTO file_v2_chunks(file_id,chunk_index,ciphertext) "
                "VALUES (%s,0,%s)",
                (file_id, b"x" * (size + route.AES_GCM_FRAME_OVERHEAD)),
            )

    def publish(file_id: str, *, content_tag: bytes, name_tag: bytes,
                action: str = "prompt") -> dict:
        return route.publish_new_file(
            file_id,
            route.PublishNewFile(
                confirm=True, content_token=_encoded(content_tag),
                name_tokens=[_encoded(name_tag)], duplicate_action=action,
            ),
            principal,
        )

    try:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
                "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
                (vault_id, f"vault-{vault_id.replace('-', '')}",
                 secrets.token_bytes(15), secrets.token_bytes(32),
                 secrets.token_bytes(48)),
            )
            cur.execute(
                "INSERT INTO auth_sessions(token_id,vault_id,expires_at,"
                "file_v2_reader_capable,auth_method) "
                "VALUES (%s,%s,NOW()+INTERVAL '1 hour',TRUE,'opaque')",
                (token_id, vault_id),
            )
            cur.execute(
                "INSERT INTO uploaded_files(id,vault_id,file_name,file_size,"
                "encrypted_file_data,storage_mode,upload_status) "
                "VALUES (%s,%s,'old.txt',5,'opaque-frame','inline','complete')",
                (legacy_id, vault_id),
            )
        with psycopg2.connect(dsn) as conn, conn.cursor(
            cursor_factory=RealDictCursor,
        ) as cur:
            cur.execute(
                f"SELECT {', '.join(FILE_SOURCE_FIELDS)} "
                "FROM uploaded_files WHERE id=%s AND vault_id=%s",
                (legacy_id, vault_id),
            )
            snapshot = source_snapshot(
                "file", cur.fetchone(), vault_id=vault_id,
                record_id=legacy_id,
            )
            index_existing_file(
                cur, vault_id=vault_id, file_id=legacy_id, file_size=5,
                content_token=content, name_tokens=(name,),
                expected_source_snapshot=snapshot,
            )
            mark_index_complete(cur, vault_id=vault_id)
            cur.execute(
                "UPDATE file_private_conflict_state SET enforced=TRUE "
                "WHERE vault_id=%s", (vault_id,),
            )

        duplicate_id = _new_id()
        stage(duplicate_id)
        with pytest.raises(HTTPException) as duplicate:
            publish(duplicate_id, content_tag=content, name_tag=other)
        assert duplicate.value.status_code == 409
        assert duplicate.value.detail == {
            "code": "duplicate_found", "existing_file_id": legacy_id,
        }
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM file_v2_records WHERE file_id=%s",
                        (duplicate_id,))
            assert cur.fetchone() is not None
            cur.execute("SELECT 1 FROM uploaded_files WHERE id=%s",
                        (duplicate_id,))
            assert cur.fetchone() is None

        skipped = publish(duplicate_id, content_tag=content,
                          name_tag=other, action="skip")
        assert skipped == {
            "file_id": duplicate_id, "status": "skipped_duplicate",
            "duplicate_of_file_id": legacy_id,
        }
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM file_v2_records WHERE file_id=%s",
                        (duplicate_id,))
            assert cur.fetchone() is None

        kept_id = _new_id()
        stage(kept_id)
        with pytest.raises(HTTPException) as version_needed:
            publish(kept_id, content_tag=content, name_tag=name,
                    action="keep_both")
        assert version_needed.value.detail == {
            "code": "name_conflict", "existing_file_id": legacy_id,
        }
        assert publish(kept_id, content_tag=content, name_tag=other,
                       action="keep_both")["status"] == "published"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT duplicate_of_file_id FROM uploaded_files "
                "WHERE id=%s AND vault_id=%s", (kept_id, vault_id),
            )
            assert cur.fetchone()[0] == legacy_id

        same_name_id = _new_id()
        stage(same_name_id)
        with pytest.raises(HTTPException) as name_conflict:
            publish(same_name_id, content_tag=b"d" * 32, name_tag=name)
        assert name_conflict.value.detail == {
            "code": "name_conflict", "existing_file_id": legacy_id,
        }
        # The client can prepare a new manifest with an encrypted versioned
        # name and retry under a fresh ID. The server sees only its new tag.
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM file_v2_records WHERE file_id=%s",
                        (same_name_id,))
        versioned_id = _new_id()
        stage(versioned_id)
        assert publish(versioned_id, content_tag=b"d" * 32,
                       name_tag=b"v" * 32)["status"] == "published"

        raced_ids = (_new_id(), _new_id())
        for file_id in raced_ids:
            stage(file_id)

        def race(file_id: str) -> str:
            try:
                return publish(file_id, content_tag=b"e" * 32,
                               name_tag=b"r" * 32)["status"]
            except HTTPException as exc:
                assert exc.status_code == 409
                return exc.detail["code"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(race, raced_ids)) == [
                "duplicate_found", "published",
            ]

        name_race_ids = (_new_id(), _new_id())
        for file_id in name_race_ids:
            stage(file_id)

        def race_name(entry: tuple[int, str]) -> str:
            index, file_id = entry
            try:
                return publish(file_id, content_tag=bytes([40 + index]) * 32,
                               name_tag=b"s" * 32)["status"]
            except HTTPException as exc:
                assert exc.status_code == 409
                return exc.detail["code"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(race_name, enumerate(name_race_ids))) == [
                "name_conflict", "published",
            ]

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM uploaded_files WHERE id IN (%s,%s)",
                raced_ids,
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT COUNT(*) FROM uploaded_files WHERE id IN (%s,%s)",
                name_race_ids,
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT inventory_generation,indexed_generation,enforced "
                "FROM file_private_conflict_state WHERE vault_id=%s",
                (vault_id,),
            )
            generation, indexed, enforced = cur.fetchone()
            assert generation == indexed and enforced is True
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))


def test_publish_requires_canonical_blind_tokens_and_known_action():
    tags = route._publish_conflict_tags
    with pytest.raises(HTTPException) as absent:
        tags(route.PublishNewFile(confirm=True))
    assert absent.value.detail == "private_file_conflict_token_invalid"
    with pytest.raises(HTTPException) as bad_action:
        tags(route.PublishNewFile(
            confirm=True, content_token=_encoded(b"c" * 32),
            name_tokens=[_encoded(b"n" * 32)], duplicate_action="replace",
        ))
    assert bad_action.value.detail == "private_file_duplicate_action_invalid"
    with pytest.raises(HTTPException) as repeated:
        tags(route.PublishNewFile(
            confirm=True, content_token=_encoded(b"c" * 32),
            name_tokens=[_encoded(b"n" * 32)] * 2,
        ))
    assert repeated.value.detail == "private_file_conflict_token_invalid"
