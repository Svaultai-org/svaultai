

from __future__ import annotations

import json
import logging
import os
import re
import time
import unittest
from typing import Optional
from unittest.mock import patch

import vault_device_vault as vdv
import vault_device_reminder as vdr
import vault_device_card_envelope as vdce


def _fake_encrypt(plain: str, key: bytes) -> str:


    import base64
    k = key[0] if key else 0
    out = bytes(b ^ k for b in plain.encode("utf-8"))
    return base64.b64encode(out).decode("ascii")


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


def _reset_all():
    vdr._reset_store_for_test()


_PHONE_IMEI_1 = "352099001761481"                       
_PHONE_IMEI_2 = "352099001761482"
_PHONE_SERIAL = "C7XW19RZ4NQF"
_PHONE_NUMBER = "+1-415-555-0179"
_MAC_ADDRESS  = "AA:BB:CC:DD:EE:FF"
_BITLOCKER    = "BK-ABCD-1234-5678-9012-3456-7890-1234-XYZW"
_LOCK_NOTE    = "If found please call 415-555-0100"
_NOTES        = "Bought from Apple Store, AppleCare valid until 2027"


class TestMaskingHelpers(unittest.TestCase):


    def test_imei_masked_to_last_four(self):
        out = vdv._mask_tail(_PHONE_IMEI_1, keep=4)
        self.assertEqual(out, "ending 1481")
                                         
        self.assertNotIn(_PHONE_IMEI_1, out)

    def test_serial_masked_to_last_four(self):
        out = vdv._mask_tail(_PHONE_SERIAL, keep=4)
        self.assertEqual(out, "ending 4NQF")
        self.assertNotIn(_PHONE_SERIAL, out)

    def test_phone_masked(self):
        out = vdv._mask_phone(_PHONE_NUMBER)
                                                        
        self.assertEqual(out, "ending 0179")
        self.assertNotIn("415", out)
        self.assertNotIn("+1-415-555-0179", out)

    def test_mac_masked(self):
        out = vdv._mask_mac(_MAC_ADDRESS)
        self.assertEqual(out, "ending EE:FF")
        self.assertNotIn(_MAC_ADDRESS, out)
        self.assertNotIn("AA:BB", out)

    def test_short_value_does_not_leak(self):
                                                                  
                                                             
        out = vdv._mask_tail("123", keep=4)
        self.assertNotIn("123", out)
        self.assertIn("char value", out)

    def test_empty_or_none_returns_empty(self):
        self.assertEqual(vdv._mask_tail(""), "")
        self.assertEqual(vdv._mask_tail(None), "")
        self.assertEqual(vdv._mask_phone(None), "")
        self.assertEqual(vdv._mask_mac(""), "")


