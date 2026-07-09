

from __future__ import annotations

import json
import re
import unittest

import vault_device_safety_copy as vds
import vault_device_reveal_gate as vdrg
import vault_device_search as vdss
import vault_device_card_envelope as vdce
import vault_chat_style_sanitizer as vsz


class TestOverclaimDetection(unittest.TestCase):


    _BAD_REPLIES = (
        ("VaultAI will track your stolen phone.", "overclaim"),
        ("I will track your stolen phone for you.", "overclaim"),
        ("I'll locate your lost iPhone.", "overclaim"),
        ("The vault tracks your devices.", "overclaim"),
        ("Your vault will recover your stolen laptop.", "overclaim"),
        ("VaultAI tracks devices for you.", "overclaim"),
        ("I can help you track your stolen iPhone.", "overclaim"),
    )

    _SAFE_REPLIES = (
                                                        
        "You can use Find My iPhone to locate your stolen phone.",
        "Your carrier can blocklist the device if you give them the IMEI.",
        "Filing a police report with the serial number helps recovery.",
        "Save your IMEI so you can report the device if it's stolen.",
        "I'll store the IMEI for you.",
        "I can save your iPhone details.",
    )

    def test_overclaim_shapes_detected(self):
        for reply, _ in self._BAD_REPLIES:
            with self.subTest(reply=reply):
                self.assertIsNotNone(vds.detect_overclaim(reply))

    def test_safe_replies_not_misdetected(self):
        for reply in self._SAFE_REPLIES:
            with self.subTest(reply=reply):
                self.assertIsNone(vds.detect_overclaim(reply))


class TestOverclaimRewrite(unittest.TestCase):
    def test_rewrite_uses_operator_pinned_safe_framing(self):
        bad = (
            "Sure — VaultAI will track your stolen phone. Just "
            "give me the serial."
        )
        out, slug = vds.rewrite_overclaim(bad)
        self.assertIsNotNone(slug)
        self.assertIn(
            "I store the details you'll need", out,
        )
                                         
        self.assertNotIn("track your stolen phone", out)

    def test_safe_text_unchanged(self):
        safe = "Use Find My iPhone with the serial saved here."
        out, slug = vds.rewrite_overclaim(safe)
        self.assertIsNone(slug)
        self.assertEqual(out, safe)


class TestStyleSanitizerCatchesOverclaim(unittest.TestCase):


    def test_overclaim_caught_in_full_pipeline(self):
        ugly = (
            "**VaultAI** will track your stolen phone. "
            "1. Open the app\n2. Tap track"
        )
        out, slugs = vsz.sanitize_reply_style(ugly)
                            
        self.assertNotIn("track your stolen phone", out)
                               
        self.assertIn("I store the details you'll need", out)
                                                   
        self.assertTrue(
            any(s.startswith("overclaim_") for s in slugs),
        )


