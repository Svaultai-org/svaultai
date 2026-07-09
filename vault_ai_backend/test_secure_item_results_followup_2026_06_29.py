

from __future__ import annotations

import json
import unittest
from typing import Any, Optional

from vault_active_context import (
    ALL_CONTEXTS,
    CONTEXT_SECURE_ITEM_RESULTS,
)
from vault_saved_item_chat_intent import (
    INTENT_RETRIEVE_SECURE_ITEM,
    SecureItemIntent,
)
from vault_saved_item_taxonomy import (
    CATEGORY_IMEI,
    CATEGORY_LOGIN,
    CATEGORY_LICENSE_KEY,
)
from vault_secure_item_card_envelope import (
    build_secure_item_card,
    build_secure_item_results_envelope,
)
from vault_secure_item_draft import _reset_store_for_test as _reset_draft_store
from vault_secure_item_results_followup import (
    FOLLOWUP_CLARIFY,
    FOLLOWUP_DELETE_ONE,
    FOLLOWUP_NONE,
    FOLLOWUP_REVEAL_ONE,
    SecureItemResultsCard,
    _reset_store_for_test,
    classify_results_followup,
    get_results_context,
    store_results_context,
)
from vault_secure_item_save import (
    BAND_DELETE_PROMPT,
    BAND_FOLLOWUP_CLARIFY,
    BAND_NOT_FOUND,
    BAND_RETRIEVED,
    route_secure_item_message,
)


VAULT_ID = "vault-followup-tests-abc"
KEY = bytes(range(32))


class TestActiveContextLabelRegistered(unittest.TestCase):
    def test_secure_item_results_label_in_all_contexts(self) -> None:
        self.assertIn(
            CONTEXT_SECURE_ITEM_RESULTS, ALL_CONTEXTS,
            msg=(
                "CONTEXT_SECURE_ITEM_RESULTS must be a closed-set "
                "context label so set_active_context accepts it"
            ),
        )

    def test_label_value_is_stable(self) -> None:
                                                                
                       
        self.assertEqual(
            CONTEXT_SECURE_ITEM_RESULTS, "secure_item_results",
        )