class TestDeviceSaveListRoundTrip(unittest.TestCase):


    def setUp(self):
        _reset_all()
        self.key = b"\x01" * 32
        self.vault_id = "vault-A"
        self._rows: list[dict] = []
        self._enc_patches = _patch_crypto()
        for p in self._enc_patches:
            p.start()

    def tearDown(self):
        for p in self._enc_patches:
            try:
                p.stop()
            except Exception:
                pass

    def _executor(self, action: str, payload: dict):
                                                             
        if action == "upsert":
            existing = [
                r for r in self._rows
                if r["service"] == payload["device_id"]
            ]
            if existing:
                existing[0]["encrypted_data"] = payload["encrypted_data"]
            else:
                self._rows.append({
                    "service":        payload["device_id"],
                    "encrypted_data": payload["encrypted_data"],
                })

    def _reader(self, vault_id: str):
        return list(reversed(self._rows))

    def _save_phone(self) -> str:
        result = vdv.save_device_entry(
            vault_id=self.vault_id,
            key=self.key,
            args={
                "device_kind": "phone",
                "fields": {
                    "device_name":      "iPhone 15 Pro",
                    "brand":            "Apple",
                    "model":            "iPhone 15 Pro",
                    "imei_1":           _PHONE_IMEI_1,
                    "imei_2":           _PHONE_IMEI_2,
                    "serial_number":    _PHONE_SERIAL,
                    "phone_number":     _PHONE_NUMBER,
                    "sim_provider":     "Verizon",
                    "color":            "Natural Titanium",
                    "lock_screen_note": _LOCK_NOTE,
                    "notes":            _NOTES,
                    "purchase_date":    "2024-09-22",
                    "find_my_status":   "Active",
                    "emergency_contact": "Jane Doe +1 415 555 0123",
                },
            },
            db_executor=self._executor,
        )
        return result["device_id"]

    def test_save_returns_masked_preview_only(self):
        device_id = self._save_phone()
                                                                   
        listed = vdv.list_devices(
            vault_id=self.vault_id, key=self.key,
            db_reader=self._reader,
        )
        self.assertEqual(listed["count"], 1)
        item = listed["devices"][0]
        self.assertEqual(item["device_id"], device_id)
        self.assertEqual(item["device_kind"], "phone")
        preview = item["preview"]
                                                               
                                                                    
        for forbidden in (
            _PHONE_IMEI_1, _PHONE_IMEI_2, _PHONE_SERIAL,
            _PHONE_NUMBER, _LOCK_NOTE, _NOTES,
            "415-555",                                   
            "+1-415",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, json.dumps(preview),
                )
                                              
        self.assertEqual(preview["imei_1_mask"], "ending 1481")
        self.assertEqual(preview["imei_2_mask"], "ending 1482")
        self.assertEqual(preview["serial_mask"], "ending 4NQF")
        self.assertEqual(preview["phone_mask"],  "ending 0179")
                                        
        self.assertEqual(preview["device_name"], "iPhone 15 Pro")
        self.assertEqual(preview["color"], "Natural Titanium")
        self.assertEqual(preview["find_my_status"], "Active")

    def test_stored_blob_is_not_plaintext(self):
                                                             
                                       
        self._save_phone()
        blob = self._rows[0]["encrypted_data"]
        for forbidden in (
            _PHONE_IMEI_1, _PHONE_SERIAL, _PHONE_NUMBER,
            "iPhone 15 Pro", "Verizon",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, blob)

    def test_get_device_entry_returns_full_plaintext(self):
        device_id = self._save_phone()
        record = vdv.get_device_entry(
            vault_id=self.vault_id, key=self.key,
            device_id=device_id,
            db_reader=self._reader,
        )
        self.assertIsNotNone(record)
                                                
        self.assertEqual(record["imei_1"], _PHONE_IMEI_1)
        self.assertEqual(record["serial_number"], _PHONE_SERIAL)
        self.assertEqual(record["phone_number"], _PHONE_NUMBER)
        self.assertEqual(record["notes"], _NOTES)

    def test_get_device_entry_unknown_id_returns_none(self):
        self._save_phone()
        self.assertIsNone(
            vdv.get_device_entry(
                vault_id=self.vault_id, key=self.key,
                device_id="not-a-real-device",
                db_reader=self._reader,
            )
        )

    def test_locked_vault_rejected(self):
        with self.assertRaises(vdv.DeviceSaveInvalidError) as cm:
            vdv.save_device_entry(
                vault_id=self.vault_id, key=b"short",
                args={
                    "device_kind": "phone",
                    "fields": {"device_name": "test", "imei_1": "1"},
                },
                db_executor=self._executor,
            )
        self.assertEqual(cm.exception.slug, "vault_locked")


