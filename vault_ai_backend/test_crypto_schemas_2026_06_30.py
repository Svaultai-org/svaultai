

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import crypto_schemas as cs
import crypto_balance_query as cbq
import vault_saved_item_chat_intent as ci
import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store
import vault_secure_item_save as vsi


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


_BTC_ADDR = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_ETH_ADDR = "0x0000000000000000000000000000000000000001"
_USDT_TRC20_ADDR = "TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY"
_XMR_ADDR = "4" + "1" * 94                        
_RECOVERY_PHRASE = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
_PRIVATE_KEY = (
    "L1aW4aubDFB7yfras2S1mN3bqg9nwySY8nkoLmJebSLD5BWv3ENZ"
)
_SEED = (
    "witch collapse practice feed shame open despair "
    "creek road again ice least"
)


class TestSchemaConstants(unittest.TestCase):
    def test_wallet_profile_schema_string(self):
        self.assertEqual(
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "crypto_wallet_profile_v1",
        )

    def test_sensitive_backup_schema_string(self):
        self.assertEqual(
            cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            "crypto_sensitive_backup_v1",
        )

    def test_crypto_note_schema_string(self):
        self.assertEqual(
            cs.SCHEMA_CRYPTO_NOTE_V1,
            "crypto_note_v1",
        )

    def test_secret_type_constants(self):
        self.assertEqual(cs.SECRET_TYPE_SEED_PHRASE,     "seed_phrase")
        self.assertEqual(cs.SECRET_TYPE_PRIVATE_KEY,     "private_key")
        self.assertEqual(cs.SECRET_TYPE_RECOVERY_PHRASE, "recovery_phrase")

    def test_asset_constants(self):
        self.assertEqual(
            cs.ALL_CRYPTO_ASSETS,
            ("BTC", "ETH", "USDT_TRC20", "USDT_ERC20", "USDC_ERC20",
             "SOL", "BNB", "XMR"),
        )

    def test_xmr_is_the_only_privacy_chain(self):
        self.assertEqual(cs.PRIVACY_CHAIN_ASSETS, frozenset({"XMR"}))


class TestCategorySchemaMapping(unittest.TestCase):
    def test_wallet_address_maps_to_wallet_profile_schema(self):
        self.assertEqual(
            cs.schema_for_category(t.CATEGORY_CRYPTO_WALLET_ADDRESS),
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
        )

    def test_seed_private_recovery_map_to_sensitive_backup_schema(self):
        for cat in (
            t.CATEGORY_CRYPTO_SEED_PHRASE,
            t.CATEGORY_CRYPTO_PRIVATE_KEY,
            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
        ):
            self.assertEqual(
                cs.schema_for_category(cat),
                cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
                f"category {cat} must map to sensitive_backup_v1",
            )

    def test_crypto_notes_all_map_to_crypto_note_schema(self):
        for cat in (
            t.CATEGORY_CRYPTO_NOTE,
            t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
            t.CATEGORY_CRYPTO_EXCHANGE_NOTE,
            t.CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
        ):
            self.assertEqual(
                cs.schema_for_category(cat),
                cs.SCHEMA_CRYPTO_NOTE_V1,
                f"category {cat} must map to crypto_note_v1",
            )

    def test_non_crypto_category_returns_none(self):
        self.assertIsNone(cs.schema_for_category("login"))
        self.assertIsNone(cs.schema_for_category("imei"))
        self.assertIsNone(cs.schema_for_category(None))

    def test_requires_warning_confirmation_for_sensitive_backups_only(self):
        self.assertTrue(cs.requires_warning_confirmation(
            cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1))
        self.assertFalse(cs.requires_warning_confirmation(
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1))
        self.assertFalse(cs.requires_warning_confirmation(
            cs.SCHEMA_CRYPTO_NOTE_V1))
                                            
        self.assertTrue(
            cs.requires_warning_confirmation_for_category(
                t.CATEGORY_CRYPTO_SEED_PHRASE))
        self.assertFalse(
            cs.requires_warning_confirmation_for_category(
                t.CATEGORY_CRYPTO_WALLET_ADDRESS))


