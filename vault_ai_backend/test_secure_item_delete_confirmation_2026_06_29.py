

from __future__ import annotations

import logging
import logging.handlers
import unittest
from typing import Any, Optional

from vault_active_context import (
    ALL_CONTEXTS,
    CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION,
)
from vault_secure_item_delete_confirmation import (
    BAND_DELETE_CANCELLED,
    BAND_DELETE_CONFIRMATION_PENDING,
    BAND_DELETED,
    BAND_NO_PENDING_DELETE,
    DELETE_INTENT_TTL_SECONDS,
    SENTINEL_PREFIX,
    SecureItemDeleteIntent,
    _reset_store_for_test,
    cancelled_reply,
    clear_pending_delete_intent,
    confirmation_question,
    consume_pending_delete_intent,
    deleted_reply,
    get_pending_delete_intent,
    is_cancel_delete_phrase,
    is_confirm_delete_phrase,
    is_delete_intent_sentinel,
    parse_delete_intent_sentinel,
    store_delete_intent,
)
from vault_secure_item_results_followup import (
    _reset_store_for_test as _reset_results_store,
    store_results_context,
)
from vault_secure_item_save import route_secure_item_message


VAULT_ID = "vault-delete-confirmation-tests"
KEY = bytes(range(32))


class _StubDB:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.deletes: list[dict] = []

    def executor(self, action: str, payload: dict) -> Any:
        if action == "delete":
            self.deletes.append(dict(payload))
                                                                       
            removed = [
                r for r in self.rows
                if r["item_type"] == payload["item_type"]
                and (r.get("service") or "").lower()
                    == (payload["service"] or "").lower()
            ]
            for r in removed:
                self.rows.remove(r)
            return len(removed)
        if action == "upsert":
                                                       
            return None
        return None

    def reader(self, vault_id: str, category: str) -> list[dict]:
        return [r for r in self.rows if r["item_type"] == category]

    def reader_all(self, vault_id: str) -> list[dict]:
        return list(self.rows)


class TestActiveContextLabel(unittest.TestCase):
    def test_label_value_pinned(self) -> None:
        self.assertEqual(
            CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION,
            "secure_item_delete_confirmation",
        )

    def test_label_in_all_contexts(self) -> None:
        self.assertIn(
            CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION,
            ALL_CONTEXTS,
        )


class TestDeleteIntentStore(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_round_trip_login_intent(self) -> None:
        intent = store_delete_intent(
            vault_id=VAULT_ID,
            service="Union Bank",
            item_type="login",
        )
        self.assertTrue(intent.is_login)
        self.assertEqual(intent.service, "Union Bank")
        self.assertEqual(intent.item_type, "login")
        pending = get_pending_delete_intent(vault_id=VAULT_ID)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.intent_id, intent.intent_id)

    def test_round_trip_non_login_intent(self) -> None:
        intent = store_delete_intent(
            vault_id=VAULT_ID,
            service="iPhone 15 IMEI",
            item_type="imei",
        )
        self.assertFalse(intent.is_login)

    def test_consume_removes_intent(self) -> None:
        store_delete_intent(
            vault_id=VAULT_ID, service="X", item_type="imei",
        )
        consumed = consume_pending_delete_intent(vault_id=VAULT_ID)
        self.assertIsNotNone(consumed)
        self.assertIsNone(get_pending_delete_intent(vault_id=VAULT_ID))

    def test_clear_drops_intent(self) -> None:
        store_delete_intent(
            vault_id=VAULT_ID, service="X", item_type="imei",
        )
        self.assertTrue(clear_pending_delete_intent(VAULT_ID))
        self.assertIsNone(get_pending_delete_intent(vault_id=VAULT_ID))

    def test_ttl_zero_falls_back_to_default(self) -> None:
        intent = store_delete_intent(
            vault_id=VAULT_ID, service="X", item_type="imei",
            ttl_seconds=-1,
        )
                      
        self.assertGreater(intent.expires_at, intent.created_at + 100)

    def test_credential_type_is_login_like(self) -> None:
        intent = store_delete_intent(
            vault_id=VAULT_ID,
            service="Generated cred",
            item_type="credential",
        )
        self.assertTrue(intent.is_login)

    def test_repr_redacts_title(self) -> None:
        intent = store_delete_intent(
            vault_id=VAULT_ID,
            service="Union Bank — PRIVATE",
            item_type="login",
        )
        self.assertNotIn("Union Bank", repr(intent))
        self.assertNotIn("Union Bank", str(intent))
        self.assertIn("<REDACTED>", repr(intent))


