

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_card_envelope as env
import vault_secure_item_draft as draft_store
import vault_secure_item_delete_confirmation as delete_store
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


class TestExtractRetrieveTitle(unittest.TestCase):


    def test_specific_brand_extracted_from_login_query(self):
                              
        self.assertEqual(
            ci._extract_retrieve_title("show my revolut bank login"),
            "revolut bank",
        )

    def test_specific_brand_extracted_case_insensitive(self):
        self.assertEqual(
            ci._extract_retrieve_title("show my Revolut Bank login"),
            "revolut bank",
        )

    def test_short_brand_extracted(self):
        self.assertEqual(
            ci._extract_retrieve_title("show my chase login"),
            "chase",
        )

    def test_two_word_brand_extracted(self):
        self.assertEqual(
            ci._extract_retrieve_title("show my union bank login"),
            "union bank",
        )

    def test_payment_card_brand_extracted(self):
                                                                        
        self.assertEqual(
            ci._extract_retrieve_title("show my payment card login"),
            "payment card",
        )

    def test_phone_imei_kept_as_specific_title(self):
                                                                    
                                                                    
        self.assertEqual(
            ci._extract_retrieve_title("show my Phone IMEI login"),
            "phone imei",
        )

    def test_norton_key_brand_extracted(self):
                                                          
        self.assertEqual(
            ci._extract_retrieve_title("show my Norton key"),
            "norton",
        )

    def test_broad_logins_returns_none(self):
        self.assertIsNone(
            ci._extract_retrieve_title("show my logins"),
        )

    def test_broad_bank_logins_returns_none(self):
                                                                   
                              
        self.assertIsNone(
            ci._extract_retrieve_title("show my bank logins"),
        )

    def test_broad_imei_returns_none(self):
                                                            
                                                                 
        self.assertIsNone(
            ci._extract_retrieve_title("show my IMEI"),
        )

    def test_broad_phone_imei_returns_none(self):
                                                              
                                             
        self.assertIsNone(
            ci._extract_retrieve_title("show my Phone IMEI"),
        )

    def test_broad_private_notes_returns_none(self):
        self.assertIsNone(
            ci._extract_retrieve_title("show my private notes"),
        )

    def test_broad_saved_items_returns_none(self):
        self.assertIsNone(
            ci._extract_retrieve_title("show my saved items"),
        )

    def test_broad_full_imei_returns_none(self):
                                                                 
                              
        self.assertIsNone(
            ci._extract_retrieve_title("show the full IMEI"),
        )

    def test_show_me_my_logins_returns_none(self):
                                                          
        self.assertIsNone(
            ci._extract_retrieve_title("show me my logins"),
        )

    def test_show_me_my_revolut_extracted(self):
        self.assertEqual(
            ci._extract_retrieve_title("show me my Revolut Bank login"),
            "revolut bank",
        )


class TestRankTitleMatch(unittest.TestCase):

    def test_empty_query_returns_strong(self):
                                                                 
                                                         
        self.assertEqual(
            vsi._rank_title_match("", "Revolut Bank"),
            vsi._RANK_STRONG_SUBSTRING,
        )

    def test_exact_match_wins(self):
        self.assertEqual(
            vsi._rank_title_match("revolut bank", "Revolut Bank"),
            vsi._RANK_EXACT,
        )

    def test_normalised_match_above_substring(self):
                                                                
                                                    
        self.assertEqual(
            vsi._rank_title_match("revolut bank login", "Revolut Bank"),
            vsi._RANK_NORMALISED,
        )

    def test_strong_substring_match(self):
                                                       
        self.assertEqual(
            vsi._rank_title_match("revolut", "Revolut Bank"),
            vsi._RANK_STRONG_SUBSTRING,
        )

    def test_no_match(self):
        self.assertEqual(
            vsi._rank_title_match("revolut", "Union Bank"),
            vsi._RANK_NO_MATCH,
        )

    def test_unrelated_row_does_not_match_revolut_query(self):
                                                               
                               
        self.assertEqual(
            vsi._rank_title_match("revolut bank", "Chase Bank"),
            vsi._RANK_NO_MATCH,
        )


class TestRetrieveKeepsHighestTier(unittest.TestCase):


    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()
        results_store._reset_store_for_test()
        try:
            delete_store._reset_store_for_test()
        except Exception:
            pass

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        draft_store._reset_store_for_test()
        results_store._reset_store_for_test()
        try:
            delete_store._reset_store_for_test()
        except Exception:
            pass

    def _login_row(self, *, row_id: str, title: str,
                   username: str, password: str) -> dict:
        record = {
            "category": t.CATEGORY_LOGIN,
            "title":    title,
            "fields":   {
                "username": username,
                "password": password,
            },
        }
        return {
            "id":             row_id,
            "item_type":      "login",
            "service":        title,
            "encrypted_data": _fake_encrypt(json.dumps(record), self.key),
            "created_at":     1_700_000_000.0,
        }

    def _reader_three_banks(self, vault_id, category):
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

    def test_revolut_bank_login_returns_only_revolut(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Revolut Bank login",
            db_reader=self._reader_three_banks,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        titles = [c["title"] for c in envelope["items"]]
        self.assertEqual(titles, ["Revolut Bank"])
                                                        
        self.assertNotIn("Union Bank", titles)
        self.assertNotIn("Chase Bank", titles)
                                                                   
                                                    
        self.assertNotIn(_UNION_PASSWORD, result["envelope"])
        self.assertNotIn(_CHASE_PASSWORD, result["envelope"])

    def test_union_bank_login_returns_only_union(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Union Bank login",
            db_reader=self._reader_three_banks,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["items"][0]["title"], "Union Bank")

    def test_chase_bank_login_returns_only_chase(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Chase Bank login",
            db_reader=self._reader_three_banks,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["items"][0]["title"], "Chase Bank")

    def test_show_my_logins_returns_all_three(self):
                                                                 
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my logins",
            db_reader=self._reader_three_banks,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 3)
        titles = sorted(c["title"] for c in envelope["items"])
        self.assertEqual(
            titles,
            ["Chase Bank", "Revolut Bank", "Union Bank"],
        )


