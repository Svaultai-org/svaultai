

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_card_envelope as env
import vault_secure_item_delete_confirmation as delete_store
import vault_secure_item_draft as draft_store
import vault_secure_item_results_followup as results_store
import vault_secure_item_save as vsi


_REVOLUT_USERNAME = "user_revolut"
_REVOLUT_PASSWORD = "RBank-Hunter-3399-Long-Pass"
_UNION_USERNAME   = "user_union"
_UNION_PASSWORD   = "UBank-Hunter-7711-Long-Pass"
_CHASE_USERNAME   = "user_chase"
_CHASE_PASSWORD   = "CBank-Hunter-5544-Long-Pass"
_IMEI             = "352099001761481"
_NORTON_KEY       = "NRT-AAAA-BBBB-CCCC-DDDD-EEEE"
_PRIVATE_NOTE     = "blue tiger sleeps under the willow"


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
    try:
        delete_store._reset_store_for_test()
    except Exception:
        pass


class TestDisplayModeOnEnvelopeBuilder(unittest.TestCase):

    def test_constants_are_closed_set(self):
        self.assertEqual(env.DISPLAY_MODE_DETAIL, "detail")
        self.assertEqual(env.DISPLAY_MODE_LIST,   "list")
        self.assertEqual(
            set(env.ALL_DISPLAY_MODES),
            {"detail", "list"},
        )

    def test_default_for_revealed_single_match_is_detail(self):
        envelope_json = env.build_secure_item_results_envelope(
            items=[{
                "item_id": "x", "type": t.CATEGORY_LOGIN,
                "title":   "Revolut Bank",
                "preview": {
                    "category": t.CATEGORY_LOGIN,
                    "title":    "Revolut Bank",
                    "username": "u",
                    "password": "p",
                    "revealed": True,
                },
                "available_actions": ["open", "copy_username",
                                      "edit", "delete"],
            }],
            reveal=True,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["display_mode"], "detail")

    def test_default_for_multi_row_is_list(self):
        envelope_json = env.build_secure_item_results_envelope(
            items=[
                {"item_id": "a", "type": t.CATEGORY_LOGIN,
                 "title": "Revolut Bank", "preview": {}},
                {"item_id": "b", "type": t.CATEGORY_LOGIN,
                 "title": "Union Bank",   "preview": {}},
            ],
            reveal=False,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["display_mode"], "list")

    def test_default_for_masked_single_match_is_list(self):
                                                            
                                                            
        envelope_json = env.build_secure_item_results_envelope(
            items=[{
                "item_id": "x", "type": t.CATEGORY_IMEI,
                "title": "Phone IMEI",
                "preview": {"imei_1_mask": "ending 1481"},
            }],
            reveal=False,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["display_mode"], "list")

    def test_explicit_list_override_wins_even_on_single_reveal(self):
        envelope_json = env.build_secure_item_results_envelope(
            items=[{
                "item_id": "x", "type": t.CATEGORY_LOGIN,
                "title": "Revolut Bank",
                "preview": {"username": "u", "password": "p",
                            "revealed": True},
            }],
            reveal=True,
            display_mode=env.DISPLAY_MODE_LIST,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["display_mode"], "list")

    def test_explicit_detail_override_wins_on_multi_row(self):
        envelope_json = env.build_secure_item_results_envelope(
            items=[
                {"item_id": "a", "type": t.CATEGORY_LOGIN,
                 "title": "Revolut Bank", "preview": {}},
                {"item_id": "b", "type": t.CATEGORY_LOGIN,
                 "title": "Union Bank",   "preview": {}},
            ],
            display_mode=env.DISPLAY_MODE_DETAIL,
        )
        payload = json.loads(envelope_json)
        self.assertEqual(payload["display_mode"], "detail")

    def test_unknown_override_falls_back_to_list(self):
        envelope_json = env.build_secure_item_results_envelope(
            items=[{
                "item_id": "x", "type": t.CATEGORY_LOGIN,
                "title": "Revolut Bank", "preview": {},
            }],
            display_mode="nonsense",
        )
        payload = json.loads(envelope_json)
                                                              
                                                                  
        self.assertEqual(payload["display_mode"], "list")


class TestSpecificLookupShipsDetail(unittest.TestCase):


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

    def _login_row(self, *, row_id: str, title: str,
                   username: str, password: str) -> dict:
        record = {
            "category": t.CATEGORY_LOGIN,
            "title":    title,
            "fields":   {"username": username, "password": password},
        }
        return {
            "id":             row_id,
            "item_type":      "login",
            "service":        title,
            "encrypted_data": _fake_encrypt(json.dumps(record), self.key),
            "created_at":     1_700_000_000.0,
        }

    def _three_bank_reader(self, vault_id, category):
        if category != "login":
            return []
        return [
            self._login_row(
                row_id="row-revolut", title="Revolut Bank",
                username=_REVOLUT_USERNAME, password=_REVOLUT_PASSWORD,
            ),
            self._login_row(
                row_id="row-union", title="Union Bank",
                username=_UNION_USERNAME, password=_UNION_PASSWORD,
            ),
            self._login_row(
                row_id="row-chase", title="Chase Bank",
                username=_CHASE_USERNAME, password=_CHASE_PASSWORD,
            ),
        ]

    def test_show_my_union_bank_login_ships_detail_with_username_password(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Union Bank login",
            db_reader=self._three_bank_reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "detail")
        self.assertEqual(envelope["count"], 1)
        self.assertTrue(envelope["reveal"])
        preview = envelope["items"][0]["preview"]
                                                            
                                                                
        self.assertEqual(preview["username"], _UNION_USERNAME)
        self.assertEqual(preview["password"], _UNION_PASSWORD)

    def test_show_my_revolut_bank_login_ships_detail(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Revolut Bank login",
            db_reader=self._three_bank_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "detail")
        preview = envelope["items"][0]["preview"]
        self.assertEqual(preview["username"], _REVOLUT_USERNAME)
        self.assertEqual(preview["password"], _REVOLUT_PASSWORD)

    def test_show_my_chase_bank_login_ships_detail(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Chase Bank login",
            db_reader=self._three_bank_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "detail")
        preview = envelope["items"][0]["preview"]
        self.assertEqual(preview["username"], _CHASE_USERNAME)
        self.assertEqual(preview["password"], _CHASE_PASSWORD)


