"""Synthetic route/SQL regressions; run directly with unittest, no server.

The PostgreSQL placeholder adapter executes the actual route SQL against a
task-local, in-memory SQLite database. FastAPI validates and serializes real
request/response models. No credentials, real vault rows or network are used.
"""
from __future__ import annotations

import base64
import os
import sqlite3
import unittest
from unittest.mock import patch

# Set before importing the real routes. The connection factory is always
# patched, and dotenv must never read a workstation's unrelated configuration.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "postgresql://synthetic:synthetic@127.0.0.1:1/never_connect"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import vault_ciphertext_write_routes as reader
from routes import vault_metadata_migration_routes as migration


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class Cursor:
    def __init__(self, cursor, dictionary: bool):
        self.cursor = cursor
        self.dictionary = dictionary

    def execute(self, sql, params=()):
        return self.cursor.execute(
            sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP"), params
        )

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None and self.dictionary else row

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows] if self.dictionary else rows


class Connection:
    def __init__(self, database):
        self.database = database

    def cursor(self, cursor_factory=None):
        return Cursor(self.database.cursor(), cursor_factory is not None)

    def commit(self):
        self.database.commit()

    def close(self):
        # Match pooled PostgreSQL close: unsuccessful batches are rolled back.
        self.database.rollback()


class MemoryMigrationPreservationTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:", check_same_thread=False)
        self.database.row_factory = sqlite3.Row
        self.database.executescript("""
            CREATE TABLE vault_ai_memory (
                id INTEGER PRIMARY KEY, vault_id TEXT, memory_type TEXT DEFAULT 'note',
                memory_key TEXT, memory_value TEXT, memory_normalized_key TEXT,
                payload_ciphertext BLOB, memory_record_id TEXT, memory_lookup_hash BLOB,
                superseded_at TEXT, unknown_custom TEXT
            );
            CREATE TABLE uploaded_files (
                id INTEGER PRIMARY KEY, vault_id TEXT,
                file_name TEXT, saved_name TEXT, content_type TEXT, detected_type TEXT,
                detected_service TEXT, asset_type TEXT, file_name_ciphertext BLOB,
                saved_name_ciphertext BLOB, content_type_ciphertext BLOB,
                detected_type_ciphertext BLOB, detected_service_ciphertext BLOB,
                asset_type_ciphertext BLOB, unknown_custom TEXT
            );
            CREATE TABLE vault_metadata_migration_state (
                vault_id TEXT PRIMARY KEY, uploaded_files_done_upto TEXT,
                vault_items_done_upto TEXT, notifications_done_upto TEXT,
                vault_ai_memory_done_upto TEXT, completed_at TEXT, updated_at TEXT
            );
            INSERT INTO vault_metadata_migration_state
                (vault_id, uploaded_files_done_upto, vault_items_done_upto, notifications_done_upto)
                VALUES ('owned-vault', 'done', 'done', 'done');
        """)
        self.application = FastAPI()
        self.application.include_router(migration.router)
        self.application.include_router(reader.router)
        self.application.dependency_overrides[migration.verify_trusted_device] = lambda: {
            "vault_id": "owned-vault"
        }
        self.client = TestClient(self.application)
        self.flags = patch.dict(os.environ, {"MEMORY_V2_READ_ENABLED": "true"})
        self.flags.start()
        self.migration_db = patch.object(migration, "get_db", self.connection)
        self.reader_db = patch.object(reader, "get_db", self.connection)
        self.migration_db.start()
        self.reader_db.start()

    def tearDown(self):
        self.reader_db.stop()
        self.migration_db.stop()
        self.flags.stop()
        self.client.close()
        self.database.close()

    def connection(self):
        return Connection(self.database)

    def seed(self, row_id=1, vault="owned-vault", ciphertext=None, record_id=None):
        self.database.execute("""
            INSERT INTO vault_ai_memory
                (id, vault_id, memory_key, memory_value, memory_normalized_key,
                 payload_ciphertext, memory_record_id, unknown_custom)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (row_id, vault, "Synthetic title", "SYNTHETIC-MEMORY-CANARY-2819",
              "synthetic title", ciphertext, record_id, "preserve-unknown"))
        self.database.commit()

    def apply(self, rows, marker=migration.MEMORY_PAYLOAD_FORMAT, table="vault_ai_memory"):
        body = {"table": table, "rows": rows}
        if marker is not None:
            body["memory_payload_format"] = marker
        return self.client.post("/vault/metadata-migration/apply-batch", json=body)

    @staticmethod
    def row(row_id=1, value=b"\x01" + b"synthetic-opaque-envelope-1234"):
        return {"row_id": row_id, "ciphertext": {"payload_ciphertext": encoded(value)}}

    def test_scalar_client_is_rejected_before_database_access(self):
        self.seed()
        for marker in (None, "scalar", "json_object_v0"):
            with self.subTest(marker=marker), patch.object(
                migration, "get_db", side_effect=AssertionError("must not open DB")
            ) as factory:
                response = self.apply([self.row()], marker=marker)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"], "memory_payload_format_required")
                factory.assert_not_called()
        source = self.database.execute("SELECT * FROM vault_ai_memory").fetchone()
        self.assertEqual(source["memory_value"], "SYNTHETIC-MEMORY-CANARY-2819")
        self.assertIsNone(source["payload_ciphertext"])

    def test_aggregate_apply_then_real_reader_serialization(self):
        self.seed()
        response = self.apply([self.row()])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"applied": 1, "skipped": 0})
        source = self.database.execute("SELECT * FROM vault_ai_memory").fetchone()
        self.assertEqual(source["payload_ciphertext"],
                         b"\x01" + b"synthetic-opaque-envelope-1234")
        self.assertEqual(source["memory_record_id"], "memory-migrated-1")
        self.assertEqual(source["memory_key"], "Synthetic title")
        self.assertEqual(source["memory_value"], "SYNTHETIC-MEMORY-CANARY-2819")
        self.assertEqual(source["memory_normalized_key"], "synthetic title")
        self.assertEqual(source["unknown_custom"], "preserve-unknown")
        readback = self.client.get("/vault/metadata-migration/memory-readback/1")
        self.assertEqual(readback.status_code, 200)
        self.assertEqual(readback.json(), {
            "row_id": 1, "payload_ciphertext": encoded(source["payload_ciphertext"]),
        })
        self.assertEqual(readback.headers["cache-control"], "no-store")
        listed = self.client.get("/vault/ciphertext/vault-ai-memory")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [{
            "memory_id": "memory-migrated-1", "memory_type": "note",
            "payload_ciphertext": encoded(b"\x01" + b"synthetic-opaque-envelope-1234"),
            "memory_lookup_hash": "",
        }])
        self.assertNotIn("CANARY", listed.text)
        self.assertNotIn("Synthetic title", listed.text)

    def test_existing_ciphertext_and_id_are_never_overwritten_or_cleared(self):
        self.seed(ciphertext=b"existing-durable-envelope", record_id="owned-record")
        before = dict(self.database.execute("SELECT * FROM vault_ai_memory").fetchone())
        for _ in range(2):
            response = self.apply([self.row(value=b"\x01" + b"replacement-must-not-win-123")])
            self.assertEqual(response.json(), {"applied": 0, "skipped": 1})
            after = dict(self.database.execute("SELECT * FROM vault_ai_memory").fetchone())
            self.assertEqual(after, before)

    def test_preexisting_unreadable_copy_without_source_is_not_rewritten(self):
        self.seed(ciphertext=b"\x01broken", record_id=None)
        self.database.execute("""UPDATE vault_ai_memory
            SET memory_key = NULL, memory_value = NULL,
                memory_normalized_key = NULL WHERE id = 1""")
        self.database.commit()
        before = dict(self.database.execute("SELECT * FROM vault_ai_memory").fetchone())
        self.assertEqual(self.apply([self.row()]).json(),
                         {"applied": 0, "skipped": 1})
        batch = self.client.get("/vault/metadata-migration/next-batch").json()
        self.assertEqual(batch["table"], "")
        after = dict(self.database.execute("SELECT * FROM vault_ai_memory").fetchone())
        self.assertEqual(after, before)

    def test_lost_ack_retry_preserves_first_ciphertext_and_existing_id(self):
        self.seed(record_id="already-stable")
        self.assertEqual(self.apply([self.row()]).json()["applied"], 1)
        self.assertEqual(self.apply([self.row(value=b"\x01" + b"x" * 28)]).json(),
                         {"applied": 0, "skipped": 1})
        source = self.database.execute("SELECT * FROM vault_ai_memory").fetchone()
        self.assertEqual(source["payload_ciphertext"],
                         b"\x01" + b"synthetic-opaque-envelope-1234")
        self.assertEqual(source["memory_record_id"], "already-stable")

    def test_existing_lookup_hash_serialization_and_filter_are_preserved(self):
        self.seed(record_id="legacy-row")
        self.seed(row_id=2, ciphertext=b"existing-envelope", record_id="v2-row")
        lookup = bytes(range(32))
        self.database.execute(
            "UPDATE vault_ai_memory SET memory_lookup_hash = ? WHERE id = 2", (lookup,)
        )
        self.database.commit()
        self.assertEqual(self.apply([self.row()]).json()["applied"], 1)
        response = self.client.get("/vault/ciphertext/vault-ai-memory",
                                   params={"memory_lookup_hash": encoded(lookup)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{
            "memory_id": "v2-row", "memory_type": "note",
            "payload_ciphertext": encoded(b"existing-envelope"),
            "memory_lookup_hash": encoded(lookup),
        }])

    def test_invalid_later_row_rolls_back_the_entire_batch(self):
        self.seed()
        self.seed(row_id=2)
        response = self.apply([self.row(), {
            "row_id": 2, "ciphertext": {"payload_ciphertext": ""}
        }])
        self.assertEqual(response.status_code, 400)
        rows = self.database.execute("SELECT * FROM vault_ai_memory ORDER BY id").fetchall()
        self.assertTrue(all(row["payload_ciphertext"] is None for row in rows))
        self.assertTrue(all(row["memory_value"] is not None for row in rows))

    def test_cross_vault_rows_and_malformed_requests_are_untouched(self):
        self.seed(vault="another-vault")
        self.seed(row_id=2)
        rows = [self.row(), {"row_id": 2,
                             "ciphertext": {"unknown_column": encoded(b"opaque")}}]
        self.assertEqual(self.apply(rows).status_code, 400)
        self.assertEqual(self.client.get("/vault/ciphertext/vault-ai-memory").json(), [])
        for row in self.database.execute("SELECT * FROM vault_ai_memory"):
            self.assertIsNone(row["payload_ciphertext"])
            self.assertIsNotNone(row["memory_value"])

    def test_real_next_batch_split_resume_returns_complete_rows(self):
        self.seed()
        self.seed(row_id=2)
        self.database.execute("UPDATE vault_ai_memory SET memory_key = NULL WHERE id = 2")
        self.database.commit()
        path = "/vault/metadata-migration/next-batch?limit=1"
        first = self.client.get(path).json()
        self.assertEqual(first["remaining_estimate"], 2)
        self.assertEqual(first["rows"][0]["plaintext"], {
            "memory_key": "Synthetic title", "memory_value": "SYNTHETIC-MEMORY-CANARY-2819",
            "memory_normalized_key": "synthetic title",
        })
        self.assertEqual(self.apply([self.row(first["rows"][0]["row_id"])]).json()["applied"], 1)
        second = self.client.get(path).json()
        self.assertEqual(second["remaining_estimate"], 1)
        self.assertEqual(second["rows"][0]["row_id"], 2)
        self.assertEqual(second["rows"][0]["plaintext"], {
            "memory_value": "SYNTHETIC-MEMORY-CANARY-2819",
            "memory_normalized_key": "synthetic title",
        })
        self.assertEqual(self.apply([self.row(2)]).json()["applied"], 1)
        finished = self.client.get(path)
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()["table"], "")
        self.assertEqual(len(self.client.get("/vault/ciphertext/vault-ai-memory").json()), 2)

    def test_capabilities_require_auth_and_readback_is_vault_scoped(self):
        self.seed(vault="another-vault", ciphertext=b"not-owned")
        capabilities = self.client.get(
            "/vault/metadata-migration/memory-capabilities")
        self.assertEqual(capabilities.status_code, 200)
        self.assertEqual(capabilities.json(), {
            "memory_payload_format": "json_object_v1",
            "preserves_legacy_source": True,
            "opaque_readback": True,
        })
        self.assertEqual(self.client.get(
            "/vault/metadata-migration/memory-readback/1").status_code, 404)

    def test_rejects_malformed_envelope_without_touching_source(self):
        self.seed()
        for value in (b"scalar", b"\x02" + b"x" * 28):
            with self.subTest(value=value):
                self.assertEqual(self.apply([self.row(value=value)]).status_code,
                                 400)
        source = self.database.execute("SELECT * FROM vault_ai_memory").fetchone()
        self.assertIsNone(source["payload_ciphertext"])
        self.assertIsNotNone(source["memory_value"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
