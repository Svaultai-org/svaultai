

from __future__ import annotations

import os
import unittest
from pathlib import Path


_ROUTES_SRC = Path(__file__).parent / "routes" / "crypto_wallet_routes.py"


def _read_routes_src() -> str:
    return _ROUTES_SRC.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    a = src.find(start_marker)
    if a < 0:
        return ""
    b = src.find(end_marker, a + len(start_marker))
    if b < 0:
        return src[a:]
    return src[a:b]


class MainnetBalanceRouteIsolationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = _read_routes_src()
        self._mainnet_balance = _slice_between(
            self._src,
            "def _get_mainnet_balance(",
            "def _list_mainnet_transactions(",
        )
        self.assertGreater(
            len(self._mainnet_balance), 500,
            "Failed to locate _get_mainnet_balance in routes source",
        )

    def test_mainnet_balance_reads_only_mainnet_rpc_helper(self):
        self.assertIn("ethereum_mainnet_rpc_url", self._mainnet_balance)
        self.assertNotIn(
            "ethereum_sepolia_rpc_url", self._mainnet_balance,
            "mainnet balance must not touch sepolia RPC URL helper",
        )

    def test_mainnet_balance_never_imports_sepolia_helpers(self):
        for banned in (
            "ethereum_sepolia_rpc_url",
            "ethereum_sepolia_token_contract",
            "ethereum_sepolia_tx_indexer",
        ):
            self.assertNotIn(banned, self._mainnet_balance)

    def test_mainnet_balance_uses_mainnet_token_contract_registry(self):
        self.assertIn("NETWORK_ETHEREUM_MAINNET", self._mainnet_balance)
        self.assertIn("token_contract_for", self._mainnet_balance)


class MainnetTransactionsRouteIsolationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = _read_routes_src()
        self._mainnet_txs = _slice_between(
            self._src,
            "def _list_mainnet_transactions(",
            "@router",
        )
        self.assertGreater(
            len(self._mainnet_txs), 300,
            "Failed to locate _list_mainnet_transactions",
        )

    def test_mainnet_transactions_never_imports_sepolia_indexer(self):
        for banned in (
            "ethereum_sepolia_tx_indexer_provider",
            "ethereum_sepolia_tx_indexer_api_key",
            "ethereum_sepolia_tx_indexer_base_url",
        ):
            self.assertNotIn(banned, self._mainnet_txs)


class MainnetSendRouteIsolationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = _read_routes_src()

    def test_mainnet_send_broadcast_route_present(self):
        self.assertIn(
            "/crypto/wallet/network/{network}/{asset}/send/broadcast",
            self._src,
        )

    def test_mainnet_send_dispatch_never_falls_through_to_sepolia_rpc(self):
        broadcast_slice = _slice_between(
            self._src,
            "def broadcast_signed_transaction_network(",
            "@router",
        )
        self.assertGreater(len(broadcast_slice), 200)
        mainnet_branch_idx = broadcast_slice.find(
            "NETWORK_ETHEREUM_MAINNET",
        )
        if mainnet_branch_idx > 0:
            mainnet_slice = broadcast_slice[mainnet_branch_idx:]
            self.assertNotIn(
                "ethereum_sepolia_rpc_url", mainnet_slice,
                "mainnet send broadcast branch must not read "
                "sepolia RPC URL",
            )


class MainnetReceiveRouteIsolationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = _read_routes_src()

    def test_mainnet_receive_route_registered(self):
        self.assertIn(
            "/crypto/wallet/network/{network}/{asset}/receive",
            self._src,
        )

    def test_mainnet_receive_helper_never_hardcodes_sepolia_label(self):
        receive_dispatch = _slice_between(
            self._src,
            "def get_wallet_receive_network(",
            "@router",
        )
        self.assertGreater(len(receive_dispatch), 200)
        self.assertNotIn(
            "Ethereum Sepolia", receive_dispatch,
            "mainnet receive dispatch must not hardcode sepolia label",
        )


class FeaturesEnvelopeMainnetShapeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap: dict[str, str | None] = {}
        for k in (
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
            "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            self._snap[k] = os.environ.get(k)
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_mainnet_features_env_reports_mainnet(self):
        os.environ["VAULTAI_CRYPTO_DEFAULT_NETWORK"] = "ethereum_mainnet"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ[
            "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED"
        ] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertEqual(env["defaultNetwork"], "ethereum_mainnet")
        self.assertTrue(env["mainnetReceiveEnabled"])
        self.assertTrue(env["mainnetErc20ReceiveEnabled"])
        self.assertTrue(env["mainnetSendEnabled"])
        self.assertFalse(env["mainnetSendPaused"])

    def test_mainnet_send_paused_surfaces_in_features(self):
        os.environ["VAULTAI_CRYPTO_DEFAULT_NETWORK"] = "ethereum_mainnet"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_MAINNET_SEND_PAUSED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["mainnetSendPaused"])

    def test_disabled_mainnet_receive_reports_disabled(self):
        os.environ["VAULTAI_CRYPTO_DEFAULT_NETWORK"] = "ethereum_mainnet"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "false"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["mainnetReceiveEnabled"])

    def test_features_never_leaks_rpc_url_or_secrets(self):
        os.environ["VAULTAI_CRYPTO_DEFAULT_NETWORK"] = "ethereum_mainnet"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://mainnet.infura.io/v3/leaky-key"
        )
        os.environ["ETHEREUM_MAINNET_TX_INDEXER_API_KEY"] = (
            "leaky-indexer-key"
        )
        try:
            from crypto_wallet_health import build_features_envelope
            env = build_features_envelope()
            blob = repr(env)
            self.assertNotIn("leaky-key", blob)
            self.assertNotIn("leaky-indexer-key", blob)
            self.assertNotIn("infura.io", blob)
        finally:
            os.environ.pop("ETHEREUM_MAINNET_RPC_URL", None)
            os.environ.pop(
                "ETHEREUM_MAINNET_TX_INDEXER_API_KEY", None,
            )


class NoNewChainSurfaceTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap: dict[str, str | None] = {}
        for k in (
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            self._snap[k] = os.environ.get(k)
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_features_envelope_lists_only_ethereum_networks(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertEqual(
            sorted(env["supportedNetworks"]),
            sorted(["ethereum_mainnet", "ethereum_sepolia"]),
        )

    def test_features_envelope_never_lists_solana_tron_bnb_btc_xmr(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        supported = env["supportedNetworks"]
        for banned in (
            "solana_mainnet", "tron_mainnet", "bnb_smart_chain",
            "bitcoin_mainnet", "monero_mainnet", "usdt_trc20_network",
        ):
            self.assertNotIn(banned, supported)

    def test_health_envelope_never_lists_new_chains(self):
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        for net in env["networks"]:
            self.assertIn(
                net["id"],
                ("ethereum_mainnet", "ethereum_sepolia"),
            )


class NoExchangeSurfaceTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap: dict[str, str | None] = {}
        for k in (
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            self._snap[k] = os.environ.get(k)
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_features_envelope_never_contains_exchange_verbs(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        blob = repr(env).lower()
        for banned in ("swap", "stake", "bridge", " buy",
                       " sell", " trade"):
            self.assertNotIn(banned, blob)


class FeaturesRouteFieldsTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap: dict[str, str | None] = {}
        for k in (
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            self._snap[k] = os.environ.get(k)
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_features_envelope_shape_v1_has_all_required_fields(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        for k in (
            "status", "schema", "walletEngineEnabled",
            "sepoliaReceiveEnabled", "sepoliaSendEnabled",
            "mainnetReceiveEnabled", "mainnetErc20ReceiveEnabled",
            "mainnetSendEnabled", "mainnetSendPaused",
            "defaultNetwork", "defaultNetworkConfigValid",
            "supportedNetworks", "supportedAssetsByNetwork",
        ):
            self.assertIn(
                k, env,
                f"features envelope missing required field: {k}",
            )


if __name__ == "__main__":
    unittest.main()
