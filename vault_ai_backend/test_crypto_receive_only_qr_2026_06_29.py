

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


_BTC = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_USDT_TRC20 = "TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY"
_XMR = (
    "8AaWDoNomZ5GtP6Wn34CpEh4i7p9oVUaeRkTr2VtcqK"
    "L5d9bF8U6Q4xz1vXmAZbWqYTKpcRfPjN3eGsHmDnLs"
)
_SEED = (
    "mountain river apple thunder sapphire orchid cinnamon "
    "valley horizon crystal velvet tiger"
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


class TestReceiveIntentDetector(unittest.TestCase):

    def test_operator_phrases_trigger_receive_intent(self):
        for msg in (
            "show my bitcoin receive address",
            "show QR for my BTC wallet",
            "receive USDT TRC20",
            "show my monero receive address",
            "show QR for my ETH wallet",
            "deposit address",
            "qr code for my wallet",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(
                    ci._has_receive_intent(msg),
                    msg=f"receive intent must fire for {msg!r}",
                )

    def test_non_receive_messages_do_not_trigger(self):
        for msg in (
            "show my BTC wallet",
            "show my crypto wallets",
            "show my Instagram login",
            "save my BTC wallet bc1q...",
            "",
            "   ",
            None,
        ):
            with self.subTest(msg=msg):
                self.assertFalse(
                    ci._has_receive_intent(msg),
                    msg=f"receive intent must NOT fire for {msg!r}",
                )


class TestClassifierReceiveFlag(unittest.TestCase):

    def test_show_bitcoin_receive_address_flips_flag(self):
        out = ci.classify_secure_item_intent(
            "show my bitcoin receive address",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertEqual(out.network, "BTC")
        self.assertTrue(out.receive_intent)

    def test_show_qr_for_btc_wallet_flips_flag(self):
        out = ci.classify_secure_item_intent(
            "show QR for my BTC wallet",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertTrue(out.receive_intent)

    def test_show_monero_receive_address_flips_flag(self):
        out = ci.classify_secure_item_intent(
            "show my monero receive address",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
                                             
        self.assertEqual(out.network, "XMR")
        self.assertTrue(out.receive_intent)

    def test_show_my_btc_wallet_without_receive_does_not_flip(self):
                                                               
                                                              
        out = ci.classify_secure_item_intent(
            "show my BTC wallet",
        )
        self.assertEqual(out.intent, ci.INTENT_RETRIEVE_SECURE_ITEM)
        self.assertEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertFalse(out.receive_intent)

    def test_seed_phrase_query_with_qr_word_does_NOT_flip(self):
                                                              
                                                               
        out = ci.classify_secure_item_intent(
            "show QR for my seed phrase",
        )
                                                               
                                                               
        self.assertNotEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertFalse(out.receive_intent)

    def test_private_key_query_with_receive_word_does_NOT_flip(self):
        out = ci.classify_secure_item_intent(
            "show me my crypto wallet private key receive",
        )
                                                                     
        self.assertNotEqual(
            out.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertFalse(out.receive_intent)


class TestEnvelopeReceiveFlag(unittest.TestCase):

    def _wallet_card(self, *, item_id="r1", address=_BTC, network="BTC"):
        return env.build_secure_item_card(
            item_id=item_id,
            category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            title=f"{network} wallet",
            preview=t.revealed_preview(
                category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
                title=f"{network} wallet",
                fields={
                    "wallet_address": address,
                    "network":        network,
                },
            ),
            reveal=True,
        )

    def _seed_card(self):
        return env.build_secure_item_card(
            item_id="seed-1",
            category=t.CATEGORY_CRYPTO_SEED_PHRASE,
            title="Bitcoin seed phrase",
            preview=t.revealed_preview(
                category=t.CATEGORY_CRYPTO_SEED_PHRASE,
                title="Bitcoin seed phrase",
                fields={"seed_phrase": _SEED},
            ),
            reveal=True,
        )

    def test_receive_flag_set_for_single_wallet_reveal(self):
        envelope = json.loads(env.build_secure_item_results_envelope(
            items=[self._wallet_card()],
            category_filter=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            reveal=True,
            receive_intent=True,
        ))
        self.assertTrue(envelope["receive_intent"])

    def test_receive_flag_dropped_when_not_revealed(self):
                                                                
                                                        
        envelope = json.loads(env.build_secure_item_results_envelope(
            items=[self._wallet_card()],
            category_filter=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            reveal=False,
            receive_intent=True,
        ))
        self.assertFalse(envelope["receive_intent"])

    def test_receive_flag_dropped_for_seed_phrase_row(self):
                                                                 
                                                 
        envelope = json.loads(env.build_secure_item_results_envelope(
            items=[self._seed_card()],
            category_filter=t.CATEGORY_CRYPTO_SEED_PHRASE,
            reveal=True,
            receive_intent=True,
        ))
        self.assertFalse(envelope["receive_intent"])

    def test_receive_flag_dropped_for_multi_wallet_match(self):
                                                                 
                                                                 
        envelope = json.loads(env.build_secure_item_results_envelope(
            items=[
                self._wallet_card(item_id="r1", address=_BTC, network="BTC"),
                self._wallet_card(
                    item_id="r2",
                    address=_USDT_TRC20,
                    network="USDT TRC20",
                ),
            ],
            category_filter=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            reveal=True,
            receive_intent=True,
        ))
        self.assertFalse(envelope["receive_intent"])

    def test_zero_hits_no_result_wording(self):
                                         
        envelope = json.loads(env.build_secure_item_results_envelope(
            items=[],
            category_filter=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            reveal=True,
            receive_intent=True,
        ))
        self.assertIn(
            "I couldn't find a saved receive address",
            envelope["message"],
        )
        self.assertIn("Save one first", envelope["message"])
        self.assertIn("QR code", envelope["message"])


class TestEndToEndReceive(unittest.TestCase):

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

    def _stage_and_save(self, *, message: str):
        vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )
        vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message="save it",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_UPGRADED,
        )

    def test_show_BTC_receive_address_returns_receive_envelope(self):
        self._stage_and_save(message=f"save my BTC wallet {_BTC}")
        result = vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message="show my BTC receive address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(result["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 1)
        self.assertTrue(envelope["receive_intent"])
                                                                  
                                                                   
        card = envelope["items"][0]
        self.assertEqual(
            card["preview"]["wallet_address"], _BTC,
        )

    def test_seed_phrase_record_rejected_for_receive_envelope(self):
                                                                   
                                                             
        self._stage_and_save(
            message=f"save my Bitcoin seed phrase {_SEED}",
        )
        result = vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message="show QR for my seed phrase",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        if result["band"] == vsi.BAND_RETRIEVED:
            envelope = json.loads(result["envelope"])
            self.assertFalse(envelope["receive_intent"])
            for card in envelope["items"]:
                self.assertNotEqual(
                    card["type"], "crypto_wallet_address",
                )

    def test_wrong_network_query_does_not_false_match(self):
                                                               
                                                               
        self._stage_and_save(message=f"save my BTC wallet {_BTC}")
        result = vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message="show my USDT TRC20 receive address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
                                                                  
        if result["band"] == vsi.BAND_RETRIEVED:
            envelope = json.loads(result["envelope"])
            for card in envelope["items"]:
                with self.subTest(net=card.get("preview", {}).get("network")):
                    self.assertNotEqual(
                        card.get("preview", {}).get("network"), "BTC",
                    )
        else:
                                                     
            envelope = json.loads(result["envelope"])
            self.assertEqual(envelope["count"], 0)

    def test_zero_match_no_result_wording_carries_through(self):
                                                              
                                                         
        result = vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message="show my BTC receive address",
            db_reader=self._reader,
            user_tier=vsi.TIER_UPGRADED,
        )
        envelope = json.loads(result["envelope"])
        self.assertEqual(envelope["count"], 0)
        self.assertIn(
            "I couldn't find a saved receive address",
            envelope["message"],
        )

    def test_free_user_blocked_from_chat_save(self):
                                                                 
                                                           
        result = vsi.route_secure_item_message(
            vault_id="v-int", key=self.key,
            user_message=f"save my BTC wallet {_BTC}",
            db_executor=self._exec,
            db_reader=lambda v, c: [],
            user_tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
        self.assertEqual(len(self._rows), 0)


class TestPrivacyFloorReceive(unittest.TestCase):

    def test_receive_flow_does_not_leak_btc_or_xmr_address(self):
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
            "vault_pending_draft_confirm",
        )
        for n in names:
            log = logging.getLogger(n)
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
                f"save my BTC wallet {_BTC}",
                "save it",
                f"save my Monero wallet {_XMR}",
                "save it",
                "show my BTC receive address",
                "show my monero receive address",
                "show QR for my BTC wallet",
            ):
                vsi.route_secure_item_message(
                    vault_id="v-int", key=key,
                    user_message=msg,
                    db_executor=exec_,
                    db_reader=reader,
                    user_tier=vsi.TIER_UPGRADED,
                )
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass
            for n in names:
                logging.getLogger(n).removeHandler(sink)
            draft_store._reset_store_for_test()

        joined = "\n".join(r.getMessage() for r in records)
        for forbidden in (_BTC, _XMR):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


class TestSupportedNetworksRegistered(unittest.TestCase):

    def test_supported_networks_present_in_closed_set(self):
        for label in (
            "BTC", "ETH",
            "USDT TRC20", "USDT ERC20", "USDC ERC20",
            "SOL", "BNB",
                                                                    
                                                                    
        ):
            with self.subTest(label=label):
                self.assertIn(label, t.ALL_NETWORK_LABELS)


class TestNoSigningLibrariesAddedForReceive(unittest.TestCase):

    _MODULES = (
        "vault_saved_item_chat_intent.py",
        "vault_secure_item_card_envelope.py",
        "vault_secure_item_save.py",
    )
    _FORBIDDEN_IMPORTS = (
        "import web3", "from web3",
        "import bitcoin", "from bitcoin",
        "import eth_account", "from eth_account",
        "import solana", "from solana",
        "import ethers", "from ethers",
        "import coincurve", "from coincurve",
        "import ecdsa", "from ecdsa",
    )
    _FORBIDDEN_FUNCTION_NAMES = (
        "sign_transaction", "broadcast_transaction",
        "send_transaction", "submit_transaction",
        "create_wallet", "generate_wallet",
        "derive_address", "derive_public_key",
        "send_btc", "send_eth", "send_sol",
        "swap_crypto", "buy_crypto", "sell_crypto",
    )

    def _read(self, path):
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


if __name__ == "__main__":                    
    unittest.main()
