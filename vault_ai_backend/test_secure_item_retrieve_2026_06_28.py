

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_card_envelope as env
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


_IMEI       = "352099001761481"
_IMEI_ALT   = "352099001768823"
_SERIAL     = "C7XW19RZ4NQF"
_PHONE      = "+1-415-555-0179"
_BACKUP     = "BK-ABCD-1234-5678-9012-3456"
_PRIVATE    = "blue tiger sleeps under the willow"
_PASSWORD   = "S3cr3t-Hunter-9821-Long-Pass"


def _fake_encrypt(plain: str, key: bytes) -> str:
    k = key[0] if key else 0
    return base64.b64encode(
        bytes(b ^ k for b in plain.encode("utf-8")),
    ).decode("ascii")


def _fake_decrypt(blob: str, key: bytes) -> str:
    k = key[0] if key else 0
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ k for b in raw).decode("utf-8")


def _patch_crypto():
    return (
        patch("vault_core.encrypt_message", side_effect=_fake_encrypt),
        patch("vault_core.decrypt_message", side_effect=_fake_decrypt),
    )


class TestRetrieveClassifier(unittest.TestCase):
    def test_what_imei_did_i_save_routes_to_retrieve(self):
        out = ci.classify_secure_item_intent("what IMEI did I save?")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_IMEI)

    def test_show_my_iphone_15_imei_routes_to_retrieve(self):
        out = ci.classify_secure_item_intent("show my iPhone 15 IMEI")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_IMEI)

    def test_show_my_private_notes_routes_to_category_retrieve(self):
        out = ci.classify_secure_item_intent("show my private notes")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertIsNone(out.field)
        self.assertEqual(out.category, t.CATEGORY_PRIVATE_NOTE)

    def test_show_my_backup_codes_routes_to_category_retrieve(self):
        out = ci.classify_secure_item_intent("show my backup codes")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
                                                                  
                                                                 
        self.assertEqual(out.field, ci.FIELD_BACKUP_CODES)
        self.assertEqual(out.category, t.CATEGORY_BACKUP_CODE)

    def test_show_my_serial_numbers_routes_to_retrieve(self):
        out = ci.classify_secure_item_intent("show my serial numbers")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_SERIAL)
        self.assertEqual(out.category, t.CATEGORY_SERIAL_NUMBER)

    def test_show_my_saved_items_routes_to_filter_all(self):
        out = ci.classify_secure_item_intent("show my saved items")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.category, ci.CATEGORY_FILTER_ALL)
        self.assertIsNone(out.field)

    def test_show_my_logins_routes_to_login_category(self):
        out = ci.classify_secure_item_intent("show my logins")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertIsNone(out.field)
        self.assertEqual(out.category, t.CATEGORY_LOGIN)

    def test_list_my_secure_items_routes_to_filter_all(self):
        out = ci.classify_secure_item_intent("list my secure items")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.category, ci.CATEGORY_FILTER_ALL)


