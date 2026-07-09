

from __future__ import annotations

import json
import logging
import unittest
from typing import Optional
from unittest.mock import patch

import vault_secure_item_save as vsi
import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t


_IMEI       = "352099001761481"
_IMEI_2     = "352099001761482"
_SERIAL     = "C7XW19RZ4NQF"
_PHONE      = "+1-415-555-0179"
_MAC        = "AA:BB:CC:DD:EE:FF"
_BACKUP     = "BK-ABCD-1234-5678-9012-3456-7890-1234"


def _fake_encrypt(plain: str, key: bytes) -> str:
    import base64
    k = key[0] if key else 0
    return base64.b64encode(
        bytes(b ^ k for b in plain.encode("utf-8")),
    ).decode("ascii")


def _fake_decrypt(blob: str, key: bytes) -> str:
    import base64
    k = key[0] if key else 0
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ k for b in raw).decode("utf-8")


def _patch_crypto():
    return (
        patch("vault_core.encrypt_message", side_effect=_fake_encrypt),
        patch("vault_core.decrypt_message", side_effect=_fake_decrypt),
    )


class TestBuildSaveArgs(unittest.TestCase):
    def test_phone_imei_intent_builds_device_args(self):
        intent = ci.classify_secure_item_intent(
            f"save my phone IMEI {_IMEI}",
        )
        args = vsi.build_save_args(intent=intent)
        self.assertIsNotNone(args)
        self.assertEqual(args["secret_type"], t.CATEGORY_DEVICE)
        self.assertEqual(args["service"], "phone")
        self.assertEqual(args["fields"]["imei_1"], _IMEI)
                                            
        self.assertNotIn("username", args["fields"])
        self.assertNotIn("password", args["fields"])

    def test_laptop_serial_intent_builds_device_args(self):
        intent = ci.classify_secure_item_intent(
            f"save my laptop serial number {_SERIAL}",
        )
        args = vsi.build_save_args(intent=intent)
        self.assertIsNotNone(args)
        self.assertEqual(args["secret_type"], t.CATEGORY_DEVICE)
        self.assertEqual(args["service"], "laptop")
        self.assertEqual(args["fields"]["serial_number"], _SERIAL)

    def test_retrieve_intent_returns_none(self):
        intent = ci.classify_secure_item_intent("show my phone IMEI")
        self.assertIsNone(vsi.build_save_args(intent=intent))


