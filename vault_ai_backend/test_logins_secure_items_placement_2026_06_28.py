

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


_IMEI         = "352099001761481"
_BACKUP_CODE  = "BK-ABCD-1234-5678"
_PRIVATE_WORD = "blue tiger"
_USDT_TRC20   = "TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY"


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


class TestSurfaceSeparation(unittest.TestCase):


    def test_list_secure_items_reads_vault_items_only(self):
        src = (
            Path("routes/vault_manage_routes.py")
            .read_text(encoding="utf-8")
        )
        anchor = '@router.post("/list-secure-items")'
        start  = src.index(anchor)
        end    = src.index("@router.", start + 1) \
            if "@router." in src[start + 1:] else len(src)
        body = src[start:end]
        self.assertIn(
            "FROM vault_items", body,
            msg="/list-secure-items must read from vault_items",
        )
        for forbidden in (
            "uploaded_files",
            "FROM uploaded_files",
            "file_id",
            "encrypted_file_data",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, body,
                    msg=(
                        f"/list-secure-items must NEVER touch "
                        f"`{forbidden}` — uploaded files belong "
                        f"in the Files section"
                    ),
                )

    def test_list_uploaded_files_reads_uploaded_files_only(self):
        src = Path("main.py").read_text(encoding="utf-8")
        anchor = "def list_uploaded_files("
        start  = src.index(anchor)
                                              
        end    = src.index("\ndef ", start + 1)
        body   = src[start:end]
        self.assertIn(
            "FROM uploaded_files", body,
            msg=(
                "list_uploaded_files must read from "
                "uploaded_files"
            ),
        )
        for forbidden in (
            "FROM vault_items",
            "item_type",
            "encrypted_data",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, body,
                    msg=(
                        f"list_uploaded_files must NEVER touch "
                        f"`{forbidden}` — typed items belong in "
                        f"the Logins / secure-items surface"
                    ),
                )


