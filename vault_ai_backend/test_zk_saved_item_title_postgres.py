"""Opt-in real PostgreSQL races for private saved-item title identities.

Only a disposable loopback database named svaultai_title_qa is accepted. The
test creates and drops a private schema; it never touches a user vault.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy import create_engine

from routes import vault_ciphertext_write_routes as items


DSN = os.getenv("SVAULTAI_TITLE_RACE_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable local PostgreSQL required")
VAULT_ID = str(uuid4())


def _safe_dsn() -> str:
    parsed = urlparse(DSN)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or parsed.username != "svaultai_title_qa"
            or parsed.path != "/svaultai_title_qa"):
        pytest.fail("Refusing a non-disposable or non-loopback database")
    return DSN


def _encoded(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _request(*, item_id: int | None = None, title_hash: bytes,
             revision: int | None = None, payload: bytes = b"opaque-a"
             ) -> items.VaultItemUpsertRequest:
    return items.VaultItemUpsertRequest(
        item_id=item_id,
        mutation_intent="edit" if item_id is not None else "create",
        item_type_ciphertext=_encoded(b"opaque-type"),
        service_ciphertext=_encoded(b"opaque-title"),
        payload_ciphertext=_encoded(payload),
        title_lookup_hash=_encoded(title_hash),
        expected_title_revision=revision,
    )


class _BarrierCursor:
    def __init__(self, wrapped, barrier: threading.Barrier, mode: str):
        self.wrapped = wrapped
        self.barrier = barrier
        self.mode = mode
        self.waited = False

    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        # Concurrent creates both pass the ordinary absence check. The actual
        # PostgreSQL unique index, rather than this test barrier, must decide.
        if self.mode == "create" and normalized.startswith("select id from vault_items"):
            result = self.wrapped.execute(query, params)
            if not self.waited:
                self.waited = True
                self.barrier.wait(timeout=10)
            return result
        if self.mode == "edit" and normalized.startswith("update vault_items"):
            if not self.waited:
                self.waited = True
                self.barrier.wait(timeout=10)
        return self.wrapped.execute(query, params)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


class _BarrierConnection:
    def __init__(self, wrapped, barrier: threading.Barrier, mode: str):
        self.wrapped = wrapped
        self.barrier = barrier
        self.mode = mode

    def cursor(self, *args, **kwargs):
        return _BarrierCursor(self.wrapped.cursor(*args, **kwargs),
                              self.barrier, self.mode)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


@pytest.fixture()
def database(monkeypatch):
    dsn = _safe_dsn()
    schema = "title_" + uuid4().hex
    admin = psycopg2.connect(dsn, connect_timeout=3)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur.execute("""CREATE TABLE vault_items (
            id BIGSERIAL PRIMARY KEY, vault_id UUID NOT NULL,
            item_type TEXT, service TEXT, encrypted_data BYTEA,
            item_type_ciphertext BYTEA, service_ciphertext BYTEA,
            payload_ciphertext BYTEA, created_at TIMESTAMPTZ DEFAULT now()
        )""")
        migration_path = (Path(__file__).parent / "migrations" / "versions" /
                          "0052_zk_saved_item_title_identity.py")
        spec = importlib.util.spec_from_file_location("title_migration_0052", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine(dsn)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
        finally:
            engine.dispose()

    state: dict[str, object] = {"barrier": None, "mode": ""}

    def connect():
        conn = psycopg2.connect(dsn, connect_timeout=3,
                                options=f"-c search_path={schema}")
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 10000")
            cur.execute("SET lock_timeout = 10000")
        conn.commit()
        barrier = state["barrier"]
        if isinstance(barrier, threading.Barrier):
            return _BarrierConnection(conn, barrier, str(state["mode"]))
        return conn

    monkeypatch.setattr(items, "get_db", connect)
    monkeypatch.setattr(items, "require_content_write", lambda principal: None)
    monkeypatch.setenv("VAULTAI_ZK_SAVED_ITEM_TITLE_UNIQUE_ENABLED", "true")
    try:
        yield connect, state
    finally:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def _call(request):
    try:
        return items.vault_item_upsert_ciphertext(request, principal={"vault_id": VAULT_ID})
    except HTTPException as exc:
        return exc


def test_two_clients_creating_same_private_title_yield_one_row(database):
    connect, state = database
    state.update(barrier=threading.Barrier(2), mode="create")
    title_hash = b"T" * 32
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_call, (
            _request(title_hash=title_hash, payload=b"client-one"),
            _request(title_hash=title_hash, payload=b"client-two"),
        )))
    state["barrier"] = None
    assert sorted(getattr(result, "status_code", 200) for result in outcomes) == [200, 409]
    conflict = next(result for result in outcomes if isinstance(result, HTTPException))
    assert conflict.detail["code"] == "saved_item_title_conflict"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM vault_items WHERE vault_id = %s", (VAULT_ID,))
        assert cur.fetchone() == (1,)


def test_two_clients_editing_same_revision_yield_one_update(database):
    connect, state = database
    created = _call(_request(title_hash=b"A" * 32))
    assert not isinstance(created, HTTPException)
    state.update(barrier=threading.Barrier(2), mode="edit")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_call, (
            _request(item_id=created.item_id, title_hash=b"B" * 32,
                     revision=0, payload=b"client-one"),
            _request(item_id=created.item_id, title_hash=b"C" * 32,
                     revision=0, payload=b"client-two"),
        )))
    state["barrier"] = None
    assert sorted(getattr(result, "status_code", 200) for result in outcomes) == [200, 409]
    conflict = next(result for result in outcomes if isinstance(result, HTTPException))
    assert conflict.detail["code"] == "saved_item_revision_stale"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT title_revision,payload_ciphertext FROM vault_items WHERE id=%s",
                    (created.item_id,))
        revision, ciphertext = cur.fetchone()
        assert revision == 1
        assert bytes(ciphertext) in {b"client-one", b"client-two"}


def test_edit_into_other_items_title_is_rejected(database):
    connect, _ = database
    first = _call(_request(title_hash=b"A" * 32))
    second = _call(_request(title_hash=b"B" * 32))
    assert not isinstance(first, HTTPException)
    assert not isinstance(second, HTTPException)
    outcome = _call(_request(item_id=second.item_id, title_hash=b"A" * 32,
                            revision=0, payload=b"collision"))
    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 409
    assert outcome.detail["code"] == "saved_item_title_conflict"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT title_lookup_hash,title_revision,payload_ciphertext "
                    "FROM vault_items WHERE id=%s", (second.item_id,))
        row = cur.fetchone()
        assert bytes(row[0]) == b"B" * 32 and row[1] == 0
        assert bytes(row[2]) == b"opaque-a"


def test_existing_unindexed_v2_row_must_claim_title_before_new_write(database):
    connect, _ = database
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO vault_items (
            vault_id,item_type_ciphertext,service_ciphertext,payload_ciphertext
        ) VALUES (%s,%s,%s,%s) RETURNING id""",
                    (VAULT_ID, b"opaque-type", b"opaque-title", b"opaque-a"))
        old_id = cur.fetchone()[0]
    blocked = _call(_request(title_hash=b"N" * 32))
    assert isinstance(blocked, HTTPException)
    assert blocked.status_code == 409
    assert blocked.detail["code"] == "saved_item_title_index_required"
    indexed = items.claim_vault_item_title_index(
        old_id,
        items.VaultItemTitleIndexRequest(
            title_lookup_hash=_encoded(b"O" * 32),
            expected_title_revision=0,
            expected_service_ciphertext=_encoded(b"opaque-title"),
        ),
        principal={"vault_id": VAULT_ID},
    )
    assert indexed == {"item_id": old_id, "indexed": True, "title_revision": 1}
    new_row = _call(_request(title_hash=b"N" * 32))
    assert not isinstance(new_row, HTTPException)
    assert new_row.created


def test_backfill_duplicate_title_conflict_keeps_second_row_unchanged(database):
    connect, _ = database
    with connect() as conn, conn.cursor() as cur:
        ids = []
        for _ in range(2):
            cur.execute("""INSERT INTO vault_items (
                vault_id,item_type_ciphertext,service_ciphertext,payload_ciphertext
            ) VALUES (%s,%s,%s,%s) RETURNING id""",
                        (VAULT_ID, b"opaque-type", b"opaque-title", b"opaque-a"))
            ids.append(cur.fetchone()[0])
    claim = items.VaultItemTitleIndexRequest(
        title_lookup_hash=_encoded(b"D" * 32),
        expected_title_revision=0,
        expected_service_ciphertext=_encoded(b"opaque-title"),
    )
    assert items.claim_vault_item_title_index(
        ids[0], claim, principal={"vault_id": VAULT_ID})["indexed"]
    with pytest.raises(HTTPException) as excinfo:
        items.claim_vault_item_title_index(
            ids[1], claim, principal={"vault_id": VAULT_ID})
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "saved_item_title_conflict"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT title_lookup_hash,title_revision FROM vault_items WHERE id=%s",
                    (ids[1],))
        assert cur.fetchone() == (None, 0)
