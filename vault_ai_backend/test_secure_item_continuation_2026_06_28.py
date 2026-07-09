

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import vault_active_context as ac
import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


_IMEI       = "2345678909876543"
_SERIAL     = "C7XW19RZ4NQF"
_PHONE      = "+1-415-555-0179"
_PRIVATE    = "blue tiger"


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


class TestTitleUpdateDetector(unittest.TestCase):


    def test_operator_examples_pass(self):
        for phrase in (
            "iphone 15 imei",
            "my iphone",
            "samsung phone imei",
            "laptop serial",
            "work laptop serial",
            "blue tiger note",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    ci.looks_like_secure_item_title_update(phrase),
                    f"expected True for {phrase!r}",
                )

    def test_command_or_question_phrases_rejected(self):
        for phrase in (
            "show me my IMEI",
            "what is my IMEI?",
            "save my Netflix login",
            "create a username and password for Acme",
            "save it now",
            "hello",
            "yes",
            "ok",
            "could you save it",
            "hi there",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    ci.looks_like_secure_item_title_update(phrase),
                    f"expected False for {phrase!r}",
                )

    def test_long_or_unrelated_phrases_rejected(self):
        for phrase in (
            "this is a much longer sentence that is not a label",
            "yeah cool",                                 
            "definitely",                                
            "",                            
            "   ",                                   
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    ci.looks_like_secure_item_title_update(phrase),
                )


class TestTitleNormalizer(unittest.TestCase):


    def test_operator_examples(self):
        cases = {
            "iphone 15 imei":     "iPhone 15 IMEI",
            "work laptop serial": "Work laptop serial number",
            "samsung phone imei": "Samsung phone IMEI",
            "blue tiger note":    "Blue tiger note",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    ci.normalize_secure_item_title(raw), expected,
                )

    def test_empty_input_returns_empty(self):
        self.assertEqual(ci.normalize_secure_item_title(""), "")
        self.assertEqual(ci.normalize_secure_item_title(None), "")
        self.assertEqual(ci.normalize_secure_item_title("   "), "")


class TestSecureItemOrchestrator(unittest.TestCase):
    def setUp(self):
        self.key = b"\x07" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()
        ac._reset_store_for_test()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        draft_store._reset_store_for_test()
        ac._reset_store_for_test()

    def _exec(self, action, payload):
        self._rows.append(payload)

                             
    def test_save_my_imei_drafts_immediately_via_orchestrator(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
                                                   
                                                                 
        msg = result["message"]
        self.assertIn("Sure", msg)
        self.assertIn("Phone IMEI", msg)
        self.assertIn("save it", msg)
        self.assertIn("store it in your vault", msg)
                                                              
        self.assertNotIn("identity", msg.lower())
        self.assertNotIn("service name", msg.lower())
        self.assertNotIn("PIN", msg)
        self.assertNotIn("login", msg.lower())
                          
        self.assertEqual(len(self._rows), 0)
                                           
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.category, t.CATEGORY_IMEI)

                             
    def test_pending_draft_plus_label_message_updates_title(self):
                        
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
        )
                                         
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="iphone 15 imei",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_TITLE_UPDATED)
        msg = result["message"]
        self.assertIn("iPhone 15 IMEI", msg)
        self.assertIn("save it", msg)
        self.assertIn("store it in your vault", msg)
                                                   
        self.assertNotIn("PIN", msg)
        self.assertNotIn("retriev", msg.lower())
        self.assertNotIn("login", msg.lower())
                                                            
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.title, "iPhone 15 IMEI")
        self.assertEqual(pending.value, _IMEI)
        self.assertEqual(pending.category, t.CATEGORY_IMEI)
                            
        self.assertEqual(len(self._rows), 0)

                                                               
    def test_pending_draft_plus_retrieve_intent_runs_retrieval(self):
                        
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
        )
                                                               
                                                               
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my IMEI",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
        )
        self.assertEqual(result["band"], vsi.BAND_NOT_FOUND)
                                           
        self.assertEqual(len(self._rows), 0)
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertIsNotNone(pending)

                             
    def test_full_three_turn_flow_save_relabel_confirm(self):
                               
        r1 = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
        )
        self.assertEqual(r1["band"], vsi.BAND_DRAFTED)
                                
        r2 = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="iphone 15 imei",
            db_executor=self._exec,
        )
        self.assertEqual(r2["band"], vsi.BAND_TITLE_UPDATED)
                           
        r3 = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )
        self.assertEqual(r3["band"], vsi.BAND_SAVED)
                             
        self.assertIn("Saved to your vault", r3["message"])
        self.assertIn("🔐", r3["message"])
        self.assertNotIn("login", r3["message"].lower())
                                                            
                           
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "imei")
        self.assertEqual(row["service"], "iPhone 15 IMEI")
                                   
        self.assertNotIn(_IMEI, row["encrypted_data"])
                                     
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(decoded["fields"]["imei_1"], _IMEI)
        self.assertEqual(decoded["title"], "iPhone 15 IMEI")
                                     
        self.assertIsNone(
            draft_store.get_latest_secure_item_draft(vault_id="v1"),
        )

    def test_new_save_intent_replaces_prior_draft(self):




        _counter = [1_700_000_000.0]

        def _monotonic_now():
            _counter[0] += 0.001
            return _counter[0]

        with patch.object(draft_store, "_now",
                          side_effect=_monotonic_now):
            vsi.route_secure_item_message(
                vault_id="v1", key=self.key,
                user_message=f"save my imei {_IMEI}",
                db_executor=self._exec,
            )
            r = vsi.route_secure_item_message(
                vault_id="v1", key=self.key,
                user_message=f"save my serial number {_SERIAL}",
                db_executor=self._exec,
            )
            self.assertEqual(r["band"], vsi.BAND_DRAFTED)

            pending = draft_store.get_latest_secure_item_draft(
                vault_id="v1",
            )
        self.assertEqual(pending.category, t.CATEGORY_SERIAL_NUMBER)
        self.assertEqual(pending.value, _SERIAL)

    def test_confirm_without_pending_draft_returns_no_draft(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_NO_DRAFT)
        self.assertEqual(len(self._rows), 0)

    def test_label_message_without_pending_draft_falls_through(self):
                                                             
                                                                 
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="iphone 15 imei",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_NO_INTENT)

    def test_private_word_label_works_with_draft(self):
                                                               
                                                    
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save this private word: {_PRIVATE}",
            db_executor=self._exec,
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="blue tiger note",
            db_executor=self._exec,
        )
        self.assertEqual(result["band"], vsi.BAND_TITLE_UPDATED)
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertEqual(pending.title, "Blue tiger note")

    def test_save_login_does_not_replace_secure_item_draft(self):
                                    
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my imei {_IMEI}",
            db_executor=self._exec,
        )
                                                                 
                                                   
        r = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save my Netflix login",
            db_executor=self._exec,
        )
        self.assertEqual(r["band"], vsi.BAND_NO_INTENT)
                                         
        pending = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertEqual(pending.value, _IMEI)


