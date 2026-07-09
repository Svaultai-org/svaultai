

from __future__ import annotations

import json
import logging
import re
import unittest

import vault_saved_item_taxonomy as t
import vault_saved_item_chat_intent as ci
import vault_device_card_envelope as vdce


_IMEI_FULL    = "352099001761481"
_SERIAL_FULL  = "C7XW19RZ4NQF"
_PHONE_FULL   = "+1-415-555-0179"
_MAC_FULL     = "AA:BB:CC:DD:EE:FF"
_RECOVERY_KEY = "BK-ABCD-1234-5678-9012-3456-7890-1234"
_PRIVATE_NOTE = "Bought from Apple Store; AppleCare valid until 2027"


class TestReminderCard(unittest.TestCase):
    def test_title_is_quick_reminder(self):
        env = json.loads(vdce.build_reminder_envelope())
        self.assertEqual(env["title"], "Quick reminder 📱")

    def test_message_uses_operator_pinned_wording(self):
        env = json.loads(vdce.build_reminder_envelope())
        msg = env["message"]
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
                self.assertIn(fragment, msg)

    def test_message_does_not_overclaim_tracking(self):
        env = json.loads(vdce.build_reminder_envelope())
        msg = env["message"]
        for forbidden in (
            "VaultAI will track",
            "I'll track",
            "the vault tracks",
            "we'll track",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, msg)

    def test_three_buttons_pinned(self):
        env = json.loads(vdce.build_reminder_envelope())
        ids = [b["id"] for b in env["buttons"]]
        labels = [b["label"] for b in env["buttons"]]
                                
        self.assertEqual(len(env["buttons"]), 3)
        for action in (
            vdce.ACTION_SAVE_DEVICE_INFO,
            vdce.ACTION_REMIND_LATER,
            vdce.ACTION_DISMISS_FOREVER,
        ):
            with self.subTest(action=action):
                self.assertIn(action, ids)
        for label in (
            "Save device info",
            "Remind me later",
            "Don't show again",
        ):
            with self.subTest(label=label):
                self.assertIn(label, labels)


class TestNounForCategory(unittest.TestCase):
    def test_known_categories(self):
        cases = {
            t.CATEGORY_LOGIN:         "login",
            t.CATEGORY_DEVICE:        "device record",
            t.CATEGORY_DOCUMENT_NOTE: "note",
            t.CATEGORY_RECOVERY_CODE: "recovery code",
            t.CATEGORY_BANK:          "bank record",
            t.CATEGORY_CARD:          "card record",
            t.CATEGORY_OTHER:         "saved item",
        }
        for cat, noun in cases.items():
            with self.subTest(cat=cat):
                self.assertEqual(t.noun_for_category(cat), noun)

    def test_unknown_category_falls_back_to_saved_item(self):
        self.assertEqual(t.noun_for_category("voodoo"), "saved item")
        self.assertEqual(t.noun_for_category(None), "saved item")
        self.assertEqual(t.noun_for_category(""), "saved item")

    def test_saved_confirmation_drops_login_for_device(self):
        msg = t.saved_confirmation_message(
            category=t.CATEGORY_DEVICE, title="iPhone 15",
        )
        self.assertNotIn("login", msg)
        self.assertIn("device record", msg)
        self.assertIn("iPhone 15", msg)

    def test_saved_confirmation_login_path_unchanged(self):
        msg = t.saved_confirmation_message(
            category=t.CATEGORY_LOGIN, title="Union Bank",
        )
        self.assertIn("login", msg)
        self.assertIn("Union Bank", msg)


class TestCategoryInferenceFromFields(unittest.TestCase):
    def test_imei_fields_imply_device(self):
        for key in ("imei", "imei_1", "imei_2",
                    "serial", "serial_number",
                    "mac", "mac_address", "phone_number"):
            with self.subTest(key=key):
                self.assertEqual(
                    t.infer_category_from_fields({key: "x"}),
                    t.CATEGORY_DEVICE,
                )

    def test_recovery_fields_imply_recovery_code(self):
        for key in ("recovery_code", "recovery_key",
                    "backup_codes", "two_factor_codes"):
            with self.subTest(key=key):
                self.assertEqual(
                    t.infer_category_from_fields({key: "x"}),
                    t.CATEGORY_RECOVERY_CODE,
                )

    def test_bank_fields_imply_bank(self):
        for key in ("iban", "swift", "routing_number",
                    "account_number"):
            with self.subTest(key=key):
                self.assertEqual(
                    t.infer_category_from_fields({key: "x"}),
                    t.CATEGORY_BANK,
                )

    def test_card_fields_imply_card(self):
        for key in ("card_number", "cvv", "expiration"):
            with self.subTest(key=key):
                self.assertEqual(
                    t.infer_category_from_fields({key: "x"}),
                    t.CATEGORY_CARD,
                )

    def test_no_known_field_returns_none(self):
        self.assertIsNone(
            t.infer_category_from_fields({"username": "x"}),
        )
        self.assertIsNone(t.infer_category_from_fields({}))
        self.assertIsNone(t.infer_category_from_fields(None))