class TestLaptopAndValidation(unittest.TestCase):
    def setUp(self):
        _reset_all()
        self.key = b"\x02" * 32
        self._rows: list[dict] = []
        self._enc_patches = _patch_crypto()
        for p in self._enc_patches:
            p.start()

    def tearDown(self):
        for p in self._enc_patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append({
            "service": payload["device_id"],
            "encrypted_data": payload["encrypted_data"],
        })

    def _reader(self, vault_id):
        return list(self._rows)

    def test_laptop_save_masks_mac_and_bitlocker(self):
        result = vdv.save_device_entry(
            vault_id="v1", key=self.key,
            args={
                "device_kind": "laptop",
                "fields": {
                    "device_name":      "Personal MacBook",
                    "brand":            "Apple",
                    "model":            "MacBook Pro 16",
                    "serial_number":    _PHONE_SERIAL,
                    "mac_address":      _MAC_ADDRESS,
                    "operating_system": "macOS 15",
                    "bitlocker_recovery_reference": _BITLOCKER,
                    "notes":            "Work device",
                },
            },
            db_executor=self._exec,
        )
        preview = result["preview"]
        self.assertEqual(preview["device_kind"], "laptop")
        self.assertEqual(preview["mac_mask"], "ending EE:FF")
        self.assertEqual(preview["serial_mask"], "ending 4NQF")
        self.assertTrue(preview["has_recovery_reference"])
        self.assertTrue(preview["has_notes"])
                                                      
        for forbidden in (
            _MAC_ADDRESS, _PHONE_SERIAL, _BITLOCKER,
        ):
            self.assertNotIn(forbidden, json.dumps(preview))

    def test_kind_alias_resolution(self):
        self.assertEqual(vdv._normalise_kind("iphone"), "phone")
        self.assertEqual(vdv._normalise_kind("macbook"), "laptop")
        self.assertEqual(vdv._normalise_kind("ipad"),    "tablet")
        self.assertEqual(vdv._normalise_kind("desktop"), "other")
        self.assertEqual(vdv._normalise_kind(""),        "other")

    def test_validation_missing_kind(self):
        with self.assertRaises(vdv.DeviceSaveInvalidError) as cm:
            vdv.save_device_entry(
                vault_id="v1", key=self.key,
                args={"fields": {"device_name": "x"}},
                db_executor=self._exec,
            )
        self.assertEqual(cm.exception.slug, "missing_device_kind")

    def test_validation_empty_fields(self):
        with self.assertRaises(vdv.DeviceSaveInvalidError) as cm:
            vdv.save_device_entry(
                vault_id="v1", key=self.key,
                args={"device_kind": "phone", "fields": {}},
                db_executor=self._exec,
            )
        self.assertEqual(cm.exception.slug, "empty_fields")

    def test_disallowed_fields_dropped(self):
                                                                 
                          
        result = vdv.save_device_entry(
            vault_id="v1", key=self.key,
            args={
                "device_kind": "phone",
                "fields": {
                    "device_name": "Test Phone",
                    "mac_address": _MAC_ADDRESS,                     
                    "imei_1":       _PHONE_IMEI_1,
                },
            },
            db_executor=self._exec,
        )
                                                
        self.assertNotIn(_MAC_ADDRESS, self._rows[0]["encrypted_data"])
        self.assertEqual(result["preview"]["imei_1_mask"], "ending 1481")


class TestReceiptLinking(unittest.TestCase):


    def setUp(self):
        _reset_all()
        self.key = b"\x03" * 32
        self._rows: list[dict] = []
        self._enc_patches = _patch_crypto()
        for p in self._enc_patches:
            p.start()

    def tearDown(self):
        for p in self._enc_patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
                                                            
        for row in self._rows:
            if row["service"] == payload["device_id"]:
                row["encrypted_data"] = payload["encrypted_data"]
                return
        self._rows.append({
            "service": payload["device_id"],
            "encrypted_data": payload["encrypted_data"],
        })

    def _reader(self, vault_id):
        return list(self._rows)

    def test_attach_receipt_marks_has_receipt(self):
        saved = vdv.save_device_entry(
            vault_id="v1", key=self.key,
            args={
                "device_kind": "phone",
                "fields": {
                    "device_name": "iPhone",
                    "imei_1": _PHONE_IMEI_1,
                },
            },
            db_executor=self._exec,
        )
                                               
        self.assertFalse(saved["preview"]["has_receipt"])
                                   
        linked = vdv.link_receipt_to_device(
            vault_id="v1", key=self.key,
            device_id=saved["device_id"],
            file_id="receipt-file-uuid",
            db_executor=self._exec, db_reader=self._reader,
        )
        self.assertTrue(linked["preview"]["has_receipt"])
                                               
        record = vdv.get_device_entry(
            vault_id="v1", key=self.key,
            device_id=saved["device_id"],
            db_reader=self._reader,
        )
        self.assertEqual(record["receipt_file_id"], "receipt-file-uuid")

    def test_attach_receipt_unknown_device_returns_error(self):
        result = vdv.link_receipt_to_device(
            vault_id="v1", key=self.key,
            device_id="missing-id", file_id="r",
            db_executor=self._exec, db_reader=self._reader,
        )
        self.assertEqual(result.get("error"), "device_not_found")


