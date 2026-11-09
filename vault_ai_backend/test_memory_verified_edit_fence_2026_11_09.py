"""Default-off post-commit Memory V2 protection and concurrent source writes."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
from threading import Event
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

import durable_personal_memory as old_memory
from legacy_source_snapshot import source_snapshot
from routes import memory_routes as old_routes


def test_only_named_database_conflict_maps_to_protected_memory():
    named = SimpleNamespace(
        pgcode="23514",
        diag=SimpleNamespace(constraint_name="memory_v2_verified_edit_fence"),
    )
    other = SimpleNamespace(
        pgcode="23514", diag=SimpleNamespace(constraint_name="other_check"),
    )
    assert old_memory._is_owner_v2_edit_conflict(named)
    assert not old_memory._is_owner_v2_edit_conflict(other)
    assert not old_memory._is_owner_v2_edit_conflict(Exception("other"))


def test_old_dashboard_mutations_return_explicit_conflict(monkeypatch):
    monkeypatch.setattr(old_routes, "_legacy_memory_allowed", lambda: True)
    monkeypatch.setattr(old_routes, "_verified_vault_key", lambda *_a: ("vault", b"key"))
    monkeypatch.setattr(old_routes, "_rate_limit", lambda *_a: None)
    monkeypatch.setattr(old_routes, "_is_enabled", lambda: True)
    monkeypatch.setattr(old_routes, "require_content_write", lambda *_a: None)
    conflict = {"ok": False, "conflict": "memory_v2_owner_edit_conflict"}
    monkeypatch.setattr(old_memory, "save_memory_payload", lambda **_k: conflict)
    monkeypatch.setattr(old_memory, "update_memory_item", lambda **_k: conflict)
    monkeypatch.setattr(old_memory, "delete_memory_item", lambda **_k: conflict)
    requests = (
        (old_routes.memory_create_endpoint,
         old_routes.MemoryCreateRequest(pin="123456", title="Synthetic", value="A")),
        (old_routes.memory_update_endpoint,
         old_routes.MemoryUpdateRequest(
             id=1, pin="123456", title="Synthetic", value="B",
         )),
        (old_routes.memory_delete_endpoint,
         old_routes.MemoryDeleteRequest(id=1, pin="123456")),
    )
    for handler, payload in requests:
        with pytest.raises(HTTPException) as rejected:
            asyncio.run(handler(payload, {"vault_id": "vault"}))
        assert rejected.value.status_code == 409
        assert rejected.value.detail == "memory_updated_in_newer_app"


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_committed_owner_edit_wins_concurrent_older_source_write(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_memory_copy_qa"
    assert dsn == os.environ["DATABASE_URL"]
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    vault_id = str(uuid4())
    original = b"Q" * 50
    owner_edit = b"R" * 50
    stale_old_edit = b"S" * 50
    initial_v2 = b"\x01" + secrets.token_bytes(28)
    edited_v2 = b"\x01" + secrets.token_bytes(28)
    old_id = None
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
                "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
                (vault_id, f"vault-{vault_id.replace('-', '')}",
                 secrets.token_bytes(15), secrets.token_bytes(32),
                 secrets.token_bytes(48)),
            )
            cur.execute(
                "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
                "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s) "
                "RETURNING id", (vault_id, original),
            )
            old_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
                "memory_lookup_hash FROM vault_ai_memory WHERE id=%s", (old_id,),
            )
            snapshot = source_snapshot(
                "memory", cur.fetchone(), vault_id=vault_id, record_id=old_id,
            )
            cur.execute(
                "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,vault_id,"
                "source_snapshot,memory_record_id,memory_type,payload_ciphertext) "
                "VALUES(%s,%s,%s,%s,'note',%s)",
                (old_id, vault_id, snapshot, f"memory-migrated-{old_id}",
                 initial_v2),
            )

        owner_locked = Event()
        release_owner = Event()
        old_writer_started = Event()
        old_writer_pid: list[int] = []

        def owner_writer() -> None:
            with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id FROM vault_ai_memory WHERE id=%s FOR UPDATE", (old_id,),
                )
                owner_locked.set()
                assert release_owner.wait(15)
                cur.execute(
                    "DELETE FROM memory_v2_prepared_copies "
                    "WHERE legacy_memory_id=%s", (old_id,),
                )
                cur.execute(
                    "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s "
                    "RETURNING id,payload_ciphertext,memory_type,memory_record_id,"
                    "memory_lookup_hash", (owner_edit, old_id),
                )
                updated_snapshot = source_snapshot(
                    "memory", cur.fetchone(), vault_id=vault_id, record_id=old_id,
                )
                cur.execute(
                    "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,"
                    "vault_id,source_snapshot,memory_record_id,memory_type,"
                    "payload_ciphertext,owner_verified_edit) "
                    "VALUES(%s,%s,%s,%s,'note',%s,TRUE)",
                    (old_id, vault_id, updated_snapshot,
                     f"memory-migrated-{old_id}", edited_v2),
                )

        def older_writer() -> str:
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                old_writer_pid.append(cur.fetchone()[0])
                old_writer_started.set()
                with pytest.raises(psycopg2.errors.CheckViolation) as rejected:
                    cur.execute(
                        "UPDATE vault_ai_memory SET payload_ciphertext=%s "
                        "WHERE id=%s", (stale_old_edit, old_id),
                    )
                return str(rejected.value.diag.constraint_name)

        with ThreadPoolExecutor(max_workers=2) as pool:
            owner_future = pool.submit(owner_writer)
            try:
                assert owner_locked.wait(15)
                old_future = pool.submit(older_writer)
                assert old_writer_started.wait(15)
                # Prove the older UPDATE is waiting on the owner's source
                # row, rather than merely executing after owner commit.
                for _ in range(100):
                    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                        cur.execute(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid=%s", (old_writer_pid[0],),
                        )
                        waiting = cur.fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError("older Memory writer did not wait on source row")
            finally:
                release_owner.set()
            owner_future.result(timeout=15)
            assert old_future.result(timeout=15) == "memory_v2_verified_edit_fence"

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext FROM vault_ai_memory WHERE id=%s",
                        (old_id,))
            assert bytes(cur.fetchone()[0]) == owner_edit
            cur.execute("SELECT payload_ciphertext,owner_verified_edit "
                        "FROM memory_v2_prepared_copies WHERE legacy_memory_id=%s",
                        (old_id,))
            copy = cur.fetchone()
            assert bytes(copy[0]) == edited_v2
            assert copy[1] is True
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            # Vault-wide deletion may cascade through a protected copy.
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
