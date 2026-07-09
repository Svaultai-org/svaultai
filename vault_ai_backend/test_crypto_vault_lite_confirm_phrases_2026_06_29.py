

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


_BTC = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_USDT_TRC20 = "TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY"


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


class TestTierGateOnConfirm(unittest.TestCase):

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

    def test_free_user_save_btc_wallet_is_blocked(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my BTC wallet {_BTC}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
        self.assertEqual(len(self._rows), 0)
                                                     
        self.assertNotIn(_BTC, result["message"])

    def test_basic_user_save_wallet_is_blocked(self):
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=f"save my USDT TRC20 address {_USDT_TRC20}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_BASIC,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
                                
        self.assertIsNone(
            draft_store.get_latest_secure_item_draft(vault_id="v1"),
        )


_CONFIRM_PHRASES = (
    "save it",
    "save it now",
    "save",
    "yes",
    "yeah save it",
    "go ahead",
    "confirm",
    "save this",
)


class TestUpgradedConfirmPhrases(unittest.TestCase):

    def setUp(self):
        self.key = b"\x07" * 32
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

    def _fresh_writer(self) -> tuple[list, callable]:
        rows: list[dict] = []
        def exec_(action, payload):
            rows.append(payload)
        return rows, exec_

    def test_each_confirm_phrase_flushes_the_pending_wallet_draft(self):
        for phrase in _CONFIRM_PHRASES:
            with self.subTest(phrase=phrase):
                draft_store._reset_store_for_test()
                rows, exec_ = self._fresh_writer()
                                  
                drafted = vsi.route_secure_item_message(
                    vault_id="v1", key=self.key,
                    user_message=(
                        f"save my BTC wallet {_BTC}"
                    ),
                    db_executor=exec_,
                    db_reader=lambda v, c: [],
                    user_tier=vsi.TIER_UPGRADED,
                )
                self.assertEqual(drafted["band"], vsi.BAND_DRAFTED)
                self.assertEqual(len(rows), 0)
                                           
                saved = vsi.route_secure_item_message(
                    vault_id="v1", key=self.key,
                    user_message=phrase,
                    db_executor=exec_,
                    db_reader=lambda v, c: [],
                    user_tier=vsi.TIER_UPGRADED,
                )
                self.assertEqual(
                    saved["band"], vsi.BAND_SAVED,
                    msg=f"phrase {phrase!r} must confirm wallet draft",
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    rows[0]["item_type"], "crypto_wallet_address",
                )
                                                                
                decoded = json.loads(
                    _fake_decrypt(rows[0]["encrypted_data"], self.key),
                )
                self.assertEqual(
                    decoded["fields"]["wallet_address"], _BTC,
                )


class TestRetrievalScoping(unittest.TestCase):

    def setUp(self):
        self.key = b"\x07" * 32
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()
        self._rows: list[dict] = []

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

    def _stage_and_save(self, message: str):
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="save it",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )

    def test_show_my_btc_wallet_returns_only_wallet_addresses(self):
                                                    
        self._stage_and_save(
            f"save my BTC wallet {_BTC}",
        )
                     
        result = vsi.route_secure_item_message(
            vault_id="v1", key=self.key,
            user_message="show my BTC wallet",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        for card in envelope["items"]:
            with self.subTest(type=card["type"]):
                self.assertEqual(card["type"], "crypto_wallet_address")


class TestPrivacyFloorOnConfirm(unittest.TestCase):

    def test_confirm_phrase_save_does_not_leak_btc_address(self):
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
            "vault_pending_draft_confirm",
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
                f"save my BTC wallet {_BTC}",
                "save it",
                f"save my USDT TRC20 address {_USDT_TRC20}",
                "yeah save it",
            ):
                result = vsi.route_secure_item_message(
                    vault_id="v1", key=key, user_message=msg,
                    db_executor=exec_,
                    db_reader=lambda v, c: [],
                    user_tier=vsi.TIER_UPGRADED,
                )
                                                            
                self.assertNotIn(_BTC, result.get("message", ""))
                self.assertNotIn(_USDT_TRC20, result.get("message", ""))
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
        self.assertNotIn(_BTC, joined)
        self.assertNotIn(_USDT_TRC20, joined)


class TestCryptoTaxonomyClosedSet(unittest.TestCase):

    def test_all_crypto_categories_register(self):
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

    def test_supported_networks_present(self):
        for lbl in (
            "BTC", "ETH",
            "USDT TRC20", "USDT ERC20", "USDC ERC20",
            "SOL", "BNB",
        ):
            with self.subTest(lbl=lbl):
                self.assertIn(lbl, t.ALL_NETWORK_LABELS)


if __name__ == "__main__":                    
    unittest.main()
