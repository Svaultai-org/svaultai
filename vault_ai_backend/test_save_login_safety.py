

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from main import (
    SaveSecretError,
    SaveSecretInvalidPayloadError,
    SaveSecretStorageLimitError,
    _classify_save_login_payload,
    _maybe_extract_login_payload,
    save_secret_tool,
)


class ClassifySaveLoginPayloadTests(unittest.TestCase):


    def test_valid_payload_returns_none(self):
        ok = {
            "secret_type": "login",
            "service": "capital one",
            "fields": {"username": "foo", "password": "Bar123!"},
        }
        self.assertIsNone(_classify_save_login_payload(ok))

    def test_missing_args_dict(self):
        self.assertEqual(_classify_save_login_payload(None), "missing_args")
        self.assertEqual(_classify_save_login_payload("not a dict"), "missing_args")
        self.assertEqual(_classify_save_login_payload(["list"]), "missing_args")

    def test_missing_secret_type(self):
        bad = {"service": "gmail", "fields": {"username": "a"}}
        self.assertEqual(
            _classify_save_login_payload(bad), "missing_secret_type",
        )

    def test_service_general_is_rejected(self):
                                                                   
                                                                   
        self.assertEqual(
            _classify_save_login_payload({
                "secret_type": "login", "service": "general",
                "fields": {"username": "a"},
            }),
            "missing_service",
        )
                                                                 
        self.assertEqual(
            _classify_save_login_payload({
                "secret_type": "login", "service": "",
                "fields": {"username": "a"},
            }),
            "missing_service",
        )
        self.assertEqual(
            _classify_save_login_payload({
                "secret_type": "login", "service": "   ",
                "fields": {"username": "a"},
            }),
            "missing_service",
        )

    def test_fields_must_be_a_dict(self):
        self.assertEqual(
            _classify_save_login_payload({
                "secret_type": "login", "service": "gmail",
                "fields": "username=foo",
            }),
            "fields_not_dict",
        )

    def test_fields_must_not_be_empty(self):
        self.assertEqual(
            _classify_save_login_payload({
                "secret_type": "login", "service": "gmail", "fields": {},
            }),
            "empty_fields",
        )


class MaybeExtractLoginPayloadTests(unittest.TestCase):


    def test_chitchat_returns_none(self):
        self.assertIsNone(_maybe_extract_login_payload(
            "hey VaultAI how are you doing today",
            fallback_service=None,
        ))

    def test_bare_save_intent_with_no_credentials_returns_none(self):
                                                                     
                                                                     
        self.assertIsNone(_maybe_extract_login_payload(
            "save my login please",
            fallback_service=None,
        ))

    def test_empty_message_returns_none(self):
                                                                     
                                                                
        self.assertIsNone(_maybe_extract_login_payload(
            "",
            fallback_service=None,
        ))
        self.assertIsNone(_maybe_extract_login_payload(
            "   ",
            fallback_service=None,
        ))
        self.assertIsNone(_maybe_extract_login_payload(
            "???",
            fallback_service=None,
        ))


class SaveSecretToolMalformedPayloadTests(unittest.TestCase):


    def setUp(self):
                                                                    
                                                    
        self._patches = [
            patch("main.ensure_vault_exists", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_missing_secret_type_raises_typed_error(self):
        with self.assertRaises(SaveSecretInvalidPayloadError) as cm:
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args={"service": "gmail", "fields": {"username": "a"}},
                key=b"k" * 32,
            )
        self.assertEqual(cm.exception.reason, "missing_secret_type")

    def test_missing_service_raises_typed_error(self):
        with self.assertRaises(SaveSecretInvalidPayloadError) as cm:
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args={
                    "secret_type": "login", "service": "general",
                    "fields": {"username": "a"},
                },
                key=b"k" * 32,
            )
        self.assertEqual(cm.exception.reason, "missing_service")

    def test_empty_fields_raises_typed_error(self):
        with self.assertRaises(SaveSecretInvalidPayloadError) as cm:
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args={
                    "secret_type": "login", "service": "gmail",
                    "fields": {},
                },
                key=b"k" * 32,
            )
        self.assertEqual(cm.exception.reason, "empty_fields")

    def test_args_not_a_dict_raises_typed_error(self):
        with self.assertRaises(SaveSecretInvalidPayloadError) as cm:
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args="username=foo password=bar",                          
                key=b"k" * 32,
            )
        self.assertEqual(cm.exception.reason, "missing_args")

    def test_typed_errors_share_a_base(self):
                                                                 
                                              
        self.assertTrue(issubclass(SaveSecretInvalidPayloadError, SaveSecretError))
        self.assertTrue(issubclass(SaveSecretStorageLimitError, SaveSecretError))