class TestCategoryInferenceFromMessage(unittest.TestCase):
    def test_device_tokens(self):
        for phrase in (
            "save my phone IMEI",
            "save my laptop serial number",
            "store my iPad recovery info",             
            "remember my MacBook serial",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    t.infer_category_from_message(phrase),
                    t.CATEGORY_DEVICE,
                )

    def test_recovery_tokens(self):
        for phrase in (
            "save my recovery code",
            "remember my BitLocker key",
            "store my backup codes",
            "save my filevault key",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    t.infer_category_from_message(phrase),
                    t.CATEGORY_RECOVERY_CODE,
                )

    def test_login_tokens(self):
        for phrase in (
            "save my Union Bank login",
            "store my password for Wells Fargo",
            "remember my credentials",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    t.infer_category_from_message(phrase),
                    t.CATEGORY_LOGIN,
                )

    def test_unrelated_returns_none(self):
        for phrase in (
            "show me all ID photos",
            "what's expiring",
            "great, what more can you do for me",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    t.infer_category_from_message(phrase),
                )


class TestSecureItemValidator(unittest.TestCase):


    def test_device_save_with_imei_only_accepted(self):
                                                              
                                          
        slug = t.classify_secure_item_payload({
            "secret_type": "device",
            "service":     "iPhone 15",
            "fields":      {"imei_1": _IMEI_FULL},
        })
        self.assertIsNone(slug)

    def test_device_save_with_only_notes_accepted(self):
        slug = t.classify_secure_item_payload({
            "category": "device",
            "title":    "MacBook Pro",
            "fields":   {},
            "notes":    _PRIVATE_NOTE,
        })
        self.assertIsNone(slug)

    def test_recovery_save_with_only_recovery_code_accepted(self):
        slug = t.classify_secure_item_payload({
            "category": "recovery_code",
            "title":    "Google Recovery",
            "fields":   {"recovery_code": _RECOVERY_KEY},
        })
        self.assertIsNone(slug)

    def test_login_still_requires_username_or_password(self):
                                                                
        slug = t.classify_secure_item_payload({
            "secret_type": "login",
            "service":     "Union Bank",
            "fields":      {},
        })
        self.assertEqual(slug, "empty_login_fields")

    def test_login_with_password_only_accepted(self):
        slug = t.classify_secure_item_payload({
            "secret_type": "login",
            "service":     "Union Bank",
            "fields":      {"password": "X" * 16},
        })
        self.assertIsNone(slug)

    def test_login_with_username_only_accepted(self):
        slug = t.classify_secure_item_payload({
            "secret_type": "login",
            "service":     "Union Bank",
            "fields":      {"username": "user1"},
        })
        self.assertIsNone(slug)

    def test_missing_kind_rejected(self):
        slug = t.classify_secure_item_payload({
            "service": "iPhone 15",
            "fields":  {"imei_1": _IMEI_FULL},
        })
        self.assertEqual(slug, "missing_kind")

    def test_missing_title_rejected(self):
        slug = t.classify_secure_item_payload({
            "category": "device",
            "fields":   {"imei_1": _IMEI_FULL},
        })
        self.assertEqual(slug, "missing_title")

    def test_non_login_empty_fields_and_notes_rejected(self):
        slug = t.classify_secure_item_payload({
            "category": "device",
            "title":    "iPhone 15",
            "fields":   {},
        })
        self.assertEqual(slug, "empty_fields")