class TestReminderState(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_user_with_no_devices_sees_reminder(self):
                                 
        self.assertTrue(
            vdr.should_show_reminder(
                vault_id="v1", devices_count=0,
            )
        )

    def test_user_with_device_does_not_see_reminder(self):
                                 
        self.assertFalse(
            vdr.should_show_reminder(
                vault_id="v1", devices_count=1,
            )
        )

    def test_remind_later_hides_for_window(self):
                                                        
        vdr.mark_remind_later("v1")
        self.assertFalse(
            vdr.should_show_reminder(
                vault_id="v1", devices_count=0,
            )
        )
                                                 
        self.assertEqual(
            vdr.reminder_decision(
                vault_id="v1", devices_count=0,
            ),
            vdr.DECISION_HIDDEN_REMIND_LATER,
        )

    def test_remind_later_expires(self):
        vdr.mark_remind_later("v1")
                                       
        with patch(
            "vault_device_reminder._now",
            return_value=time.time() + vdr.DEFAULT_REMIND_LATER_S + 1,
        ):
            self.assertTrue(
                vdr.should_show_reminder(
                    vault_id="v1", devices_count=0,
                )
            )

    def test_dismissed_forever_persists(self):
                                 
        vdr.mark_dismissed_forever("v1")
        self.assertFalse(
            vdr.should_show_reminder(
                vault_id="v1", devices_count=0,
            )
        )
                                                       
        with patch(
            "vault_device_reminder._now",
            return_value=time.time() + 365 * 24 * 3600,
        ):
            self.assertEqual(
                vdr.reminder_decision(
                    vault_id="v1", devices_count=0,
                ),
                vdr.DECISION_HIDDEN_DISMISSED,
            )

    def test_recent_show_cooldown_hides_reminder(self):
                                                      
        vdr.mark_shown("v1")
        self.assertFalse(
            vdr.should_show_reminder(
                vault_id="v1", devices_count=0,
            )
        )
        self.assertEqual(
            vdr.reminder_decision(
                vault_id="v1", devices_count=0,
            ),
            vdr.DECISION_HIDDEN_COOLDOWN,
        )

    def test_per_vault_isolation(self):
        vdr.mark_dismissed_forever("v1")
                                     
        self.assertTrue(
            vdr.should_show_reminder(
                vault_id="v2", devices_count=0,
            )
        )

    def test_acquired_device_stops_reminder_band(self):
                                          
        vdr.mark_shown("v1")
        self.assertEqual(
            vdr.reminder_decision(
                vault_id="v1", devices_count=1,
            ),
            vdr.DECISION_HIDDEN_HAS_DEVICE,
        )


class TestEnvelopes(unittest.TestCase):
    def test_reminder_envelope_carries_operator_pinned_copy(self):
                                                         
        raw = vdce.build_reminder_envelope()
        parsed = json.loads(raw)
        self.assertEqual(
            parsed["type"], vdce.TYPE_DEVICE_VAULT_REMINDER,
        )
                                                              
                                                            
        self.assertEqual(parsed["title"], "Quick reminder 📱")
        for fragment in (
            "Remember to save important details",
            "phone, laptop, or other devices",
            "IMEI",
            "serial number",
            "model",
            "receipt",
            "recovery notes",
            "find them quickly",
            "lost or stolen",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, parsed["message"])
                                
        ids = [b["id"] for b in parsed["buttons"]]
        self.assertEqual(len(parsed["buttons"]), 3)
        for action in (
            vdce.ACTION_SAVE_DEVICE_INFO,
            vdce.ACTION_REMIND_LATER,
            vdce.ACTION_DISMISS_FOREVER,
        ):
            with self.subTest(action=action):
                self.assertIn(action, ids)

    def test_results_envelope_drops_unknown_keys(self):
                                                                   
                                                            
        bad_payload = [{
            "device_id":   "abc",
            "device_kind": "phone",
            "device_name": "iPhone 15",
                                                
            "imei_1":       _PHONE_IMEI_1,
            "serial_number": _PHONE_SERIAL,
            "phone_number": _PHONE_NUMBER,
            "notes":        _NOTES,
                                        
            "imei_1_mask":  "ending 1481",
            "serial_mask":  "ending 4NQF",
            "phone_mask":   "ending 0179",
            "has_notes":    True,
        }]
        raw = vdce.build_device_results_envelope(devices=bad_payload)
        parsed = json.loads(raw)
        body = json.dumps(parsed)
        for forbidden in (
            _PHONE_IMEI_1, _PHONE_SERIAL, _PHONE_NUMBER, _NOTES,
        ):
            self.assertNotIn(forbidden, body)
                                  
        for kept in ("ending 1481", "ending 4NQF", "ending 0179"):
            self.assertIn(kept, body)

    def test_results_envelope_count_matches(self):
        raw = vdce.build_device_results_envelope(devices=[{
            "device_id": "1", "device_kind": "phone",
            "device_name": "iPhone",
            "imei_1_mask": "ending 1481",
        }])
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["devices"][0]["device_name"], "iPhone")

    def test_empty_results_envelope_has_friendly_message(self):
        raw = vdce.build_device_results_envelope(devices=[])
        parsed = json.loads(raw)
        self.assertEqual(parsed["count"], 0)
        self.assertIn("haven't added", parsed["message"])

    def test_envelope_versioning(self):
        raw = vdce.build_device_results_envelope(devices=[])
        parsed = json.loads(raw)
        self.assertEqual(parsed["schema_version"], "device_vault.v1")
        self.assertEqual(
            parsed["copy_version"], "device_vault_2026_06_29",
        )