class TestBulkRetrieveEnvelope(unittest.TestCase):
    def setUp(self):
        self.key = b"\x07" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        draft_store._reset_store_for_test()

    def _exec(self, action, payload):
        self._rows.append(payload)

    def _reader(self, vault_id, category):
        return [
            {
                "id":             f"row-{i}",
                "item_type":      r["item_type"],
                "service":        r["service"],
                "encrypted_data": r["encrypted_data"],
                "created_at":     1_700_000_000.0 + i,
            }
            for i, r in enumerate(self._rows)
            if r["item_type"] == category
        ]

    def _reader_all(self, vault_id):
        return [
            {
                "id":             f"row-{i}",
                "item_type":      r["item_type"],
                "service":        r["service"],
                "encrypted_data": r["encrypted_data"],
                "created_at":     1_700_000_000.0 + i,
            }
            for i, r in enumerate(self._rows)
        ]

    def _stage_iphone_imei(self):
                                                               
                                                             
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="iphone 15 imei",
            db_executor=self._exec,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )

                                            
    def test_show_my_imei_returns_imei_card_not_login(self):
        self._stage_iphone_imei()
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my IMEI",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["type"], env.TYPE_SECURE_ITEM_RESULTS)
        self.assertEqual(envelope["count"], 1)
        self.assertGreaterEqual(len(envelope["items"]), 1)
        card = envelope["items"][0]
                                                                 
        self.assertEqual(card["type"], t.CATEGORY_IMEI)
        self.assertNotEqual(card["type"], t.CATEGORY_LOGIN)
                                                          
        self.assertEqual(card["category_label"], "Phone IMEI")
                                              
        self.assertEqual(card["title"], "iPhone 15 IMEI")
                                  
        self.assertIn("created_at", card)
                             
        self.assertEqual(card["icon"], "phone")
                         
        preview = card["preview"]
        self.assertEqual(preview["imei_1_mask"], "ending 1481")
                                              
        self.assertNotIn(_IMEI, result["envelope"])
                                                        
        self.assertNotIn("login", envelope["message"].lower())
        self.assertNotIn("username", envelope["message"].lower())
        self.assertNotIn("password", envelope["message"].lower())

                             
    def test_show_my_iphone_15_imei_filters_by_title(self):
        self._stage_iphone_imei()
                                                                 
                                               
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI_ALT}",
            db_executor=self._exec,
        )
                                                                 
                                                                  
        draft_store._reset_store_for_test()
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my iPhone 15 IMEI",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
                                                
        self.assertEqual(envelope["count"], 1)
        card = envelope["items"][0]
        self.assertIn("iPhone 15", card["title"])
        self.assertEqual(card["type"], t.CATEGORY_IMEI)

                             
    def test_show_my_private_notes_returns_hidden_preview(self):
                                                
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save this private word: {_PRIVATE}",
            db_executor=self._exec,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my private notes",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        card = envelope["items"][0]
        self.assertEqual(card["type"], t.CATEGORY_PRIVATE_NOTE)
        self.assertEqual(card["category_label"], "Private note")
                                                     
        preview = card["preview"]
        self.assertEqual(preview.get("private_value_mask"), "•••••• hidden")
                                          
        self.assertNotIn(_PRIVATE, result["envelope"])
        self.assertNotIn("tiger", result["envelope"])
                                   
        self.assertNotIn("login", envelope["message"].lower())

                             
    def test_show_my_backup_codes_returns_backup_card(self):
                                                              
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my backup codes {_BACKUP}",
            db_executor=self._exec,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my backup codes",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        card = envelope["items"][0]
        self.assertEqual(card["type"], t.CATEGORY_BACKUP_CODE)
        self.assertEqual(card["category_label"], "Backup code")
                             
        preview = card["preview"]
        self.assertIn("backup_codes_mask", preview)
        self.assertTrue(
            preview["backup_codes_mask"].startswith("ending "),
        )
                           
        self.assertNotIn(_BACKUP, result["envelope"])

                             
    def test_default_retrieval_is_masked(self):
        self._stage_iphone_imei()
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my IMEI",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        envelope = json.loads(result["envelope"])
                                           
        self.assertFalse(envelope["reveal"])
                                                             
                    
        preview = envelope["items"][0]["preview"]
        self.assertIn("imei_1_mask", preview)
        self.assertNotIn("imei_1", preview)

    def test_explicit_reveal_phrase_surfaces_full_value(self):
        self._stage_iphone_imei()
                                                 
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show the full IMEI",
            db_executor=self._exec,
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
                                          
        self.assertTrue(envelope["reveal"])
                                                      
        preview = envelope["items"][0]["preview"]
        self.assertEqual(preview["imei_1"], _IMEI)

    def test_show_my_saved_items_returns_mixed_envelope(self):
                                            
        self._stage_iphone_imei()
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save this private word: {_PRIVATE}",
            db_executor=self._exec,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my saved items",
            db_executor=self._exec,
            db_reader_all=self._reader_all,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        types_in_envelope = {c["type"] for c in envelope["items"]}
        self.assertIn(t.CATEGORY_IMEI, types_in_envelope)
        self.assertIn(t.CATEGORY_PRIVATE_NOTE, types_in_envelope)
                                              
        self.assertIn("saved items", envelope["message"])


