

from __future__ import annotations

import os
import unittest


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


_ENV_NETWORK = "VAULTAI_CRYPTO_DEFAULT_NETWORK"
_ENV_TOKENS = (
    "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
)


class CryptoDefaultNetworkResolutionTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_unset_defaults_to_sepolia(self) -> None:
        from vault_config import crypto_default_network
        self.assertEqual(crypto_default_network(), "ethereum_sepolia")

    def test_ethereum_mainnet_accepted(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        from vault_config import crypto_default_network
        self.assertEqual(
            crypto_default_network(), "ethereum_mainnet",
        )

    def test_ethereum_sepolia_accepted(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_sepolia"
        from vault_config import crypto_default_network
        self.assertEqual(
            crypto_default_network(), "ethereum_sepolia",
        )

    def test_case_insensitive_and_whitespace_tolerant(self) -> None:
        os.environ[_ENV_NETWORK] = "  Ethereum_Mainnet  "
        from vault_config import crypto_default_network
        self.assertEqual(
            crypto_default_network(), "ethereum_mainnet",
        )

    def test_unknown_value_routes_to_sepolia_fallback(self) -> None:
        os.environ[_ENV_NETWORK] = "solana_mainnet"
        from vault_config import crypto_default_network
        self.assertEqual(
            crypto_default_network(), "ethereum_sepolia",
        )

    def test_unknown_value_never_returns_bitcoin_or_solana(self) -> None:
        for bad in ("bitcoin", "solana", "solana_mainnet",
                    "tron_mainnet", "usdt_trc20", "bnb_smart_chain"):
            with self.subTest(bad=bad):
                os.environ[_ENV_NETWORK] = bad
                from vault_config import crypto_default_network
                self.assertIn(
                    crypto_default_network(),
                    ("ethereum_mainnet", "ethereum_sepolia"),
                )


class CryptoDefaultNetworkConfigValidTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_unset_valid_in_development(self) -> None:
        from vault_config import crypto_default_network_config_valid
        self.assertTrue(crypto_default_network_config_valid())

    def test_unset_invalid_in_production(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        from vault_config import crypto_default_network_config_valid
        self.assertFalse(crypto_default_network_config_valid())

    def test_mainnet_valid_in_production(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        from vault_config import crypto_default_network_config_valid
        self.assertTrue(crypto_default_network_config_valid())

    def test_sepolia_valid_in_production(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ[_ENV_NETWORK] = "ethereum_sepolia"
        from vault_config import crypto_default_network_config_valid
        self.assertTrue(crypto_default_network_config_valid())

    def test_unknown_value_invalid_in_dev_and_prod(self) -> None:
        os.environ[_ENV_NETWORK] = "solana_mainnet"
        from vault_config import crypto_default_network_config_valid
        self.assertFalse(crypto_default_network_config_valid())
        os.environ["VAULTAI_ENV"] = "production"
        self.assertFalse(crypto_default_network_config_valid())


class FeaturesEnvelopeDefaultNetworkTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_envelope_exposes_default_network(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertEqual(env["defaultNetwork"], "ethereum_mainnet")
        self.assertTrue(env["defaultNetworkConfigValid"])

    def test_features_envelope_default_network_sepolia(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_sepolia"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertEqual(env["defaultNetwork"], "ethereum_sepolia")
        self.assertTrue(env["defaultNetworkConfigValid"])

    def test_features_envelope_unknown_flags_invalid(self) -> None:
        os.environ[_ENV_NETWORK] = "solana_mainnet"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertIn(env["defaultNetwork"],
                      ("ethereum_mainnet", "ethereum_sepolia"))
        self.assertFalse(env["defaultNetworkConfigValid"])

    def test_features_envelope_never_exposes_rpc_url(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://mainnet.infura.io/v3/secret-key"
        )
        try:
            from crypto_wallet_health import build_features_envelope
            env = build_features_envelope()
            for v in env.values():
                if isinstance(v, str):
                    self.assertNotIn("secret-key", v)
                    self.assertNotIn("infura.io", v)
        finally:
            os.environ.pop("ETHEREUM_MAINNET_RPC_URL", None)


class HealthEnvelopeDefaultNetworkTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_health_envelope_exposes_default_network(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        self.assertEqual(env["defaultNetwork"], "ethereum_mainnet")
        self.assertTrue(env["defaultNetworkConfigValid"])

    def test_health_envelope_never_exposes_secrets(self) -> None:
        os.environ[_ENV_NETWORK] = "ethereum_mainnet"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://mainnet.infura.io/v3/leaky-key"
        )
        os.environ["ETHEREUM_MAINNET_TX_INDEXER_API_KEY"] = (
            "leaky-etherscan-key"
        )
        try:
            from crypto_wallet_health import build_health_envelope
            env = build_health_envelope()
            blob = repr(env)
            self.assertNotIn("leaky-key", blob)
            self.assertNotIn("leaky-etherscan-key", blob)
            self.assertNotIn("infura.io", blob)
        finally:
            os.environ.pop("ETHEREUM_MAINNET_RPC_URL", None)
            os.environ.pop(
                "ETHEREUM_MAINNET_TX_INDEXER_API_KEY", None,
            )

    def test_health_envelope_unknown_default_marks_not_ready(self) -> None:
        os.environ[_ENV_NETWORK] = "solana_mainnet"
        from crypto_wallet_health import (
            OVERALL_NOT_READY,
            build_health_envelope,
        )
        env = build_health_envelope()
        self.assertEqual(env["overallStatus"], OVERALL_NOT_READY)
        self.assertFalse(env["defaultNetworkConfigValid"])


class ChatDefaultNetworkTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_chat_parser_accepts_mainnet_default(self) -> None:
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my ETH balance",
            default_network="ethereum_mainnet",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["network"], "ethereum_mainnet")

    def test_chat_parser_accepts_sepolia_default(self) -> None:
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my ETH balance",
            default_network="ethereum_sepolia",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["network"], "ethereum_sepolia")

    def test_chat_explicit_sepolia_overrides_mainnet_default(self) -> None:
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my ETH balance on sepolia",
            default_network="ethereum_mainnet",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["network"], "ethereum_sepolia")

    def test_chat_explicit_mainnet_overrides_sepolia_default(self) -> None:
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my ETH balance on mainnet",
            default_network="ethereum_sepolia",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["network"], "ethereum_mainnet")

    def test_main_py_threads_default_network_into_parser(self) -> None:
        src = (
            open("main.py", "r", encoding="utf-8").read()
        )
        self.assertIn("crypto_default_network", src)
        self.assertIn(
            "default_network=crypto_default_network()", src,
        )


class MainPyImportSurfaceTests(unittest.TestCase):

    def test_vault_config_exports_default_network_helpers(self) -> None:
        import vault_config
        self.assertIn(
            "crypto_default_network", vault_config.__all__,
        )
        self.assertIn(
            "crypto_default_network_config_valid",
            vault_config.__all__,
        )


class NonExchangeSurfaceTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(_ENV_NETWORK, *_ENV_TOKENS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_envelope_supported_networks_ethereum_only(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        supported = env["supportedNetworks"]
        for banned in (
            "bitcoin_mainnet", "solana_mainnet",
            "tron_mainnet", "bnb_smart_chain", "monero_mainnet",
        ):
            self.assertNotIn(banned, supported)
        self.assertEqual(
            sorted(supported),
            sorted(["ethereum_sepolia", "ethereum_mainnet"]),
        )

    def test_features_envelope_supported_assets_no_swap_stake(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        blob = repr(env).lower()
        for banned in ("swap", "stake", "bridge",
                       "trade", "buy", "sell"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