class TestUpdatePendingDraftTitle(unittest.TestCase):
    def setUp(self):
        draft_store._reset_store_for_test()

    def tearDown(self):
        draft_store._reset_store_for_test()

    def test_update_preserves_category_field_value_notes_expiry(self):
        original = draft_store.store_secure_item_draft(
            vault_id="v1",
            category=t.CATEGORY_IMEI,
            title="Phone IMEI",
            field=ci.FIELD_IMEI,
            value=_IMEI,
            notes="bought 2026-06-01",
        )
        updated = draft_store.update_pending_secure_item_draft_title(
            vault_id="v1", title="iPhone 15 IMEI",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.title, "iPhone 15 IMEI")
                                             
        self.assertEqual(updated.draft_id,   original.draft_id)
        self.assertEqual(updated.category,   original.category)
        self.assertEqual(updated.field,      original.field)
        self.assertEqual(updated.value,      original.value)
        self.assertEqual(updated.notes,      original.notes)
        self.assertEqual(updated.expires_at, original.expires_at)
        self.assertEqual(updated.created_at, original.created_at)
                                                                
        latest = draft_store.get_latest_secure_item_draft(vault_id="v1")
        self.assertEqual(latest.title, "iPhone 15 IMEI")

    def test_update_with_no_pending_draft_returns_none(self):
        out = draft_store.update_pending_secure_item_draft_title(
            vault_id="v1", title="Anything",
        )
        self.assertIsNone(out)

    def test_update_with_empty_title_returns_none(self):
        draft_store.store_secure_item_draft(
            vault_id="v1",
            category=t.CATEGORY_IMEI,
            title="Phone IMEI",
            field=ci.FIELD_IMEI,
            value=_IMEI,
        )
        for bad in ("", "  ", None):
            with self.subTest(title=bad):
                self.assertIsNone(
                    draft_store.update_pending_secure_item_draft_title(
                        vault_id="v1", title=bad,
                    ),
                )


class TestContinuationPrivacy(unittest.TestCase):


    def test_module_logs_carry_no_imei_or_private_value(self):
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
            "vault_active_context",
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
        ac._reset_store_for_test()
        try:
            for msg in (
                f"save my imei {_IMEI}",
                "iphone 15 imei",
                "save it now",
                f"save this private word: {_PRIVATE}",
                "blue tiger note",
                "save it now",
            ):
                vsi.route_secure_item_message(
                    vault_id="v1", key=key,
                    user_message=msg, db_executor=exec_,
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
            ac._reset_store_for_test()

        joined = "\n".join(r.getMessage() for r in records)
        for forbidden in (_IMEI, _PRIVATE, _SERIAL, _PHONE):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestSecureItemActiveContext(unittest.TestCase):


    def setUp(self):
        ac._reset_store_for_test()

    def tearDown(self):
        ac._reset_store_for_test()

    def test_secure_item_draft_label_in_all_contexts(self):
        self.assertIn(ac.CONTEXT_SECURE_ITEM_DRAFT, ac.ALL_CONTEXTS)
        self.assertEqual(
            ac.CONTEXT_SECURE_ITEM_DRAFT, "secure_item_draft",
        )

    def test_set_then_get_secure_item_draft_context(self):
        ac.set_active_context("v1", ac.CONTEXT_SECURE_ITEM_DRAFT)
        self.assertEqual(
            ac.get_active_context("v1"),
            ac.CONTEXT_SECURE_ITEM_DRAFT,
        )


if __name__ == "__main__":                    
    unittest.main()
