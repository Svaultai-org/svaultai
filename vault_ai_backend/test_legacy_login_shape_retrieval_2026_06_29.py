

from __future__ import annotations

import base64
import inspect
import json
import logging
import unittest
from unittest.mock import patch

import vault_pending_draft_confirm as pdc
import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_card_envelope as env
import vault_secure_item_draft as draft_store
import vault_secure_item_results_followup as results_store
import vault_secure_item_save as vsi


_INSTAGRAM_USERNAME = "snoworchard686"
_INSTAGRAM_PASSWORD = "YOWlu)c*XlqDjw6z%w6V"


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


def _reset_all() -> None:
    draft_store._reset_store_for_test()
    results_store._reset_store_for_test()


class TestSchemaNormaliser(unittest.TestCase):

    def test_schema_b_returns_envelope_fields(self):
        record = {
            "category": "login",
            "title":    "Instagram",
            "fields":   {"username": "u", "password": "p"},
            "notes":    None,
            "item_id":  "uuid-abc",
        }
        fields, notes, cat, title = vsi._normalise_record_to_fields(record)
        self.assertEqual(fields, {"username": "u", "password": "p"})
        self.assertIsNone(notes)
        self.assertEqual(cat, "login")
        self.assertEqual(title, "Instagram")

    def test_schema_a_treats_record_as_fields(self):
                                                 
                                      
        record = {"username": "snoworchard686", "password": "secret-pw"}
        fields, notes, cat, title = vsi._normalise_record_to_fields(record)
        self.assertEqual(fields, record)
        self.assertIsNone(notes)
                                                         
                                              
        self.assertIsNone(cat)
        self.assertIsNone(title)

    def test_schema_a_with_imei_like_fields(self):
                                                               
                                                         
        record = {"imei_1": "352099001761481"}
        fields, _, _, _ = vsi._normalise_record_to_fields(record)
        self.assertEqual(fields, {"imei_1": "352099001761481"})

    def test_schema_b_with_missing_fields_key_returns_empty(self):
                                                            
                                                            
        record = {
            "category": "login",
            "title":    "Instagram",
                             
        }
        fields, _, cat, title = vsi._normalise_record_to_fields(record)
        self.assertEqual(fields, {})
        self.assertEqual(cat, "login")
        self.assertEqual(title, "Instagram")

    def test_non_dict_input_returns_empty(self):
        for v in (None, 42, "abc", [], object()):
            fields, notes, cat, title = vsi._normalise_record_to_fields(v)
            self.assertEqual(fields, {})
            self.assertIsNone(notes)
            self.assertIsNone(cat)
            self.assertIsNone(title)


class TestLegacyShapeRetrieval(unittest.TestCase):

    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        _reset_all()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        _reset_all()

    def _legacy_login_row(self) -> dict:
                                                                 
                                                               
        bare_fields = {
            "username": _INSTAGRAM_USERNAME,
            "password": _INSTAGRAM_PASSWORD,
        }
        return {
            "id":             "row-1",
            "item_type":      "login",
            "service":        "Instagram",
            "encrypted_data": _fake_encrypt(
                json.dumps(bare_fields), self.key,
            ),
            "created_at":     1_700_000_000.0,
        }

    def _reader(self, vault_id, category):
        if category != "login":
            return []
        return [self._legacy_login_row()]

    def test_show_my_instagram_login_surfaces_username_and_password(self):
                                                           
                                                             
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Instagram login",
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["display_mode"], "detail")
        self.assertTrue(envelope["reveal"])
        preview = envelope["items"][0]["preview"]
                                                              
                                                
        self.assertEqual(preview["username"], _INSTAGRAM_USERNAME)
        self.assertEqual(preview["password"], _INSTAGRAM_PASSWORD)
                                                             
        card = envelope["items"][0]
        self.assertEqual(card["title"], "Instagram")
        self.assertEqual(card["type"],  t.CATEGORY_LOGIN)

    def test_broad_show_my_logins_lists_legacy_row(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my logins",
            db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
                                            
        self.assertEqual(envelope["display_mode"], "list")
        self.assertFalse(envelope["reveal"])
        card = envelope["items"][0]
        self.assertEqual(card["title"], "Instagram")
        self.assertEqual(card["type"],  t.CATEGORY_LOGIN)
                                                          
                                             
        preview = card["preview"]
        self.assertEqual(preview.get("username"), _INSTAGRAM_USERNAME)
        self.assertNotIn(_INSTAGRAM_PASSWORD, result["envelope"])

    def test_legacy_and_secure_item_rows_coexist(self):
                                                             
                                                                  
        bare_login = {
            "username": _INSTAGRAM_USERNAME,
            "password": _INSTAGRAM_PASSWORD,
        }
        envelope_note = {
            "category": t.CATEGORY_PRIVATE_NOTE,
            "title":    "evening reminders",
            "fields":   {"private_value": "blue tiger"},
            "notes":    None,
            "item_id":  "uuid-note",
        }

        def _reader_all(vault_id):
            return [
                {
                    "id":             "row-1",
                    "item_type":      "login",
                    "service":        "Instagram",
                    "encrypted_data": _fake_encrypt(
                        json.dumps(bare_login), self.key,
                    ),
                    "created_at":     1_700_000_000.0,
                },
                {
                    "id":             "row-2",
                    "item_type":      "private_note",
                    "service":        "evening reminders",
                    "encrypted_data": _fake_encrypt(
                        json.dumps(envelope_note), self.key,
                    ),
                    "created_at":     1_700_000_001.0,
                },
            ]

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my saved items",
            db_reader_all=_reader_all,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 2)
        types = {c["type"] for c in envelope["items"]}
        self.assertIn(t.CATEGORY_LOGIN,        types)
        self.assertIn(t.CATEGORY_PRIVATE_NOTE, types)


