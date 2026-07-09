


from __future__ import annotations

from typing import Any


CRYPTO_WALLET_DIAGNOSIS_SCHEMA: str = "crypto_wallet_diagnosis_v1"


DIAG_REASON_FEATURE_DISABLED:      str = "feature_disabled"
DIAG_REASON_RPC_NOT_CONFIGURED:    str = "rpc_not_configured"
DIAG_REASON_TOKEN_CONTRACT:        str = "token_contract_not_configured"
DIAG_REASON_READY:                 str = "ready"


ROW_ETHEREUM_MAINNET_ETH:          str = "ethereum_mainnet_eth"
ROW_ETHEREUM_MAINNET_USDT_ERC20:   str = "ethereum_mainnet_usdt_erc20"
ROW_ETHEREUM_MAINNET_USDC_ERC20:   str = "ethereum_mainnet_usdc_erc20"
ROW_SOLANA_MAINNET_SOL:            str = "solana_mainnet_sol"
ROW_TRON_MAINNET_USDT_TRC20:       str = "tron_mainnet_usdt_trc20"
ROW_MONERO_MAINNET_XMR:            str = "monero_mainnet_xmr"


def _diagnosis_reason(
    *,
    feature_enabled: bool,
    rpc_configured: bool,
    token_contract_required: bool,
    token_contract_configured: bool,
) -> str:


    if not feature_enabled:
        return DIAG_REASON_FEATURE_DISABLED
    if not rpc_configured:
        return DIAG_REASON_RPC_NOT_CONFIGURED
    if token_contract_required and not token_contract_configured:
        return DIAG_REASON_TOKEN_CONTRACT
    return DIAG_REASON_READY


def _ethereum_mainnet_rows() -> list[dict[str, Any]]:


    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, is_receive_enabled, token_contract_for,
    )
    from vault_config import (
        crypto_wallet_engine_enabled,
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_rpc_url,
    )

    engine_on = crypto_wallet_engine_enabled()
    receive_on = is_receive_enabled(NETWORK_ETHEREUM_MAINNET)
    erc20_on = ethereum_mainnet_erc20_receive_enabled()
    rpc_configured = bool(ethereum_mainnet_rpc_url())
    usdt_contract_configured = bool(
        token_contract_for(NETWORK_ETHEREUM_MAINNET, "USDT_ERC20"),
    )
    usdc_contract_configured = bool(
        token_contract_for(NETWORK_ETHEREUM_MAINNET, "USDC_ERC20"),
    )

    eth_feature = engine_on and receive_on
    usdt_feature = engine_on and receive_on and erc20_on
    usdc_feature = engine_on and receive_on and erc20_on

    def _row(
        *,
        row_id: str,
        asset: str,
        display_name: str,
        network_id: str,
        feature_enabled: bool,
        feature_flag_env: str,
        rpc_env_var: str,
        rpc_configured: bool,
        token_contract_required: bool,
        token_contract_configured: bool,
        token_contract_env_var: str,
    ) -> dict[str, Any]:
        return {
            "rowId":                     row_id,
            "asset":                     asset,
            "displayName":               display_name,
            "network":                   network_id,
            "featureEnabled":            feature_enabled,
            "featureFlagEnvVar":         feature_flag_env,
            "rpcConfigured":             rpc_configured,
            "rpcEnvVar":                 rpc_env_var,
            "tokenContractRequired":     token_contract_required,
            "tokenContractConfigured":   token_contract_configured,
            "tokenContractEnvVar":       token_contract_env_var,
            "balanceRouteReady":         (
                feature_enabled
                and rpc_configured
                and (not token_contract_required or token_contract_configured)
            ),
            "lastBalanceReason":         _diagnosis_reason(
                feature_enabled=feature_enabled,
                rpc_configured=rpc_configured,
                token_contract_required=token_contract_required,
                token_contract_configured=token_contract_configured,
            ),
        }

    return [
        _row(
            row_id=ROW_ETHEREUM_MAINNET_ETH,
            asset="ETH",
            display_name="Ethereum Mainnet",
            network_id=NETWORK_ETHEREUM_MAINNET,
            feature_enabled=eth_feature,
            feature_flag_env="VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            rpc_env_var="ETHEREUM_MAINNET_RPC_URL",
            rpc_configured=rpc_configured,
            token_contract_required=False,
            token_contract_configured=True,
            token_contract_env_var="",
        ),
        _row(
            row_id=ROW_ETHEREUM_MAINNET_USDT_ERC20,
            asset="USDT_ERC20",
            display_name="USDT (ERC20) on Ethereum Mainnet",
            network_id=NETWORK_ETHEREUM_MAINNET,
            feature_enabled=usdt_feature,
            feature_flag_env="VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
            rpc_env_var="ETHEREUM_MAINNET_RPC_URL",
            rpc_configured=rpc_configured,
            token_contract_required=True,
            token_contract_configured=usdt_contract_configured,
            token_contract_env_var="ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
        ),
        _row(
            row_id=ROW_ETHEREUM_MAINNET_USDC_ERC20,
            asset="USDC_ERC20",
            display_name="USDC (ERC20) on Ethereum Mainnet",
            network_id=NETWORK_ETHEREUM_MAINNET,
            feature_enabled=usdc_feature,
            feature_flag_env="VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
            rpc_env_var="ETHEREUM_MAINNET_RPC_URL",
            rpc_configured=rpc_configured,
            token_contract_required=True,
            token_contract_configured=usdc_contract_configured,
            token_contract_env_var="ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
        ),
    ]


