

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


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


_SOLANA_ENV_KEYS = (
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "SOLANA_RPC_URL",
    "SOLANA_TX_INDEXER_PROVIDER",
    "SOLANA_TX_INDEXER_API_KEY",
    "SOLANA_TX_INDEXER_BASE_URL",
)


_VALID_SOLANA_ADDR_1 = "So11111111111111111111111111111111111111112"
_VALID_SOLANA_ADDR_2 = "11111111111111111111111111111111"


class SolanaConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_solana_disabled_by_default(self):
        from vault_config import solana_enabled
        self.assertFalse(solana_enabled())

    def test_solana_enabled_when_env_true(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from vault_config import solana_enabled
        self.assertTrue(solana_enabled())

    def test_solana_rpc_url_empty_by_default(self):
        from vault_config import solana_rpc_url
        self.assertEqual(solana_rpc_url(), "")

    def test_solana_tx_indexer_unconfigured_by_default(self):
        from vault_config import solana_tx_indexer_configured
        self.assertFalse(solana_tx_indexer_configured())


class SolanaAddressValidationTests(unittest.TestCase):

    def test_valid_solana_native_program_ids(self):
        from solana_rpc import is_valid_solana_address
        self.assertTrue(is_valid_solana_address(_VALID_SOLANA_ADDR_1))
        self.assertTrue(is_valid_solana_address(_VALID_SOLANA_ADDR_2))

    def test_invalid_empty_address(self):
        from solana_rpc import is_valid_solana_address
        self.assertFalse(is_valid_solana_address(""))
        self.assertFalse(is_valid_solana_address(None))

    def test_invalid_shape_rejected(self):
        from solana_rpc import is_valid_solana_address
        for bad in (
            "0000000000000000000000000000000000000000",
            "1234",
            "not-a-solana-addr",
            "1" * 60,
            "OIl0",
        ):
            self.assertFalse(is_valid_solana_address(bad))

    def test_ethereum_address_shape_rejected(self):
        from solana_rpc import is_valid_solana_address
        self.assertFalse(is_valid_solana_address(
            "0x" + "a" * 40,
        ))


class LamportsFormattingTests(unittest.TestCase):

    def test_zero_lamports(self):
        from solana_rpc import lamports_to_sol_string
        self.assertEqual(lamports_to_sol_string(0), "0")

    def test_one_lamport(self):
        from solana_rpc import lamports_to_sol_string
        self.assertEqual(
            lamports_to_sol_string(1), "0.000000001",
        )

    def test_one_full_sol(self):
        from solana_rpc import lamports_to_sol_string
        self.assertEqual(
            lamports_to_sol_string(1_000_000_000), "1",
        )

    def test_partial_sol(self):
        from solana_rpc import lamports_to_sol_string
        self.assertEqual(
            lamports_to_sol_string(1_500_000_000), "1.5",
        )


class SolanaFeaturesEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_default_solana_disabled(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["solanaEnabled"])
        self.assertFalse(env["solanaReceiveEnabled"])
        self.assertFalse(env["solanaSendEnabled"])
        self.assertFalse(env["solanaBalanceEnabled"])

    def test_features_solana_enabled_flags_present(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://api.mainnet-beta.example"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["solanaEnabled"])
        self.assertTrue(env["solanaReceiveEnabled"])
        self.assertFalse(env["solanaSendEnabled"])
        self.assertTrue(env["solanaBalanceEnabled"])

    def test_features_solana_supported_networks(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertIn("solana_mainnet", env["supportedNetworks"])
        self.assertEqual(
            env["supportedAssetsByNetwork"]["solana_mainnet"], ["SOL"],
        )

    def test_features_solana_never_exposes_rpc_url(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = (
            "https://mainnet.helius-rpc.com/?api-key=leaky-solana-key"
        )
        os.environ["SOLANA_TX_INDEXER_API_KEY"] = "leaky-indexer-sol"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        blob = repr(env)
        self.assertNotIn("leaky-solana-key", blob)
        self.assertNotIn("leaky-indexer-sol", blob)
        self.assertNotIn("helius-rpc.com", blob)


class SolanaHealthEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_health_includes_solana_section(self):
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        self.assertIn("solana", env)
        sol = env["solana"]
        self.assertEqual(sol["id"], "solana_mainnet")
        self.assertFalse(sol["solanaEnabled"])
        self.assertFalse(sol["solanaSendEnabled"])

    def test_health_never_exposes_rpc_url_or_api_key(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = (
            "https://mainnet.helius-rpc.com/?api-key=leaky-sol"
        )
        os.environ["SOLANA_TX_INDEXER_API_KEY"] = "leaky-sol-indexer"
        with mock.patch(
            "solana_rpc.sol_get_health_at_url", return_value=False,
        ):
            from crypto_wallet_health import build_health_envelope
            env = build_health_envelope()
        blob = repr(env)
        self.assertNotIn("leaky-sol", blob)
        self.assertNotIn("helius-rpc.com", blob)


class SolanaRouteBranchSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")

    def test_receive_branch_present(self):
        self.assertIn("_solana_receive", self._src)
        self.assertIn(
            "if nid == NETWORK_SOLANA_MAINNET:", self._src,
        )

    def test_balance_branch_present(self):
        self.assertIn("_solana_balance", self._src)

    def test_transactions_branch_present(self):
        self.assertIn("_solana_transactions", self._src)

    def test_create_branch_present(self):
        self.assertIn("_create_solana_wallet_account", self._src)

    def test_send_disabled_envelope_used_for_solana(self):
        self.assertIn(
            "_solana_send_not_enabled_envelope", self._src,
        )

    def test_no_backend_signing_for_solana(self):
        low = self._src.lower()
        self.assertNotIn("solana.transaction.sign", low)
        self.assertNotIn("solana_send_transaction", low)


class SolanaRouteBehaviorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_solana_receive_disabled_when_flag_off(self):
        from routes.crypto_wallet_routes import _solana_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _solana_receive("SOL", principal)
        self.assertEqual(result["wallet_engine"], "solana_not_enabled")

    def test_solana_balance_reports_rpc_not_configured(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _solana_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _solana_balance(
            "SOL", _VALID_SOLANA_ADDR_1, principal,
        )
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(result["reason"], "rpc_not_configured")

    def test_solana_balance_invalid_address_reason(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://x.example"
        from routes.crypto_wallet_routes import _solana_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _solana_balance("SOL", "notanaddress", principal)
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(result["reason"], "invalid_address")

    def test_solana_balance_zero_returns_real_zero(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://x.example"
        with mock.patch(
            "solana_rpc.sol_get_balance_lamports_at_url",
            return_value=0,
        ):
            from routes.crypto_wallet_routes import _solana_balance
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _solana_balance(
                "SOL", _VALID_SOLANA_ADDR_1, principal,
            )
        self.assertEqual(result["balanceStatus"], "available")
        self.assertEqual(result["availableAmount"], "0")
        self.assertEqual(result["unit"], "SOL")
        self.assertEqual(result["lamports"], "0")

    def test_solana_balance_positive_returns_formatted_sol(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://x.example"
        with mock.patch(
            "solana_rpc.sol_get_balance_lamports_at_url",
            return_value=1_234_500_000,
        ):
            from routes.crypto_wallet_routes import _solana_balance
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _solana_balance(
                "SOL", _VALID_SOLANA_ADDR_1, principal,
            )
        self.assertEqual(result["availableAmount"], "1.2345")

    def test_solana_transactions_returns_honest_unavailable(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _solana_transactions
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = _solana_transactions("SOL", 20, principal)
        self.assertEqual(result["transactionsStatus"], "unavailable")
        self.assertEqual(result["reason"], "no_wallet_yet")
        self.assertEqual(result["transactions"], [])

    def test_solana_send_draft_returns_not_enabled(self):
        from routes.crypto_wallet_routes import (
            _solana_send_not_enabled_envelope,
        )
        result = _solana_send_not_enabled_envelope("SOL")
        self.assertEqual(
            result["wallet_engine"], "solana_send_not_enabled",
        )
        self.assertIn("not enabled", result["message"].lower())


class PlaintextKeyAliasRejectionTests(unittest.TestCase):

    def test_solana_private_key_alias_rejected(self):
        from crypto_wallet_schemas import (
            PlaintextKeyRejected, rejects_plaintext_secret,
        )
        for alias in (
            "solanaPrivateKey", "solana_private_key",
            "solanaSecretKey", "solana_secret_key",
            "solanaSeedPhrase", "solanaMnemonic",
        ):
            with self.subTest(alias=alias):
                with self.assertRaises(PlaintextKeyRejected):
                    rejects_plaintext_secret({alias: "leaked"})

    def test_solana_send_txn_alias_rejected(self):
        from crypto_wallet_schemas import (
            PlaintextKeyRejected, rejects_plaintext_secret,
        )
        with self.assertRaises(PlaintextKeyRejected):
            rejects_plaintext_secret({
                "solana_recovery_phrase": "leaked",
            })

    def test_encrypted_secret_alone_not_rejected(self):
        from crypto_wallet_schemas import rejects_plaintext_secret
        rejects_plaintext_secret({
            "encryptedWalletSecret": "ciphertext",
            "publicAddress": _VALID_SOLANA_ADDR_1,
        })


class ChatParserSolanaTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_chat_sol_disabled_returns_unsupported(self):
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my SOL balance",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_chat_sol_enabled_routes_to_solana_mainnet(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my SOL balance",
        )
        self.assertEqual(parsed["network"], "solana_mainnet")
        self.assertEqual(parsed["asset"], "SOL")

    def test_chat_solana_wallet_routes_to_solana_mainnet(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my Solana wallet",
        )
        self.assertEqual(parsed["network"], "solana_mainnet")

    def test_chat_sol_receive_intent(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "give me my SOL receive address",
        )
        self.assertEqual(parsed["intent"], "receive_address")
        self.assertEqual(parsed["network"], "solana_mainnet")

    def test_chat_sol_send_disabled_even_when_solana_enabled(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "send 0.5 SOL to abc",
        )
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_chat_sol_never_routes_to_ethereum_when_enabled(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my SOL balance",
        )
        self.assertNotIn(parsed["network"], (
            "ethereum_sepolia", "ethereum_mainnet",
        ))


class NoBackendSigningImportsTests(unittest.TestCase):

    def test_solana_rpc_does_not_import_transaction_signer(self):
        src = (_BACKEND_ROOT / "solana_rpc.py").read_text(
            encoding="utf-8",
        )
        low = src.lower()
        for banned in (
            "sign_transaction", "signtransaction",
            "solana.transaction.sign",
            "ed25519.sign",
        ):
            self.assertNotIn(banned, low,
                             f"solana_rpc.py leaked signer symbol: "
                             f"{banned}")

    def test_solana_helpers_never_reference_seed_or_private_key(self):
        src = (_BACKEND_ROOT / "solana_rpc.py").read_text(
            encoding="utf-8",
        )
        low = src.lower()
        for banned in (
            "seed_phrase", "seedphrase", "private_key",
            "privatekey", "mnemonic",
        ):
            self.assertNotIn(banned, low,
                             f"solana_rpc.py leaked banned token: "
                             f"{banned}")


class NoExchangeCopyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_solana_receive_copy_no_exchange_verbs(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _solana_receive
        principal = {
            "vault_id": "00000000-0000-0000-0000-000000000000",
        }
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            blob = repr(
                _solana_receive("SOL", principal),
            ).lower()
        for banned in ("swap", "stake", "bridge",
                       " buy ", " sell ", " trade "):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