class TestEndToEndSave(unittest.TestCase):
    def setUp(self):
        self.key = b"\x07" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append(payload)

    def test_save_my_phone_imei_writes_device_row(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_SAVED)
                                             
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "device")
        self.assertEqual(row["service"], "phone")
                                                 
        self.assertNotIn(_IMEI, row["encrypted_data"])
                                         
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(decoded["fields"]["imei_1"], _IMEI)
        self.assertEqual(decoded["category"], "device")

    def test_save_my_laptop_serial_number_writes_device_row(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my laptop serial number {_SERIAL}",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_SAVED)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "device")
        self.assertEqual(row["service"], "laptop")
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(decoded["fields"]["serial_number"], _SERIAL)

    def test_no_username_or_password_required(self):
                                                           
                                                               
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_SAVED)
        plain = _fake_decrypt(self._rows[0]["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertNotIn("username", decoded["fields"])
        self.assertNotIn("password", decoded["fields"])

    def test_confirmation_uses_device_record_noun_not_login(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
        msg = result["message"]
        self.assertIn("device record", msg)
        self.assertNotIn("login", msg)

    def test_confirmation_surfaces_masked_tail(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
                                                              
                                                 
        self.assertIn("ending 1481", result["message"])
        self.assertNotIn(_IMEI, result["message"])

    def test_preview_masks_imei(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
        preview = result["preview"]
        self.assertNotIn(_IMEI, json.dumps(preview))
        self.assertEqual(preview["imei_1_mask"], "ending 1481")


class TestClarificationFlow(unittest.TestCase):
    def setUp(self):
        self.key = b"\x08" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append(payload)

    def test_missing_value_asks_one_short_question(self):
                                                       
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message="save my phone IMEI",
            db_executor=self._exec,
        )
        self.assertEqual(
            result["band"], vsi.BAND_NEEDS_CLARIFICATION,
        )
        self.assertIn("What value", result["message"])
                               
        self.assertEqual(len(self._rows), 0)

    def test_locked_vault_returns_friendly_message(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=b"short",
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_VAULT_LOCKED)
        self.assertIn("Unlock", result["message"])

    def test_no_save_intent_returns_no_intent_band(self):
        result = vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message="great, what more can you do for me",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_NO_INTENT)
        self.assertEqual(len(self._rows), 0)


class TestRetrieveFlow(unittest.TestCase):
    def setUp(self):
        self.key = b"\x09" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append(payload)

    def _reader(self, vault_id, category):
        return [
            {"encrypted_data": r["encrypted_data"]}
            for r in self._rows
            if r["item_type"] == category
        ]

    def test_save_then_retrieve_returns_masked_preview(self):
                     
        vsi.save_secure_item_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my phone IMEI {_IMEI}",
            db_executor=self._exec,
        )
                        
        intent = ci.classify_secure_item_intent("show my phone IMEI")
        result = vsi.retrieve_secure_item_from_intent(
            vault_id="v1", key=self.key,
            intent=intent, db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        preview = result["preview"]
                               
        self.assertEqual(preview["imei_1_mask"], "ending 1481")
                                                 
        self.assertNotIn(_IMEI, json.dumps(preview))

    def test_retrieve_no_match_returns_not_found_band(self):
        intent = ci.classify_secure_item_intent("show my phone IMEI")
        result = vsi.retrieve_secure_item_from_intent(
            vault_id="v1", key=self.key,
            intent=intent, db_reader=lambda v, c: [],
        )
        self.assertEqual(result["band"], vsi.BAND_NOT_FOUND)
        self.assertIn("Save it first", result["message"])


class TestExistingLoginPathUnchanged(unittest.TestCase):


    def test_login_validator_still_requires_username_or_password(self):
                                                                   
                                                              
        slug = t.classify_secure_item_payload({
            "secret_type": "login",
            "service":     "Union Bank",
            "fields":      {},
        })
        self.assertEqual(slug, "empty_login_fields")

    def test_login_save_with_password_only_validates(self):
        slug = t.classify_secure_item_payload({
            "secret_type": "login",
            "service":     "Union Bank",
            "fields":      {"password": "X" * 16},
        })
        self.assertIsNone(slug)


class TestSecureItemPrivacy(unittest.TestCase):
    def setUp(self):
        self.key = b"\x0a" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append(payload)

    def test_save_logs_carry_no_sensitive_values(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        for name in (
            "vault_secure_item_save",
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
        ):
            log = logging.getLogger(name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)
        try:
            for msg in (
                f"save my phone IMEI {_IMEI}",
                f"save my laptop serial number {_SERIAL}",
                f"save my Phone number {_PHONE}",
                f"save my recovery code {_BACKUP}",
            ):
                vsi.save_secure_item_from_message(
                    vault_id="vault_secret_xyz_user_password_12345",
                    key=self.key,
                    user_message=msg,
                    db_executor=self._exec,
                )
        finally:
            for name in (
                "vault_secure_item_save",
                "vault_saved_item_taxonomy",
                "vault_saved_item_chat_intent",
            ):
                logging.getLogger(name).removeHandler(sink)
        joined = "\n".join(r.getMessage() for r in records)
                                              
        self.assertNotIn(
            "vault_secret_xyz_user_password_12345", joined,
        )
                                        
        for forbidden in (_IMEI, _SERIAL, _PHONE, _MAC, _BACKUP):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


if __name__ == "__main__":                    
    unittest.main()
