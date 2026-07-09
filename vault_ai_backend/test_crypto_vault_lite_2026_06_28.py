

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


_USDT_TRC20_ADDRESS = "TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY"
_ETH_ADDRESS        = "0x1234567890abcdef1234567890abcdef12345678"
_BTC_ADDRESS        = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_SEED_PHRASE        = (
    "mountain river apple thunder sapphire orchid cinnamon "
    "valley horizon crystal velvet tiger"
)
_PRIVATE_KEY        = "L1aW4aubDFB7yfras2S1mN6bMcSPVeeHJYaBPiBgVcZGu8ELRiE9"
_RECOVERY_PHRASE    = (
    "alpha bravo charlie delta echo foxtrot golf hotel "
    "india juliet kilo lima"
)


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


class TestCryptoTaxonomy(unittest.TestCase):
    def test_crypto_categories_present(self):
        for cat in (
            t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            t.CATEGORY_CRYPTO_SEED_PHRASE,
            t.CATEGORY_CRYPTO_PRIVATE_KEY,
            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            t.CATEGORY_CRYPTO_NOTE,
            t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
            t.CATEGORY_CRYPTO_EXCHANGE_NOTE,
            t.CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
        ):
            with self.subTest(cat=cat):
                self.assertIn(cat, t.ALL_CATEGORIES)
                self.assertIn(cat, t.CRYPTO_CATEGORIES)
                self.assertIn(cat, t.NON_LOGIN_CATEGORIES)

    def test_crypto_warn_categories_subset(self):
        self.assertIn(
            t.CATEGORY_CRYPTO_SEED_PHRASE, t.CRYPTO_WARN_CATEGORIES,
        )
        self.assertIn(
            t.CATEGORY_CRYPTO_PRIVATE_KEY, t.CRYPTO_WARN_CATEGORIES,
        )
        self.assertIn(
            t.CATEGORY_CRYPTO_RECOVERY_PHRASE, t.CRYPTO_WARN_CATEGORIES,
        )
                                                                  
        self.assertNotIn(
            t.CATEGORY_CRYPTO_WALLET_ADDRESS, t.CRYPTO_WARN_CATEGORIES,
        )
        self.assertNotIn(
            t.CATEGORY_CRYPTO_NOTE, t.CRYPTO_WARN_CATEGORIES,
        )

    def test_crypto_hidden_categories_skip_wallet_address(self):
                                                              
                                                         
        self.assertNotIn(
            t.CATEGORY_CRYPTO_WALLET_ADDRESS, t.CRYPTO_HIDDEN_CATEGORIES,
        )
                                                                   
                                                
        for cat in (
            t.CATEGORY_CRYPTO_SEED_PHRASE,
            t.CATEGORY_CRYPTO_PRIVATE_KEY,
            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
            t.CATEGORY_CRYPTO_EXCHANGE_NOTE,
        ):
            with self.subTest(cat=cat):
                self.assertIn(cat, t.CRYPTO_HIDDEN_CATEGORIES)

    def test_wallet_address_mask_first6_last4(self):
                                                          
        self.assertEqual(
            t.mask_wallet_address(_USDT_TRC20_ADDRESS),
            "TQx2P5…Y7Lr"[:6] + "…" + _USDT_TRC20_ADDRESS[-4:],
        )
                              
        masked = t.mask_wallet_address(_USDT_TRC20_ADDRESS)
        self.assertEqual(masked[:6], _USDT_TRC20_ADDRESS[:6])
        self.assertEqual(masked[-4:], _USDT_TRC20_ADDRESS[-4:])
        self.assertIn("…", masked)
                           
        self.assertEqual(
            t.mask_wallet_address(_ETH_ADDRESS),
            _ETH_ADDRESS[:6] + "…" + _ETH_ADDRESS[-4:],
        )

    def test_short_pseudo_address_collapses_to_tail(self):
        self.assertEqual(t.mask_wallet_address(""), "")
        self.assertTrue(
            t.mask_wallet_address("abc").startswith("3-char"),
        )

    def test_network_labels_pinned(self):
        for lbl in (
            "BTC", "ETH",
            "USDT TRC20", "USDT ERC20",
            "SOL", "BNB",
        ):
            with self.subTest(lbl=lbl):
                self.assertIn(lbl, t.ALL_NETWORK_LABELS)


