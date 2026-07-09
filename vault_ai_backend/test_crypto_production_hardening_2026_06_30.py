

from __future__ import annotations

import unittest
from pathlib import Path

import crypto_schemas as cs
import crypto_balance_query as cbq
import vault_saved_item_taxonomy as t


class TestSchemaStringsPinnedVerbatim(unittest.TestCase):
    def test_wallet_profile_schema_string(self) -> None:
        self.assertEqual(
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "crypto_wallet_profile_v1",
        )

    def test_sensitive_backup_schema_string(self) -> None:
        self.assertEqual(
            cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            "crypto_sensitive_backup_v1",
        )

    def test_note_schema_string(self) -> None:
        self.assertEqual(
            cs.SCHEMA_CRYPTO_NOTE_V1, "crypto_note_v1",
        )

    def test_all_schemas_tuple(self) -> None:
        self.assertEqual(
            cs.ALL_CRYPTO_SCHEMAS,
            (
                "crypto_wallet_profile_v1",
                "crypto_sensitive_backup_v1",
                "crypto_note_v1",
            ),
        )


class TestAssetCatalog(unittest.TestCase):
    def test_eight_assets_in_canonical_order(self) -> None:
        self.assertEqual(
            cs.ALL_CRYPTO_ASSETS,
            ("BTC", "ETH",
             "USDT_TRC20", "USDT_ERC20", "USDC_ERC20",
             "SOL", "BNB", "XMR"),
        )

    def test_xmr_is_only_privacy_chain(self) -> None:
        self.assertEqual(
            cs.PRIVACY_CHAIN_ASSETS, frozenset({"XMR"}),
        )


class TestNetworkLabels(unittest.TestCase):
    def test_network_labels_pinned(self) -> None:
        self.assertEqual(
            cs.NETWORK_LABEL_FOR_ASSET,
            {
                "BTC":         "Bitcoin",
                "ETH":         "Ethereum",
                "USDT_TRC20":  "Tron TRC20",
                "USDT_ERC20":  "Ethereum ERC20",
                "USDC_ERC20":  "Ethereum ERC20",
                "SOL":         "Solana",
                "BNB":         "BNB Smart Chain",
                "XMR":         "Monero",
            },
        )


class TestBalanceHelperHonest(unittest.TestCase):
    def test_xmr_returns_privacy_unavailable(self) -> None:
        self.assertEqual(
            cs.balance_status_for_asset("XMR"),
            cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY,
        )
        self.assertEqual(
            cs.balance_status_message(
                cs.BALANCE_STATUS_UNAVAILABLE_PRIVACY),
            "Balance unavailable for Monero privacy addresses.",
        )

    def test_all_non_xmr_assets_return_lookup_not_connected(self) -> None:
        for asset in cs.ALL_CRYPTO_ASSETS:
            if asset == "XMR":
                continue
            self.assertEqual(
                cs.balance_status_for_asset(asset),
                cs.BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
                msg=f"asset={asset} must be lookup_not_connected "
                    "until a real provider is wired",
            )

    def test_balance_status_pool_is_closed_set(self) -> None:


        self.assertEqual(
            cs.ALL_BALANCE_STATUSES,
            (
                "unavailable",
                "unavailable_privacy",
                "lookup_not_connected",
            ),
        )

    def test_messages_pinned_verbatim(self) -> None:
        self.assertEqual(
            cs.BALANCE_MESSAGE_UNAVAILABLE, "Balance unavailable",
        )
        self.assertEqual(
            cs.BALANCE_MESSAGE_UNAVAILABLE_PRIVACY,
            "Balance unavailable for Monero privacy addresses.",
        )
        self.assertEqual(
            cs.BALANCE_MESSAGE_LOOKUP_NOT_CONNECTED,
            "Balance lookup not connected",
        )


class TestSecretTypeDiscriminators(unittest.TestCase):
    def test_secret_type_strings(self) -> None:
        self.assertEqual(
            cs.SECRET_TYPE_SEED_PHRASE, "seed_phrase",
        )
        self.assertEqual(
            cs.SECRET_TYPE_PRIVATE_KEY, "private_key",
        )
        self.assertEqual(
            cs.SECRET_TYPE_RECOVERY_PHRASE, "recovery_phrase",
        )
        self.assertEqual(
            cs.ALL_SECRET_TYPES,
            ("seed_phrase", "private_key", "recovery_phrase"),
        )


