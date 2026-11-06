"""The Files list must work with schema-0056 UUID/text IDs without writes.

Run only against a disposable PostgreSQL instance through TEST_DATABASE_URL.
All fixture tables are temporary and disappear when the connection closes.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql://fixture.invalid/test")

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import file_v2_routes


class _BorrowedConnection:
    def __init__(self, conn):
        self.conn = conn
        self.commits = 0

    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)

    def commit(self):
        self.commits += 1
        self.conn.commit()

    def close(self):
        # The route borrows this one fixture connection so its temporary
        # schema can be inspected after the request.
        pass


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="disposable PostgreSQL required",
)
def test_file_v2_get_lists_without_uuid_text_error_or_deletion(monkeypatch):
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    vault_id = str(uuid.uuid4())
    other_vault_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TEMP TABLE uploaded_files (
                    id TEXT PRIMARY KEY, vault_id UUID NOT NULL
                )
            """)
            cur.execute("""
                CREATE TEMP TABLE file_v2_records (
                    file_id TEXT PRIMARY KEY, vault_id TEXT NOT NULL,
                    crypto_version TEXT NOT NULL, total_bytes BIGINT NOT NULL,
                    chunk_size INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    verification_state TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            cur.execute("""
                INSERT INTO file_v2_records VALUES
                    ('synthetic-unfinished', %s, 'client_mvk_v2', 5, 5, 1,
                     'file_v2_written', 'not_verified', NOW() - INTERVAL '25 hours'),
                    ('synthetic-ready', %s, 'client_mvk_v2', 8, 8, 1,
                     'client_v2_ready', 'client_verified', NOW()),
                    ('other-vault-file', %s, 'client_mvk_v2', 1, 1, 1,
                     'client_v2_ready', 'client_verified', NOW())
            """, (vault_id, vault_id, other_vault_id))
        conn.commit()

        borrowed = _BorrowedConnection(conn)
        monkeypatch.setattr(file_v2_routes, "get_db", lambda: borrowed)
        monkeypatch.setattr(file_v2_routes, "_enabled", lambda write=False: None)
        app = FastAPI()
        app.include_router(file_v2_routes.router)
        app.dependency_overrides[file_v2_routes.verify_trusted_device] = (
            lambda: {"vault_id": vault_id}
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/vault/file-v2")

        assert response.status_code == 200, response.text
        assert [row["file_id"] for row in response.json()["files"]] == [
            "synthetic-ready", "synthetic-unfinished",
        ]
        assert borrowed.commits == 0
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM file_v2_records")
            assert cur.fetchone()[0] == 3
    finally:
        conn.close()
