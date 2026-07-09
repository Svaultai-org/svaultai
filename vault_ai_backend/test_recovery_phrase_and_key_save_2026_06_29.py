

from __future__ import annotations

import logging
import logging.handlers
import unittest
from typing import Any, Optional

from vault_saved_item_chat_intent import (
    CATEGORY_FILTER_ALL,
    FIELD_LICENSE_KEY,
    FIELD_PRIVATE_KEY,
    FIELD_PRODUCT_KEY,
    FIELD_ACTIVATION_KEY,
    FIELD_RECOVERY_CODE,
    FIELD_RECOVERY_PHRASE,
    INTENT_NONE,
    INTENT_SAVE_SECURE_ITEM,
    SecureItemIntent,
    classify_secure_item_intent,
    has_crypto_marker,
    looks_like_secure_item_title_update,
    normalize_secure_item_title,
)
from vault_saved_item_taxonomy import (
    ALL_CATEGORIES,
    CATEGORY_ACTIVATION_KEY,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
    CATEGORY_LICENSE_KEY,
    CATEGORY_LOGIN,
    CATEGORY_PRIVATE_KEY,
    CATEGORY_PRODUCT_KEY,
    CATEGORY_RECOVERY_PHRASE,
    KEY_FAMILY_CATEGORIES,
    LOGIN_LIKE_CATEGORIES,
    NON_LOGIN_CATEGORIES,
    category_label,
    masked_preview,
)
from vault_secure_item_draft import (
    SecureItemDraft,
    _drafts_for_test,
    _reset_store_for_test,
    get_latest_secure_item_draft,
    store_secure_item_draft,
)
from vault_secure_item_save import (
    BAND_DRAFTED,
    BAND_NO_INTENT,
    BAND_SAVED,
    BAND_TITLE_UPDATED,
    propose_secure_item_draft_from_intent,
    propose_secure_item_draft_from_message,
    route_secure_item_message,
    update_pending_secure_item_draft_title_from_message,
)


VAULT_ID = "vault-abc-def-recovery-key-tests"
KEY = bytes(range(32))                                       


class _StubDB:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def executor(self, action: str, payload: dict) -> None:
        if action == "upsert":
            self.rows.append(dict(payload))

    def by_item_type(self, item_type: str) -> list[dict]:
        return [r for r in self.rows if r["item_type"] == item_type]


class TestNewCategoriesRegistered(unittest.TestCase):
    def test_new_key_family_categories_in_all_categories(self) -> None:
        for cat in (
            CATEGORY_LICENSE_KEY, CATEGORY_PRODUCT_KEY,
            CATEGORY_ACTIVATION_KEY, CATEGORY_PRIVATE_KEY,
            CATEGORY_RECOVERY_PHRASE,
        ):
            with self.subTest(category=cat):
                self.assertIn(
                    cat, ALL_CATEGORIES,
                    msg=(
                        f"category {cat} must be in ALL_CATEGORIES "
                        "for masked_preview / list-secure-items to "
                        "recognise it"
                    ),
                )

    def test_key_family_categories_are_non_login(self) -> None:
        for cat in KEY_FAMILY_CATEGORIES:
            with self.subTest(category=cat):
                self.assertIn(
                    cat, NON_LOGIN_CATEGORIES,
                    msg=(
                        f"{cat} should NOT require username/password — "
                        "operator: secure items, not logins"
                    ),
                )
                self.assertNotIn(
                    cat, LOGIN_LIKE_CATEGORIES,
                    msg=(
                        f"{cat} is in LOGIN_LIKE_CATEGORIES — that "
                        "forces a username/password floor on what "
                        "should be a free-form secret"
                    ),
                )

    def test_each_key_family_category_has_label(self) -> None:
        expected = {
            CATEGORY_LICENSE_KEY:     "License key",
            CATEGORY_PRODUCT_KEY:     "Product key",
            CATEGORY_ACTIVATION_KEY:  "Activation key",
            CATEGORY_PRIVATE_KEY:     "Private key",
            CATEGORY_RECOVERY_PHRASE: "Recovery phrase",
        }
        for cat, want in expected.items():
            with self.subTest(category=cat):
                self.assertEqual(category_label(cat), want)

    def test_key_family_masked_preview_hides_value(self) -> None:
        for cat, fname in (
            (CATEGORY_LICENSE_KEY,    "license_key"),
            (CATEGORY_PRODUCT_KEY,    "product_key"),
            (CATEGORY_ACTIVATION_KEY, "activation_key"),
        ):
            with self.subTest(category=cat):
                preview = masked_preview(
                    category=cat, title="Norton",
                    fields={fname: "78490GHFHF779585"},
                )
                self.assertEqual(preview[f"{fname}_mask"], "•••••• hidden")
                self.assertTrue(preview[f"has_{fname}"])
                                                                 
                self.assertNotIn(
                    "78490GHFHF779585", repr(preview),
                    msg=(
                        f"{cat} preview leaked the raw value — must "
                        "be hidden, not partial-masked"
                    ),
                )