class TestResultsContextStore(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def _card(self, **kw) -> dict:
        defaults = {
            "item_id": "uuid-1",
            "type":    CATEGORY_LOGIN,
            "title":   "Netflix",
        }
        defaults.update(kw)
        return defaults

    def test_round_trip_preserves_cards(self) -> None:
        store_results_context(
            vault_id=VAULT_ID,
            cards=[
                self._card(item_id="a", type="imei", title="Phone IMEI"),
                self._card(item_id="b", type="login", title="Netflix"),
            ],
            last_query="show my saved items",
        )
        ctx = get_results_context(vault_id=VAULT_ID)
        self.assertIsNotNone(ctx)
        self.assertEqual(len(ctx.cards), 2)
        self.assertEqual(ctx.cards[0].title, "Phone IMEI")
        self.assertEqual(ctx.cards[1].item_type, "login")

    def test_clears_after_ttl_zero(self) -> None:
        store_results_context(
            vault_id=VAULT_ID,
            cards=[self._card()],
            last_query="",
            ttl_seconds=-1,                         
        )
        ctx = get_results_context(vault_id=VAULT_ID)
        self.assertIsNotNone(ctx,
            msg="negative ttl must fall back to default")


class TestFollowupClassifier(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def _ctx(self, cards):
        return store_results_context(
            vault_id=VAULT_ID,
            cards=cards,
            last_query="show my saved items",
        )

    def _card(self, **kw):
        defaults = {"item_id": "uuid", "type": "login", "title": "Netflix"}
        defaults.update(kw)
        return defaults

    def test_show_me_with_one_card_resolves_to_reveal_one(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", type="imei", title="iPhone 15 IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="show me", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(len(resolution.cards), 1)
        self.assertEqual(resolution.cards[0].title, "iPhone 15 IMEI")

    def test_show_me_with_many_cards_clarifies(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", type="card",  title="Payment Card"),
            self._card(item_id="b", type="bank",  title="Bank Account"),
            self._card(item_id="c", type="imei",  title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="show me", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_CLARIFY)
                                                    
        self.assertIn("3 saved items", resolution.message)
        self.assertIn("Payment Card", resolution.message)
        self.assertIn("Bank Account", resolution.message)
        self.assertIn("Phone IMEI", resolution.message)

    def test_open_it_with_one_card_resolves(self) -> None:
        ctx = self._ctx([
            self._card(item_id="x", type="login", title="Netflix"),
        ])
        resolution = classify_results_followup(
            user_message="open it", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)

    def test_reveal_it_marks_reveal_flag(self) -> None:
        ctx = self._ctx([self._card()])
        resolution = classify_results_followup(
            user_message="reveal it", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertTrue(resolution.reveal,
            msg="'reveal it' must surface the full value")

    def test_show_full_reveals(self) -> None:
        ctx = self._ctx([self._card()])
        resolution = classify_results_followup(
            user_message="show full", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertTrue(resolution.reveal)

    def test_first_one_picks_first_card(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Bank Account"),
            self._card(item_id="c", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="show the first one", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(resolution.cards[0].item_id, "a")

    def test_second_picks_second(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Bank Account"),
        ])
        resolution = classify_results_followup(
            user_message="show me the second", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(resolution.cards[0].item_id, "b")

    def test_last_picks_last(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Bank Account"),
            self._card(item_id="c", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="open the last one", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(resolution.cards[0].item_id, "c")

    def test_show_me_my_phone_imei_login_resolves_imei(self) -> None:


        ctx = self._ctx([
            self._card(item_id="a", type="login", title="Netflix"),
            self._card(item_id="b", type="imei",  title="iPhone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="show me my Phone IMEI login", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(resolution.cards[0].item_id, "b")
        self.assertEqual(resolution.cards[0].item_type, "imei")

    def test_target_phrase_picks_unique_match(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Bank Account"),
            self._card(item_id="c", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="show me the payment card", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_REVEAL_ONE)
        self.assertEqual(resolution.cards[0].title, "Payment Card")

    def test_target_phrase_with_multiple_matches_clarifies(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Norton key"),
            self._card(item_id="b", title="Norton recovery phrase"),
        ])
        resolution = classify_results_followup(
            user_message="show me Norton", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_CLARIFY)
        self.assertIn("Norton key", resolution.message)
        self.assertIn("Norton recovery phrase", resolution.message)

    def test_delete_it_with_one_card_resolves_delete(self) -> None:
        ctx = self._ctx([
            self._card(item_id="x", type="imei", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="delete it", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_DELETE_ONE)
        self.assertEqual(resolution.cards[0].item_type, "imei")

    def test_delete_the_payment_card(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="delete the payment card", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_DELETE_ONE)
        self.assertEqual(resolution.cards[0].title, "Payment Card")

    def test_delete_with_many_cards_clarifies(self) -> None:
        ctx = self._ctx([
            self._card(item_id="a", title="Payment Card"),
            self._card(item_id="b", title="Phone IMEI"),
        ])
        resolution = classify_results_followup(
            user_message="delete it", context=ctx,
        )
        self.assertEqual(resolution.band, FOLLOWUP_CLARIFY)
        self.assertIn("delete", resolution.message)

    def test_unrelated_message_returns_none(self) -> None:
        ctx = self._ctx([self._card()])
        for msg in (
            "what time is it",
            "tell me a joke",
            "save my Norton key 78490",
        ):
            with self.subTest(msg=msg):
                resolution = classify_results_followup(
                    user_message=msg, context=ctx,
                )
                self.assertEqual(resolution.band, FOLLOWUP_NONE)

    def test_no_context_returns_none(self) -> None:
        resolution = classify_results_followup(
            user_message="show me", context=None,
        )
        self.assertEqual(resolution.band, FOLLOWUP_NONE)


class _StubDB:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.upserts: list[tuple[str, dict]] = []

    def executor(self, action: str, payload: dict) -> None:
        self.upserts.append((action, payload))

    def reader(self, vault_id: str, category: str) -> list[dict]:
        return [r for r in self.rows if r["item_type"] == category]

    def reader_all(self, vault_id: str) -> list[dict]:
        return list(self.rows)


def _make_encrypted_row(
    *, item_id: int, item_type: str, service: str,
    title: str, fields: Optional[dict] = None,
) -> dict:
    from vault_core import encrypt_message
    record = {
        "category": item_type,
        "title":    title,
        "fields":   fields or {},
        "notes":    None,
        "item_id":  f"item-{item_id}",
    }
    blob = encrypt_message(json.dumps(record), KEY)
    return {
        "id":             item_id,
        "item_type":      item_type,
        "service":        service,
        "encrypted_data": blob,
        "created_at":     None,
    }


class TestOrchestratorWiresFollowup(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()
        _reset_draft_store()
        self.db = _StubDB()
        self.db.rows = [
            _make_encrypted_row(
                item_id=1, item_type="login",
                service="Netflix", title="Netflix",
                fields={"username": "alice"},
            ),
            _make_encrypted_row(
                item_id=2, item_type="imei",
                service="Phone IMEI", title="Phone IMEI",
                fields={"imei_1": "123456789012345"},
            ),
            _make_encrypted_row(
                item_id=3, item_type="license_key",
                service="Norton key", title="Norton key",
                fields={"license_key": "ABCDE-FGHIJ-KLMNO"},
            ),
        ]

    def tearDown(self) -> None:
        _reset_store_for_test()
        _reset_draft_store()

    def test_show_my_saved_items_then_show_me_resolves_card(self) -> None:
                                                
        r1 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show my saved items",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r1["band"], BAND_RETRIEVED)
        self.assertEqual(r1["count"], 3)
                         
        ctx = get_results_context(vault_id=VAULT_ID)
        self.assertIsNotNone(ctx)
        self.assertEqual(len(ctx.cards), 3)

                                                   
        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show me",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r2["band"], BAND_FOLLOWUP_CLARIFY)
        self.assertIn("3 saved items", r2["message"])

    def test_one_result_then_show_me_opens_the_card(self) -> None:
                                                         
        self.db.rows = [
            _make_encrypted_row(
                item_id=1, item_type="license_key",
                service="Norton key", title="Norton key",
                fields={"license_key": "ABCDE-FGHIJ"},
            ),
        ]
        r1 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show my Norton key",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r1["band"], BAND_RETRIEVED)
        self.assertEqual(r1["count"], 1)
                                                            
        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show me",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r2["band"], BAND_RETRIEVED)
        self.assertEqual(r2["count"], 1)

    def test_followup_delete_routes_through_confirmation(self) -> None:
                                                       
                                                                 
        from vault_secure_item_save import (
            BAND_DELETE_CONFIRMATION_PENDING,
        )
        self.db.rows = [
            _make_encrypted_row(
                item_id=1, item_type="imei",
                service="Phone IMEI", title="Phone IMEI",
                fields={"imei_1": "12345"},
            ),
        ]
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show my imei",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="delete it",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r2["band"], BAND_DELETE_CONFIRMATION_PENDING)
                                                                
                
        self.assertEqual(r2["type"], "imei")
        self.assertEqual(r2["title"], "Phone IMEI")
        msg_lower = r2["message"].lower()
                                                    
        self.assertIn("phone imei", msg_lower)
        for forbidden in (
            "phone imei login",
            "imei login",
            "login imei",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, msg_lower)

    def test_followup_message_uses_saved_items_language(self) -> None:
                                                                
                                      
        r1 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show my saved items",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r1["band"], BAND_RETRIEVED)
        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="show me",
            db_reader=self.db.reader,
            db_reader_all=self.db.reader_all,
        )
        self.assertEqual(r2["band"], BAND_FOLLOWUP_CLARIFY)
        self.assertIn("saved items", r2["message"].lower())


if __name__ == "__main__":                    
    unittest.main()
