"""Owner-confirmed staged Memory copy, using only a disposable database."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import secrets
from threading import Event
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from legacy_source_snapshot import source_snapshot
from routes import legacy_memory_v2_copy_routes as copy


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_stage_confirmation_is_off_before_database(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_MEMORY_STAGE_CONFIRM_ENABLED", raising=False)
    monkeypatch.setattr(copy, "get_db", lambda: pytest.fail("database opened"))
    payload = copy.LegacyMemoryCopyConfirmRequest(
        source_snapshot="A" * 43,
        payload_sha256="B" * 43,
        zk_proof_token="synthetic-proof",
        client_verified_readback=True,
    )
    with pytest.raises(HTTPException) as denied:
        copy.confirm_legacy_memory_copy(1, payload, {"vault_id": str(uuid4())})
    assert denied.value.status_code == 404


def test_confirmation_rejects_pin_and_plaintext_fields():
    body = {
        "source_snapshot": "A" * 43,
        "payload_sha256": "B" * 43,
        "zk_proof_token": "synthetic-proof",
        "client_verified_readback": True,
    }
    for forbidden in ("pin", "memory_value", "title"):
        with pytest.raises(ValidationError):
            copy.LegacyMemoryCopyConfirmRequest.model_validate({
                **body, forbidden: "synthetic private value",
            })


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_confirmation_preserves_old_read_and_rejects_later_old_write(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_memory_copy_qa"
    assert dsn == os.environ["DATABASE_URL"]
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_STAGE_CONFIRM_ENABLED", "true")
    monkeypatch.setattr(copy, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(copy, "require_content_write", lambda _p: None)
    monkeypatch.setattr(
        copy, "consume_recent_zk_proof_on_cursor",
        lambda _proof, _principal, _cur: None,
    )
    vault_id = str(uuid4())
    principal = {"vault_id": vault_id}
    old_bytes = b"Q" * 50
    v2_bytes = b"\x01" + secrets.token_bytes(28)
    memory_id = None
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
                "RETURNING id", (vault_id, old_bytes),
            )
            memory_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
                "memory_lookup_hash FROM vault_ai_memory WHERE id=%s", (memory_id,),
            )
            snapshot = source_snapshot(
                "memory", cur.fetchone(), vault_id=vault_id, record_id=memory_id,
            )
            cur.execute(
                "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,vault_id,"
                "source_snapshot,memory_record_id,memory_type,payload_ciphertext) "
                "VALUES(%s,%s,%s,%s,'note',%s)",
                (memory_id, vault_id, snapshot,
                 f"memory-migrated-{memory_id}", v2_bytes),
            )
        payload = copy.LegacyMemoryCopyConfirmRequest(
            source_snapshot=snapshot,
            payload_sha256=_encoded(hashlib.sha256(v2_bytes).digest()),
            zk_proof_token="synthetic-confirm-proof",
            client_verified_readback=True,
        )
        wrong = payload.model_copy(update={"payload_sha256": "A" * 43})
        with pytest.raises(HTTPException) as mismatched:
            copy.confirm_legacy_memory_copy(memory_id, wrong, principal)
        assert mismatched.value.status_code == 409
        assert mismatched.value.detail == "memory_copy_changed"
        confirmed = copy.confirm_legacy_memory_copy(memory_id, payload, principal)
        assert confirmed["confirmed"] is True
        assert confirmed["older_client_writes_blocked"] is True
        assert confirmed["payload_sha256"] == payload.payload_sha256
        assert copy.confirm_legacy_memory_copy(memory_id, payload, principal) == confirmed
        readback = copy.readback_legacy_memory_copy(memory_id, principal=principal)
        assert readback["payload_ciphertext"] == _encoded(v2_bytes)
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload_ciphertext,owner_verified_stage "
                "FROM memory_v2_prepared_copies WHERE legacy_memory_id=%s",
                (memory_id,),
            )
            stored = cur.fetchone()
            assert bytes(stored[0]) == v2_bytes
            assert stored[1] is True
            # Metadata-only activity does not invalidate a confirmed copy.
            cur.execute("UPDATE vault_ai_memory SET updated_at=NOW() WHERE id=%s",
                        (memory_id,))
        old_conn = psycopg2.connect(dsn)
        try:
            with old_conn.cursor() as cur:
                with pytest.raises(psycopg2.errors.CheckViolation) as rejected:
                    cur.execute(
                        "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
                        (b"R" * 50, memory_id),
                    )
            assert rejected.value.diag.constraint_name == "memory_v2_verified_edit_fence"
        finally:
            old_conn.rollback()
            old_conn.close()
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext FROM vault_ai_memory WHERE id=%s",
                        (memory_id,))
            assert bytes(cur.fetchone()[0]) == old_bytes
        reused = copy.stage_legacy_memory_copy(
            memory_id,
            copy.LegacyMemoryCopyStageRequest(
                source_snapshot=snapshot,
                payload_ciphertext=_encoded(b"\x01" + secrets.token_bytes(28)),
                zk_proof_token="synthetic-reuse-proof",
                client_verified_source=True,
            ),
            principal,
        )
        assert reused["reused_verified_copy"] is True
        assert copy.readback_legacy_memory_copy(
            memory_id, principal=principal,
        )["payload_ciphertext"] == _encoded(v2_bytes)

        # The confirm transaction locks the source before it marks the copy.
        # An older writer already waiting on that row must see the committed
        # marker and fail, not delete the copy through the 0064 trigger.
        second_v2 = b"\x01" + secrets.token_bytes(28)
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
                "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s) "
                "RETURNING id", (vault_id, old_bytes),
            )
            second_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
                "memory_lookup_hash FROM vault_ai_memory WHERE id=%s", (second_id,),
            )
            second_snapshot = source_snapshot(
                "memory", cur.fetchone(), vault_id=vault_id, record_id=second_id,
            )
            cur.execute(
                "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,vault_id,"
                "source_snapshot,memory_record_id,memory_type,payload_ciphertext) "
                "VALUES(%s,%s,%s,%s,'note',%s)",
                (second_id, vault_id, second_snapshot,
                 f"memory-migrated-{second_id}", second_v2),
            )
        second_payload = payload.model_copy(update={
            "source_snapshot": second_snapshot,
            "payload_sha256": _encoded(hashlib.sha256(second_v2).digest()),
        })
        confirm_locked = Event()
        release_confirm = Event()
        older_started = Event()
        older_pid: list[int] = []

        def pause_proof(_proof, _principal, _cur):
            confirm_locked.set()
            assert release_confirm.wait(15)

        monkeypatch.setattr(copy, "consume_recent_zk_proof_on_cursor", pause_proof)

        def older_write() -> str:
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                older_pid.append(cur.fetchone()[0])
                older_started.set()
                with pytest.raises(psycopg2.errors.CheckViolation) as rejected:
                    cur.execute(
                        "UPDATE vault_ai_memory SET payload_ciphertext=%s "
                        "WHERE id=%s", (b"S" * 50, second_id),
                    )
                return str(rejected.value.diag.constraint_name)

        with ThreadPoolExecutor(max_workers=2) as pool:
            confirmation = pool.submit(
                copy.confirm_legacy_memory_copy,
                second_id, second_payload, principal,
            )
            try:
                assert confirm_locked.wait(15)
                older = pool.submit(older_write)
                assert older_started.wait(15)
                for _ in range(100):
                    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                        cur.execute(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid=%s", (older_pid[0],),
                        )
                        waiting = cur.fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError("older Memory writer did not wait on confirm")
            finally:
                release_confirm.set()
            assert confirmation.result(timeout=15)["confirmed"] is True
            assert older.result(timeout=15) == "memory_v2_verified_edit_fence"
        assert copy.readback_legacy_memory_copy(
            second_id, principal=principal,
        )["payload_ciphertext"] == _encoded(second_v2)
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