class TestWalletProfileBuilder(unittest.TestCase):
    def test_metamask_eth_wallet_profile_shape(self):
        rec = cs.build_wallet_profile_record(
            asset="ETH",
            wallet_label="MetaMask",
            public_address=_ETH_ADDR,
            note="Daily driver",
        )
        self.assertEqual(rec["schema"], "crypto_wallet_profile_v1")
        self.assertEqual(rec["asset"],        "ETH")
        self.assertEqual(rec["network"],      "Ethereum")
        self.assertEqual(rec["walletLabel"],  "MetaMask")
        self.assertEqual(rec["publicAddress"], _ETH_ADDR)
        self.assertEqual(rec["note"],         "Daily driver")
                                                              
        self.assertEqual(
            rec["balanceStatus"],
            cs.BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
        )

    def test_trust_wallet_usdt_trc20_profile_shape(self):
        rec = cs.build_wallet_profile_record(
            asset="USDT_TRC20",
            wallet_label="Trust Wallet",
            public_address=_USDT_TRC20_ADDR,
        )
        self.assertEqual(rec["asset"], "USDT_TRC20")
        self.assertEqual(rec["network"], "Tron TRC20")
        self.assertEqual(rec["walletLabel"], "Trust Wallet")
        self.assertEqual(rec["publicAddress"], _USDT_TRC20_ADDR)
        self.assertEqual(rec["note"], "")

    def test_xmr_wallet_profile_pins_privacy_balance_status(self):
        rec = cs.build_wallet_profile_record(
            asset="XMR",
            wallet_label="Monero GUI",
            public_address=_XMR_ADDR,
        )
        self.assertEqual(
            rec["balanceStatus"],
            cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY,
        )

    def test_builder_rejects_missing_fields(self):
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_wallet_profile_record(
                asset="ETH", wallet_label="", public_address=_ETH_ADDR,
            )
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_wallet_profile_record(
                asset="ETH", wallet_label="MetaMask", public_address="",
            )
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_wallet_profile_record(
                asset="UNKNOWN", wallet_label="MetaMask",
                public_address=_ETH_ADDR,
            )


class TestSensitiveBackupBuilderGate(unittest.TestCase):
    def test_builder_refuses_without_warning_confirmed(self):
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_sensitive_backup_record(
                asset="BTC", wallet_label="Ledger",
                secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
                secret_value=_RECOVERY_PHRASE,
                warning_confirmed=False,
            )
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_sensitive_backup_record(
                asset="BTC", wallet_label="Ledger",
                secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
                secret_value=_RECOVERY_PHRASE,
                warning_confirmed=None,                          
            )

    def test_builder_succeeds_with_warning_confirmed_true(self):
        rec = cs.build_sensitive_backup_record(
            asset="BTC", wallet_label="Ledger",
            secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
            secret_value=_RECOVERY_PHRASE,
            note="cold storage",
            warning_confirmed=True,
        )
        self.assertEqual(rec["schema"], "crypto_sensitive_backup_v1")
        self.assertEqual(rec["asset"], "BTC")
        self.assertEqual(rec["network"], "Bitcoin")
        self.assertEqual(rec["walletLabel"], "Ledger")
        self.assertEqual(rec["secretType"], "recovery_phrase")
        self.assertEqual(rec["secretValue"], _RECOVERY_PHRASE)
        self.assertEqual(rec["warningConfirmed"], True)

    def test_builder_rejects_unknown_secret_type(self):
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_sensitive_backup_record(
                wallet_label="Ledger",
                secret_type="api_key",                     
                secret_value="x",
                warning_confirmed=True,
            )

    def test_each_closed_set_secret_type_builds(self):
        for st, val in (
            (cs.SECRET_TYPE_SEED_PHRASE,     _SEED),
            (cs.SECRET_TYPE_PRIVATE_KEY,     _PRIVATE_KEY),
            (cs.SECRET_TYPE_RECOVERY_PHRASE, _RECOVERY_PHRASE),
        ):
            rec = cs.build_sensitive_backup_record(
                wallet_label="Ledger",
                secret_type=st, secret_value=val,
                warning_confirmed=True,
            )
            self.assertEqual(rec["secretType"], st)
            self.assertEqual(rec["warningConfirmed"], True)