class TestSystemPromptRuleBlock(unittest.TestCase):
    def test_static_prompt_includes_anti_overclaim_block(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
                                                                   
                                                                 
        flat = re.sub(r"\s+", " ", STATIC_VAULT_SYSTEM_PROMPT)
        for fragment in (
            "DEVICE VAULT",
            "anti-overclaim",
            "do NOT track",
            "Find My iPhone",
            "Find My Device",
            "carrier",
            "police",
            "Store the details you'll need",
            "IMEI ending 1234",
            "serial ending 8821",
            "MAC ending A9:2F",
            "phone ending 4412",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, flat)


class TestReminderEnvelopeCopySafe(unittest.TestCase):
    def test_reminder_message_uses_safe_framing(self):
        env = json.loads(vdce.build_reminder_envelope())
        msg = env["message"]
                                                                 
                                                              
        for safe_fragment in (
            "Remember to save important details",
            "phone, laptop, or other devices",
            "find them quickly",
            "lost or stolen",
        ):
            with self.subTest(safe_fragment=safe_fragment):
                self.assertIn(safe_fragment, msg)
                                                 
        for forbidden in (
            "VaultAI will track",
            "I'll track",
            "we'll track",
            "we will locate",
            "the vault tracks",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, msg)


class TestRevealGateExplicit(unittest.TestCase):


    def test_imei_explicit_reveal(self):
        for phrase in (
            "show the full IMEI",
            "show me my IMEI",
            "what IMEI did I save?",
            "what is the imei",
            "reveal the imei",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    vdrg.reveal_target_field(phrase),
                    vdrg.REVEAL_FIELD_IMEI,
                )

    def test_serial_explicit_reveal(self):
        for phrase in (
            "show my laptop serial number",
            "show the full serial",
            "what's the serial number",
            "reveal the serial",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    vdrg.reveal_target_field(phrase),
                    vdrg.REVEAL_FIELD_SERIAL,
                )

    def test_mac_explicit_reveal(self):
        for phrase in (
            "show the MAC address",
            "what's my mac address",
            "reveal the full MAC",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    vdrg.reveal_target_field(phrase),
                    vdrg.REVEAL_FIELD_MAC,
                )

    def test_phone_explicit_reveal(self):
        for phrase in (
            "show the full phone number",
            "what's my phone number",
            "reveal the phone number",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    vdrg.reveal_target_field(phrase),
                    vdrg.REVEAL_FIELD_PHONE,
                )

    def test_open_device_reveals_all(self):
        for phrase in (
            "open this device",
            "open the iPhone",
            "open that laptop",
            "show the full details",
            "reveal the full record",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    vdrg.reveal_target_field(phrase),
                    vdrg.REVEAL_FIELD_ALL,
                )

    def test_non_reveal_phrases_return_none(self):
        for phrase in (
            "show me all my devices",
            "list my phones",
            "my phone was stolen",
            "do I have a laptop",
            "find receipt for my iPhone",
            "great, what more can you do for me",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    vdrg.reveal_target_field(phrase),
                )

    def test_is_explicit_reveal_request_boolean(self):
        self.assertTrue(
            vdrg.is_explicit_reveal_request("show the full IMEI"),
        )
        self.assertFalse(
            vdrg.is_explicit_reveal_request("show my phones"),
        )


class TestDeviceSearchClassifier(unittest.TestCase):


    def test_show_my_phones(self):
        q = vdss.classify_device_query("show my phones")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_FILTER_KIND)
        self.assertEqual(q.kind, "phone")

    def test_show_my_laptop_serial_number(self):
                                                  
        q = vdss.classify_device_query("show my laptop serial number")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_REVEAL_FIELD)
        self.assertEqual(q.reveal_field, vdrg.REVEAL_FIELD_SERIAL)
        self.assertEqual(q.kind, "laptop")

    def test_what_imei_did_i_save(self):
        q = vdss.classify_device_query("what IMEI did I save?")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_REVEAL_FIELD)
        self.assertEqual(q.reveal_field, vdrg.REVEAL_FIELD_IMEI)

    def test_my_phone_was_stolen(self):
        q = vdss.classify_device_query("my phone was stolen")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_STOLEN)
        self.assertEqual(q.kind, "phone")

    def test_my_laptop_is_lost(self):
        q = vdss.classify_device_query("I lost my laptop yesterday")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_STOLEN)
        self.assertEqual(q.kind, "laptop")

    def test_find_receipt_for_my_iphone(self):
        q = vdss.classify_device_query("find receipt for my iPhone")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_FILTER_KIND)
        self.assertEqual(q.kind, "phone")

    def test_show_all_apple_devices(self):
        q = vdss.classify_device_query("show all Apple devices")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_FILTER_BRAND)
        self.assertEqual(q.brand, "apple")

    def test_show_devices_without_receipts(self):
        q = vdss.classify_device_query("show devices without receipts")
        self.assertEqual(
            q.intent, vdss.DEVICE_INTENT_FILTER_MISSING_RECEIPT,
        )

    def test_show_all_devices(self):
        q = vdss.classify_device_query("show all devices")
        self.assertEqual(q.intent, vdss.DEVICE_INTENT_LIST_ALL)

    def test_unrelated_phrase_returns_none(self):
        for phrase in (
            "great, what more can you do for me",
            "find my passport",
            "create a login for Union Bank",
        ):
            with self.subTest(phrase=phrase):
                q = vdss.classify_device_query(phrase)
                self.assertEqual(q.intent, vdss.DEVICE_INTENT_NONE)

    def test_empty_input(self):
        self.assertEqual(
            vdss.classify_device_query("").intent,
            vdss.DEVICE_INTENT_NONE,
        )
        self.assertEqual(
            vdss.classify_device_query(None).intent,
            vdss.DEVICE_INTENT_NONE,
        )