class TestCryptoMarkerDetector(unittest.TestCase):
    def test_recognises_crypto_words(self) -> None:
        for msg in (
            "save my Bitcoin wallet private key XYZ",
            "save my BTC wallet address ABCDEFGH123456",
            "save my Ethereum seed phrase ...",
            "save my USDT TRC20 wallet ...",
            "save my MetaMask recovery phrase ...",
            "save my Coinbase exchange notes ...",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(
                    has_crypto_marker(msg),
                    msg=f"{msg!r} should be flagged as crypto context",
                )

    def test_does_not_flag_norton_key(self) -> None:
                                                            
        for msg in (
            "save my Norton key 78490GHFHF779585",
            "save my recovery phrase for my norton key 78490",
            "save my private key for SSH server ABC123",
            "save my license key for Office XXXXX-YYYYY",
            "save my product key for Windows 12345",
            "save my activation key for Photoshop ABC",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(
                    has_crypto_marker(msg),
                    msg=(
                        f"{msg!r} should NOT be flagged as crypto — "
                        "operator: 'key' alone is a license / recovery "
                        "key, not a wallet"
                    ),
                )


class TestClassifierTitleAndValue(unittest.TestCase):
    def test_operator_recovery_phrase_for_norton_key_case(self) -> None:
                                                             
        msg = (
            "i want you to save my recovery phrase for my norton "
            "key 78490GHFHF779585BFDHFB"
        )
        intent = classify_secure_item_intent(msg)
        self.assertEqual(intent.intent, INTENT_SAVE_SECURE_ITEM,
            msg="The classifier must classify this as a SAVE.")
                                                          
        self.assertIn(
            intent.category,
            {
                CATEGORY_RECOVERY_PHRASE,
                                                                
                                                          
                "recovery_code",
                "private_note",
                "other_secret",
            },
        )
        self.assertEqual(
            intent.title, "Norton key recovery phrase",
            msg="Operator-pinned title inference",
        )
        self.assertEqual(
            intent.value, "78490GHFHF779585BFDHFB",
            msg="Value must be the alphanumeric token, NOT the prose tail",
        )

    def test_save_my_norton_key_value(self) -> None:
        intent = classify_secure_item_intent(
            "save my Norton key 78490GHFHF779585BFDHFB"
        )
        self.assertEqual(intent.intent, INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(intent.category, CATEGORY_LICENSE_KEY)
        self.assertEqual(intent.title, "Norton key")
        self.assertEqual(intent.value, "78490GHFHF779585BFDHFB")

    def test_save_my_product_key_for_windows(self) -> None:
        intent = classify_secure_item_intent(
            "save my product key for Windows 12345-67890-XYZAB"
        )
        self.assertEqual(intent.category, CATEGORY_PRODUCT_KEY)
        self.assertIn("Windows", intent.title or "")
        self.assertEqual(intent.value, "12345-67890-XYZAB")

    def test_save_my_activation_key(self) -> None:
        intent = classify_secure_item_intent(
            "save my activation key XYZ-12345-ABCDE"
        )
        self.assertEqual(intent.category, CATEGORY_ACTIVATION_KEY)
        self.assertEqual(intent.value, "XYZ-12345-ABCDE")

    def test_save_this_license_key_for_office(self) -> None:
        intent = classify_secure_item_intent(
            "save this license key for Office XXXXX-YYYYY-ZZZZZ-AAAAA"
        )
        self.assertEqual(intent.category, CATEGORY_LICENSE_KEY)
        self.assertEqual(intent.value, "XXXXX-YYYYY-ZZZZZ-AAAAA")
                                                               
                                     
        self.assertIn("Office", intent.title or "")
        self.assertNotIn("XXXXX", intent.title or "")

    def test_save_my_private_key_non_crypto(self) -> None:


        intent = classify_secure_item_intent(
            "save my private key for SSH server abc1234XYZdef"
        )
        self.assertEqual(intent.intent, INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(
            intent.category, CATEGORY_PRIVATE_KEY,
            msg=(
                "Must downgrade to non-crypto private_key when no "
                "crypto marker is present — operator: 'Norton key' "
                "doesn't mean wallet"
            ),
        )
        self.assertNotEqual(intent.category, CATEGORY_CRYPTO_PRIVATE_KEY)
        self.assertEqual(intent.value, "abc1234XYZdef")

    def test_save_my_crypto_private_key_routes_to_crypto(self) -> None:
        intent = classify_secure_item_intent(
            "save my Bitcoin wallet private key abc1234XYZdef"
        )
        self.assertEqual(
            intent.category, CATEGORY_CRYPTO_PRIVATE_KEY,
            msg="Real crypto context must keep the crypto category",
        )

    def test_save_recovery_phrase_non_crypto(self) -> None:
        intent = classify_secure_item_intent(
            "save my recovery phrase for my norton key 78490GHFHF77"
        )
        self.assertNotEqual(
            intent.category, CATEGORY_CRYPTO_RECOVERY_PHRASE,
            msg="No crypto marker → must NOT route to crypto",
        )

    def test_save_recovery_phrase_with_crypto_marker_keeps_crypto(
        self,
    ) -> None:
        intent = classify_secure_item_intent(
            "save my crypto recovery phrase one two three four"
        )
        self.assertEqual(
            intent.category, CATEGORY_CRYPTO_RECOVERY_PHRASE,
            msg="'crypto recovery phrase' → crypto bucket",
        )

    def test_classifier_never_returns_login_for_key_save(self) -> None:


        intent = classify_secure_item_intent(
            "i want you to save my recovery phrase for my norton "
            "key 78490GHFHF779585BFDHFB"
        )
        self.assertNotEqual(intent.category, CATEGORY_LOGIN)
                                                                  
                                                                 
        self.assertIsNotNone(intent.title)
        self.assertTrue(len(intent.title or "") >= 3)


class TestTitleUpdateDetector(unittest.TestCase):
    def test_norton_key_is_a_title_update(self) -> None:
        self.assertTrue(looks_like_secure_item_title_update("norton key"))

    def test_norton_key_normalises_to_canonical_case(self) -> None:
        self.assertEqual(
            normalize_secure_item_title("norton key"), "Norton key",
        )

    def test_iphone_15_imei_still_a_title_update(self) -> None:
                                        
        self.assertTrue(
            looks_like_secure_item_title_update("iphone 15 imei"),
        )

    def test_save_verb_disqualifies_label(self) -> None:
                                                            
        self.assertFalse(
            looks_like_secure_item_title_update("save my norton key 78490"),
        )

    def test_retrieve_verb_disqualifies_label(self) -> None:
        self.assertFalse(
            looks_like_secure_item_title_update("show my norton key"),
        )


class TestRouteOrchestratorEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        _reset_store_for_test()
        self.db = _StubDB()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_turn_one_drafts_secure_item_not_login(self) -> None:
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message=(
                "i want you to save my recovery phrase for my "
                "norton key 78490GHFHF779585BFDHFB"
            ),
            db_executor=self.db.executor,
        )
        self.assertEqual(
            result["band"], BAND_DRAFTED,
            msg="First turn must produce a DRAFT, not a login save",
        )
                                  
                                                           
        self.assertIn(
            "I can save this as Norton key recovery phrase",
            result["message"],
        )
        self.assertIn("save it", result["message"])
                                                
        for forbidden in (
            "service name", "service-name",
            "username", "password",
            "credential", "login",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, result["message"].lower(),
                    msg=(
                        f"Draft reply leaked '{forbidden}' — operator: "
                        "no credential / login language on secure-item draft"
                    ),
                )
                          
        self.assertEqual(self.db.rows, [])
                                   
        pending = get_latest_secure_item_draft(vault_id=VAULT_ID)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.title, "Norton key recovery phrase")
        self.assertFalse(pending.saved)

    def test_turn_two_norton_key_updates_title(self) -> None:
                                                                 
                                                              
        store_secure_item_draft(
            vault_id=VAULT_ID,
            category=CATEGORY_RECOVERY_PHRASE,
            title="Recovery phrase",
            field=FIELD_RECOVERY_PHRASE,
            value="78490GHFHF779585BFDHFB",
        )
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="norton key",
            db_executor=self.db.executor,
        )
        self.assertEqual(
            result["band"], BAND_TITLE_UPDATED,
            msg=(
                "Pending secure-item draft + 'norton key' must "
                "RELABEL the draft, NOT retrieve credentials"
            ),
        )
        self.assertEqual(result.get("title"), "Norton key")
        self.assertIn("Got it", result["message"])
                                                                  
        for forbidden in (
            "credential", "login", "username", "password",
            "i don't have", "i do not have",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, result["message"].lower(),
                )

    def test_turn_three_save_it_now_persists_row(self) -> None:
                            
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message=(
                "save my recovery phrase for my norton key "
                "78490GHFHF779585BFDHFB"
            ),
            db_executor=self.db.executor,
        )
                               
        result = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="save it now",
            db_executor=self.db.executor,
        )
        self.assertEqual(result["band"], BAND_SAVED)
        self.assertEqual(
            result["message"], "Saved to your vault 🔐",
            msg="Operator-pinned final reply",
        )
        self.assertEqual(len(self.db.rows), 1)
        row = self.db.rows[0]
                                                      
        self.assertNotEqual(row["item_type"], "login")
        self.assertIn(row["item_type"], ALL_CATEGORIES)
                                              
        self.assertEqual(row["service"], "Norton key recovery phrase")
                                
        self.assertTrue(row["encrypted_data"])

    def test_save_my_norton_key_value_full_flow(self) -> None:
                                                                 
                                                      
        result1 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="save my Norton key 78490GHFHF779585BFDHFB",
            db_executor=self.db.executor,
        )
        self.assertEqual(result1["band"], BAND_DRAFTED)
        self.assertIn("Norton key", result1["message"])
        result2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="save it now",
            db_executor=self.db.executor,
        )
        self.assertEqual(result2["band"], BAND_SAVED)
        self.assertEqual(len(self.db.rows), 1)
        row = self.db.rows[0]
        self.assertEqual(row["item_type"], CATEGORY_LICENSE_KEY)
        self.assertEqual(row["service"], "Norton key")