class TestCryptoNoteBuilder(unittest.TestCase):
    def test_crypto_note_shape(self):
        rec = cs.build_crypto_note_record(
            asset="BTC",
            title="Rotate cold wallet quarterly",
            note="Q3 rotation due Sept 15",
        )
        self.assertEqual(rec["schema"], "crypto_note_v1")
        self.assertEqual(rec["asset"], "BTC")
        self.assertEqual(rec["network"], "Bitcoin")
        self.assertEqual(rec["title"], "Rotate cold wallet quarterly")
        self.assertEqual(rec["note"], "Q3 rotation due Sept 15")

    def test_crypto_note_without_asset_is_allowed(self):
        rec = cs.build_crypto_note_record(
            title="General reminder",
            note="Back up Yubikey before travel",
        )
        self.assertEqual(rec["asset"], "")
        self.assertEqual(rec["network"], "")
        self.assertEqual(rec["title"], "General reminder")

    def test_crypto_note_requires_title_and_note(self):
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(title="", note="x")
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(title="x", note="")


class TestReceiveQRGate(unittest.TestCase):
    def test_wallet_profile_with_address_is_qr_eligible(self):
        wallet = cs.build_wallet_profile_record(
            asset="BTC", wallet_label="Ledger",
            public_address=_BTC_ADDR,
        )
        self.assertTrue(cs.is_receive_qr_eligible(wallet))

    def test_sensitive_backup_is_NEVER_qr_eligible(self):
        backup = cs.build_sensitive_backup_record(
            wallet_label="Ledger",
            secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
            secret_value=_RECOVERY_PHRASE,
            warning_confirmed=True,
        )
        self.assertFalse(cs.is_receive_qr_eligible(backup))

    def test_crypto_note_is_NEVER_qr_eligible(self):
        note = cs.build_crypto_note_record(
            asset="BTC", title="reminder", note="rotate Q3",
        )
        self.assertFalse(cs.is_receive_qr_eligible(note))

    def test_wallet_profile_with_empty_address_is_not_eligible(self):
                                                            
                           
        self.assertFalse(cs.is_receive_qr_eligible({
            "schema": cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "publicAddress": "",
        }))

    def test_none_and_non_mapping_inputs_are_not_eligible(self):
        self.assertFalse(cs.is_receive_qr_eligible(None))
        self.assertFalse(cs.is_receive_qr_eligible("not a dict"))
        self.assertFalse(cs.is_receive_qr_eligible(123))


class TestBalanceHelpers(unittest.TestCase):
    def test_xmr_pins_privacy_status(self):
        self.assertEqual(
            cs.balance_status_for_asset("XMR"),
            cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY,
        )
        self.assertEqual(
            cs.balance_status_message(cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY),
            "Balance unavailable for Monero privacy addresses.",
        )

    def test_btc_eth_sol_bnb_pin_lookup_not_connected(self):
        for asset in ("BTC", "ETH", "USDT_TRC20", "USDT_ERC20",
                      "USDC_ERC20", "SOL", "BNB"):
            self.assertEqual(
                cs.balance_status_for_asset(asset),
                cs.BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
                f"asset {asset} must be lookup_not_connected",
            )

    def test_lookup_not_connected_message_is_pinned(self):
        self.assertEqual(
            cs.balance_status_message(
                cs.BALANCE_STATUS_LOOKUP_NOT_CONNECTED),
            "Balance lookup not connected",
        )

    def test_unavailable_message_is_pinned(self):
        self.assertEqual(
            cs.balance_status_message(cs.BALANCE_STATUS_UNAVAILABLE),
            "Balance unavailable",
        )


