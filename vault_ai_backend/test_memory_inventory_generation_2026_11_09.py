"""Default-off Memory inventory fence and optional disposable DB proof."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
from threading import Event
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from auth_local import PIN_FREE_MEMORY_OFFER
from legacy_source_snapshot import source_snapshot
from routes import vault_ciphertext_write_routes as memory


class _Cursor:
    def __init__(self, generation: int, old_row: bool = False):
        self.generation = generation
        self.old_row = old_row
        self.queries = []

    def execute(self, query, _params):
        self.queries.append(query)

    def fetchone(self):
        if "memory_inventory_generation" in self.queries[-1]:
            return {"memory_inventory_generation": self.generation}
        return {"exists": 1} if self.old_row else None


def test_generation_fence_rejects_stale_inventory_after_mutation():
    cursor = _Cursor(43)
    with pytest.raises(HTTPException) as exc:
        memory._verify_memory_inventory_generation(
            cursor, str(uuid4()), "41", own_advances=1, signed_memory=True,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "memory_inventory_changed"
    assert "FOR UPDATE" in cursor.queries[0]


def test_generation_fence_allows_single_own_mutation():
    memory._verify_memory_inventory_generation(
        _Cursor(42), str(uuid4()), "41", own_advances=1,
        signed_memory=True,
    )


def test_prepared_edit_counts_source_invalidation_and_replacement_copy():
    memory._verify_memory_inventory_generation(
        _Cursor(44), str(uuid4()), "41", own_advances=3,
        signed_memory=True,
    )
    with pytest.raises(HTTPException) as exc:
        memory._verify_memory_inventory_generation(
            _Cursor(45), str(uuid4()), "41", own_advances=3,
            signed_memory=True,
        )
    assert exc.value.detail == "memory_inventory_changed"


def test_signed_native_client_requires_generation_when_old_row_exists(
    monkeypatch,
):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    cursor = _Cursor(41, old_row=True)
    with pytest.raises(HTTPException) as exc:
        memory._verify_memory_inventory_generation(
            cursor, str(uuid4()), None, own_advances=1, signed_memory=True,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "memory_inventory_generation_required"


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_old_writer_invalidates_copy_and_stale_v2_write_rolls_back(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_memory_copy_qa"
    assert dsn == os.environ["DATABASE_URL"]
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    monkeypatch.setattr(memory, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(memory, "_memory_v2_route_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(memory, "require_content_write", lambda _p: None)

    vault_id = str(uuid4())
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
            "RETURNING id", (vault_id, b"Q" * 50),
        )
        old_id = cur.fetchone()["id"]
        cur.execute(
            "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
            "memory_lookup_hash FROM vault_ai_memory WHERE id=%s", (old_id,),
        )
        row = cur.fetchone()
        snapshot = source_snapshot(
            "memory", row, vault_id=vault_id, record_id=old_id,
        )
        cur.execute(
            "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,vault_id,"
            "source_snapshot,memory_record_id,memory_type,payload_ciphertext) "
            "VALUES(%s,%s,%s,%s,'note',%s)",
            (old_id, vault_id, snapshot, f"memory-migrated-{old_id}",
             b"\x01" + secrets.token_bytes(28)),
        )
        cur.execute(
            "SELECT memory_inventory_generation FROM vaults WHERE vault_id=%s",
            (vault_id,),
        )
        before_old_write = cur.fetchone()["memory_inventory_generation"]

    # This is the older-client path: its row write invalidates the private
    # copy through 0064 and bumps generation in the same transaction.
    with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
            (b"R" * 50, old_id),
        )
        cur.execute(
            "SELECT 1 FROM memory_v2_prepared_copies WHERE legacy_memory_id=%s",
            (old_id,),
        )
        assert cur.fetchone() is None
        cur.execute(
            "SELECT memory_inventory_generation FROM vaults WHERE vault_id=%s",
            (vault_id,),
        )
        assert cur.fetchone()["memory_inventory_generation"] > before_old_write

    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
    payload = memory.AiMemoryCiphertextRequest(
        memory_id="synthetic-native-memory",
        memory_type="note",
        memory_lookup_hash=encode(secrets.token_bytes(32)),
        payload_ciphertext=encode(b"\x01" + secrets.token_bytes(28)),
        expected_memory_generation=str(before_old_write),
    )
    principal = {
        "vault_id": vault_id,
        "pin_free_read_offers": PIN_FREE_MEMORY_OFFER,
    }
    with pytest.raises(HTTPException) as exc:
        memory.ai_memory_ciphertext_upsert(payload, principal)
    assert exc.value.status_code == 409
    assert exc.value.detail == "memory_inventory_changed"
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM vault_ai_memory WHERE vault_id=%s "
            "AND memory_record_id='synthetic-native-memory'", (vault_id,),
        )
        assert cur.fetchone()[0] == 0

    # Opposite ordering: the V2 transaction reaches its generation trigger
    # first. The older writer may lock its own source row, but its generation
    # bump waits until V2 commits; it then invalidates the copy normally.
    with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
            "memory_lookup_hash FROM vault_ai_memory WHERE id=%s", (old_id,),
        )
        row = cur.fetchone()
        snapshot = source_snapshot(
            "memory", row, vault_id=vault_id, record_id=old_id,
        )
        cur.execute(
            "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,vault_id,"
            "source_snapshot,memory_record_id,memory_type,payload_ciphertext) "
            "VALUES(%s,%s,%s,%s,'note',%s)",
            (old_id, vault_id, snapshot, f"memory-migrated-{old_id}",
             b"\x01" + secrets.token_bytes(28)),
        )
        cur.execute(
            "SELECT memory_inventory_generation FROM vaults WHERE vault_id=%s",
            (vault_id,),
        )
        current_generation = cur.fetchone()["memory_inventory_generation"]

    first_write_ready = Event()
    allow_v2_check = Event()
    old_row_locked = Event()
    verify = memory._verify_memory_inventory_generation

    def paused_verify(*args, **kwargs):
        first_write_ready.set()
        assert allow_v2_check.wait(10)
        return verify(*args, **kwargs)

    monkeypatch.setattr(memory, "_verify_memory_inventory_generation", paused_verify)

    def old_writer():
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM vault_ai_memory WHERE id=%s FOR UPDATE",
                        (old_id,))
            old_row_locked.set()
            cur.execute("UPDATE vault_ai_memory SET payload_ciphertext=%s "
                        "WHERE id=%s", (b"S" * 50, old_id))

    fresh_payload = payload.model_copy(update={
        "memory_id": "synthetic-native-after-old",
        "memory_lookup_hash": encode(secrets.token_bytes(32)),
        "expected_memory_generation": str(current_generation),
    })
    with ThreadPoolExecutor(max_workers=2) as pool:
        v2_future = pool.submit(
            memory.ai_memory_ciphertext_upsert, fresh_payload, principal,
        )
        try:
            assert first_write_ready.wait(10)
            old_future = pool.submit(old_writer)
            assert old_row_locked.wait(10)
            allow_v2_check.set()
            v2_result = v2_future.result(timeout=10)
            old_future.result(timeout=10)
        finally:
            allow_v2_check.set()
    assert v2_result.duplicate is False
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM vault_ai_memory WHERE vault_id=%s "
                    "AND memory_record_id='synthetic-native-after-old'",
                    (vault_id,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM memory_v2_prepared_copies "
                    "WHERE legacy_memory_id=%s", (old_id,))
        assert cur.fetchone()[0] == 0