class TestMaskedPreviewCrypto(unittest.TestCase):
    def test_wallet_address_preview_is_first6_last4(self):
                                 
        preview = t.masked_preview(
            category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            title="USDT TRC20 wallet",
            fields={
                "wallet_address": _USDT_TRC20_ADDRESS,
                "network":        "USDT TRC20",
            },
        )
        mask = preview["wallet_address_mask"]
        self.assertEqual(mask[:6], _USDT_TRC20_ADDRESS[:6])
        self.assertEqual(mask[-4:], _USDT_TRC20_ADDRESS[-4:])
        self.assertEqual(preview["network"], "USDT TRC20")
                                            
        self.assertNotIn(_USDT_TRC20_ADDRESS, json.dumps(preview))

    def test_seed_phrase_preview_is_hidden(self):
                                                 
        preview = t.masked_preview(
            category=t.CATEGORY_CRYPTO_SEED_PHRASE,
            title="Seed phrase",
            fields={"seed_phrase": _SEED_PHRASE},
        )
        self.assertEqual(preview["seed_phrase_mask"], "•••••• hidden")
        self.assertTrue(preview["has_seed_phrase"])
        self.assertNotIn(_SEED_PHRASE, json.dumps(preview))
                                              
        for word in _SEED_PHRASE.split():
            with self.subTest(word=word):
                self.assertNotIn(word, json.dumps(preview))

    def test_private_key_preview_is_hidden(self):
        preview = t.masked_preview(
            category=t.CATEGORY_CRYPTO_PRIVATE_KEY,
            title="Private key",
            fields={"private_key": _PRIVATE_KEY},
        )
        self.assertEqual(preview["private_key_mask"], "•••••• hidden")
        self.assertNotIn(_PRIVATE_KEY, json.dumps(preview))

    def test_recovery_phrase_preview_is_hidden(self):
        preview = t.masked_preview(
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            title="Recovery phrase",
            fields={"recovery_phrase": _RECOVERY_PHRASE},
        )
        self.assertEqual(preview["recovery_phrase_mask"], "•••••• hidden")
        self.assertNotIn(_RECOVERY_PHRASE, json.dumps(preview))

    def test_transaction_and_exchange_notes_hidden(self):
        preview = t.masked_preview(
            category=t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
            title="Transaction note",
            fields={"transaction_note": "Sent 1.5 ETH to Alice for invoice 17"},
        )
        self.assertEqual(
            preview["transaction_note_mask"], "•••••• hidden",
        )
        preview2 = t.masked_preview(
            category=t.CATEGORY_CRYPTO_EXCHANGE_NOTE,
            title="Binance",
            fields={"exchange_note": "API key XYZ used for sub-account 7"},
        )
        self.assertEqual(
            preview2["exchange_note_mask"], "•••••• hidden",
        )