class TestBalanceQueryHandler(unittest.TestCase):
    def setUp(self):
        self.wallet_btc = cs.build_wallet_profile_record(
            asset="BTC", wallet_label="Ledger",
            public_address=_BTC_ADDR,
        )
        self.wallet_eth_a = cs.build_wallet_profile_record(
            asset="ETH", wallet_label="MetaMask",
            public_address=_ETH_ADDR,
        )
        self.wallet_eth_b = cs.build_wallet_profile_record(
            asset="ETH", wallet_label="Trezor",
            public_address=_ETH_ADDR.replace("0001", "0002"),
        )
        self.wallet_xmr = cs.build_wallet_profile_record(
            asset="XMR", wallet_label="Monero GUI",
            public_address=_XMR_ADDR,
        )
        self.backup = cs.build_sensitive_backup_record(
            wallet_label="Ledger",
            secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
            secret_value=_RECOVERY_PHRASE,
            warning_confirmed=True,
        )
        self.note = cs.build_crypto_note_record(
            asset="BTC", title="reminder", note="rotate Q3",
        )

    def test_returns_eight_canonical_assets(self):
        summary = cbq.build_balance_summary([])
        self.assertEqual(
            [a["asset"] for a in summary["assets"]],
            list(cs.ALL_CRYPTO_ASSETS),
        )

    def test_counts_only_wallet_profile_records(self):
        summary = cbq.build_balance_summary([
            self.wallet_btc, self.wallet_eth_a, self.wallet_eth_b,
            self.wallet_xmr, self.backup, self.note,
        ])
        by_asset = {a["asset"]: a for a in summary["assets"]}
        self.assertEqual(by_asset["BTC"]["savedWallets"], 1)
        self.assertEqual(by_asset["ETH"]["savedWallets"], 2)
        self.assertEqual(by_asset["XMR"]["savedWallets"], 1)
        self.assertEqual(by_asset["SOL"]["savedWallets"], 0)
        self.assertEqual(by_asset["BNB"]["savedWallets"], 0)
                                                           
                                            
        self.assertEqual(
            sum(a["savedWallets"] for a in summary["assets"]),
            4,
        )

    def test_xmr_pins_privacy_message_in_summary(self):
        summary = cbq.build_balance_summary([self.wallet_xmr])
        by_asset = {a["asset"]: a for a in summary["assets"]}
        self.assertEqual(
            by_asset["XMR"]["status"],
            cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY,
        )
        self.assertEqual(
            by_asset["XMR"]["message"],
            "Balance unavailable for Monero privacy addresses.",
        )

    def test_other_assets_pin_lookup_not_connected_in_summary(self):
        summary = cbq.build_balance_summary([self.wallet_btc])
        by_asset = {a["asset"]: a for a in summary["assets"]}
        for asset in ("BTC", "ETH", "USDT_TRC20", "USDT_ERC20",
                      "USDC_ERC20", "SOL", "BNB"):
            self.assertEqual(
                by_asset[asset]["status"],
                cs.BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
                f"{asset} status must be lookup_not_connected",
            )


class TestBalanceHandlerNeverReadsSecrets(unittest.TestCase):
    def test_allowed_input_fields_is_a_closed_set_without_secret_keys(self):
        allowed = set(cbq.ALLOWED_BALANCE_INPUT_FIELDS)
                          
        self.assertEqual(
            allowed,
            {"schema", "asset", "network", "publicAddress"},
        )
                                          
        for forbidden in cs.SECRET_FIELDS:
            self.assertNotIn(forbidden, allowed)

    def test_secret_field_values_are_NEVER_present_in_summary(self):
                                                                
                                                              
        hostile = {
            "schema":           cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "asset":            "BTC",
            "publicAddress":    _BTC_ADDR,
                                                             
                                                      
            "secretValue":      _RECOVERY_PHRASE,
            "seed_phrase":      _SEED,
            "private_key":      _PRIVATE_KEY,
            "recovery_phrase":  _RECOVERY_PHRASE,
        }
        summary = cbq.build_balance_summary([hostile])
        rendered = json.dumps(summary)
        for needle in (_RECOVERY_PHRASE, _SEED, _PRIVATE_KEY):
            self.assertNotIn(
                needle, rendered,
                f"summary must NEVER contain secret value (got: {needle!r})",
            )
                                                               
                                                             
        by_asset = {a["asset"]: a for a in summary["assets"]}
        self.assertEqual(by_asset["BTC"]["savedWallets"], 1)


class TestNoFakeBalances(unittest.TestCase):
    def test_summary_has_no_currency_number(self):
        summary = cbq.build_balance_summary([
            cs.build_wallet_profile_record(
                asset="BTC", wallet_label="Ledger",
                public_address=_BTC_ADDR,
            ),
        ])
        rendered = cbq.format_balance_summary_message(summary)
                                                                    
        import re
        self.assertIsNone(
            re.search(
                r"(?:\$\s*\d|\d+\.?\d*\s*"
                r"(?:USD|BTC|ETH|SOL|BNB|XMR|USDT|USDC)\b)",
                rendered, flags=re.IGNORECASE,
            ),
            f"summary text must not contain a synthetic balance: "
            f"{rendered!r}",
        )

    def test_summary_does_not_imply_we_can_see_monero_balance(self):
        summary = cbq.build_balance_summary([
            cs.build_wallet_profile_record(
                asset="XMR", wallet_label="Monero GUI",
                public_address=_XMR_ADDR,
            ),
        ])
        text = cbq.format_balance_summary_message(summary).lower()
                                                               
        self.assertIn("monero privacy", text)