class TestAutoRevealOnSingleStrongMatch(TestRetrieveKeepsHighestTier):


    def test_revolut_login_auto_reveals_password(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my Revolut Bank login",
            db_reader=self._reader_three_banks,
        )
        envelope = json.loads(result["envelope"])
                                                             
        self.assertTrue(envelope["reveal"])
        preview = envelope["items"][0]["preview"]
                                                                
                                                                  
        self.assertEqual(preview["username"], _REVOLUT_USERNAME)
        self.assertEqual(preview["password"], _REVOLUT_PASSWORD)
        self.assertTrue(preview["revealed"])

    def test_broad_logins_stays_masked(self):
                                                                
                   
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my logins",
            db_reader=self._reader_three_banks,
        )
        envelope = json.loads(result["envelope"])
        self.assertFalse(envelope["reveal"])
                                          
        self.assertNotIn(_REVOLUT_PASSWORD, result["envelope"])
        self.assertNotIn(_UNION_PASSWORD,   result["envelope"])
        self.assertNotIn(_CHASE_PASSWORD,   result["envelope"])


class TestSpecificNonLoginAutoReveal(unittest.TestCase):


    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()
        results_store._reset_store_for_test()
        try:
            delete_store._reset_store_for_test()
        except Exception:
            pass

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        draft_store._reset_store_for_test()
        results_store._reset_store_for_test()
        try:
            delete_store._reset_store_for_test()
        except Exception:
            pass

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

    def test_specific_phone_imei_auto_reveals(self):
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
        self.assertEqual(envelope["count"], 1)
        preview = envelope["items"][0]["preview"]
                                                                 
        self.assertTrue(envelope["reveal"])
        self.assertEqual(preview["imei_1"], _IMEI)

    def test_norton_key_specific_auto_reveals(self):
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
        self.assertEqual(envelope["count"], 1)
        self.assertTrue(envelope["reveal"])
        preview = envelope["items"][0]["preview"]
                                                              
                                                         
        self.assertIn("license_key", preview)
        self.assertEqual(preview["license_key"], _NORTON_KEY)

    def test_show_my_private_notes_broad_stays_masked(self):
                                                              
                                                                 
        rows = [
            self._row(
                row_id="row-pn",
                item_type=t.CATEGORY_PRIVATE_NOTE,
                category=t.CATEGORY_PRIVATE_NOTE,
                title="My evening reminders",
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
        self.assertEqual(envelope["count"], 1)
                                 
        self.assertFalse(envelope["reveal"])
                                    
        self.assertNotIn(_PRIVATE_NOTE, result["envelope"])

    def test_explicit_reveal_phrase_still_works(self):
                                                             
                                                              
        rows = [
            self._row(
                row_id="row-iphone-1",
                item_type=t.CATEGORY_IMEI,
                category=t.CATEGORY_IMEI,
                title="iPhone 15 IMEI",
                fields={"imei_1": _IMEI},
            ),
            self._row(
                row_id="row-iphone-2",
                item_type=t.CATEGORY_IMEI,
                category=t.CATEGORY_IMEI,
                title="Galaxy IMEI",
                fields={"imei_1": "352099001768823"},
            ),
        ]

        def _reader(vault_id, category):
            return [r for r in rows if r["item_type"] == category]

        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show the full IMEI",
            db_reader=_reader,
        )
        envelope = json.loads(result["envelope"])
                                                                 
        self.assertTrue(envelope["reveal"])
                                         
        self.assertIn(_IMEI, result["envelope"])


class TestEnvelopeDropsRevealAction(unittest.TestCase):


    def test_login_card_actions(self):
        card = env.build_secure_item_card(
            item_id="x",
            category=t.CATEGORY_LOGIN,
            title="Revolut Bank",
            preview={"category": t.CATEGORY_LOGIN, "username": "u"},
            reveal=False,
        )
        self.assertNotIn("reveal", card["available_actions"])
                                                                    
                                                   
        self.assertIn("open", card["available_actions"])
        self.assertIn("copy_username", card["available_actions"])
        self.assertIn("edit", card["available_actions"])
        self.assertIn("delete", card["available_actions"])

    def test_non_login_card_actions(self):
        card = env.build_secure_item_card(
            item_id="x",
            category=t.CATEGORY_IMEI,
            title="Phone IMEI",
            preview={"category": t.CATEGORY_IMEI, "imei_1_mask": "ending 1481"},
            reveal=False,
        )
        self.assertNotIn("reveal", card["available_actions"])
        self.assertIn("open", card["available_actions"])
        self.assertIn("edit", card["available_actions"])
        self.assertIn("delete", card["available_actions"])
                                                        
        self.assertNotIn("copy_username", card["available_actions"])


if __name__ == "__main__":                    
    unittest.main()