class TestBroadLookupShipsList(TestSpecificLookupShipsDetail):

    def test_show_my_logins_ships_list(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my logins",
            db_reader=self._three_bank_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "list")
        self.assertEqual(envelope["count"], 3)
        self.assertFalse(envelope["reveal"])
                                               
        self.assertNotIn(_REVOLUT_PASSWORD, result["envelope"])
        self.assertNotIn(_UNION_PASSWORD,   result["envelope"])
        self.assertNotIn(_CHASE_PASSWORD,   result["envelope"])


class TestNonLoginSpecificDetail(unittest.TestCase):

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

    def _row(self, *, row_id: str, item_type: str, category: str,
             title: str, fields: dict) -> dict:
        record = {
            "category": category,
            "title":    title,
            "fields":   fields,
        }
        return {
            "id":             row_id,
            "item_type":      item_type,
            "service":        title,
            "encrypted_data": _fake_encrypt(json.dumps(record), self.key),
            "created_at":     1_700_000_000.0,
        }

    def test_norton_key_ships_detail_with_full_value(self):
        rows = [
            self._row(
                row_id="row-norton",
                item_type=t.CATEGORY_LICENSE_KEY,
                category=t.CATEGORY_LICENSE_KEY,
                title="Norton key",
                fields={"license_key": _NORTON_KEY},
            ),
        ]

        def _reader(vault_id, category):
            return [r for r in rows if r["item_type"] == category]

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Norton key",
            db_reader=_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "detail")
        self.assertTrue(envelope["reveal"])
        preview = envelope["items"][0]["preview"]
        self.assertEqual(preview["license_key"], _NORTON_KEY)

    def test_phone_imei_ships_detail_with_full_value(self):
                                                              
                                                             
        rows = [
            self._row(
                row_id="row-iphone",
                item_type=t.CATEGORY_IMEI,
                category=t.CATEGORY_IMEI,
                title="iPhone 15 IMEI",
                fields={"imei_1": _IMEI},
            ),
        ]

        def _reader(vault_id, category):
            return [r for r in rows if r["item_type"] == category]

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my iPhone 15 IMEI",
            db_reader=_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "detail")
        self.assertEqual(envelope["items"][0]["preview"]["imei_1"], _IMEI)

    def test_broad_private_notes_ships_list(self):
                                                                  
                                                               
        rows = [
            self._row(
                row_id="row-pn",
                item_type=t.CATEGORY_PRIVATE_NOTE,
                category=t.CATEGORY_PRIVATE_NOTE,
                title="evening reminders",
                fields={"private_value": _PRIVATE_NOTE},
            ),
        ]

        def _reader(vault_id, category):
            return [r for r in rows if r["item_type"] == category]

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my private notes",
            db_reader=_reader,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "list")
        self.assertFalse(envelope["reveal"])
        self.assertNotIn(_PRIVATE_NOTE, result["envelope"])


class TestMixedSavedItemsListMode(unittest.TestCase):

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

    def test_show_my_saved_items_ships_list(self):
        def _record(title, item_type, fields):
            return {
                "category": item_type, "title": title, "fields": fields,
            }

        rows = [
            {
                "id": "r1", "item_type": "login", "service": "Netflix",
                "encrypted_data": _fake_encrypt(
                    json.dumps(_record(
                        "Netflix", "login",
                        {"username": "u", "password": "pw"})),
                    self.key,
                ),
                "created_at": 1_700_000_000.0,
            },
            {
                "id": "r2", "item_type": "imei", "service": "Phone IMEI",
                "encrypted_data": _fake_encrypt(
                    json.dumps(_record(
                        "Phone IMEI", "imei", {"imei_1": _IMEI})),
                    self.key,
                ),
                "created_at": 1_700_000_001.0,
            },
        ]

        def _reader_all(vault_id):
            return rows

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my saved items",
            db_reader_all=_reader_all,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["display_mode"], "list")
        self.assertEqual(envelope["count"], 2)
        types = {c["type"] for c in envelope["items"]}
        self.assertIn(t.CATEGORY_LOGIN, types)
        self.assertIn(t.CATEGORY_IMEI,  types)
                                                   
        self.assertNotIn(_IMEI, result["envelope"])


if __name__ == "__main__":                    
    unittest.main()