class TestSentinelParser(unittest.TestCase):
    def test_basic_parse(self) -> None:
        out = parse_delete_intent_sentinel(
            "__delete_item:imei:iPhone 15 IMEI",
        )
        self.assertEqual(out, ("imei", "iPhone 15 IMEI"))

    def test_credential_type(self) -> None:
        out = parse_delete_intent_sentinel(
            "__delete_item:credential:Union Bank",
        )
        self.assertEqual(out, ("credential", "Union Bank"))

    def test_non_sentinel_returns_none(self) -> None:
        for msg in (
            "yes delete it",
            "delete it",
            "show me",
            "save my Norton key 12345",
            "",
            None,
        ):
            with self.subTest(msg=msg):
                self.assertIsNone(
                    parse_delete_intent_sentinel(msg),
                )

    def test_is_sentinel(self) -> None:
        self.assertTrue(
            is_delete_intent_sentinel("__delete_item:imei:Phone IMEI"),
        )
        self.assertFalse(is_delete_intent_sentinel("yes delete it"))

    def test_sentinel_prefix_constant_pinned(self) -> None:
                                                    
        self.assertEqual(SENTINEL_PREFIX, "__delete_item:")


class TestConfirmClassifier(unittest.TestCase):
    def test_pinned_confirm_phrases_match(self) -> None:
        for phrase in (
            "yes",
            "yes delete it",
            "yes, delete it",
            "yes delete now",
            "yes remove it",
            "delete it",
            "delete that",
            "delete now",
            "remove it",
            "remove that",
            "confirm",
            "confirm delete",
            "go ahead",
            "go ahead and delete it",
            "go ahead delete it",
            "proceed",
            "do it",
            "ok, delete it",
            "okay, delete it",
            "yep, delete it",
            "sure delete it",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    is_confirm_delete_phrase(phrase),
                    msg=f"closed-set confirm should match {phrase!r}",
                )

    def test_open_ended_phrases_do_not_confirm(self) -> None:
                                                             
                                                        
        for phrase in (
            "could you delete it tomorrow",
            "i think i'll delete it later",
            "maybe delete it",
            "should i delete it",
            "delete my Norton key 12345",                             
            "what would happen if i deleted it",
            "yes you can do that",
            "yes that's fine",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    is_confirm_delete_phrase(phrase),
                )


class TestCancelClassifier(unittest.TestCase):
    def test_pinned_cancel_phrases_match(self) -> None:
        for phrase in (
            "no",
            "nope",
            "cancel",
            "cancel it",
            "cancel that",
            "cancel delete",
            "don't delete",
            "don't delete it",
            "do not delete",
            "do not delete it",
            "stop",
            "keep it",
            "keep them",
            "never mind",
            "nevermind",
            "on second thought",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    is_cancel_delete_phrase(phrase),
                    msg=f"closed-set cancel should match {phrase!r}",
                )

    def test_open_ended_phrases_do_not_cancel(self) -> None:
        for phrase in (
            "no you can't do that",
            "no thanks i'll do it myself",
            "i don't think i should",
            "stop and think for a second",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    is_cancel_delete_phrase(phrase),
                )


class TestOperatorPinnedWording(unittest.TestCase):
    def test_confirmation_login(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="Union Bank", item_type="login",
            item_id=None, is_login=True,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            confirmation_question(intent),
            "Are you sure you want to delete Union Bank login "
            "from your vault?",
        )

    def test_confirmation_non_login_with_title(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="Phone IMEI", item_type="imei",
            item_id=None, is_login=False,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            confirmation_question(intent),
            "Are you sure you want to delete Phone IMEI from your vault?",
        )

    def test_confirmation_non_login_no_title(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="", item_type="imei",
            item_id=None, is_login=False,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            confirmation_question(intent),
            "Are you sure you want to delete this saved item from your vault?",
        )

    def test_deleted_reply_login(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="Union Bank", item_type="login",
            item_id=None, is_login=True,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            deleted_reply(intent),
            "Deleted Union Bank login from your vault.",
        )

    def test_deleted_reply_non_login(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="Phone IMEI", item_type="imei",
            item_id=None, is_login=False,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            deleted_reply(intent),
            "Deleted Phone IMEI from your vault.",
        )

    def test_deleted_reply_no_title(self) -> None:
        intent = SecureItemDeleteIntent(
            intent_id="x", vault_id=VAULT_ID,
            service="", item_type="imei",
            item_id=None, is_login=False,
            created_at=0.0, expires_at=99999999.0,
        )
        self.assertEqual(
            deleted_reply(intent),
            "Deleted saved item from your vault.",
        )

    def test_cancelled_reply(self) -> None:
        self.assertEqual(
            cancelled_reply(),
            "Okay — I won't delete it.",
        )


class TestRouteOrchestratorEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()
        _reset_results_store()
        self.db = _StubDB()
                                                    
        self.db.rows = [
            {"id": 1, "item_type": "imei",
             "service": "iPhone 15 IMEI", "encrypted_data": b"x"},
            {"id": 2, "item_type": "login",
             "service": "Union Bank", "encrypted_data": b"y"},
        ]

    def tearDown(self) -> None:
        _reset_store_for_test()
        _reset_results_store()

    def test_sentinel_starts_confirmation_no_db_write(self) -> None:
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CONFIRMATION_PENDING)
        self.assertEqual(result["title"], "iPhone 15 IMEI")
        self.assertEqual(result["type"], "imei")
        self.assertFalse(result["is_login"])
        self.assertEqual(
            result["message"],
            "Are you sure you want to delete iPhone 15 IMEI "
            "from your vault?",
        )
                          
        self.assertEqual(self.db.deletes, [])
                                
        self.assertIsNotNone(
            get_pending_delete_intent(vault_id=VAULT_ID),
        )

    def test_sentinel_login_uses_login_wording(self) -> None:
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:login:Union Bank",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CONFIRMATION_PENDING)
        self.assertTrue(result["is_login"])
        self.assertIn("Union Bank login", result["message"])

    def test_yes_after_sentinel_deletes(self) -> None:
                           
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
                        
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETED)
        self.assertEqual(
            result["message"],
            "Deleted iPhone 15 IMEI from your vault.",
        )
        self.assertEqual(result["count"], 1)
                                              
        self.assertEqual(len(self.db.deletes), 1)
        self.assertEqual(
            self.db.deletes[0],
            {
                "vault_id":  VAULT_ID,
                "item_type": "imei",
                "service":   "iPhone 15 IMEI",
            },
        )
                                 
        self.assertIsNone(
            get_pending_delete_intent(vault_id=VAULT_ID),
        )

    def test_delete_it_after_sentinel_also_confirms(self) -> None:
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="delete it",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETED)

    def test_cancel_after_sentinel_does_not_delete(self) -> None:
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="cancel",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CANCELLED)
        self.assertEqual(result["message"], "Okay — I won't delete it.")
                      
        self.assertEqual(self.db.deletes, [])
                                 
        self.assertIsNone(
            get_pending_delete_intent(vault_id=VAULT_ID),
        )

    def test_no_after_sentinel_cancels(self) -> None:
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="no",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CANCELLED)

    def test_dont_delete_cancels(self) -> None:
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:imei:iPhone 15 IMEI",
            db_executor=self.db.executor,
        )
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="don't delete",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CANCELLED)

    def test_yes_without_pending_returns_no_pending(self) -> None:
                                                               
                                                             
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=self.db.executor,
        )
        self.assertIn(result["band"], {"no_intent", "no_draft"})
        self.assertEqual(self.db.deletes, [])

    def test_followup_delete_it_after_results_envelope_confirms(self) -> None:
                                                               
                                                  
        store_results_context(
            vault_id=VAULT_ID,
            cards=[{
                "item_id": "uuid-a",
                "type":    "imei",
                "title":   "iPhone 15 IMEI",
            }],
            last_query="show my imei",
        )
                                                              
                             
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="delete it",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_DELETE_CONFIRMATION_PENDING,
            msg=(
                "Follow-up 'delete it' against a results envelope "
                "must route through confirmation, not immediate delete"
            ),
        )
        self.assertEqual(result["title"], "iPhone 15 IMEI")
        self.assertEqual(self.db.deletes, [],
            msg="No DB write until the user confirms",
        )
                                    
        result2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=self.db.executor,
        )
        self.assertEqual(result2["band"], BAND_DELETED)
        self.assertEqual(len(self.db.deletes), 1)


class TestPrivacyFloor(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_orchestrator_logs_do_not_carry_title(self) -> None:
        secret_title = "iPhone 15 IMEI 123456789012345"
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "imei",
             "service": secret_title, "encrypted_data": b"x"},
        ]
        handler = logging.handlers.MemoryHandler(capacity=4096)
        logger = logging.getLogger("vault_secure_item_save")
        prior_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
                                             
        del_logger = logging.getLogger(
            "vault_secure_item_delete_confirmation",
        )
        del_prior_level = del_logger.level
        del_logger.setLevel(logging.DEBUG)
        del_logger.addHandler(handler)
        try:
            route_secure_item_message(
                vault_id=VAULT_ID, key=KEY,
                user_message=f"__delete_item:imei:{secret_title}",
                db_executor=db.executor,
            )
            route_secure_item_message(
                vault_id=VAULT_ID, key=KEY,
                user_message="yes",
                db_executor=db.executor,
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prior_level)
            del_logger.removeHandler(handler)
            del_logger.setLevel(del_prior_level)
        for record in handler.buffer:
            with self.subTest(message=record.getMessage()):
                self.assertNotIn(
                    "123456789012345",
                    record.getMessage(),
                    msg=(
                        "Closed-set telemetry must not carry the "
                        "raw title — privacy floor violation"
                    ),
                )


class TestTTLBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_ttl_default_is_ten_minutes(self) -> None:
        self.assertEqual(DELETE_INTENT_TTL_SECONDS, 600)

    def test_expired_intent_returns_none(self) -> None:
                                                                  
                                                               
        import time
        from vault_secure_item_delete_confirmation import (
            _store, _lock,
        )
        intent = store_delete_intent(
            vault_id=VAULT_ID, service="X", item_type="imei",
            ttl_seconds=10,
        )
                                         
        from dataclasses import replace
        with _lock:
            _store[VAULT_ID] = replace(
                intent, expires_at=time.time() - 1.0,
            )
        self.assertIsNone(get_pending_delete_intent(vault_id=VAULT_ID))


if __name__ == "__main__":                    
    unittest.main()