class TestChatIntentClassifier(unittest.TestCase):


    def test_save_my_phone_imei(self):
        out = ci.classify_secure_item_intent(
            f"save my phone IMEI {_IMEI_FULL}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_DEVICE)
        self.assertEqual(out.field, ci.FIELD_IMEI)
        self.assertEqual(out.title, "phone")
                                                        
        self.assertIsNotNone(out.value)
        self.assertIn("352099001761481", out.value or "")

    def test_save_my_laptop_serial_number(self):
        out = ci.classify_secure_item_intent(
            f"save my laptop serial number {_SERIAL_FULL}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_DEVICE)
        self.assertEqual(out.field, ci.FIELD_SERIAL)
        self.assertEqual(out.title, "laptop")

    def test_save_my_iphone_imei(self):
        out = ci.classify_secure_item_intent(
            f"save my iPhone IMEI {_IMEI_FULL}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.title, "iPhone")

    def test_save_my_recovery_code(self):
        out = ci.classify_secure_item_intent(
            f"save my recovery code {_RECOVERY_KEY}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_RECOVERY_CODE)
        self.assertEqual(out.field, ci.FIELD_RECOVERY_CODE)

    def test_show_my_phone_imei(self):
        out = ci.classify_secure_item_intent("show my phone IMEI")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_DEVICE)
        self.assertEqual(out.field, ci.FIELD_IMEI)

    def test_what_is_my_serial_number(self):
        out = ci.classify_secure_item_intent(
            "what's my laptop serial number",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_SERIAL)

    def test_unrelated_message_returns_none(self):
        for phrase in (
            "show me all ID photos",
            "create a login for Union Bank",
            "what documents are expiring?",
            "great, what more can you do for me",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    ci.classify_secure_item_intent(phrase).intent,
                    ci.INTENT_NONE,
                )

    def test_empty_or_none_input(self):
        self.assertEqual(
            ci.classify_secure_item_intent("").intent,
            ci.INTENT_NONE,
        )
        self.assertEqual(
            ci.classify_secure_item_intent(None).intent,
            ci.INTENT_NONE,
        )

    def test_no_value_in_save_message_still_classifies(self):
                                                                 
                                                                
        out = ci.classify_secure_item_intent("save my phone IMEI")
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_DEVICE)
        self.assertEqual(out.field, ci.FIELD_IMEI)
        self.assertIsNone(out.value)


class TestMaskedPreview(unittest.TestCase):


    def test_device_preview_masks_imei_serial_phone_mac(self):
        preview = t.masked_preview(
            category=t.CATEGORY_DEVICE,
            title="iPhone 15",
            fields={
                "imei_1":       _IMEI_FULL,
                "imei_2":       "352099001761482",
                "serial_number": _SERIAL_FULL,
                "phone_number": _PHONE_FULL,
                "mac_address":  _MAC_FULL,
            },
            notes=_PRIVATE_NOTE,
        )
                             
        body = json.dumps(preview)
        for forbidden in (
            _IMEI_FULL, _SERIAL_FULL, _PHONE_FULL, _MAC_FULL,
            _PRIVATE_NOTE,
            "415-555",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)
                               
        self.assertEqual(preview["imei_1_mask"], "ending 1481")
        self.assertEqual(preview["serial_number_mask"], "ending 4NQF")
        self.assertEqual(preview["phone_number_mask"], "ending 0179")
        self.assertEqual(preview["mac_address_mask"], "ending EE:FF")
                                         
        self.assertTrue(preview["has_notes"])

    def test_login_preview_surfaces_username_only(self):
        preview = t.masked_preview(
            category=t.CATEGORY_LOGIN,
            title="Union Bank",
            fields={"username": "user1", "password": "secret"},
        )
                                                         
        self.assertEqual(preview["username"], "user1")
        self.assertTrue(preview["has_password"])
        self.assertNotIn("secret", json.dumps(preview))

    def test_unknown_category_falls_back_to_other(self):
        preview = t.masked_preview(
            category="voodoo",
            title="Bag of Stuff",
            fields={"serial_number": _SERIAL_FULL},
        )
        self.assertEqual(preview["category"], t.CATEGORY_OTHER)
        self.assertEqual(preview["noun"], "saved item")
        self.assertEqual(preview["serial_number_mask"], "ending 4NQF")


class TestTaxonomyPrivacy(unittest.TestCase):


    def test_module_logs_carry_no_sensitive_values(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        for name in (
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
        ):
            log = logging.getLogger(name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)
        try:
            t.classify_secure_item_payload({
                "category": "device",
                "title":    "iPhone 15",
                "fields":   {
                    "imei_1":       _IMEI_FULL,
                    "serial_number": _SERIAL_FULL,
                    "phone_number": _PHONE_FULL,
                },
                "notes": _PRIVATE_NOTE,
            })
            t.masked_preview(
                category="device", title="iPhone 15",
                fields={
                    "imei_1": _IMEI_FULL,
                    "phone_number": _PHONE_FULL,
                },
                notes=_PRIVATE_NOTE,
            )
            t.saved_confirmation_message(
                category="device", title="iPhone 15",
            )
            ci.classify_secure_item_intent(
                f"save my phone IMEI {_IMEI_FULL}",
            )
        finally:
            for name in (
                "vault_saved_item_taxonomy",
                "vault_saved_item_chat_intent",
            ):
                logging.getLogger(name).removeHandler(sink)
        joined = "\n".join(r.getMessage() for r in records)
        for forbidden in (
            _IMEI_FULL, _SERIAL_FULL, _PHONE_FULL, _MAC_FULL,
            _PRIVATE_NOTE,
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


if __name__ == "__main__":                    
    unittest.main()