class SaveSecretToolStorageLimitTests(unittest.TestCase):


    def setUp(self):
                                                                        
        self.fake_conn = self._fake_conn()
        self._patches = [
            patch("main.ensure_vault_exists", return_value=None),
            patch("main.get_db", return_value=self.fake_conn),
            patch("main.encrypt_message", return_value="X" * 1024),
            patch("main.MAX_VAULT_BYTES", 2048),
            patch("main.get_vault_total_bytes", return_value=2000),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _fake_conn(self):
        conn = MagicMock(name="conn")
        cursor = MagicMock(name="cursor")
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None
        return conn

    def test_storage_limit_raises_typed_error(self):
        with self.assertRaises(SaveSecretStorageLimitError) as cm:
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args={
                    "secret_type": "login",
                    "service": "capital one",
                    "fields": {"username": "foo", "password": "Bar123"},
                },
                key=b"k" * 32,
            )
        self.assertEqual(cm.exception.used_bytes, 2000)
        self.assertEqual(cm.exception.limit_bytes, 2048)
                                                                      
        self.assertEqual(cm.exception.projected_bytes, 3024)

    def test_storage_limit_error_is_not_a_value_error(self):
                                                                     
                                                                     
        self.assertFalse(issubclass(SaveSecretStorageLimitError, ValueError))

    def test_storage_limit_error_does_not_commit(self):
                                                           
        with self.assertRaises(SaveSecretStorageLimitError):
            save_secret_tool(
                vault_id="00000000-0000-4000-8000-0000000000e1",
                args={
                    "secret_type": "login",
                    "service": "capital one",
                    "fields": {"username": "foo", "password": "Bar123"},
                },
                key=b"k" * 32,
            )
        self.fake_conn.commit.assert_not_called()


class SaveSecretToolSuccessfulSaveTests(unittest.TestCase):


    def setUp(self):
        self.fake_conn = self._fake_conn()
        self._patches = [
            patch("main.ensure_vault_exists", return_value=None),
            patch("main.get_db", return_value=self.fake_conn),
            patch("main.MAX_VAULT_BYTES", 10 * 1024 * 1024),
            patch("main.get_vault_total_bytes", return_value=0),
            patch("main.encrypt_message", return_value="encrypted-blob"),
            patch("main.bump_vault_total_bytes", return_value=None),
            patch("main._set_last_service", return_value=None),
            patch("main.remember_service", return_value=None),
            patch("main.password_strength_warning", return_value=None),
        ]
        for p in self._patches:
            p.start()
                                                                       
                                                                      
        self._inline_patches = [
            patch("semantic_embedder.enqueue_vault_item_embedding",
                  return_value=None, create=True),
            patch("asset_tagger.tag_vault_item_safe",
                  return_value=None, create=True),
            patch("password_audit.upsert_password_audit_safe",
                  return_value=None, create=True),
            patch("relationship_builder.build_relationships_for_item_safe",
                  return_value=None, create=True),
        ]
        for p in self._inline_patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for p in self._inline_patches:
            p.stop()

    def _fake_conn(self):
        conn = MagicMock(name="conn")
        cursor = MagicMock(name="cursor")
        conn.cursor.return_value = cursor
                                                                   
                                  
        cursor.fetchone.side_effect = [None, {"id": 42}]
        return conn

    def test_successful_save_returns_explicit_confirmation(self):
        result = save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000e1",
            args={
                "secret_type": "login",
                "service": "capital one",
                "fields": {"username": "foo", "password": "Bar123ZZ!"},
            },
            key=b"k" * 32,
        )
        self.assertIsInstance(result, str)
        self.assertTrue(result.strip(), "confirmation must be non-empty")
        self.assertIn("Capital One", result)

    def test_successful_save_commits(self):
                                                                
                                                                   
        save_secret_tool(
            vault_id="00000000-0000-4000-8000-0000000000e1",
            args={
                "secret_type": "login",
                "service": "gmail",
                "fields": {"username": "u", "password": "p"},
            },
            key=b"k" * 32,
        )
        self.fake_conn.commit.assert_called()
        self.assertGreaterEqual(self.fake_conn.commit.call_count, 1)


if __name__ == "__main__":
    unittest.main()