class TestAnnotationHook(unittest.TestCase):
    def test_wallet_address_category_gets_schema_stamp(self):
        rec = {
            "category": t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            "title":    "MetaMask ETH wallet",
            "fields":   {"wallet_address": _ETH_ADDR, "network": "ETH"},
            "notes":    "",
            "item_id":  "deadbeef",
        }
        cs.annotate_crypto_record(
            rec,
            category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertEqual(rec["schema"], "crypto_wallet_profile_v1")
        self.assertNotIn("warningConfirmed", rec)

    def test_seed_phrase_category_gets_schema_AND_warning_confirmed(self):
        rec = {
            "category": t.CATEGORY_CRYPTO_SEED_PHRASE,
            "title":    "Ledger BTC recovery",
            "fields":   {"seed_phrase": _SEED, "network": "BTC"},
            "notes":    "",
            "item_id":  "deadbeef",
        }
        cs.annotate_crypto_record(
            rec,
            category=t.CATEGORY_CRYPTO_SEED_PHRASE,
            warning_confirmed=True,
        )
        self.assertEqual(rec["schema"], "crypto_sensitive_backup_v1")
        self.assertEqual(rec["warningConfirmed"], True)

    def test_annotation_REFUSES_sensitive_backup_without_confirmed(self):
        rec = {
            "category": t.CATEGORY_CRYPTO_PRIVATE_KEY,
            "title":    "x", "fields": {}, "notes": "", "item_id": "x",
        }
        with self.assertRaises(cs.CryptoSchemaError):
            cs.annotate_crypto_record(
                rec,
                category=t.CATEGORY_CRYPTO_PRIVATE_KEY,
                warning_confirmed=False,
            )
        with self.assertRaises(cs.CryptoSchemaError):
            cs.annotate_crypto_record(
                rec,
                category=t.CATEGORY_CRYPTO_PRIVATE_KEY,
                warning_confirmed=None,
            )

    def test_non_crypto_category_is_a_noop(self):
        rec = {"category": "login", "title": "x", "fields": {}}
        cs.annotate_crypto_record(rec, category="login")
        self.assertNotIn("schema", rec)
        self.assertNotIn("warningConfirmed", rec)


class TestEncryptedSaveCarriesSchema(unittest.TestCase):
    def setUp(self):
        self.key = b"\x07" * 32
        self.rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        draft_store._reset_store_for_test()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        draft_store._reset_store_for_test()

    def _executor(self, action: str, payload: dict) -> None:
        if action == "upsert":
            self.rows.append(payload)

    def _stage_wallet_draft(self) -> None:
        draft_store.store_secure_item_draft(
            vault_id="v1",
            category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            title="MetaMask ETH wallet",
            field="wallet_address",
            value=_ETH_ADDR,
            notes="Daily driver",
            network="ETH",
        )

    def _stage_recovery_draft(self) -> None:
        draft_store.store_secure_item_draft(
            vault_id="v1",
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            title="Ledger BTC recovery",
            field="recovery_phrase",
            value=_RECOVERY_PHRASE,
            notes="cold storage",
            network="BTC",
        )

    def test_wallet_address_save_carries_wallet_profile_schema(self):
        self._stage_wallet_draft()
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key, db_executor=self._executor,
        )
        self.assertEqual(result["band"], "saved")
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        decrypted = json.loads(
            _fake_decrypt(row["encrypted_data"], self.key)
        )
        self.assertEqual(
            decrypted["schema"], "crypto_wallet_profile_v1",
        )
        self.assertNotIn("warningConfirmed", decrypted)

    def test_recovery_phrase_save_carries_sensitive_backup_schema(self):
        self._stage_recovery_draft()
        result = vsi.confirm_pending_secure_item_save(
            vault_id="v1", key=self.key, db_executor=self._executor,
        )
        self.assertEqual(result["band"], "saved")
        row = self.rows[0]
        decrypted = json.loads(
            _fake_decrypt(row["encrypted_data"], self.key)
        )
        self.assertEqual(
            decrypted["schema"], "crypto_sensitive_backup_v1",
        )
        self.assertEqual(decrypted["warningConfirmed"], True)