class TestNoteTypeDiscriminators(unittest.TestCase):
    def test_note_type_strings(self) -> None:
        self.assertEqual(cs.NOTE_TYPE_GENERAL, "general")
        self.assertEqual(
            cs.NOTE_TYPE_TRANSACTION_NOTE, "transaction_note",
        )
        self.assertEqual(
            cs.ALL_NOTE_TYPES, ("general", "transaction_note"),
        )


class TestReceiveQRGateExhaustive(unittest.TestCase):
    def test_wallet_profile_with_address_is_eligible(self) -> None:
        rec = cs.build_wallet_profile_record(
            asset="BTC", wallet_label="Ledger",
            public_address="bc1q" + "x" * 30,
        )
        self.assertTrue(cs.is_receive_qr_eligible(rec))

    def test_wallet_profile_with_empty_address_is_not_eligible(
        self,
    ) -> None:
        self.assertFalse(cs.is_receive_qr_eligible({
            "schema":        cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "publicAddress": "",
        }))

    def test_sensitive_backup_is_never_eligible(self) -> None:
        rec = cs.build_sensitive_backup_record(
            wallet_label="Ledger",
            secret_type=cs.SECRET_TYPE_RECOVERY_PHRASE,
            secret_value="x" * 40,
            warning_confirmed=True,
        )
        self.assertFalse(cs.is_receive_qr_eligible(rec))

    def test_note_is_never_eligible(self) -> None:
        for note_type in cs.ALL_NOTE_TYPES:
            rec = cs.build_crypto_note_record(
                title="x", note="y",
                note_type=note_type,
            )
            self.assertFalse(cs.is_receive_qr_eligible(rec))

    def test_hostile_schema_string_refused(self) -> None:
        for hostile in (None, "", "login", "imei",
                        "crypto_unknown_v999"):
            self.assertFalse(cs.is_receive_qr_eligible({
                "schema":        hostile,
                "publicAddress": "0x" + "1" * 40,
            }))


class TestRedactionExhaustive(unittest.TestCase):
    def test_redact_covers_every_sensitive_key(self) -> None:
        payload = {
            "secretValue":      "S",
            "seed_phrase":      "S",
            "private_key":      "S",
            "recovery_phrase":  "S",
            "value":            "S",
            "publicAddress":    "A",
            "wallet_address":   "A",
                                             
            "asset":            "BTC",
            "schema":           "crypto_sensitive_backup_v1",
            "noteType":         "general",
        }
        out = cs.redact_crypto_payload(payload)
        for k in (
            "secretValue", "seed_phrase", "private_key",
            "recovery_phrase", "value",
            "publicAddress", "wallet_address",
        ):
            self.assertEqual(
                out[k], "***",
                msg=f"{k} must be scrubbed",
            )
        for k in ("asset", "schema", "noteType"):
            self.assertEqual(
                out[k], payload[k],
                msg=f"{k} must pass through",
            )

    def test_redact_recurses_into_nested_dicts(self) -> None:
        payload = {
            "fields": {
                "wallet_address": "A",
                "seed_phrase":    "S",
            },
            "preview": {
                "wallet_address": "A",
            },
        }
        out = cs.redact_crypto_payload(payload)
        self.assertEqual(out["fields"]["wallet_address"], "***")
        self.assertEqual(out["fields"]["seed_phrase"],    "***")
        self.assertEqual(out["preview"]["wallet_address"], "***")

    def test_secret_fields_set_is_canonical(self) -> None:
        self.assertEqual(
            cs.SECRET_FIELDS,
            frozenset({
                "secretValue", "seed_phrase", "private_key",
                "recovery_phrase", "value",
            }),
        )
        self.assertEqual(
            cs.PUBLIC_ADDRESS_FIELDS,
            frozenset({"publicAddress", "wallet_address"}),
        )


