

from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import MagicMock, patch

import vault_secure_item_save as vsi
from main import (
    save_secret_tool,
    SaveSecretInvalidPayloadError,
    SaveSecretStorageLimitError,
)


_INSTAGRAM_USER = "snoworchard686"
_INSTAGRAM_PASS = "YOWlu)c*XlqDjw6z%w6V"
_NEW_PASS       = "qB-r0t8t#new-pass#xz"


def _fake_encrypt_passthrough(plain: str, key: bytes) -> str:


    return plain


def _fake_decrypt_passthrough(blob: str, key: bytes) -> str:

    return blob


class _BaseHarness(unittest.TestCase):


    def setUp(self):
        self._writes: list[tuple[str, tuple]] = []
        self._existing_row: dict | None = None
        self._fake_conn = self._build_fake_conn()
        self._patches = [
            patch("main.ensure_vault_exists", return_value=None),
            patch("main.get_db", return_value=self._fake_conn),
            patch("main.MAX_VAULT_BYTES", 10 * 1024 * 1024),
            patch("main.get_vault_total_bytes", return_value=0),
            patch(
                "main.encrypt_message",
                side_effect=_fake_encrypt_passthrough,
            ),
            patch(
                "main.decrypt_message",
                side_effect=_fake_decrypt_passthrough,
            ),
            patch("main.bump_vault_total_bytes", return_value=None),
            patch("main._set_last_service", return_value=None),
            patch("main.remember_service", return_value=None),
            patch(
                "main.password_strength_warning", return_value=None,
            ),
            patch(
                "semantic_embedder.enqueue_vault_item_embedding",
                return_value=None, create=True,
            ),
            patch(
                "asset_tagger.tag_vault_item_safe",
                return_value=None, create=True,
            ),
            patch(
                "password_audit.upsert_password_audit_safe",
                return_value=None, create=True,
            ),
            patch(
                "relationship_builder.on_vault_item_save_or_change",
                return_value=None, create=True,
            ),
            patch(
                "vault_intelligence_updater.on_credential_changed",
                return_value=None, create=True,
            ),
            patch(
                "billing.get_account_id_for_vault",
                return_value=None, create=True,
            ),
        ]
        for p in self._patches:
            p.start()
        self._sink_records: list[logging.LogRecord] = []
        self._log_handler = self._make_handler()
        for name in ("main",):
            log = logging.getLogger(name)
            log.addHandler(self._log_handler)
            log.setLevel(logging.DEBUG)

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        for name in ("main",):
            logging.getLogger(name).removeHandler(self._log_handler)

    def _make_handler(self) -> logging.Handler:
        records = self._sink_records

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        return sink

    def _build_fake_conn(self):
        conn = MagicMock(name="conn")
        cursor = MagicMock(name="cursor")
        conn.cursor.return_value = cursor

                          
        writes = self._writes
        get_existing = lambda: self._existing_row

        def _execute(sql, params=None):
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("SELECT"):
                cursor._next = "select"
                return
            if sql_upper.startswith("UPDATE"):
                writes.append(("UPDATE", params))
                cursor._next = "update"
                return
            if sql_upper.startswith("INSERT"):
                writes.append(("INSERT", params))
                cursor._next = "insert"
                return
            cursor._next = "noop"

        def _fetchone():
            if getattr(cursor, "_next", None) == "select":
                return get_existing()
            if getattr(cursor, "_next", None) == "insert":
                return {"id": 42}
            return None

        cursor.execute.side_effect = _execute
        cursor.fetchone.side_effect = _fetchone
        return conn

    def _last_encrypted_blob(self) -> str:
                                                                 
                                                                     
        if not self._writes:
            return ""
        action, params = self._writes[-1]
        if action == "INSERT":
            return params[3]
        if action == "UPDATE":
            return params[0]
        return ""


class TestFreshInsertWritesSchemaB(_BaseHarness):

    def test_generated_login_writes_canonical_schema_b(self):
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields": {
                    "username": _INSTAGRAM_USER,
                    "password": _INSTAGRAM_PASS,
                },
            },
            key=b"k" * 32,
            generated=True,
        )
        blob = self._last_encrypted_blob()
        decoded = json.loads(blob)
                            
        self.assertEqual(decoded["category"], "login")
        self.assertEqual(decoded["title"],    "instagram")
        self.assertIsInstance(decoded["fields"], dict)
        self.assertEqual(
            decoded["fields"]["username"], _INSTAGRAM_USER,
        )
        self.assertEqual(
            decoded["fields"]["password"], _INSTAGRAM_PASS,
        )
        self.assertEqual(decoded["notes"], "")
                                                               
                               
        self.assertNotIn("username", decoded)
        self.assertNotIn("password", decoded)


class TestUpdateLegacySchemaANormalisesToSchemaB(_BaseHarness):

    def setUp(self):
        super().setUp()
                                                                 
                                                          
        legacy_blob = json.dumps({
            "username": _INSTAGRAM_USER,
            "password": _INSTAGRAM_PASS,
        })
        self._existing_row = {
            "id": 17,
            "encrypted_data": legacy_blob,
        }

    def test_password_update_on_legacy_row_writes_schema_b(self):
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields":      {"password": _NEW_PASS},
            },
            key=b"k" * 32,
            generated=True,
        )
        blob = self._last_encrypted_blob()
        decoded = json.loads(blob)
                                            
        self.assertEqual(decoded["category"], "login")
        self.assertEqual(decoded["title"],    "instagram")
                                                                 
                   
        self.assertEqual(
            decoded["fields"]["username"], _INSTAGRAM_USER,
        )
        self.assertEqual(
            decoded["fields"]["password"], _NEW_PASS,
        )
                                                   
        self.assertNotIn("username", decoded)
        self.assertNotIn("password", decoded)


