

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


_IMEI         = "345678909876548"
_IMEI_IPHONE  = "352099001761481"
_SERIAL       = "C7XW19RZ4NQF"
_PHONE        = "+1-415-555-0179"
_PRIVATE_WORD = "blue tiger"
_PRIVATE_LONG = "passport is in the drawer under the bed"


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


class TestBareImeiSerialClassifier(unittest.TestCase):


    def test_save_bare_imei_classifies_as_secure_item(self):
        out = ci.classify_secure_item_intent(
            f"save my imei {_IMEI}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_IMEI)
        self.assertEqual(out.value, _IMEI)
                                                             
                                                       
        self.assertEqual(out.category, t.CATEGORY_IMEI)
                                                        
        self.assertEqual(out.title, "Phone IMEI")

    def test_save_bare_serial_classifies_as_serial_number(self):
        out = ci.classify_secure_item_intent(
            f"save my serial number {_SERIAL}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_SERIAL)
        self.assertEqual(out.value, _SERIAL)
        self.assertEqual(out.category, t.CATEGORY_SERIAL_NUMBER)
        self.assertEqual(out.title, "Serial number")

    def test_save_iphone_imei_keeps_iphone_title(self):
                                                           
                                                              
        out = ci.classify_secure_item_intent(
            f"save my iPhone IMEI {_IMEI_IPHONE}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
                                                            
        self.assertEqual(out.category, t.CATEGORY_DEVICE)
        self.assertEqual(out.title, "iPhone")
                                             
        self.assertNotEqual(out.category, t.CATEGORY_LOGIN)


class TestPrivateNoteClassifier(unittest.TestCase):


    def test_save_private_word_with_colon(self):
        out = ci.classify_secure_item_intent(
            f"save this private word: {_PRIVATE_WORD}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_PRIVATE_NOTE)
        self.assertEqual(out.field, ci.FIELD_PRIVATE_VALUE)
        self.assertEqual(out.value, _PRIVATE_WORD)
        self.assertEqual(out.title, "Private note")

    def test_save_private_word_without_colon(self):
        out = ci.classify_secure_item_intent(
            f"save this private word {_PRIVATE_WORD}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_PRIVATE_NOTE)
        self.assertEqual(out.value, _PRIVATE_WORD)

    def test_save_private_note_full_sentence(self):
        out = ci.classify_secure_item_intent(
            f"save this private note: {_PRIVATE_LONG}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_PRIVATE_NOTE)
        self.assertEqual(out.value, _PRIVATE_LONG)


class TestConfirmSaveClassifier(unittest.TestCase):
    def test_save_it_now_classifies_as_confirm(self):
        out = ci.classify_secure_item_intent("save it now")
        self.assertEqual(out.intent, ci.INTENT_CONFIRM_SAVE)
                                                             

    def test_save_it_now_with_period(self):
        for phrase in (
            "save it now.",
            "save it now!",
            "Save it now",
            "  save it now  ",
        ):
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(out.intent, ci.INTENT_CONFIRM_SAVE)

    def test_other_confirm_phrases(self):
        for phrase in (
            "save it",
            "save that",
            "save now",
            "yes, save it",
            "confirm save",
            "ok save it",
            "go ahead and save it",
        ):
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(out.intent, ci.INTENT_CONFIRM_SAVE)

    def test_save_it_now_inside_longer_request_is_not_confirm(self):
                                                            
                                                             
        out = ci.classify_secure_item_intent(
            f"could you save it now please for my account?",
        )
                                                          
        self.assertEqual(out.intent, ci.INTENT_NONE)


class TestLoginFlowPreserved(unittest.TestCase):


    def test_save_netflix_login_falls_through(self):
        out = ci.classify_secure_item_intent("save my Netflix login")
        self.assertEqual(out.intent, ci.INTENT_NONE)

    def test_save_login_for_X_falls_through(self):
        out = ci.classify_secure_item_intent(
            "save my login for Wells Fargo",
        )
        self.assertEqual(out.intent, ci.INTENT_NONE)

    def test_create_username_and_password_falls_through(self):
        for phrase in (
            "create username and password for Union Bank",
            "generate a username and password for Acme",
            "make a credential for Wells Fargo",
            "create a login for Capital One",
        ):
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(out.intent, ci.INTENT_NONE)


class TestProposeDraftAndConfirm(unittest.TestCase):
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

    def test_save_my_imei_creates_secure_item_draft_not_db_row(self):
                                 
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
                          
        self.assertEqual(len(self._rows), 0)
                                    
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertIsNotNone(pending)
                                                             
        self.assertEqual(pending.category, t.CATEGORY_IMEI)

    def test_draft_message_names_item_and_asks_to_confirm(self):
                                                          
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
        msg = result["message"]
        self.assertIn("Sure", msg)
        self.assertIn("Phone IMEI", msg)
                                                           
                                                             
        self.assertIn("save it", msg)
        self.assertIn("store it in your vault", msg)
                                                            
        self.assertNotIn("login", msg.lower())

    def test_iphone_imei_draft_labels_secure_item_not_login(self):
                                 
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my iPhone IMEI {_IMEI_IPHONE}",
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
        self.assertEqual(result["category"], t.CATEGORY_DEVICE)
        self.assertNotIn("login", result["message"].lower())

    def test_save_it_now_consumes_draft_and_writes_row(self):
                                 
        vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
        self.assertEqual(len(self._rows), 0)              
                             
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_SAVED)
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
                                               
        self.assertEqual(row["item_type"], "imei")
        self.assertEqual(row["service"], "Phone IMEI")
                                                
        self.assertNotIn(_IMEI, row["encrypted_data"])
                                     
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(decoded["fields"]["imei_1"], _IMEI)
        self.assertEqual(decoded["category"], "imei")
                            
        self.assertIsNone(
            draft_store.get_latest_secure_item_draft(vault_id="v1"),
        )

    def test_final_reply_says_saved_to_your_vault_not_login(self):
                                                                 
        vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
        msg = result["message"]
                                                   
        self.assertIn("Saved to your vault", msg)
        self.assertIn("🔐", msg)
                                            
        self.assertNotIn("login", msg.lower())
                                               
        self.assertNotIn("Saved your login", msg)

    def test_private_word_draft_then_confirm_saves_private_note(self):
                                 
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save this private word: {_PRIVATE_WORD}",
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
                       
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertEqual(pending.category, t.CATEGORY_PRIVATE_NOTE)
                  
        result2 = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
        self.assertEqual(result2["band"], vsi.BAND_SAVED)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "private_note")
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(
            decoded["fields"]["private_value"], _PRIVATE_WORD,
        )

    def test_save_my_serial_drafts_serial_number_category(self):
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my serial number {_SERIAL}",
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertEqual(pending.category, t.CATEGORY_SERIAL_NUMBER)
                  
        vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
        self.assertEqual(self._rows[0]["item_type"], "serial_number")

    def test_confirm_with_no_pending_draft_returns_no_draft_band(self):
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_NO_DRAFT)
        self.assertEqual(len(self._rows), 0)

    def test_locked_vault_blocks_draft(self):
        result = vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=b"short",
            user_message=f"save my imei {_IMEI}",
        )
        self.assertEqual(result["band"], vsi.BAND_VAULT_LOCKED)
                                          
        self.assertIsNone(
            draft_store.get_latest_secure_item_draft(vault_id="v1"),
        )

    def test_locked_vault_blocks_confirm(self):
                                               
        vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
                                                 
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=b"short",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_VAULT_LOCKED)
        self.assertEqual(len(self._rows), 0)


class TestRetrieveAfterDraftConfirm(unittest.TestCase):


    def setUp(self):
        self.key = b"\x0b" * 32
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
            {"encrypted_data": r["encrypted_data"]}
            for r in self._rows
            if r["item_type"] == category
        ]

    def test_show_my_imei_retrieves_masked_preview(self):
                          
        vsi.propose_secure_item_draft_from_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
        )
        vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key,
            db_executor=self._exec,
        )
                   
        intent = ci.classify_secure_item_intent("show my IMEI")
        self.assertEqual(
            intent.intent, ci.INTENT_RETRIEVE_SECURE_ITEM,
        )
        result = vsi.retrieve_secure_item_from_intent(
            vault_id="v1", key=self.key,
            intent=intent, db_reader=self._reader,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        preview = result["preview"]
        self.assertEqual(preview["imei_1_mask"], "ending 6548")
                                                 
        self.assertNotIn(_IMEI, json.dumps(preview))


class TestSecureItemDraftPrivacy(unittest.TestCase):


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
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
        )
        for name in names:
            log = logging.getLogger(name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)

        key = b"\x0c" * 32
        rows: list[dict] = []

        def exec_(action, payload):
            rows.append(payload)

        patches = _patch_crypto()
        for p in patches:
            p.start()
        draft_store._reset_store_for_test()
        try:
            for msg in (
                f"save my imei {_IMEI}",
                f"save my serial number {_SERIAL}",
                f"save my phone number {_PHONE}",
                f"save this private word: {_PRIVATE_WORD}",
                f"save this private note: {_PRIVATE_LONG}",
            ):
                vsi.propose_secure_item_draft_from_message(
                    vault_id="v1", key=key, user_message=msg,
                )
                vsi.confirm_pending_secure_item_save(
                    vault_id="v1", key=key, db_executor=exec_,
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
        for forbidden in (
            _IMEI, _SERIAL, _PHONE,
            _PRIVATE_WORD, _PRIVATE_LONG,
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestSecureItemDraftRepr(unittest.TestCase):
    def test_repr_redacts_value(self):
        draft = draft_store.SecureItemDraft(
            draft_id="abc123",
            vault_id="vault_xxx_aaa",
            category=t.CATEGORY_IMEI,
            title="Phone IMEI",
            field=ci.FIELD_IMEI,
            value=_IMEI,
            notes=None,
            created_at=0.0,
            expires_at=999999.0,
            saved=False,
        )
        text = repr(draft)
        self.assertIn("REDACTED", text)
        self.assertNotIn(_IMEI, text)


if __name__ == "__main__":                    
    unittest.main()