class TestBalanceHandlerInputAllowlist(unittest.TestCase):
    def test_allowed_input_fields_is_closed_set(self) -> None:
        self.assertEqual(
            cbq.ALLOWED_BALANCE_INPUT_FIELDS,
            frozenset({"schema", "asset", "network", "publicAddress"}),
        )

    def test_no_secret_field_overlaps_with_allowlist(self) -> None:
        for secret in cs.SECRET_FIELDS:
            self.assertNotIn(
                secret, cbq.ALLOWED_BALANCE_INPUT_FIELDS,
                msg=f"secret field {secret!r} must NOT be in the "
                    "balance-handler input allowlist",
            )

    def test_balance_summary_drops_hostile_record_with_secret(
        self,
    ) -> None:


        import json
        hostile = {
            "schema":        cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
            "asset":         "BTC",
            "publicAddress": "bc1q" + "x" * 30,
            "secretValue":   "DO_NOT_LEAK",
            "seed_phrase":   "DO_NOT_LEAK_2",
        }
        rendered = json.dumps(
            cbq.build_balance_summary([hostile]),
        )
        self.assertNotIn("DO_NOT_LEAK", rendered)
        self.assertNotIn("DO_NOT_LEAK_2", rendered)


_ROUTE_SRC = Path(
    "routes/login_routes.py",
).read_text(encoding="utf-8")


def _slice_handler(anchor: str) -> str:
    start = _ROUTE_SRC.index(anchor)
    nxt = _ROUTE_SRC.find("@router.", start + 1)
    end = nxt if nxt != -1 else len(_ROUTE_SRC)
    return _ROUTE_SRC[start:end]


CRYPTO_ROUTE_ANCHORS = (
    '@router.post("/crypto/save-wallet-profile")',
    '@router.post("/crypto/save-sensitive-backup")',
    '@router.post("/crypto/reveal-sensitive-backup")',
    '@router.post("/crypto/save-note")',
)


PROHIBITED_CODE_PATTERNS = (
    "send_transaction", "send_tx", "send_btc", "send_eth",
    "broadcast_transaction", "broadcast_tx",
    "sign_transaction", "sign_tx",
    "create_wallet", "generate_wallet",
    "connect_metamask",
    "buy_crypto", "sell_crypto", "swap_crypto",
    "verify_transaction",
    "import_transaction_history",
    "blockchain_rpc",
    "rpc_call",
    "web3.",
)


class TestRouteSourceAntiClaim(unittest.TestCase):
    def test_no_crypto_route_imports_active_flow_helpers(self) -> None:
        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            for needle in PROHIBITED_CODE_PATTERNS:
                self.assertNotIn(
                    needle, body,
                    msg=(
                        f"crypto route {anchor!r} must NOT call "
                        f"{needle!r}"
                    ),
                )


SENSITIVE_TOKENS = (
    "payload.pin",
    "payload.secretValue",
    "payload.publicAddress",
    "payload.txHash",
    "payload.walletLabel",
    "payload.note",
    "payload.title",
    "record[\"secretValue\"]",
    "record[\"publicAddress\"]",
    "record[\"note\"]",
    "record[\"title\"]",
    "record[\"walletLabel\"]",
    "record[\"txHash\"]",
    "secret_value",
    "wallet_address",
    "seed_phrase",
    "private_key",
    "recovery_phrase",
)

LOGGER_CALL_PREFIXES = (
    "logger.info", "logger.debug",
    "logger.warning", "logger.error",
    "logger.exception",
    "_logger.info", "_logger.debug",
    "_logger.warning", "_logger.error",
    "_logger.exception",
    "print(",
)


class TestRouteLogRedactionAudit(unittest.TestCase):
    def test_no_logger_call_embeds_sensitive_field(self) -> None:
        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            for line in body.splitlines():
                line_l = line.strip()
                if not any(p in line_l for p in LOGGER_CALL_PREFIXES):
                    continue
                for token in SENSITIVE_TOKENS:
                    self.assertNotIn(
                        token, line_l,
                        msg=(
                            f"crypto route {anchor!r} log line "
                            f"emits {token!r}: {line!r}"
                        ),
                    )

    def test_no_route_logs_entire_payload_object(self) -> None:


        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            for line in body.splitlines():
                line_l = line.strip()
                                                                 
                                                               
                if any(p in line_l for p in LOGGER_CALL_PREFIXES):
                    self.assertNotIn(
                        ", payload)", line_l,
                        msg=(
                            f"crypto route {anchor!r} logs the "
                            f"whole payload object: {line!r}"
                        ),
                    )
                    self.assertNotIn(
                        "(payload)", line_l,
                        msg=(
                            f"crypto route {anchor!r} logs the "
                            f"whole payload object: {line!r}"
                        ),
                    )