class TestLoginCardPreservation(unittest.TestCase):


    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _login_row(self) -> dict:
        record = {
            "category": t.CATEGORY_LOGIN,
            "title":    "Union Bank",
            "fields":   {
                "username": "user_chosen",
                "password": _PASSWORD,
            },
        }
        plain = json.dumps(record)
        encrypted = _fake_encrypt(plain, self.key)
        return {
            "id":             "row-1",
            "item_type":      "login",
            "service":        "Union Bank",
            "encrypted_data": encrypted,
            "created_at":     1_700_000_000.0,
        }

    def _reader(self, vault_id, category):
        if category == "login":
            return [self._login_row()]
        return []

    def test_show_my_logins_returns_login_card(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my logins",
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        card = envelope["items"][0]
                                             
        self.assertEqual(card["type"], t.CATEGORY_LOGIN)
        self.assertEqual(card["category_label"], "Login")
                                                           
        preview = card["preview"]
        self.assertEqual(preview["username"], "user_chosen")
        self.assertTrue(preview["has_password"])
        self.assertNotIn("password", preview)
                                             
        self.assertNotIn(_PASSWORD, result["envelope"])
                                                         
        self.assertIn("copy_username", card["available_actions"])


class TestEnvelopeShape(unittest.TestCase):
    def test_envelope_carries_closed_set_keys(self):
        card = env.build_secure_item_card(
            item_id="x",
            category=t.CATEGORY_IMEI,
            title="iPhone 15 IMEI",
            preview={"imei_1_mask": "ending 1481"},
            created_at=1_700_000_000.0,
        )
        ev = env.build_secure_item_results_envelope(items=[card])
        payload = json.loads(ev)
        self.assertEqual(payload["type"], env.TYPE_SECURE_ITEM_RESULTS)
        self.assertEqual(payload["schema_version"], env.SCHEMA_VERSION)
        self.assertEqual(payload["count"], 1)
        self.assertIn("items", payload)
        item = payload["items"][0]
        for required in (
            "item_id", "type", "title", "category_label",
            "icon", "preview", "available_actions", "created_at",
        ):
            with self.subTest(required=required):
                self.assertIn(required, item)

    def test_envelope_filter_drops_unknown_preview_keys(self):
                                                                 
                                            
        card = env.build_secure_item_card(
            item_id="x",
            category=t.CATEGORY_IMEI,
            title="iPhone IMEI",
            preview={
                "imei_1_mask":   "ending 1481",
                "imei_1":        _IMEI,                     
                "evil_key":       "leak",
            },
        )
                                                                 
        self.assertNotIn("imei_1", card["preview"])
        self.assertNotIn("evil_key", card["preview"])
        self.assertIn("imei_1_mask", card["preview"])

    def test_count_line_uses_operator_pinned_wording(self):
        ev1 = json.loads(
            env.build_secure_item_results_envelope(
                items=[
                    env.build_secure_item_card(
                        item_id="x",
                        category=t.CATEGORY_IMEI,
                        title="iPhone IMEI",
                        preview={"imei_1_mask": "ending 1481"},
                    ),
                ],
            ),
        )
        self.assertIn("Here's the saved item I found", ev1["message"])
        ev3 = json.loads(
            env.build_secure_item_results_envelope(
                items=[
                    env.build_secure_item_card(
                        item_id=str(i),
                        category=t.CATEGORY_IMEI,
                        title=f"IMEI {i}",
                        preview={"imei_1_mask": "ending xxxx"},
                    ) for i in range(3)
                ],
            ),
        )
        self.assertIn("I found 3 saved items", ev3["message"])
                                                
        self.assertIn("🔐", ev3["message"])

    def test_zero_items_yields_none_found_message(self):
        ev = json.loads(
            env.build_secure_item_results_envelope(
                items=[], category_filter=t.CATEGORY_IMEI,
            ),
        )
        self.assertEqual(ev["count"], 0)
        self.assertIn("IMEI", ev["message"])


class TestRetrievalPrivacy(unittest.TestCase):


    def test_module_logs_carry_no_sensitive_values(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        names = (
            "vault_secure_item_save",
            "vault_secure_item_draft",
            "vault_secure_item_card_envelope",
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
            "vault_device_reveal_gate",
        )
        for name in names:
            log = logging.getLogger(name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)

        key = b"\x0c" * 32
        rows: list[dict] = []

        def exec_(action, payload):
            rows.append(payload)

        def reader(vault_id, category):
            return [
                {
                    "id":             f"row-{i}",
                    "item_type":      r["item_type"],
                    "service":        r["service"],
                    "encrypted_data": r["encrypted_data"],
                    "created_at":     1_700_000_000.0 + i,
                }
                for i, r in enumerate(rows)
                if r["item_type"] == category
            ]

        patches = _patch_crypto()
        for p in patches:
            p.start()
        draft_store._reset_store_for_test()
        try:
            for msg in (
                f"save my imei {_IMEI}",
                "save it now",
                f"save this private word: {_PRIVATE}",
                "save it now",
                f"save my backup codes {_BACKUP}",
                "save it now",
                "show my IMEI",
                "show my private notes",
                "show my backup codes",
                "show the full IMEI",
            ):
                vsi.route_secure_item_message(
                    vault_id="v1", key=key, user_message=msg,
                    db_executor=exec_, db_reader=reader,
                )
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass
            for name in names:
                logging.getLogger(name).removeHandler(sink)
            draft_store._reset_store_for_test()

        joined = "\n".join(r.getMessage() for r in records)
        for forbidden in (_IMEI, _PRIVATE, _BACKUP):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestRevealGateExtensions(unittest.TestCase):
    def test_reveal_backup_code(self):
        from vault_device_reveal_gate import (
            REVEAL_FIELD_BACKUP, reveal_target_field,
        )
        self.assertEqual(
            reveal_target_field("show the full backup code"),
            REVEAL_FIELD_BACKUP,
        )

    def test_reveal_private_note(self):
        from vault_device_reveal_gate import (
            REVEAL_FIELD_PRIVATE, reveal_target_field,
        )
        self.assertEqual(
            reveal_target_field("show my private note"),
            REVEAL_FIELD_PRIVATE,
        )

    def test_reveal_account_note(self):
        from vault_device_reveal_gate import (
            REVEAL_FIELD_ACCOUNT, reveal_target_field,
        )
        self.assertEqual(
            reveal_target_field("reveal the full account note"),
            REVEAL_FIELD_ACCOUNT,
        )


if __name__ == "__main__":                    
    unittest.main()
