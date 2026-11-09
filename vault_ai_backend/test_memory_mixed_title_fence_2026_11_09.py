"""Cross-version Memory title safety on an explicit disposable database.

The flag is off by default. These tests only accept a loopback database with
the exact synthetic QA name, never a production connection.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from routes.vault_ciphertext_write_routes import _verify_memory_inventory_generation


def _dsn() -> str:
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_memory_title_qa"
    assert dsn == os.environ["DATABASE_URL"]
    return dsn


def _vault(cur, vault_id: str, *, fence: bool = False) -> None:
    cur.execute(
        """INSERT INTO vaults
           (vault_id,vault_name,pin_salt,pin_verifier,kdf_iterations,
            memory_mixed_title_fence_enabled)
           VALUES (%s,%s,'synthetic','synthetic',600000,%s)""",
        (vault_id, f"vault-{vault_id.replace('-', '')}", fence),
    )


def _old(cur, vault_id: str, marker: bytes = b"legacy-opaque-ciphertext") -> int:
    cur.execute(
        """INSERT INTO vault_ai_memory
           (vault_id,memory_type,payload_ciphertext,memory_lookup_hash)
           VALUES (%s,'note',%s,%s) RETURNING id""",
        (vault_id, marker, os.urandom(32)),
    )
    row = cur.fetchone()
    return int(row["id"] if isinstance(row, dict) else row[0])


def _native(cur, vault_id: str) -> int:
    cur.execute(
        """INSERT INTO vault_ai_memory
           (vault_id,memory_type,payload_ciphertext,memory_lookup_hash,
            memory_record_id)
           VALUES (%s,'note',%s,%s,%s) RETURNING id""",
        (vault_id, b"\x01" + os.urandom(40), os.urandom(32),
         f"synthetic-{uuid4()}"),
    )
    row = cur.fetchone()
    return int(row["id"] if isinstance(row, dict) else row[0])


def _constraint(exc: psycopg2.Error) -> str | None:
    return getattr(getattr(exc, "diag", None), "constraint_name", None)


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_default_off_and_legacy_only_writes_remain_available():
    dsn = _dsn()
    vault_id = str(uuid4())
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            _vault(cur, vault_id)
            _native(cur, vault_id)
            # Existing behavior is unchanged after the migration itself.
            _old(cur, vault_id)
            cur.execute(
                "SELECT memory_mixed_title_fence_enabled FROM vaults "
                "WHERE vault_id=%s", (vault_id,),
            )
            assert cur.fetchone()[0] is False
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vault_ai_memory WHERE vault_id=%s", (vault_id,))
            cur.execute(
                "UPDATE vaults SET memory_mixed_title_fence_enabled=TRUE "
                "WHERE vault_id=%s", (vault_id,),
            )
            first = _old(cur, vault_id)
            cur.execute(
                "UPDATE vault_ai_memory SET payload_ciphertext=%s "
                "WHERE id=%s", (b"new-legacy-opaque-ciphertext", first),
            )
            second = _old(cur, vault_id)
            assert first != second
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_opted_in_mixed_vault_rejects_old_content_without_erasing_reads():
    dsn = _dsn()
    vault_id = str(uuid4())
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            _vault(cur, vault_id)
            old_id = _old(cur, vault_id)
            native_id = _native(cur, vault_id)
            cur.execute(
                "UPDATE vaults SET memory_mixed_title_fence_enabled=TRUE "
                "WHERE vault_id=%s", (vault_id,),
            )
        for sql, params in (
            (
                "INSERT INTO vault_ai_memory "
                "(vault_id,memory_type,payload_ciphertext,memory_lookup_hash) "
                "VALUES (%s,'note',%s,%s)",
                (vault_id, b"another-legacy-ciphertext", os.urandom(32)),
            ),
            (
                "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
                (b"changed-legacy-ciphertext", old_id),
            ),
            (
                "UPDATE vault_ai_memory SET superseded_at=NOW() WHERE id=%s",
                (native_id,),
            ),
        ):
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                with pytest.raises(psycopg2.Error) as blocked:
                    cur.execute(sql, params)
                assert blocked.value.pgcode == "23514"
                assert _constraint(blocked.value) == "memory_mixed_title_fence"
                conn.rollback()
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload_ciphertext FROM vault_ai_memory WHERE id=%s",
                (old_id,),
            )
            assert bytes(cur.fetchone()[0]) == b"legacy-opaque-ciphertext"
            cur.execute(
                "UPDATE vault_ai_memory SET updated_at=NOW() WHERE id=%s",
                (old_id,),
            )
            cur.execute(
                "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
                (b"\x01" + os.urandom(40), native_id),
            )
            cur.execute(
                "UPDATE vault_ai_memory SET superseded_at=NOW() WHERE id=%s",
                (old_id,),
            )
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_native_first_old_insert_waits_then_refuses_after_commit():
    dsn = _dsn()
    vault_id = str(uuid4())
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        _vault(cur, vault_id, fence=True)

    def old_writer() -> tuple[str | None, str | None]:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='5s'")
            try:
                _old(cur, vault_id)
            except psycopg2.Error as exc:
                return exc.pgcode, _constraint(exc)
            return None, None

    try:
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                _native(cur, vault_id)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(old_writer)
                time.sleep(0.1)
                assert not pending.done(), "old writer should wait on vault row"
                conn.commit()
                assert pending.result(timeout=5) == ("23514", "memory_mixed_title_fence")
        finally:
            conn.close()
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_stale_native_inventory_rolls_back_after_old_first():
    dsn = _dsn()
    vault_id = str(uuid4())
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            _vault(cur, vault_id, fence=True)
            cur.execute(
                "SELECT memory_inventory_generation FROM vaults WHERE vault_id=%s",
                (vault_id,),
            )
            generation = str(cur.fetchone()[0])
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            _old(cur, vault_id)
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _native(cur, vault_id)
            with pytest.raises(HTTPException) as stale:
                _verify_memory_inventory_generation(
                    cur, vault_id, generation,
                    own_advances=1, signed_memory=True,
                )
            assert stale.value.status_code == 409
            assert stale.value.detail == "memory_inventory_changed"
            conn.rollback()
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM vault_ai_memory WHERE vault_id=%s",
                (vault_id,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