class TestChatSaveLandsTypedRows(unittest.TestCase):


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

    def _save_via_chat(self, *, message: str, tier: str):


        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=tier,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=tier,
        )

    def test_chat_save_imei_lands_imei_row(self):
        self._save_via_chat(
            message=f"save my imei {_IMEI}",
            tier=vsi.TIER_FREE,
        )
        self.assertEqual(len(self._rows), 1)
        self.assertEqual(self._rows[0]["item_type"], "imei")

    def test_chat_save_private_note_lands_private_note_row(self):
        self._save_via_chat(
            message=f"save this private word: {_PRIVATE_WORD}",
            tier=vsi.TIER_FREE,
        )
        self.assertEqual(len(self._rows), 1)
        self.assertEqual(self._rows[0]["item_type"], "private_note")

    def test_chat_save_backup_code_lands_backup_code_row(self):
        self._save_via_chat(
            message=f"save my backup codes {_BACKUP_CODE}",
            tier=vsi.TIER_FREE,
        )
        self.assertEqual(len(self._rows), 1)
                                                           
                                                       
        self.assertEqual(self._rows[0]["item_type"], "backup_code")

    def test_chat_save_crypto_wallet_lands_crypto_wallet_row(self):
        self._save_via_chat(
            message=f"save my USDT TRC20 address {_USDT_TRC20}",
            tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(len(self._rows), 1)
        self.assertEqual(
            self._rows[0]["item_type"], "crypto_wallet_address",
        )

    def test_every_typed_save_lands_in_secure_items_list_categories(self):
                                                           
                                                             
        cases = [
            (f"save my imei {_IMEI}",                       "imei",                  vsi.TIER_FREE),
            (f"save this private word: {_PRIVATE_WORD}",    "private_note",          vsi.TIER_FREE),
            (f"save my backup codes {_BACKUP_CODE}",        "backup_code",           vsi.TIER_FREE),
            (f"save my USDT TRC20 address {_USDT_TRC20}",   "crypto_wallet_address", vsi.TIER_UPGRADED),
        ]
        for msg, expected_type, tier in cases:
            with self.subTest(msg=msg):
                self._rows.clear()
                draft_store._reset_store_for_test()
                self._save_via_chat(message=msg, tier=tier)
                self.assertEqual(len(self._rows), 1)
                row = self._rows[0]
                self.assertEqual(row["item_type"], expected_type)
                                                               
                                                        
                self.assertIn(row["item_type"], t.ALL_CATEGORIES)
                                                       
                                                             
                if expected_type != "login":
                    plain = _fake_decrypt(
                        row["encrypted_data"], self.key,
                    )
                    decoded = json.loads(plain)
                    self.assertNotIn(
                        "password", decoded.get("fields") or {},
                        msg=(
                            f"non-login save of `{expected_type}` "
                            "must NOT carry a password field"
                        ),
                    )
                    self.assertNotIn(
                        "username", decoded.get("fields") or {},
                        msg=(
                            f"non-login save of `{expected_type}` "
                            "must NOT carry a username field"
                        ),
                    )


class TestRetrievalScopes(unittest.TestCase):


    def test_show_my_logins_intent_targets_login_category(self):
        out = ci.classify_secure_item_intent("show my logins")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_LOGIN)

    def test_show_my_saved_items_intent_targets_all_categories(self):
        for phrase in (
            "show my saved items",
            "show my secure items",
            "list my vault items",
        ):
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(
                    out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM,
                )
                self.assertEqual(
                    out.category, ci.CATEGORY_FILTER_ALL,
                )

    def test_show_my_logins_retrieval_envelope_carries_only_login_rows(self):
                                                           
                                                            
        key = b"\x07" * 32
        rows: list[dict] = []
        patches = _patch_crypto()
        for p in patches:
            p.start()
        draft_store._reset_store_for_test()
        try:
                                                
            vsi.route_secure_item_message(
                vault_id="v1", key=key,
                user_message=f"save my imei {_IMEI}",
                db_executor=lambda *a: rows.append(a[1]),
                db_reader=lambda v, c: [],
                user_tier=vsi.TIER_FREE,
            )
            vsi.route_secure_item_message(
                vault_id="v1", key=key,
                user_message="save it now",
                db_executor=lambda *a: rows.append(a[1]),
                db_reader=lambda v, c: [],
                user_tier=vsi.TIER_FREE,
            )
                                          
            login_record = {
                "category": "login",
                "title":    "Netflix",
                "fields":   {"username": "u1", "password": "p1"},
                "item_id":  "login-1",
            }
            rows.append({
                "vault_id":       "v1",
                "item_type":      "login",
                "service":        "Netflix",
                "encrypted_data": _fake_encrypt(
                    json.dumps(login_record), key,
                ),
            })

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

            result = vsi.route_secure_item_message(
                vault_id="v1", key=key,
                user_message="show my logins",
                db_reader=reader,
                user_tier=vsi.TIER_FREE,
            )
            self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
            envelope = json.loads(result["envelope"])
            types = {c["type"] for c in envelope["items"]}
            self.assertEqual(types, {"login"})
                                                         
            for c in envelope["items"]:
                self.assertNotEqual(c["type"], "imei")
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass
            draft_store._reset_store_for_test()

    def test_show_my_saved_items_retrieval_envelope_spans_categories(self):
        key = b"\x07" * 32
        rows: list[dict] = []
        patches = _patch_crypto()
        for p in patches:
            p.start()
        draft_store._reset_store_for_test()
        try:
                                                     
            for msg in (
                f"save my imei {_IMEI}",
                "save it now",
                f"save this private word: {_PRIVATE_WORD}",
                "save it now",
            ):
                vsi.route_secure_item_message(
                    vault_id="v1", key=key, user_message=msg,
                    db_executor=lambda *a: rows.append(a[1]),
                    db_reader=lambda v, c: [],
                    user_tier=vsi.TIER_FREE,
                )

            def reader_all(vault_id):
                return [
                    {
                        "id":             f"row-{i}",
                        "item_type":      r["item_type"],
                        "service":        r["service"],
                        "encrypted_data": r["encrypted_data"],
                        "created_at":     1_700_000_000.0 + i,
                    }
                    for i, r in enumerate(rows)
                ]

            result = vsi.route_secure_item_message(
                vault_id="v1", key=key,
                user_message="show my saved items",
                db_reader_all=reader_all,
                user_tier=vsi.TIER_FREE,
            )
            self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
            envelope = json.loads(result["envelope"])
            types = {c["type"] for c in envelope["items"]}
                                                          
            self.assertIn("imei", types)
            self.assertIn("private_note", types)
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass
            draft_store._reset_store_for_test()


class TestNonLoginCategoriesShape(unittest.TestCase):


    def test_non_login_categories_do_not_validate_with_only_username_or_password(self):
                                                            
                                                                 
        for cat in (
            t.CATEGORY_IMEI,
            t.CATEGORY_PRIVATE_NOTE,
            t.CATEGORY_BACKUP_CODE,
            t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            t.CATEGORY_CRYPTO_SEED_PHRASE,
        ):
            with self.subTest(cat=cat):
                                                       
                slug = t.classify_secure_item_payload({
                    "secret_type": cat,
                    "service":     "Test",
                    "fields":      {"value": "x"},
                })
                self.assertIsNone(slug)
                                                                
                                                            
                self.assertNotIn(cat, t.LOGIN_LIKE_CATEGORIES)


if __name__ == "__main__":                    
    unittest.main()