class TestLogRedaction(unittest.TestCase):
    def test_redacts_secret_value(self):
        out = cs.redact_crypto_payload({
            "schema":        cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            "secretValue":   _RECOVERY_PHRASE,
            "walletLabel":   "Ledger",
        })
        self.assertEqual(out["secretValue"], "***")
        self.assertEqual(out["walletLabel"], "Ledger")                

    def test_redacts_public_address(self):
        out = cs.redact_crypto_payload({
            "publicAddress": _BTC_ADDR,
            "asset":         "BTC",
        })
        self.assertEqual(out["publicAddress"], "***")
        self.assertEqual(out["asset"], "BTC")

    def test_recursively_redacts_nested_fields(self):
        out = cs.redact_crypto_payload({
            "fields": {
                "wallet_address": _ETH_ADDR,
                "seed_phrase":    _SEED,
                "network":        "ETH",
            },
            "preview": {
                "wallet_address": _ETH_ADDR,
            },
        })
        self.assertEqual(out["fields"]["wallet_address"], "***")
        self.assertEqual(out["fields"]["seed_phrase"],    "***")
        self.assertEqual(out["fields"]["network"],        "ETH")
        self.assertEqual(out["preview"]["wallet_address"], "***")

    def test_redaction_handles_lists_of_dicts(self):
        out = cs.redact_crypto_payload({
            "items": [
                {"publicAddress": _BTC_ADDR, "asset": "BTC"},
                {"secretValue":   _SEED,     "asset": "ETH"},
            ],
        })
        self.assertEqual(out["items"][0]["publicAddress"], "***")
        self.assertEqual(out["items"][0]["asset"], "BTC")
        self.assertEqual(out["items"][1]["secretValue"], "***")

    def test_secret_field_names_match_operator_brief(self):
                                                    
        self.assertEqual(
            cs.SECRET_FIELDS,
            frozenset({
                "secretValue",
                "seed_phrase",
                "private_key",
                "recovery_phrase",
                "value",
            }),
        )
        self.assertEqual(
            cs.PUBLIC_ADDRESS_FIELDS,
            frozenset({"publicAddress", "wallet_address"}),
        )

    def test_no_secret_in_save_module_log_records(self):


        key = b"\x07" * 32
        patches = _patch_crypto()
        rows: list[dict] = []
        try:
            for p in patches:
                p.start()
            draft_store._reset_store_for_test()
            draft_store.store_secure_item_draft(
                vault_id="v1",
                category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
                title="MetaMask ETH wallet",
                field="wallet_address",
                value=_ETH_ADDR,
                notes="",
                network="ETH",
            )
            with self.assertLogs(
                "vault_secure_item_save", level="DEBUG",
            ) as cap:
                vsi.confirm_pending_secure_item_save(
                    vault_id="v1", key=key,
                    db_executor=lambda a, p: rows.append(p),
                )
            for line in cap.output:
                self.assertNotIn(
                    _ETH_ADDR, line,
                    "save module log MUST NOT include the wallet address",
                )
        finally:
            for p in patches:
                p.stop()
            draft_store._reset_store_for_test()


class TestBalanceIntentRouting(unittest.TestCase):
    def test_canonical_phrases_route_to_balance_query(self):
        for phrase in (
            "show my crypto balances",
            "show my wallet balances",
            "what's my crypto balance",
            "list all my wallet balances",
            "my crypto balances",
            "tell me my crypto balance",
        ):
            intent = ci.classify_secure_item_intent(phrase)
            self.assertEqual(
                intent.intent,
                ci.INTENT_CRYPTO_BALANCE_QUERY,
                f"phrase {phrase!r} must route to balance query",
            )

    def test_balance_query_does_not_hijack_regular_retrieves(self):
                                                           
        intent = ci.classify_secure_item_intent(
            "show my BTC wallet",
        )
        self.assertNotEqual(
            intent.intent, ci.INTENT_CRYPTO_BALANCE_QUERY,
        )

    def test_balance_query_pure_phrase_detector(self):
        self.assertTrue(cbq.is_crypto_balance_query(
            "show my crypto balances"))
        self.assertTrue(cbq.is_crypto_balance_query(
            "what's my wallet balance"))
        self.assertFalse(cbq.is_crypto_balance_query(
            "show my BTC wallet"))
        self.assertFalse(cbq.is_crypto_balance_query(
            "save my recovery phrase"))
        self.assertFalse(cbq.is_crypto_balance_query(None))
        self.assertFalse(cbq.is_crypto_balance_query(""))