class TestUpdateSchemaBStaysSchemaB(_BaseHarness):

    def setUp(self):
        super().setUp()
        envelope_blob = json.dumps({
            "category": "login",
            "title":    "instagram",
            "fields": {
                "username": _INSTAGRAM_USER,
                "password": _INSTAGRAM_PASS,
            },
            "notes":    "user-typed note",
            "item_id":  "row-instagram",
        })
        self._existing_row = {
            "id": 17,
            "encrypted_data": envelope_blob,
        }

    def test_envelope_keys_never_leak_into_inner_fields(self):
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields":      {"password": _NEW_PASS},
            },
            key=b"k" * 32,
            generated=True,
        )
        blob = self._last_encrypted_blob()
        decoded = json.loads(blob)
                            
        self.assertEqual(decoded["category"], "login")
        self.assertEqual(decoded["title"],    "instagram")
                                                               
        self.assertEqual(
            decoded["fields"]["username"], _INSTAGRAM_USER,
        )
        self.assertEqual(
            decoded["fields"]["password"], _NEW_PASS,
        )
                                                                 
                                                       
        self.assertEqual(decoded["notes"], "user-typed note")
                                                                 
                                                             
        for forbidden in ("category", "title", "notes", "item_id"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, decoded["fields"])


class TestNormaliseRecordReadsBothShapes(unittest.TestCase):

    def test_legacy_schema_a_round_trips_through_normalise(self):
                                                  
        decoded = {
            "username": _INSTAGRAM_USER,
            "password": _INSTAGRAM_PASS,
        }
        fields, notes, cat, title = vsi._normalise_record_to_fields(decoded)
        self.assertEqual(fields["username"], _INSTAGRAM_USER)
        self.assertEqual(fields["password"], _INSTAGRAM_PASS)
        self.assertIsNone(notes)
        self.assertIsNone(cat)
        self.assertIsNone(title)

    def test_canonical_schema_b_round_trips_through_normalise(self):
        decoded = {
            "category": "login",
            "title":    "instagram",
            "fields": {
                "username": _INSTAGRAM_USER,
                "password": _INSTAGRAM_PASS,
            },
            "notes":    "user-typed note",
            "item_id":  "row-instagram",
        }
        fields, notes, cat, title = vsi._normalise_record_to_fields(decoded)
        self.assertEqual(fields["username"], _INSTAGRAM_USER)
        self.assertEqual(fields["password"], _INSTAGRAM_PASS)
        self.assertEqual(notes, "user-typed note")
        self.assertEqual(cat,   "login")
        self.assertEqual(title, "instagram")


class TestNoPrivateValueInLogs(_BaseHarness):

    def test_fresh_insert_does_not_leak_password_in_logs(self):
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields": {
                    "username": _INSTAGRAM_USER,
                    "password": _INSTAGRAM_PASS,
                },
            },
            key=b"k" * 32,
            generated=True,
        )
        joined = "\n".join(r.getMessage() for r in self._sink_records)
                                                            
        for forbidden in (_INSTAGRAM_USER, _INSTAGRAM_PASS):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)

    def test_legacy_update_does_not_leak_old_or_new_password(self):
                                                                  
        legacy_blob = json.dumps({
            "username": _INSTAGRAM_USER,
            "password": _INSTAGRAM_PASS,
        })
        self._existing_row = {
            "id": 17,
            "encrypted_data": legacy_blob,
        }
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields":      {"password": _NEW_PASS},
            },
            key=b"k" * 32,
            generated=True,
        )
        joined = "\n".join(r.getMessage() for r in self._sink_records)
        for forbidden in (_INSTAGRAM_USER, _INSTAGRAM_PASS, _NEW_PASS):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestStorageQuotaUsesNewBlobSize(_BaseHarness):

    def setUp(self):
        super().setUp()
                                                              
                                                                
        self._bump_mock = MagicMock()
        self._extra_patches = [
            patch("main.bump_vault_total_bytes", self._bump_mock),
            patch("main.get_vault_total_bytes", return_value=1000),
        ]
        for p in self._extra_patches:
            p.start()

    def tearDown(self):
        for p in self._extra_patches:
            try:
                p.stop()
            except Exception:
                pass
        super().tearDown()

    def test_fresh_insert_bumps_quota_by_new_blob_size(self):
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields": {
                    "username": _INSTAGRAM_USER,
                    "password": _INSTAGRAM_PASS,
                },
            },
            key=b"k" * 32,
            generated=True,
        )
        blob = self._last_encrypted_blob()
        new_size = len(blob.encode("utf-8"))
                                                                 
                                              
        called_args = self._bump_mock.call_args
        self.assertIsNotNone(called_args)
        args, kwargs = called_args
        self.assertEqual(args[1], new_size)
                                                                 
                                                               
        decoded = json.loads(blob)
        self.assertEqual(decoded["category"], "login")

    def test_update_bumps_quota_by_delta(self):
        legacy_blob = json.dumps({
            "username": _INSTAGRAM_USER,
            "password": _INSTAGRAM_PASS,
        })
        previous_size = len(legacy_blob.encode("utf-8"))
        self._existing_row = {
            "id": 17,
            "encrypted_data": legacy_blob,
        }
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000aa",
            args={
                "secret_type": "login",
                "service":     "Instagram",
                "fields":      {"password": _NEW_PASS},
            },
            key=b"k" * 32,
            generated=True,
        )
        blob = self._last_encrypted_blob()
        new_size = len(blob.encode("utf-8"))
        expected_delta = new_size - previous_size
        called_args = self._bump_mock.call_args
        self.assertIsNotNone(called_args)
        args, kwargs = called_args
        self.assertEqual(args[1], expected_delta)


if __name__ == "__main__":                    
    unittest.main()