class TestEndToEndGeneratedCredentialRetrieval(unittest.TestCase):


    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        _reset_all()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        _reset_all()

    def test_save_secret_tool_shape_round_trips(self):


        fields_dict = {
            "username": _INSTAGRAM_USERNAME,
            "password": _INSTAGRAM_PASSWORD,
        }
        encrypted = _fake_encrypt(json.dumps(fields_dict), self.key)
        rows = [{
            "id":             "row-instagram",
            "item_type":      "login",
            "service":        "Instagram",
            "encrypted_data": encrypted,
            "created_at":     1_700_000_000.0,
        }]

        def _reader(vault_id, category):
            return rows if category == "login" else []

                                                           
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="Show my instagram login",
            db_reader=_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["display_mode"], "detail")
        preview = envelope["items"][0]["preview"]
        self.assertEqual(preview["username"], _INSTAGRAM_USERNAME)
        self.assertEqual(preview["password"], _INSTAGRAM_PASSWORD)
                                                        
        self.assertNotIn(
            "No saved value attached", result["envelope"],
        )


class TestConfirmationPhrases(unittest.TestCase):

    def test_operator_brief_phrases_match(self):
        for phrase in [
            "save it", "yeah save it", "yes",
            "go ahead", "save",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    pdc.is_pending_draft_confirm_phrase(phrase),
                )
                self.assertEqual(
                    ci.classify_secure_item_intent(phrase).intent,
                    ci.INTENT_CONFIRM_SAVE,
                )


class TestPrivacyFloor(unittest.TestCase):

    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        _reset_all()
        self._log_records: list[logging.LogRecord] = []
        self._handler = logging.Handler()
        self._handler.emit = self._log_records.append
        logging.getLogger("vault_secure_item_save").addHandler(self._handler)
        logging.getLogger("vault_secure_item_card_envelope").addHandler(
            self._handler,
        )

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        _reset_all()
        logging.getLogger("vault_secure_item_save").removeHandler(self._handler)
        logging.getLogger("vault_secure_item_card_envelope").removeHandler(
            self._handler,
        )

    def test_retrieval_logs_never_carry_password(self):
        fields_dict = {
            "username": _INSTAGRAM_USERNAME,
            "password": _INSTAGRAM_PASSWORD,
        }
        encrypted = _fake_encrypt(json.dumps(fields_dict), self.key)
        rows = [{
            "id":             "row-instagram",
            "item_type":      "login",
            "service":        "Instagram",
            "encrypted_data": encrypted,
            "created_at":     1_700_000_000.0,
        }]

        def _reader(vault_id, category):
            return rows if category == "login" else []

        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="Show my instagram login",
            db_reader=_reader,
        )
                                                          
                                                                
        for rec in self._log_records:
            msg = rec.getMessage()
            self.assertNotIn(_INSTAGRAM_PASSWORD, msg)
            self.assertNotIn(_INSTAGRAM_USERNAME, msg)


class TestSourceLevelGuards(unittest.TestCase):

    def test_normaliser_is_defined_in_vault_secure_item_save(self):
        self.assertTrue(
            hasattr(vsi, "_normalise_record_to_fields"),
            "vault_secure_item_save must export the shape-tolerant "
            "fields normaliser.",
        )

    def test_normaliser_used_in_bulk_retrieve(self):
                                                               
                                                             
        src = inspect.getsource(
            vsi.retrieve_secure_items_from_intent,
        )
        self.assertIn("_normalise_record_to_fields", src)

    def test_normaliser_used_in_single_retrieve(self):
        src = inspect.getsource(
            vsi.retrieve_secure_item_from_intent,
        )
        self.assertIn("_normalise_record_to_fields", src)


if __name__ == "__main__":                    
    unittest.main()