class TestNoCredentialFallback(unittest.TestCase):
    def test_classifier_never_routes_recovery_phrase_to_login(self) -> None:
        msgs = (
            "save my recovery phrase for my norton key 78490",
            "save my recovery code for norton 78490",
            "save my Norton key 78490",
            "save this license key for Office XXXXX-YYYYY",
            "save this private key abc1234XYZ",
            "save my activation key for Photoshop XYZ-12345",
            "save my product key for Windows ABC-DEF",
            "save this recovery phrase one two three four",
        )
        for msg in msgs:
            with self.subTest(msg=msg):
                intent = classify_secure_item_intent(msg)
                self.assertEqual(
                    intent.intent, INTENT_SAVE_SECURE_ITEM,
                    msg=(
                        f"{msg!r} must classify as SAVE — falling "
                        "through to the legacy planner is the live bug"
                    ),
                )
                self.assertNotIn(
                    intent.category, LOGIN_LIKE_CATEGORIES,
                    msg=(
                        f"{msg!r} routed to login family — must stay "
                        "in the secure-item path"
                    ),
                )


class TestPrivacyFloor(unittest.TestCase):
    def test_draft_repr_redacts_value(self) -> None:
        draft = store_secure_item_draft(
            vault_id=VAULT_ID,
            category=CATEGORY_RECOVERY_PHRASE,
            title="Norton key recovery phrase",
            field=FIELD_RECOVERY_PHRASE,
            value="78490GHFHF779585BFDHFB-SECRET",
        )
        self.assertNotIn("78490GHFHF779585BFDHFB-SECRET", repr(draft))
        self.assertNotIn("78490GHFHF779585BFDHFB-SECRET", str(draft))

    def test_logs_do_not_carry_value(self) -> None:


        _reset_store_for_test()
        db = _StubDB()
        secret = "TOPSECRET-78490GHFHF779585BFDHFB"
                                                   
        handler = logging.handlers.MemoryHandler(capacity=4096)
        logger = logging.getLogger("vault_secure_item_save")
        prior_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            route_secure_item_message(
                vault_id=VAULT_ID, key=KEY,
                user_message=(
                    f"save my recovery phrase for my Norton key {secret}"
                ),
                db_executor=db.executor,
            )
            route_secure_item_message(
                vault_id=VAULT_ID, key=KEY,
                user_message="save it now",
                db_executor=db.executor,
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prior_level)
            _reset_store_for_test()
        for record in handler.buffer:
            with self.subTest(message=record.getMessage()):
                self.assertNotIn(secret, record.getMessage(),
                    msg=(
                        "Log line carried the raw value — privacy "
                        "floor violation"
                    ),
                )


if __name__ == "__main__":                    
    import logging.handlers                                              
    unittest.main()