def _solana_row() -> dict[str, Any]:


    from vault_config import (
        crypto_wallet_engine_enabled, solana_enabled, solana_rpc_url,
    )
    engine_on = crypto_wallet_engine_enabled()
    sol_on = solana_enabled()
    feature_enabled = engine_on and sol_on
    rpc_configured = bool(solana_rpc_url())
    return {
        "rowId":                   ROW_SOLANA_MAINNET_SOL,
        "asset":                   "SOL",
        "displayName":             "Solana Mainnet",
        "network":                 "solana_mainnet",
        "featureEnabled":          feature_enabled,
        "featureFlagEnvVar":       "VAULTAI_CRYPTO_SOLANA_ENABLED",
        "rpcConfigured":           rpc_configured,
        "rpcEnvVar":               "SOLANA_RPC_URL",
        "tokenContractRequired":   False,
        "tokenContractConfigured": True,
        "tokenContractEnvVar":     "",
        "balanceRouteReady":       feature_enabled and rpc_configured,
        "lastBalanceReason":       _diagnosis_reason(
            feature_enabled=feature_enabled,
            rpc_configured=rpc_configured,
            token_contract_required=False,
            token_contract_configured=True,
        ),
    }


def _tron_row() -> dict[str, Any]:


    from vault_config import (
        crypto_wallet_engine_enabled, tron_api_base_url, tron_enabled,
        tron_usdt_contract_address,
    )
    engine_on = crypto_wallet_engine_enabled()
    tron_on = tron_enabled()
    feature_enabled = engine_on and tron_on
    api_configured = bool(tron_api_base_url())
    contract_configured = bool(tron_usdt_contract_address())
    return {
        "rowId":                   ROW_TRON_MAINNET_USDT_TRC20,
        "asset":                   "USDT_TRC20",
        "displayName":             "USDT (TRC20) on TRON Mainnet",
        "network":                 "tron_mainnet",
        "featureEnabled":          feature_enabled,
        "featureFlagEnvVar":       "VAULTAI_CRYPTO_TRON_ENABLED",
        "rpcConfigured":           api_configured,
        "rpcEnvVar":               "TRON_API_BASE_URL",
        "tokenContractRequired":   True,
        "tokenContractConfigured": contract_configured,
        "tokenContractEnvVar":     "TRON_USDT_CONTRACT_ADDRESS",
        "balanceRouteReady":       (
            feature_enabled and api_configured and contract_configured
        ),
        "lastBalanceReason":       _diagnosis_reason(
            feature_enabled=feature_enabled,
            rpc_configured=api_configured,
            token_contract_required=True,
            token_contract_configured=contract_configured,
        ),
    }


def _monero_row() -> dict[str, Any]:


    from vault_config import (
        crypto_wallet_engine_enabled, monero_enabled, monero_scanner_mode,
    )
    engine_on = crypto_wallet_engine_enabled()
    xmr_on = monero_enabled()
    feature_enabled = engine_on and xmr_on
    scanner_mode = monero_scanner_mode()
    scanner_active = scanner_mode != "none"
    return {
        "rowId":                   ROW_MONERO_MAINNET_XMR,
        "asset":                   "XMR",
        "displayName":             "Monero Mainnet",
        "network":                 "monero_mainnet",
        "featureEnabled":          feature_enabled,
        "featureFlagEnvVar":       "VAULTAI_CRYPTO_XMR_ENABLED",
        "rpcConfigured":           scanner_active,
        "rpcEnvVar":               "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
        "tokenContractRequired":   False,
        "tokenContractConfigured": True,
        "tokenContractEnvVar":     "",
        "scannerMode":             scanner_mode,
        "walletGenerationStatus":  "client_side_ready",
        "xmrClientScannerSupported": False,
        "xmrBackendScannerEnabled": False,
        "balanceRouteReady":       False,
        "xmrBalanceReason":        (
            "feature_disabled" if not feature_enabled
            else "xmr_scanner_client_required"
        ),
        "lastBalanceReason":       (
            "feature_disabled" if not feature_enabled
            else "xmr_scanner_client_required"
        ),
    }


def build_diagnosis_envelope() -> dict[str, Any]:


    from vault_config import (
        crypto_default_network,
        crypto_default_network_config_valid,
        crypto_wallet_engine_enabled,
    )

    rows: list[dict[str, Any]] = []
    rows.extend(_ethereum_mainnet_rows())
    rows.append(_solana_row())
    rows.append(_tron_row())
    rows.append(_monero_row())

    engine_on = crypto_wallet_engine_enabled()
    default_network = crypto_default_network()
    default_network_valid = crypto_default_network_config_valid()

    ready_count = sum(1 for r in rows if r["balanceRouteReady"])
    total_count = len(rows)

    return {
        "status":                     "ok",
        "schema":                     CRYPTO_WALLET_DIAGNOSIS_SCHEMA,
        "walletEngineEnabled":        engine_on,
        "defaultNetwork":             default_network,
        "defaultNetworkConfigValid":  default_network_valid,
        "assets":                     rows,
        "assetsReady":                ready_count,
        "assetsTotal":                total_count,
    }


__all__ = [
    "CRYPTO_WALLET_DIAGNOSIS_SCHEMA",
    "DIAG_REASON_FEATURE_DISABLED",
    "DIAG_REASON_RPC_NOT_CONFIGURED",
    "DIAG_REASON_TOKEN_CONTRACT",
    "DIAG_REASON_READY",
    "ROW_ETHEREUM_MAINNET_ETH",
    "ROW_ETHEREUM_MAINNET_USDT_ERC20",
    "ROW_ETHEREUM_MAINNET_USDC_ERC20",
    "ROW_SOLANA_MAINNET_SOL",
    "ROW_TRON_MAINNET_USDT_TRC20",
    "ROW_MONERO_MAINNET_XMR",
    "build_diagnosis_envelope",
]