class TestCryptoChatIntent(unittest.TestCase):
    def test_usdt_trc20_wallet_address_classifies(self):
        out = ci.classify_secure_item_intent(
            f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_WALLET_ADDRESS)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS)
        self.assertEqual(out.network, "USDT TRC20")
        self.assertEqual(out.title, "USDT TRC20 wallet")
        self.assertEqual(out.value, _USDT_TRC20_ADDRESS)

    def test_eth_wallet_address_classifies(self):
        out = ci.classify_secure_item_intent(
            f"save my ETH wallet address {_ETH_ADDRESS}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_WALLET_ADDRESS)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS)
        self.assertEqual(out.network, "ETH")
        self.assertIn(_ETH_ADDRESS, out.value or "")

    def test_seed_phrase_classifies_with_value(self):
        out = ci.classify_secure_item_intent(
            f"save my Bitcoin seed phrase {_SEED_PHRASE}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_SEED_PHRASE)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_SEED_PHRASE)
        self.assertEqual(out.network, "BTC")
        self.assertIn("mountain", out.value or "")

    def test_private_key_classifies(self):
                                                                
                                                                 
        out = ci.classify_secure_item_intent(
            f"save my crypto wallet private key {_PRIVATE_KEY}",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_PRIVATE_KEY)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_PRIVATE_KEY)

    def test_crypto_note_classifies(self):
        out = ci.classify_secure_item_intent(
            "save this crypto note: bought BTC at 50k average",
        )
        self.assertEqual(out.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_CRYPTO_NOTE)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_NOTE)
        self.assertIn("bought", (out.value or "").lower())

    def test_show_my_crypto_wallets_routes_to_retrieve(self):
        out = ci.classify_secure_item_intent("show my crypto wallets")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )

    def test_show_my_usdt_trc20_address_filters_by_network(self):
        out = ci.classify_secure_item_intent(
            "show my USDT TRC20 address",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.field, ci.FIELD_WALLET_ADDRESS)
        self.assertEqual(out.network, "USDT TRC20")

    def test_show_my_seed_phrases_routes_to_seed_category(self):
        out = ci.classify_secure_item_intent("show my seed phrases")
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(out.category, t.CATEGORY_CRYPTO_SEED_PHRASE)

    def test_network_detector_pins_canonical_labels(self):
        cases = {
            "save my BTC address xyz":                "BTC",
            "save my ETH wallet xyz":                 "ETH",
            "save my USDT TRC20 wallet xyz":          "USDT TRC20",
            "save my USDT ERC20 wallet xyz":          "USDT ERC20",
            "save my SOL wallet xyz":                 "SOL",
            "save my BNB wallet xyz":                 "BNB",
        }
        for msg, expected in cases.items():
            with self.subTest(msg=msg):
                self.assertEqual(
                    ci.detect_network_label(msg), expected,
                )


class TestTierGate(unittest.TestCase):


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

    def test_free_user_cannot_save_crypto_wallet(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
                      
        self.assertEqual(len(self._rows), 0)
                          
        self.assertIsNone(
            draft_store.get_latest_secure_item_draft(vault_id="v1"),
        )
                                                                 
                                                                   
        self.assertIn("available with upgrade", result["message"])
        self.assertNotIn("you can send", result["message"].lower())
        self.assertNotIn("you can receive", result["message"].lower())
        self.assertNotIn("login", result["message"].lower())

    def test_basic_user_cannot_save_seed_phrase(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my Bitcoin seed phrase {_SEED_PHRASE}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_BASIC,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
        self.assertEqual(len(self._rows), 0)
                                                       
        for word in _SEED_PHRASE.split():
            with self.subTest(word=word):
                self.assertNotIn(word, result["message"])

    def test_missing_tier_is_treated_as_free(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)

    def test_non_crypto_save_unaffected_by_tier_gate(self):
                                                          
                                                      
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save my imei 352099001761481",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)


class TestUpgradedCryptoSaveAndRetrieve(unittest.TestCase):


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

    def _stage_and_confirm(self, *, message: str):
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )

    def test_upgraded_user_saves_wallet_address_as_encrypted_row(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
                                                              
                                                           
        msg = result["message"]
        self.assertIn("save it", msg)
        self.assertNotIn("login", msg.lower())
        self.assertNotIn("send", msg.lower())
                  
        result2 = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result2["band"], vsi.BAND_SAVED)
                                                         
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "crypto_wallet_address")
                                      
        self.assertNotIn(_USDT_TRC20_ADDRESS, row["encrypted_data"])
                                     
        plain = _fake_decrypt(row["encrypted_data"], self.key)
        decoded = json.loads(plain)
        self.assertEqual(
            decoded["fields"]["wallet_address"], _USDT_TRC20_ADDRESS,
        )
        self.assertEqual(decoded["fields"]["network"], "USDT TRC20")

    def test_upgraded_user_saves_crypto_note(self):
        self._stage_and_confirm(
            message="save this crypto note: bought BTC at 50k average",
        )
        self.assertEqual(self._rows[0]["item_type"], "crypto_note")

    def test_show_my_crypto_wallets_returns_crypto_cards(self):
                                  
        self._stage_and_confirm(
            message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
        )
        self._stage_and_confirm(
            message=f"save my ETH wallet address {_ETH_ADDRESS}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my crypto wallets",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        types = [c["type"] for c in envelope["items"]]
        for t_ in types:
            with self.subTest(type=t_):
                self.assertEqual(t_, "crypto_wallet_address")
                self.assertNotEqual(t_, "login")
                                     
        for card in envelope["items"]:
            self.assertIn(
                "wallet_address_mask", card["preview"],
                msg="wallet address preview must be masked by default",
            )
            self.assertNotIn("wallet_address", card["preview"])

    def test_show_my_usdt_trc20_address_filters_by_network(self):
        self._stage_and_confirm(
            message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
        )
        self._stage_and_confirm(
            message=f"save my ETH wallet address {_ETH_ADDRESS}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my USDT TRC20 address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        card = envelope["items"][0]
        self.assertEqual(card["preview"]["network"], "USDT TRC20")


class TestSeedKeyWarnFlow(unittest.TestCase):


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

    def test_seed_phrase_save_returns_warn_drafted_band(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my Bitcoin seed phrase {_SEED_PHRASE}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_WARN_DRAFTED)
        msg = result["message"]
                                            
        for fragment in (
            "extremely sensitive",
            "Anyone with this phrase or key can control the wallet",
            "Store it only if you understand the risk",
            "save it now",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, msg)
                          
        self.assertEqual(len(self._rows), 0)
                                                      
        result2 = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result2["band"], vsi.BAND_SAVED)
        self.assertEqual(self._rows[0]["item_type"], "crypto_seed_phrase")

    def test_private_key_save_warns_first(self):
                                                                
                                                                     
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my Bitcoin wallet private key {_PRIVATE_KEY}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_WARN_DRAFTED)
        self.assertIn("extremely sensitive", result["message"])
                                                               
        self.assertNotIn(_PRIVATE_KEY, result["message"])

    def test_wallet_address_save_does_NOT_warn(self):
                                                               
                       
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
        self.assertNotEqual(result["band"], vsi.BAND_WARN_DRAFTED)
        self.assertNotIn("extremely sensitive", result["message"])