class TestWalletProfileChatIntent(unittest.TestCase):
    def test_metamask_eth_wallet_phrase_routes_to_wallet_address_save(self):
        intent = ci.classify_secure_item_intent(
            f"save my MetaMask ETH wallet address {_ETH_ADDR}",
        )
        self.assertEqual(intent.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(
            intent.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertEqual(intent.field, ci.FIELD_WALLET_ADDRESS)
        self.assertEqual(intent.network, "ETH")
        self.assertEqual(intent.value, _ETH_ADDR)
                                          
        self.assertEqual(
            cs.schema_for_category(intent.category),
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
        )

    def test_trust_wallet_usdt_trc20_phrase_routes_to_wallet_address_save(self):
        intent = ci.classify_secure_item_intent(
            f"save my Trust Wallet USDT TRC20 address {_USDT_TRC20_ADDR}",
        )
        self.assertEqual(intent.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(
            intent.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )
        self.assertEqual(intent.network, "USDT TRC20")
        self.assertEqual(intent.value, _USDT_TRC20_ADDR)

    def test_show_my_btc_wallet_routes_to_retrieve(self):
        intent = ci.classify_secure_item_intent("show my BTC wallet")
        self.assertEqual(
            intent.intent, ci.INTENT_RETRIEVE_SECURE_ITEM,
        )
        self.assertEqual(intent.network, "BTC")

    def test_show_my_saved_wallets_routes_to_retrieve(self):
        intent = ci.classify_secure_item_intent("show my saved wallets")
        self.assertEqual(
            intent.intent, ci.INTENT_RETRIEVE_SECURE_ITEM,
        )
                                                                
        self.assertEqual(
            intent.category, t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        )

    def test_show_my_bitcoin_receive_qr_sets_receive_intent(self):
        intent = ci.classify_secure_item_intent(
            "show my bitcoin receive QR",
        )
        self.assertEqual(
            intent.intent, ci.INTENT_RETRIEVE_SECURE_ITEM,
        )
        self.assertEqual(intent.network, "BTC")
        self.assertTrue(intent.receive_intent)


class TestSensitiveBackupChatIntent(unittest.TestCase):
    def test_save_my_ledger_recovery_phrase_routes_to_recovery_save(self):
        intent = ci.classify_secure_item_intent(
            "save my ledger recovery phrase " + _RECOVERY_PHRASE,
        )
        self.assertEqual(intent.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(intent.field, ci.FIELD_RECOVERY_PHRASE)
                                                            
                                                                   
        self.assertEqual(
            intent.category,
            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
        )
                                               
        self.assertEqual(
            cs.schema_for_category(intent.category),
            cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
        )
                                           
        self.assertTrue(
            cs.requires_warning_confirmation_for_category(
                intent.category),
        )

    def test_save_my_seed_phrase_routes_to_seed_save(self):
        intent = ci.classify_secure_item_intent(
            "save my crypto seed phrase " + _SEED,
        )
        self.assertEqual(intent.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(intent.field, ci.FIELD_SEED_PHRASE)
        self.assertEqual(
            intent.category, t.CATEGORY_CRYPTO_SEED_PHRASE,
        )
        self.assertTrue(
            cs.requires_warning_confirmation_for_category(
                intent.category),
        )

    def test_save_my_metamask_private_key_routes_to_crypto_private_key(self):
        intent = ci.classify_secure_item_intent(
            "save my metamask private key " + _PRIVATE_KEY,
        )
        self.assertEqual(intent.intent, ci.INTENT_SAVE_SECURE_ITEM)
        self.assertEqual(intent.field, ci.FIELD_PRIVATE_KEY)
        self.assertEqual(
            intent.category, t.CATEGORY_CRYPTO_PRIVATE_KEY,
        )
        self.assertTrue(
            cs.requires_warning_confirmation_for_category(
                intent.category),
        )


if __name__ == "__main__":
    unittest.main()