class TestPrivacyFloor(unittest.TestCase):


    def setUp(self):
        _reset_all()
        self._rows: list[dict] = []
        self.key = b"\x05" * 32
        self._enc_patches = _patch_crypto()
        for p in self._enc_patches:
            p.start()

    def tearDown(self):
        for p in self._enc_patches:
            try:
                p.stop()
            except Exception:
                pass

    def _exec(self, action, payload):
        self._rows.append({
            "service": payload["device_id"],
            "encrypted_data": payload["encrypted_data"],
        })

    def _reader(self, vault_id):
        return list(self._rows)

    def test_save_log_carries_no_sensitive_values(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        for logger_name in (
            "vault_device_vault",
            "vault_device_reminder",
            "vault_device_card_envelope",
        ):
            log = logging.getLogger(logger_name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)
        try:
            saved = vdv.save_device_entry(
                vault_id="vault_secret_xyz_123",
                key=self.key,
                args={
                    "device_kind": "phone",
                    "fields": {
                        "device_name":   "Hot Phone",
                        "imei_1":        _PHONE_IMEI_1,
                        "imei_2":        _PHONE_IMEI_2,
                        "serial_number": _PHONE_SERIAL,
                        "phone_number":  _PHONE_NUMBER,
                        "notes":         _NOTES,
                        "lock_screen_note": _LOCK_NOTE,
                    },
                },
                db_executor=self._exec,
            )
            vdv.list_devices(
                vault_id="vault_secret_xyz_123", key=self.key,
                db_reader=self._reader,
            )
            vdv.get_device_entry(
                vault_id="vault_secret_xyz_123", key=self.key,
                device_id=saved["device_id"],
                db_reader=self._reader,
            )
            vdr.mark_shown("vault_secret_xyz_123")
            vdce.build_device_results_envelope(devices=[
                saved | {"preview": {
                    "device_kind": "phone", "device_name": "Hot Phone",
                    "imei_1_mask": "ending 1481",
                }}
            ])
        finally:
            for logger_name in (
                "vault_device_vault",
                "vault_device_reminder",
                "vault_device_card_envelope",
            ):
                logging.getLogger(logger_name).removeHandler(sink)

        joined = "\n".join(r.getMessage() for r in records)
                                                    
        self.assertNotIn("vault_secret_xyz_123", joined)
                                                
        for forbidden in (
            _PHONE_IMEI_1, _PHONE_IMEI_2, _PHONE_SERIAL,
            _PHONE_NUMBER, _NOTES, _LOCK_NOTE,
            "Hot Phone",                                                   
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestUnlockCopy(unittest.TestCase):


    def _read_main_dart(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(
            here, "..", "vault_ai_frontend", "lib", "main.dart",
        ))
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_unlock_copy_uses_new_phrasing(self):
                                                              
                                                                  
        src = self._read_main_dart()
                                       
        self.assertIn("Your vault is unlocked 🔓", src)
                                                          
        for fragment in (
            "documents",
            "photos",
            "videos",
            "audio",
            "IDs",
            "credentials",
            "receipts",
            "device details",
            "notes",
            "personal records",
                                           
            "find something",
            "save something",
            "organize",
            "understand what",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, src)

    def test_unlock_copy_does_not_carry_device_reminder_text(self):
                                                                
                                                            
        src = self._read_main_dart()
                                                           
                                                    
        idx = src.find("Your vault is unlocked 🔓")
        self.assertGreater(idx, 0)
        welcome_block = src[idx:idx + 800]
        for forbidden in (
            "IMEI",
            "serial number",
            "Find My iPhone",
            "Find My Device",
            "lost or stolen",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, welcome_block)

    def test_legacy_unlock_copy_removed(self):
        src = self._read_main_dart()
                                     
        self.assertNotIn(
            "You can type credentials or upload photos, PDFs, "
            "docs, and spreadsheets",
            src,
        )
                                                                  
                                                             
        idx = src.find("Your vault is unlocked 🔓")
        self.assertGreater(idx, 0)
        welcome_block = src[idx:idx + 800]
        self.assertNotIn(
            "device details like IMEI", welcome_block,
        )


if __name__ == "__main__":                    
    unittest.main()