class TestCryptoReveal(unittest.TestCase):


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

    def _stage(self, message: str):
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it now",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )

    def test_specific_wallet_query_auto_reveals(self):
                                                                  
                                                                   
        self._stage(
            f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my USDT TRC20 address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        envelope = json.loads(result["envelope"])
                                            
        self.assertTrue(envelope["reveal"])
        card = envelope["items"][0]
        self.assertEqual(
            card["preview"]["wallet_address"], _USDT_TRC20_ADDRESS,
        )

    def test_show_the_full_wallet_address_reveals(self):
        self._stage(
            f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show the full wallet address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        envelope = json.loads(result["envelope"])
        self.assertTrue(envelope["reveal"])
        card = envelope["items"][0]
        self.assertEqual(
            card["preview"]["wallet_address"], _USDT_TRC20_ADDRESS,
        )

    def test_reveal_my_seed_phrase_surfaces_full_value(self):
        self._stage(
            f"save my Bitcoin seed phrase {_SEED_PHRASE}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="reveal my seed phrase",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        envelope = json.loads(result["envelope"])
        self.assertTrue(envelope["reveal"])
        card = envelope["items"][0]
        self.assertEqual(card["preview"]["seed_phrase"], _SEED_PHRASE)


class TestCryptoPrivacy(unittest.TestCase):


    def test_module_logs_carry_no_crypto_values(self):
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
                f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
                "save it now",
                f"save my Bitcoin seed phrase {_SEED_PHRASE}",
                "save it now",
                f"save my private key {_PRIVATE_KEY}",
                "save it now",
                "show my crypto wallets",
                "show my seed phrases",
                "show the full wallet address",
                "reveal my seed phrase",
            ):
                vsi.route_secure_item_message(
                    vault_id="v1", key=key, user_message=msg,
                    db_executor=exec_, db_reader=reader,
                    user_tier=vsi.TIER_UPGRADED,
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
            _USDT_TRC20_ADDRESS, _ETH_ADDRESS, _BTC_ADDRESS,
            _SEED_PHRASE, _PRIVATE_KEY, _RECOVERY_PHRASE,
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)
                                                           
        for word in _SEED_PHRASE.split():
            with self.subTest(word=word):
                self.assertNotIn(word, joined)


class TestNoCryptoLibrariesOrTransactionCode(unittest.TestCase):


    _MODULES = (
        "vault_saved_item_taxonomy.py",
        "vault_saved_item_chat_intent.py",
        "vault_secure_item_draft.py",
        "vault_secure_item_save.py",
        "vault_secure_item_card_envelope.py",
        "vault_crypto_locked_card.py",
        "vault_crypto_locked_chat.py",
    )

    _FORBIDDEN_IMPORTS = (
        "import web3",
        "from web3",
        "import bitcoin",
        "from bitcoin",
        "import eth_account",
        "from eth_account",
        "import ecdsa",
        "from ecdsa",
        "import secp256k1",
        "from secp256k1",
        "import coincurve",
        "from coincurve",
        "import solana",
        "from solana",
        "import ethers",
        "from ethers",
    )

    _FORBIDDEN_FUNCTION_NAMES = (
        "sign_transaction", "broadcast_transaction",
        "submit_transaction", "send_transaction",
        "create_wallet", "generate_wallet", "generate_seed_phrase",
        "generate_private_key", "derive_address",
        "derive_public_key",
        "post_to_blockchain", "post_to_network",
        "rpc_node", "rpc_endpoint", "rpc_url",
        "ethereum_rpc", "bitcoin_rpc", "solana_rpc",
        "send_btc", "send_eth", "send_sol",
        "swap_crypto", "exchange_crypto",
        "buy_crypto", "sell_crypto", "trade_crypto",
    )

    def _read(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_no_signing_or_blockchain_imports(self):
        for mod in self._MODULES:
            src = self._read(mod)
            for needle in self._FORBIDDEN_IMPORTS:
                with self.subTest(mod=mod, needle=needle):
                    self.assertNotIn(
                        needle, src,
                        msg=f"{mod} must NEVER carry `{needle}`",
                    )

    def test_no_transaction_or_wallet_gen_function_names(self):
        for mod in self._MODULES:
            src = self._read(mod)
            for needle in self._FORBIDDEN_FUNCTION_NAMES:
                with self.subTest(mod=mod, needle=needle):
                    self.assertNotIn(
                        needle, src,
                        msg=f"{mod} must NEVER carry `{needle}`",
                    )


class TestAntiClaimGuardrails(unittest.TestCase):
    _FORBIDDEN = (
        "you can send",
        "you can receive",
        "you can buy",
        "you can sell",
        "you can trade",
        "you can swap",
        "you can exchange",
        "guaranteed",
        "profit",
        "high return",
        "investment return",
        "make money",
        "to the moon",
        "vaultai sells",
        "vaultai is an exchange",
        "we are an exchange",
    )

    def test_tier_required_reply_carries_no_forbidden_claims(self):
                                                                
                                                                     
        result = vsi.route_secure_item_message(
            vault_id="v1", key=b"\x07" * 32,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20_ADDRESS}",
            db_executor=lambda *_: None,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
        body = result["message"].lower()
        for needle in self._FORBIDDEN:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, body)

    def test_warn_reply_carries_no_forbidden_claims(self):
        key = b"\x07" * 32
        patches = _patch_crypto()
        for p in patches:
            p.start()
        draft_store._reset_store_for_test()
        try:
            result = vsi.route_secure_item_message(
                vault_id="v1", key=key,
                user_message=f"save my Bitcoin seed phrase {_SEED_PHRASE}",
                db_executor=lambda *_: None,
                db_reader=lambda v, c: [],
                user_tier=vsi.TIER_UPGRADED,
            )
            self.assertEqual(result["band"], vsi.BAND_WARN_DRAFTED)
            body = result["message"].lower()
            for needle in self._FORBIDDEN:
                with self.subTest(needle=needle):
                    self.assertNotIn(needle, body)
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass
            draft_store._reset_store_for_test()


if __name__ == "__main__":                    
    unittest.main()
