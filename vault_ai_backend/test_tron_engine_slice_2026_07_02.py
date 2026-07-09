

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock


_BACKEND_ROOT = Path(__file__).parent


def _wipe_env(*names: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore_env(snap: dict[str, str | None]) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_TRON_ENV_KEYS = (
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "TRON_API_BASE_URL",
    "TRON_RPC_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "TRON_USDT_DECIMALS",
)


TRON_USDT_MAINNET: str = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"


def _derive_burn_tron_address() -> str:
    from tron_rpc import hex_to_tron_address
    return hex_to_tron_address("00" * 20)


class TronConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_tron_disabled_by_default(self):
        from vault_config import tron_enabled
        self.assertFalse(tron_enabled())

    def test_tron_api_base_url_empty_by_default(self):
        from vault_config import tron_api_base_url
        self.assertEqual(tron_api_base_url(), "")

    def test_tron_api_key_empty_by_default(self):
        from vault_config import tron_api_key
        self.assertEqual(tron_api_key(), "")

    def test_tron_usdt_contract_empty_by_default(self):
        from vault_config import tron_usdt_contract_address
        self.assertEqual(tron_usdt_contract_address(), "")

    def test_tron_usdt_decimals_default_6(self):
        from vault_config import tron_usdt_decimals
        self.assertEqual(tron_usdt_decimals(), 6)

    def test_tron_enabled_when_env_true(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from vault_config import tron_enabled
        self.assertTrue(tron_enabled())

    def test_tron_api_base_url_from_env(self):
        os.environ["TRON_API_BASE_URL"] = "https://api.trongrid.io"
        from vault_config import tron_api_base_url
        self.assertEqual(tron_api_base_url(), "https://api.trongrid.io")

    def test_tron_rpc_url_fallback_used_when_no_base(self):
        os.environ["TRON_RPC_URL"] = "https://api.trongrid.io"
        from vault_config import tron_api_base_url
        self.assertEqual(tron_api_base_url(), "https://api.trongrid.io")


class TronAddressValidationTests(unittest.TestCase):

    def test_valid_usdt_contract_address(self):
        from tron_rpc import is_valid_tron_address
        self.assertTrue(is_valid_tron_address(TRON_USDT_MAINNET))

    def test_burn_address_via_hex_derivation_is_valid(self):
        from tron_rpc import is_valid_tron_address
        addr = _derive_burn_tron_address()
        self.assertTrue(addr.startswith("T"))
        self.assertTrue(is_valid_tron_address(addr))

    def test_invalid_empty_address(self):
        from tron_rpc import is_valid_tron_address
        self.assertFalse(is_valid_tron_address(""))
        self.assertFalse(is_valid_tron_address(None))

    def test_wrong_prefix_rejected(self):
        from tron_rpc import is_valid_tron_address
        self.assertFalse(is_valid_tron_address(
            "A" + TRON_USDT_MAINNET[1:],
        ))

    def test_ethereum_address_rejected(self):
        from tron_rpc import is_valid_tron_address
        self.assertFalse(is_valid_tron_address(
            "0x" + "a" * 40,
        ))

    def test_bad_checksum_rejected(self):
        from tron_rpc import is_valid_tron_address
        broken = list(TRON_USDT_MAINNET)
        broken[-1] = "9" if broken[-1] != "9" else "A"
        self.assertFalse(is_valid_tron_address("".join(broken)))

    def test_short_address_rejected(self):
        from tron_rpc import is_valid_tron_address
        self.assertFalse(is_valid_tron_address("T" + "1" * 5))

    def test_hex_roundtrip_matches_original(self):
        from tron_rpc import (
            tron_address_to_hex, hex_to_tron_address,
        )
        h = tron_address_to_hex(TRON_USDT_MAINNET)
        self.assertEqual(len(h), 42)
        self.assertTrue(h.startswith("41"))
        back = hex_to_tron_address(h)
        self.assertEqual(back, TRON_USDT_MAINNET)


class TronBalanceFormattingTests(unittest.TestCase):

    def test_zero(self):
        from tron_rpc import base_units_to_decimal_string
        self.assertEqual(base_units_to_decimal_string(0, 6), "0")

    def test_one_micro_usdt(self):
        from tron_rpc import base_units_to_decimal_string
        self.assertEqual(
            base_units_to_decimal_string(1, 6), "0.000001",
        )

    def test_one_full_usdt(self):
        from tron_rpc import base_units_to_decimal_string
        self.assertEqual(
            base_units_to_decimal_string(1_000_000, 6), "1",
        )

    def test_partial_usdt(self):
        from tron_rpc import base_units_to_decimal_string
        self.assertEqual(
            base_units_to_decimal_string(1_500_000, 6), "1.5",
        )

    def test_1234_usdt(self):
        from tron_rpc import base_units_to_decimal_string
        self.assertEqual(
            base_units_to_decimal_string(1_234_567_890, 6),
            "1234.56789",
        )


class TronAssetCatalogFeaturesTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_default_tron_disabled(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["tronEnabled"])
        self.assertFalse(env["tronReceiveEnabled"])
        self.assertFalse(env["tronBalanceEnabled"])
        self.assertFalse(env["tronSendEnabled"])
        self.assertFalse(env["tronActivityConnected"])

    def test_features_tron_enabled_flags(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://api.trongrid.io"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["tronEnabled"])
        self.assertTrue(env["tronReceiveEnabled"])
        self.assertTrue(env["tronBalanceEnabled"])
        self.assertFalse(env["tronSendEnabled"])
        self.assertFalse(env["tronActivityConnected"])

    def test_features_tron_supported_networks_and_assets(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertIn("tron_mainnet", env["supportedNetworks"])
        self.assertEqual(
            env["supportedAssetsByNetwork"]["tron_mainnet"],
            ["USDT_TRC20"],
        )

    def test_features_tron_disabled_hides_network(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertNotIn("tron_mainnet", env["supportedNetworks"])
        self.assertNotIn(
            "tron_mainnet", env["supportedAssetsByNetwork"],
        )

    def test_features_never_exposes_tron_rpc_url_or_api_key(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = (
            "https://api.trongrid.io/?key=leaky-tron-key"
        )
        os.environ["TRON_API_KEY"] = "leaky-tron-api"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        blob = repr(env)
        self.assertNotIn("leaky-tron-key", blob)
        self.assertNotIn("leaky-tron-api", blob)
        self.assertNotIn("trongrid.io", blob)


class TronHealthEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_health_includes_tron_section(self):
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        self.assertIn("tron", env)
        tron = env["tron"]
        self.assertEqual(tron["id"], "tron_mainnet")
        self.assertFalse(tron["tronEnabled"])
        self.assertFalse(tron["tronSendEnabled"])
        self.assertFalse(tron["tronActivityConnected"])

    def test_health_tron_flags_when_enabled(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://api.trongrid.io"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        with mock.patch(
            "tron_rpc.tron_get_health_at_url", return_value=True,
        ):
            from crypto_wallet_health import build_health_envelope
            env = build_health_envelope()
        tron = env["tron"]
        self.assertTrue(tron["tronEnabled"])
        self.assertTrue(tron["tronConfigured"])
        self.assertTrue(tron["tronRpcReachable"])
        self.assertTrue(tron["tronUsdtContractConfigured"])
        self.assertTrue(tron["tronBalanceReadReady"])
        self.assertFalse(tron["tronSendEnabled"])
        self.assertFalse(tron["tronActivityConnected"])

    def test_health_never_exposes_rpc_url_or_api_key(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = (
            "https://api.trongrid.io/?key=leaky-tron"
        )
        os.environ["TRON_API_KEY"] = "leaky-tron-key"
        with mock.patch(
            "tron_rpc.tron_get_health_at_url", return_value=False,
        ):
            from crypto_wallet_health import build_health_envelope
            env = build_health_envelope()
        blob = repr(env)
        self.assertNotIn("leaky-tron", blob)
        self.assertNotIn("trongrid.io", blob)


class TronRouteBranchSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")

    def test_tron_network_constant_present(self):
        self.assertIn("NETWORK_TRON_MAINNET", self._src)
        self.assertIn('"tron_mainnet"', self._src)

    def test_receive_branch_present(self):
        self.assertIn("_tron_receive", self._src)
        self.assertIn(
            "if nid == NETWORK_TRON_MAINNET:", self._src,
        )

    def test_balance_branch_present(self):
        self.assertIn("_tron_balance", self._src)

    def test_transactions_branch_present(self):
        self.assertIn("_tron_transactions", self._src)

    def test_create_branch_present(self):
        self.assertIn("_create_tron_wallet_account", self._src)

    def test_send_disabled_envelope_used_for_tron(self):
        self.assertIn(
            "_tron_send_not_enabled_envelope", self._src,
        )

    def test_no_backend_signing_for_tron(self):
        low = self._src.lower()
        self.assertNotIn("tron_sign_transaction", low)
        self.assertNotIn("tron_send_raw", low)
        self.assertNotIn("broadcasttransaction", low)


class TronRouteBehaviorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_tron_receive_disabled_when_flag_off(self):
        from routes.crypto_wallet_routes import _tron_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_receive("USDT_TRC20", principal)
        self.assertEqual(result["wallet_engine"], "tron_not_enabled")
        self.assertEqual(result["network"], "tron_mainnet")

    def test_tron_receive_no_wallet_prompts_create(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = _tron_receive("USDT_TRC20", principal)
        self.assertEqual(
            result["wallet_engine"], "create_tron_wallet_first",
        )
        self.assertEqual(result["tokenStandard"], "TRC20")

    def test_tron_receive_ready_returns_address_and_warning(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={
                "walletLabel":   "My TRON",
                "publicAddress": TRON_USDT_MAINNET,
            },
        ):
            result = _tron_receive("USDT_TRC20", principal)
        self.assertEqual(result["wallet_engine"], "receive_ready")
        self.assertEqual(result["publicAddress"], TRON_USDT_MAINNET)
        self.assertIn("USDT TRC20 on TRON", result["warning"])
        self.assertIn("TRX", result["gasNote"])
        self.assertNotIn("Ethereum", result["warning"])
        self.assertNotIn("Solana",   result["warning"])
        self.assertNotIn("ERC20",    result["warning"])
        self.assertNotIn("Sepolia",  result["warning"])

    def test_tron_balance_reports_rpc_not_configured(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_balance(
            "USDT_TRC20", TRON_USDT_MAINNET, principal,
        )
        self.assertEqual(result["balanceStatus"], "unavailable")


        self.assertEqual(result["reason"], "tron_api_not_configured")

    def test_tron_balance_reports_no_wallet_yet_without_address(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = _tron_balance("USDT_TRC20", None, principal)
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(result["reason"], "no_wallet_yet")

    def test_tron_balance_invalid_address_reason(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        from routes.crypto_wallet_routes import _tron_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_balance("USDT_TRC20", "notanaddr", principal)
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(result["reason"], "invalid_address")

    def test_tron_balance_no_contract_reports_config(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        from routes.crypto_wallet_routes import _tron_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_balance(
            "USDT_TRC20", TRON_USDT_MAINNET, principal,
        )
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(
            result["reason"], "tron_contract_not_configured",
        )

    def test_tron_balance_zero_returns_real_zero(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        with mock.patch(
            "tron_rpc.tron_get_trc20_balance_at_url",
            return_value=0,
        ):
            from routes.crypto_wallet_routes import _tron_balance
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _tron_balance(
                "USDT_TRC20", TRON_USDT_MAINNET, principal,
            )
        self.assertEqual(result["balanceStatus"], "available")
        self.assertEqual(result["availableAmount"], "0")
        self.assertEqual(result["unit"], "USDT")
        self.assertEqual(result["baseUnits"], "0")

    def test_tron_balance_positive_returns_6_decimal_usdt(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        with mock.patch(
            "tron_rpc.tron_get_trc20_balance_at_url",
            return_value=1_234_500_000,
        ):
            from routes.crypto_wallet_routes import _tron_balance
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _tron_balance(
                "USDT_TRC20", TRON_USDT_MAINNET, principal,
            )
        self.assertEqual(result["availableAmount"], "1234.5")
        self.assertEqual(result["unit"], "USDT")
        self.assertEqual(result["decimals"], 6)

    def test_tron_transactions_returns_honest_unavailable(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_transactions
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_transactions("USDT_TRC20", 20, principal)
        self.assertEqual(result["transactionsStatus"], "unavailable")
        self.assertEqual(
            result["reason"], "tron_activity_not_connected",
        )
        self.assertEqual(result["transactions"], [])

    def test_tron_send_draft_returns_not_enabled(self):
        from routes.crypto_wallet_routes import (
            _tron_send_not_enabled_envelope,
        )
        result = _tron_send_not_enabled_envelope("USDT_TRC20")
        self.assertEqual(
            result["wallet_engine"], "tron_send_not_enabled",
        )
        self.assertIn("not enabled", result["message"].lower())

    def test_tron_transaction_status_returns_unavailable(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import (
            _tron_transaction_status,
        )
        result = _tron_transaction_status(
            "USDT_TRC20", "a" * 64,
        )
        self.assertEqual(result["transactionStatus"], "unavailable")


        self.assertIn(
            result["reason"],
            ("tron_api_not_configured", "rpc_not_configured"),
        )


class TronCreateRouteTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_create_disabled_when_flag_off(self):
        from routes.crypto_wallet_routes import (
            _create_tron_wallet_account,
        )
        from routes.crypto_wallet_routes import CreateWalletPayload
        payload = CreateWalletPayload(
            walletLabel="My TRON",
            publicAddress=TRON_USDT_MAINNET,
            network="tron_mainnet",
            encryptedWalletSecret="ciphertext-here-xxxxx",
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _create_tron_wallet_account(
            "USDT_TRC20", payload, principal,
        )
        self.assertEqual(result["wallet_engine"], "tron_not_enabled")

    def test_create_rejects_invalid_tron_address(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _create_tron_wallet_account,
        )
        from routes.crypto_wallet_routes import CreateWalletPayload
        payload = CreateWalletPayload(
            walletLabel="My TRON",
            publicAddress="0x" + "a" * 40,
            network="tron_mainnet",
            encryptedWalletSecret="ciphertext-here-xxxxx",
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with self.assertRaises(HTTPException) as ctx:
            _create_tron_wallet_account(
                "USDT_TRC20", payload, principal,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_create_stores_ciphertext_only(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import (
            _create_tron_wallet_account,
        )
        from routes.crypto_wallet_routes import CreateWalletPayload

        payload = CreateWalletPayload(
            walletLabel="My TRON",
            publicAddress=TRON_USDT_MAINNET,
            network="tron_mainnet",
            encryptedWalletSecret="ciphertext-here-xxxxx",
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        captured: dict[str, dict] = {}

        def _fake_insert(vault_id, asset, network_id, record):
            captured["record"] = record

        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_insert_wallet_account_record_network",
            side_effect=_fake_insert,
        ):
            result = _create_tron_wallet_account(
                "USDT_TRC20", payload, principal,
            )
        self.assertEqual(result["wallet_engine"], "created")
        rec = captured["record"]
        self.assertEqual(rec["asset"], "USDT_TRC20")
        self.assertEqual(rec["network"], "tron_mainnet")
        self.assertEqual(rec["tokenStandard"], "TRC20")
        self.assertEqual(rec["keyOrigin"], "generated_client_side")
        self.assertEqual(rec["signingMode"], "client_side")
        self.assertEqual(
            rec["encryptedWalletSecret"], "ciphertext-here-xxxxx",
        )


class TronPlaintextKeyRejectionTests(unittest.TestCase):

    def test_plaintext_private_key_rejected(self):
        from crypto_wallet_schemas import (
            PlaintextKeyRejected, rejects_plaintext_secret,
        )
        with self.assertRaises(PlaintextKeyRejected):
            rejects_plaintext_secret({
                "publicAddress": TRON_USDT_MAINNET,
                "tronPrivateKey": "beef" * 16,
            })

    def test_plaintext_seed_phrase_rejected(self):
        from crypto_wallet_schemas import (
            PlaintextKeyRejected, rejects_plaintext_secret,
        )
        with self.assertRaises(PlaintextKeyRejected):
            rejects_plaintext_secret({
                "publicAddress": TRON_USDT_MAINNET,
                "seedPhrase": "abandon " * 12,
            })


class TronChatIntentTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_show_usdt_trc20_wallet_when_disabled_is_unsupported(self):
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my USDT TRC20 wallet",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_TRC20")
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_receive_usdt_trc20_when_enabled_routes_to_tron(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "give me my USDT TRC20 receive address",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_TRC20")
        self.assertEqual(parsed["network"], "tron_mainnet")
        self.assertEqual(parsed["intent"], "receive_address")

    def test_send_usdt_trc20_when_enabled_is_unsupported(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "send 5 USDT TRC20 to somewhere",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_TRC20")
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_tron_alias_detected_as_network(self):
        from wallet_engine_chat import _detect_network
        self.assertEqual(_detect_network("show my tron wallet"),
                         "tron_mainnet")
        self.assertEqual(_detect_network("TRC20 balance please"),
                         "tron_mainnet")


class TronRpcModuleGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (_BACKEND_ROOT / "tron_rpc.py").read_text(
            encoding="utf-8",
        )

    def test_no_transaction_signing_helpers(self):
        low = self._src.lower()
        self.assertNotIn("sign_transaction", low)
        self.assertNotIn("createtransaction", low)
        self.assertNotIn("privatekey", low)

    def test_no_seed_or_mnemonic_helpers(self):
        low = self._src.lower()
        self.assertNotIn("mnemonic", low)
        self.assertNotIn("seed_phrase", low)
        self.assertNotIn("recovery_phrase", low)


class NoFakeTronCopyOrExchangeCopyTests(unittest.TestCase):

    def test_routes_have_no_buy_sell_swap_trade(self):
        src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8").lower()
        for word in ["buy usdt", "sell usdt", "swap usdt",
                     "trade usdt", "stake usdt", "bridge usdt"]:
            self.assertNotIn(word, src)

    def test_tron_rpc_never_hardcodes_fake_address(self):
        src = (_BACKEND_ROOT / "tron_rpc.py").read_text(
            encoding="utf-8",
        )
        self.assertNotIn("TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", src)


if __name__ == "__main__":
    unittest.main()