class TestApplyDeviceQuery(unittest.TestCase):
    def _previews(self) -> list[dict]:
        return [
            {
                "device_id": "1", "device_kind": "phone",
                "preview": {
                    "device_kind": "phone",
                    "device_name": "iPhone 15", "brand": "apple",
                    "has_receipt": True,
                },
            },
            {
                "device_id": "2", "device_kind": "phone",
                "preview": {
                    "device_kind": "phone",
                    "device_name": "Pixel 9", "brand": "google",
                    "has_receipt": False,
                },
            },
            {
                "device_id": "3", "device_kind": "laptop",
                "preview": {
                    "device_kind": "laptop",
                    "device_name": "MacBook Pro", "brand": "apple",
                    "has_receipt": True,
                },
            },
        ]

    def test_filter_kind_phone(self):
        out = vdss.apply_device_query(
            devices=self._previews(),
            query=vdss.DeviceQuery(
                intent=vdss.DEVICE_INTENT_FILTER_KIND, kind="phone",
            ),
        )
        ids = sorted(d["device_id"] for d in out)
        self.assertEqual(ids, ["1", "2"])

    def test_filter_brand_apple(self):
        out = vdss.apply_device_query(
            devices=self._previews(),
            query=vdss.DeviceQuery(
                intent=vdss.DEVICE_INTENT_FILTER_BRAND, brand="apple",
            ),
        )
        ids = sorted(d["device_id"] for d in out)
        self.assertEqual(ids, ["1", "3"])

    def test_filter_brand_apple_and_kind_phone(self):
        out = vdss.apply_device_query(
            devices=self._previews(),
            query=vdss.DeviceQuery(
                intent=vdss.DEVICE_INTENT_FILTER_BRAND,
                brand="apple", kind="phone",
            ),
        )
        ids = [d["device_id"] for d in out]
        self.assertEqual(ids, ["1"])

    def test_filter_missing_receipt(self):
        out = vdss.apply_device_query(
            devices=self._previews(),
            query=vdss.DeviceQuery(
                intent=vdss.DEVICE_INTENT_FILTER_MISSING_RECEIPT,
            ),
        )
        ids = [d["device_id"] for d in out]
        self.assertEqual(ids, ["2"])

    def test_reveal_field_passes_through(self):
                                                                
                  
        out = vdss.apply_device_query(
            devices=self._previews(),
            query=vdss.DeviceQuery(
                intent=vdss.DEVICE_INTENT_REVEAL_FIELD,
                reveal_field=vdrg.REVEAL_FIELD_IMEI,
            ),
        )
        self.assertEqual(len(out), 3)


class TestPrivacy(unittest.TestCase):
    def test_overclaim_log_carries_no_reply_body(self):
        import logging
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        log = logging.getLogger("vault_device_safety_copy")
        log.addHandler(sink)
        log.setLevel(logging.DEBUG)
        try:
            vds.rewrite_overclaim(
                "VaultAI will track your stolen phone "
                "SECRET_PASSWORD_ABC123"
            )
        finally:
            log.removeHandler(sink)
        joined = "\n".join(r.getMessage() for r in records)
                                                   
        self.assertNotIn("SECRET_PASSWORD_ABC123", joined)
        self.assertNotIn("stolen phone", joined)
                                     
        self.assertIn("overclaim", joined.lower())


if __name__ == "__main__":                    
    unittest.main()