class TestRoutesDelegateToSecureItemPath(unittest.TestCase):
    def test_save_routes_do_not_call_encrypt_message_directly(self) -> None:
        for anchor in (
            '@router.post("/crypto/save-wallet-profile")',
            '@router.post("/crypto/save-sensitive-backup")',
            '@router.post("/crypto/save-note")',
        ):
            body = _slice_handler(anchor)
            self.assertNotIn(
                "encrypt_message(", body,
                msg=(
                    f"crypto save route {anchor!r} must delegate "
                    f"to _encrypt_and_write — never call "
                    f"encrypt_message directly."
                ),
            )
            self.assertIn(
                "_encrypt_and_write(", body,
                msg=(
                    f"crypto save route {anchor!r} must call "
                    f"_encrypt_and_write."
                ),
            )

    def test_reveal_route_calls_decrypt_message_at_most_once(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        self.assertLessEqual(
            body.count("decrypt_message("), 1,
            msg=(
                "reveal route should call decrypt_message at most "
                "once (the single safe decryption boundary)."
            ),
        )


class TestRoutesMountedAtRoot(unittest.TestCase):
    def test_all_four_crypto_routes_registered(self) -> None:
        import main
        paths = {r.path for r in main.app.routes}
        for path in (
            "/crypto/save-wallet-profile",
            "/crypto/save-sensitive-backup",
            "/crypto/save-note",
            "/crypto/reveal-sensitive-backup",
        ):
            self.assertIn(
                path, paths,
                msg=f"POST {path} must be mounted at root.",
            )


class TestUnifiedAuthPattern(unittest.TestCase):
    def test_every_route_uses_verify_trusted_device(self) -> None:
        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            self.assertIn(
                "verify_trusted_device", body,
                msg=f"crypto route {anchor!r} must gate on "
                    "verify_trusted_device.",
            )

    def test_every_route_calls_verify_vault_pin(self) -> None:
        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            self.assertIn(
                "verify_vault_pin(", body,
                msg=f"crypto route {anchor!r} must call "
                    "verify_vault_pin.",
            )


class TestSchemaMappingChainCoherent(unittest.TestCase):
    def test_secret_type_to_category_to_schema_round_trips(self) -> None:
        for stype in cs.ALL_SECRET_TYPES:
            cat = cs.category_for_secret_type(stype)
            self.assertIsNotNone(cat,
                msg=f"category_for_secret_type({stype!r}) is None")
            schema = cs.schema_for_category(cat)
            self.assertEqual(
                schema, cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
                msg=f"chain {stype!r} → {cat!r} → {schema!r} broke",
            )

    def test_note_type_to_category_to_schema_round_trips(self) -> None:
        for ntype in cs.ALL_NOTE_TYPES:
            cat = cs.category_for_note_type(ntype)
            self.assertIsNotNone(cat,
                msg=f"category_for_note_type({ntype!r}) is None")
            schema = cs.schema_for_category(cat)
            self.assertEqual(
                schema, cs.SCHEMA_CRYPTO_NOTE_V1,
                msg=f"chain {ntype!r} → {cat!r} → {schema!r} broke",
            )

    def test_wallet_address_category_maps_to_wallet_profile_schema(
        self,
    ) -> None:
        self.assertEqual(
            cs.schema_for_category(t.CATEGORY_CRYPTO_WALLET_ADDRESS),
            cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,
        )


class TestWalletLabelCatalog(unittest.TestCase):
    def test_wallet_labels_pinned(self) -> None:
        self.assertEqual(
            cs.ALL_WALLET_LABELS,
            (
                "MetaMask", "Trust Wallet",
                "Ledger", "Trezor",
                "Binance", "Coinbase", "Custom",
            ),
        )


class TestErrorEnvelopesAreClosedSet(unittest.TestCase):
    def test_no_detail_echoes_payload_value(self) -> None:
        import re
                                                                 
                                                              
        detail_re = re.compile(
            r"detail=\{[^{}\n]*\}",
        )
        for anchor in CRYPTO_ROUTE_ANCHORS:
            body = _slice_handler(anchor)
            for match in detail_re.finditer(body):
                literal = match.group(0)
                for forbidden in (
                    "payload.pin", "payload.secretValue",
                    "payload.publicAddress", "payload.txHash",
                    "payload.walletLabel", "payload.note",
                    "payload.title",
                ):
                    self.assertNotIn(
                        forbidden, literal,
                        msg=(
                            f"crypto route {anchor!r} detail "
                            f"literal echoes {forbidden!r}: "
                            f"{literal!r}"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
