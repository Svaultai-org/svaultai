

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx


logger = logging.getLogger("crypto_wallet_health")


CRYPTO_WALLET_HEALTH_SCHEMA: str = "crypto_wallet_health_v1"
CRYPTO_WALLET_FEATURES_SCHEMA: str = "crypto_wallet_features_v1"


OVERALL_READY:     str = "ready"
OVERALL_DEGRADED:  str = "degraded"
OVERALL_NOT_READY: str = "not_ready"

NETWORK_READY:     str = "ready"
NETWORK_DEGRADED:  str = "degraded"
NETWORK_NOT_READY: str = "not_ready"


REASON_RPC_NOT_CONFIGURED:        str = "rpc_not_configured"
REASON_RPC_UNREACHABLE:           str = "rpc_unreachable"
REASON_CHAIN_ID_MISMATCH:         str = "chain_id_mismatch"
REASON_CHAIN_ID_UNRESOLVED:       str = "chain_id_unresolved"
REASON_INDEXER_NOT_CONFIGURED:    str = "indexer_not_configured"
REASON_INDEXER_UNREACHABLE:       str = "indexer_unreachable"
REASON_TOKEN_CONTRACT_NOT_CONFIGURED: str = "token_contract_not_configured"
REASON_INVALID_CONTRACT_ADDRESS:  str = "invalid_contract_address"
REASON_CONTRACT_READ_FAILED:      str = "contract_read_failed"
REASON_MAINNET_SEND_PAUSED:       str = "mainnet_send_paused"


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TIMEOUT_SECS: int = 4


_ALLOWED_HEALTH_METHODS: frozenset[str] = frozenset({
    "eth_chainId",
    "eth_blockNumber",
    "eth_call",
})


class _HealthRpcError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_valid_address(addr: Optional[str]) -> bool:
    if not isinstance(addr, str):
        return False
    return bool(_ETH_ADDRESS_RE.match(addr))


def _post_health_rpc(
    rpc_url: str, method: str, params: list,
) -> dict[str, Any]:


    if method not in _ALLOWED_HEALTH_METHODS:
        raise _HealthRpcError("method_forbidden")
    if not rpc_url:
        raise _HealthRpcError("rpc_not_configured")
    body = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  method,
        "params":  params,
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_SECS) as client:
            resp = client.post(
                rpc_url, json=body,
                headers={
                    "content-type": "application/json",
                    "accept":       "application/json",
                },
            )
    except httpx.TimeoutException:
        logger.warning("[WALLET-HEALTH] rpc_timeout method=%s", method)
        raise _HealthRpcError("rpc_unreachable")
    except (httpx.HTTPError, OSError):
        logger.warning("[WALLET-HEALTH] rpc_io method=%s", method)
        raise _HealthRpcError("rpc_unreachable")
    if resp.status_code != 200:
        logger.warning(
            "[WALLET-HEALTH] rpc_http method=%s status=%s",
            method, resp.status_code,
        )
        raise _HealthRpcError("rpc_unreachable")
    try:
        data = resp.json()
    except (ValueError, TypeError):
        logger.warning("[WALLET-HEALTH] rpc_bad_json method=%s", method)
        raise _HealthRpcError("rpc_unreachable")
    if not isinstance(data, dict):
        raise _HealthRpcError("rpc_unreachable")
    if "error" in data:
        raise _HealthRpcError("rpc_unreachable")
    return data


def _eth_chain_id(rpc_url: str) -> int:
    body = _post_health_rpc(rpc_url, "eth_chainId", [])
    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise _HealthRpcError("chain_id_unresolved")
    try:
        return int(result, 16)
    except ValueError:
        raise _HealthRpcError("chain_id_unresolved")


def _eth_block_number(rpc_url: str) -> int:
    body = _post_health_rpc(rpc_url, "eth_blockNumber", [])
    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise _HealthRpcError("rpc_unreachable")
    try:
        return int(result, 16)
    except ValueError:
        raise _HealthRpcError("rpc_unreachable")


def _erc20_decimals_call(rpc_url: str, contract_address: str) -> int:


    if not _is_valid_address(contract_address):
        raise _HealthRpcError("invalid_contract_address")
    body = _post_health_rpc(
        rpc_url, "eth_call",
        [{"to": contract_address, "data": "0x313ce567"}, "latest"],
    )
    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise _HealthRpcError("contract_read_failed")
    if len(result) < 2 + 64:
        raise _HealthRpcError("contract_read_failed")
    try:
        return int(result, 16)
    except ValueError:
        raise _HealthRpcError("contract_read_failed")


def _redacted_indexer_probe(
    base_url: str,
    *,
    provider: str,
) -> Optional[str]:


    if not base_url:
        return REASON_INDEXER_NOT_CONFIGURED
    try:
        with httpx.Client(timeout=_TIMEOUT_SECS) as client:
            resp = client.get(base_url)
    except httpx.TimeoutException:
        logger.warning(
            "[WALLET-HEALTH] indexer_timeout provider=%s", provider,
        )
        return REASON_INDEXER_UNREACHABLE
    except (httpx.HTTPError, OSError):
        logger.warning(
            "[WALLET-HEALTH] indexer_io provider=%s", provider,
        )
        return REASON_INDEXER_UNREACHABLE
                                                              
                                                                  
    if 500 <= resp.status_code < 600:
        logger.warning(
            "[WALLET-HEALTH] indexer_http provider=%s status=%s",
            provider, resp.status_code,
        )
        return REASON_INDEXER_UNREACHABLE
    return None


def _check_token_contract(
    rpc_url: str, contract_address: str,
) -> tuple[bool, bool, Optional[str]]:

    if not contract_address:
        return False, False, REASON_TOKEN_CONTRACT_NOT_CONFIGURED
    if not _is_valid_address(contract_address):
        return False, False, REASON_INVALID_CONTRACT_ADDRESS
    if not rpc_url:
                                                                 
                                           
        return True, False, REASON_RPC_NOT_CONFIGURED
    try:
        _erc20_decimals_call(rpc_url, contract_address)
    except _HealthRpcError as exc:
        return True, False, exc.code
    return True, True, None


def _build_sepolia_network_health() -> dict[str, Any]:
    from vault_config import (
        ethereum_sepolia_rpc_url,
        ethereum_sepolia_token_contract,
        ethereum_sepolia_tx_indexer_base_url,
        ethereum_sepolia_tx_indexer_configured,
        ethereum_sepolia_tx_indexer_provider,
    )
    from evm_networks import NETWORK_ETHEREUM_SEPOLIA, chain_id_for

    expected_chain_id = chain_id_for(NETWORK_ETHEREUM_SEPOLIA) or 11155111
    rpc_url = ethereum_sepolia_rpc_url()

    return _build_network_health_record(
        network_id=NETWORK_ETHEREUM_SEPOLIA,
        display_name="Ethereum Sepolia",
        rpc_url=rpc_url,
        expected_chain_id=expected_chain_id,
        indexer_configured=ethereum_sepolia_tx_indexer_configured(),
        indexer_provider=ethereum_sepolia_tx_indexer_provider(),
        indexer_base_url=ethereum_sepolia_tx_indexer_base_url(),
        usdt_contract=ethereum_sepolia_token_contract("USDT_ERC20"),
        usdc_contract=ethereum_sepolia_token_contract("USDC_ERC20"),
        send_section=_sepolia_send_section(),
    )


def _sepolia_send_section() -> dict[str, Any]:
    from evm_networks import (
        NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
        is_send_enabled,
    )
    return {
        "receiveEnabled": is_receive_enabled(NETWORK_ETHEREUM_SEPOLIA),
        "sendEnabled":    is_send_enabled(NETWORK_ETHEREUM_SEPOLIA),
    }


def _build_mainnet_network_health() -> dict[str, Any]:
    from vault_config import (
        ethereum_mainnet_broadcast_rate_limit,
        ethereum_mainnet_broadcast_rate_window_secs,
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_rpc_url,
        ethereum_mainnet_send_paused,
        ethereum_mainnet_tx_indexer_base_url,
        ethereum_mainnet_tx_indexer_configured,
        ethereum_mainnet_tx_indexer_provider,
    )
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, chain_id_for,
        is_receive_enabled, is_send_enabled, token_contract_for,
    )

    expected_chain_id = chain_id_for(NETWORK_ETHEREUM_MAINNET) or 1
    rpc_url = ethereum_mainnet_rpc_url()

    record = _build_network_health_record(
        network_id=NETWORK_ETHEREUM_MAINNET,
        display_name="Ethereum Mainnet",
        rpc_url=rpc_url,
        expected_chain_id=expected_chain_id,
        indexer_configured=ethereum_mainnet_tx_indexer_configured(),
        indexer_provider=ethereum_mainnet_tx_indexer_provider(),
        indexer_base_url=ethereum_mainnet_tx_indexer_base_url(),
        usdt_contract=token_contract_for(
            NETWORK_ETHEREUM_MAINNET, "USDT_ERC20",
        ),
        usdc_contract=token_contract_for(
            NETWORK_ETHEREUM_MAINNET, "USDC_ERC20",
        ),
        send_section={
            "mainnetReceiveEnabled":      is_receive_enabled(
                NETWORK_ETHEREUM_MAINNET,
            ),
            "mainnetErc20ReceiveEnabled": (
                ethereum_mainnet_erc20_receive_enabled()
            ),
            "mainnetSendEnabled":         is_send_enabled(
                NETWORK_ETHEREUM_MAINNET,
            ),
            "mainnetSendPaused":          ethereum_mainnet_send_paused(),
            "mainnetBroadcastRateLimit":  (
                ethereum_mainnet_broadcast_rate_limit()
            ),
            "mainnetBroadcastRateWindowSecs": (
                ethereum_mainnet_broadcast_rate_window_secs()
            ),
        },
    )
    return record


def _build_network_health_record(
    *,
    network_id: str,
    display_name: str,
    rpc_url: str,
    expected_chain_id: int,
    indexer_configured: bool,
    indexer_provider: str,
    indexer_base_url: str,
    usdt_contract: str,
    usdc_contract: str,
    send_section: dict[str, Any],
) -> dict[str, Any]:


    rpc_configured = bool(rpc_url)
    rpc_reachable = False
    chain_id_observed: Optional[int] = None
    rpc_reason: Optional[str] = None
    if not rpc_configured:
        rpc_reason = REASON_RPC_NOT_CONFIGURED
    else:
        try:
            chain_id_observed = _eth_chain_id(rpc_url)
            rpc_reachable = True
        except _HealthRpcError as exc:
            rpc_reason = exc.code

    chain_id_match = (
        rpc_reachable
        and chain_id_observed == expected_chain_id
    )
    if rpc_reachable and not chain_id_match:
        rpc_reason = REASON_CHAIN_ID_MISMATCH

                                                               
    indexer_reachable = False
    indexer_reason: Optional[str] = None
    if not indexer_configured:
        indexer_reason = REASON_INDEXER_NOT_CONFIGURED
    else:
        probe = _redacted_indexer_probe(
            indexer_base_url, provider=indexer_provider,
        )
        if probe is None:
            indexer_reachable = True
        else:
            indexer_reason = probe

    usdt_cfg, usdt_read, usdt_reason = _check_token_contract(
        rpc_url, usdt_contract,
    )
    usdc_cfg, usdc_read, usdc_reason = _check_token_contract(
        rpc_url, usdc_contract,
    )

                                                                   
    if not rpc_configured or not rpc_reachable:
        status = NETWORK_NOT_READY
        primary_reason = rpc_reason or REASON_RPC_NOT_CONFIGURED
    elif not chain_id_match:
        status = NETWORK_NOT_READY
        primary_reason = REASON_CHAIN_ID_MISMATCH
    elif not (indexer_reachable and indexer_configured) or \
            not (usdt_cfg and usdt_read) or \
            not (usdc_cfg and usdc_read):
        status = NETWORK_DEGRADED
        primary_reason = (
            indexer_reason or usdt_reason or usdc_reason or "degraded"
        )
    else:
        status = NETWORK_READY
        primary_reason = None

    return {
        "id":                       network_id,
        "displayName":              display_name,
        "status":                   status,
        "reason":                   primary_reason,
        "rpcConfigured":            rpc_configured,
        "rpcReachable":             rpc_reachable,
        "chainIdExpected":          expected_chain_id,
        "chainIdObserved":          chain_id_observed,
        "nativeBalanceReadReady":   rpc_reachable and chain_id_match,
        "txIndexerConfigured":      indexer_configured,
        "txIndexerReachable":       indexer_reachable,
        "txIndexerProvider":        indexer_provider or None,
        "tokens": [
            {
                "asset":      "USDT_ERC20",
                "configured": usdt_cfg,
                "readable":   usdt_read,
                "reason":     usdt_reason,
            },
            {
                "asset":      "USDC_ERC20",
                "configured": usdc_cfg,
                "readable":   usdc_read,
                "reason":     usdc_reason,
            },
        ],
        "send": send_section,
    }


def build_health_envelope(checked_at: Optional[str] = None) -> dict[str, Any]:


    from vault_config import (
        crypto_default_network,
        crypto_default_network_config_valid,
        crypto_default_network_configured_value,
        crypto_wallet_engine_enabled,
        ethereum_mainnet_broadcast_rate_limit,
        ethereum_mainnet_broadcast_rate_window_secs,
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_send_paused,
    )
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET,
        NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
        is_send_enabled,
    )

    sepolia = _build_sepolia_network_health()
    mainnet = _build_mainnet_network_health()

    default_network = crypto_default_network()
    default_network_config_valid = crypto_default_network_config_valid()

    statuses = [sepolia["status"], mainnet["status"]]
    if NETWORK_NOT_READY in statuses:
        overall = OVERALL_NOT_READY
    elif NETWORK_DEGRADED in statuses:
        overall = OVERALL_DEGRADED
    else:
        overall = OVERALL_READY

    if not default_network_config_valid:
        overall = OVERALL_NOT_READY
    elif default_network == NETWORK_ETHEREUM_MAINNET:
        if mainnet["status"] != NETWORK_READY:
            overall = OVERALL_NOT_READY

    features = {
        "walletEngineEnabled":      crypto_wallet_engine_enabled(),
        "sepoliaReceiveEnabled":    is_receive_enabled(
            NETWORK_ETHEREUM_SEPOLIA,
        ),
        "sepoliaSendEnabled":       is_send_enabled(
            NETWORK_ETHEREUM_SEPOLIA,
        ),
        "mainnetReceiveEnabled":    is_receive_enabled(
            NETWORK_ETHEREUM_MAINNET,
        ),
        "mainnetErc20ReceiveEnabled": (
            ethereum_mainnet_erc20_receive_enabled()
        ),
        "mainnetSendEnabled":       is_send_enabled(
            NETWORK_ETHEREUM_MAINNET,
        ),
        "mainnetSendPaused":        ethereum_mainnet_send_paused(),
        "broadcastRateLimit":       (
            ethereum_mainnet_broadcast_rate_limit()
        ),
        "broadcastRateWindowSecs":  (
            ethereum_mainnet_broadcast_rate_window_secs()
        ),
    }

    solana_health = _build_solana_network_health()
    tron_health = _build_tron_network_health()
    monero_health = _build_monero_network_health()

    return {
        "status":        "ok",
        "schema":        CRYPTO_WALLET_HEALTH_SCHEMA,
        "overallStatus": overall,
        "defaultNetwork":            default_network,
        "defaultNetworkConfigValid": default_network_config_valid,
        "defaultNetworkConfiguredValue": (
            crypto_default_network_configured_value()
        ),
        "networks":      [sepolia, mainnet],
        "solana":        solana_health,
        "tron":          tron_health,
        "monero":        monero_health,
        "features":      features,
        "checkedAt":     checked_at,
    }


def _build_monero_network_health() -> dict[str, Any]:
    from vault_config import (
        monero_enabled, monero_scanner_mode, monero_send_enabled,
    )
    enabled = monero_enabled()
    scanner_mode = monero_scanner_mode()
    return {
        "id":                    "monero_mainnet",
        "displayName":           "Monero",
        "xmrEnabled":            enabled,
        "xmrReceiveReady":       enabled,
        "xmrScannerMode":        scanner_mode,
        "xmrScannerReady":       False,
        "xmrSendEnabled":        False,
        "xmrActivityConnected":  False,
    }


def _build_tron_network_health() -> dict[str, Any]:
    from vault_config import (
        tron_api_base_url, tron_api_key,
        tron_broadcast_rate_limit, tron_broadcast_rate_window_secs,
        tron_enabled, tron_send_enabled, tron_send_paused,
        tron_usdt_contract_address,
    )
    from tron_rpc import (
        is_valid_tron_address, tron_get_health_at_url,
    )

    enabled = tron_enabled()
    base_url = tron_api_base_url()
    api_configured = bool(base_url)
    api_reachable = False
    if enabled and api_configured:
        try:
            api_reachable = tron_get_health_at_url(
                base_url, tron_api_key(),
            )
        except Exception:
            api_reachable = False

    contract = tron_usdt_contract_address()
    contract_configured = enabled and bool(contract) and (
        is_valid_tron_address(contract)
    )

    balance_ready = (
        enabled and api_reachable and contract_configured
    )

    send_paused = enabled and tron_send_paused()
    send_enabled = (
        enabled and tron_send_enabled() and not send_paused
    )

    return {
        "id":                        "tron_mainnet",
        "displayName":               "TRON",
        "tronEnabled":               enabled,
        "tronConfigured":            enabled and api_configured,
        "tronRpcReachable":          enabled and api_reachable,
        "tronApiReachable":          enabled and api_reachable,
        "tronUsdtContractConfigured": contract_configured,
        "tronBalanceReadReady":      balance_ready,
        "tronSendEnabled":           send_enabled,
        "tronSendPaused":            send_paused,
        "tronBroadcastRateLimit":    tron_broadcast_rate_limit(),
        "tronBroadcastRateWindowSecs": (
            tron_broadcast_rate_window_secs()
        ),
        "tronActivityConnected":     False,
    }


def _build_solana_network_health() -> dict[str, Any]:
    from vault_config import (
        solana_enabled,
        solana_rpc_url,
        solana_send_enabled,
        solana_send_paused,
        solana_tx_indexer_configured,
    )
    from solana_rpc import sol_get_health_at_url

    enabled = solana_enabled()
    rpc_url = solana_rpc_url()
    rpc_configured = bool(rpc_url)
    rpc_reachable = False
    if enabled and rpc_configured:
        try:
            rpc_reachable = sol_get_health_at_url(rpc_url)
        except Exception:
            rpc_reachable = False

    send_enabled = enabled and solana_send_enabled()
    send_paused = enabled and solana_send_paused()

    return {
        "id":                       "solana_mainnet",
        "displayName":              "Solana",
        "solanaEnabled":            enabled,
        "solanaConfigured":         enabled and rpc_configured,
        "solanaRpcReachable":       enabled and rpc_reachable,
        "solanaBalanceReadReady":   enabled and rpc_reachable,
        "solanaSendEnabled":        send_enabled and not send_paused,
        "solanaSendPaused":         send_paused,
        "solanaActivityConnected":  enabled and rpc_reachable,
        "solanaStatusReady":        enabled and rpc_reachable,
        "solanaFeeReady":           enabled and rpc_reachable,
    }


def build_features_envelope() -> dict[str, Any]:


    from vault_config import (
        crypto_default_network,
        crypto_default_network_config_valid,
        crypto_wallet_engine_enabled,
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_send_paused,
        solana_enabled,
        solana_rpc_url,
        solana_send_enabled,
        solana_send_paused,
        solana_tx_indexer_configured,
        tron_api_base_url,
        tron_enabled,
        tron_send_enabled,
        tron_send_paused,
        tron_usdt_contract_address,
        monero_enabled,
        monero_scanner_mode,
    )
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET,
        NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
        is_send_enabled,
    )

    sol_enabled = solana_enabled()
    sol_configured = sol_enabled and bool(solana_rpc_url())

    tron_on = tron_enabled()
    tron_api_ready = tron_on and bool(tron_api_base_url())
    tron_contract_ready = tron_on and bool(tron_usdt_contract_address())
    tron_balance_ready = tron_on and tron_api_ready and tron_contract_ready

    xmr_on = monero_enabled()
    xmr_scanner_mode = monero_scanner_mode()

    supported_networks = [
        NETWORK_ETHEREUM_SEPOLIA,
        NETWORK_ETHEREUM_MAINNET,
    ]
    supported_assets = {
        NETWORK_ETHEREUM_SEPOLIA: ["ETH", "USDT_ERC20", "USDC_ERC20"],
        NETWORK_ETHEREUM_MAINNET: ["ETH", "USDT_ERC20", "USDC_ERC20"],
    }
    if sol_enabled:
        supported_networks.append("solana_mainnet")
        supported_assets["solana_mainnet"] = ["SOL"]
    if tron_on:
        supported_networks.append("tron_mainnet")
        supported_assets["tron_mainnet"] = ["USDT_TRC20"]
    if xmr_on:
        supported_networks.append("monero_mainnet")
        supported_assets["monero_mainnet"] = ["XMR"]

    return {
        "status": "ok",
        "schema": CRYPTO_WALLET_FEATURES_SCHEMA,
        "walletEngineEnabled":      crypto_wallet_engine_enabled(),
        "sepoliaReceiveEnabled":    is_receive_enabled(
            NETWORK_ETHEREUM_SEPOLIA,
        ),
        "sepoliaSendEnabled":       is_send_enabled(
            NETWORK_ETHEREUM_SEPOLIA,
        ),
        "mainnetReceiveEnabled":    is_receive_enabled(
            NETWORK_ETHEREUM_MAINNET,
        ),
        "mainnetErc20ReceiveEnabled": (
            ethereum_mainnet_erc20_receive_enabled()
        ),
        "mainnetSendEnabled":       is_send_enabled(
            NETWORK_ETHEREUM_MAINNET,
        ),
        "mainnetSendPaused":        ethereum_mainnet_send_paused(),
        "solanaEnabled":            sol_enabled,
        "solanaReceiveEnabled":     sol_enabled,
        "solanaSendEnabled":        (
            sol_enabled and solana_send_enabled()
            and not solana_send_paused()
        ),
        "solanaSendPaused":         (
            sol_enabled and solana_send_paused()
        ),
        "solanaBalanceEnabled":     sol_configured,
        "solanaActivityConnected":  sol_configured,
        "solanaStatusReady":        sol_configured,
        "solanaFeeReady":           sol_configured,
        "tronEnabled":              tron_on,
        "tronReceiveEnabled":       tron_on,
        "tronBalanceEnabled":       tron_balance_ready,
        "tronSendEnabled":          (
            tron_on and tron_send_enabled()
            and not tron_send_paused()
        ),
        "tronSendPaused":           (
            tron_on and tron_send_paused()
        ),
        "tronActivityConnected":    False,
        "tronUsdtContractConfigured": tron_contract_ready,
        "xmrEnabled":               xmr_on,
        "xmrReceiveEnabled":        xmr_on,
        "xmrBalanceEnabled":        False,
        "xmrActivityConnected":     False,
        "xmrSendEnabled":           False,
        "xmrScannerMode":           xmr_scanner_mode,
        "xmrClientScannerSupported": False,
        "xmrBackendScannerEnabled": False,
        "defaultNetwork":           crypto_default_network(),
        "defaultNetworkConfigValid": (
            crypto_default_network_config_valid()
        ),
        "supportedNetworks":        supported_networks,
        "supportedAssetsByNetwork": supported_assets,
    }


__all__ = [
    "CRYPTO_WALLET_HEALTH_SCHEMA",
    "CRYPTO_WALLET_FEATURES_SCHEMA",
    "OVERALL_READY",
    "OVERALL_DEGRADED",
    "OVERALL_NOT_READY",
    "NETWORK_READY",
    "NETWORK_DEGRADED",
    "NETWORK_NOT_READY",
    "REASON_RPC_NOT_CONFIGURED",
    "REASON_RPC_UNREACHABLE",
    "REASON_CHAIN_ID_MISMATCH",
    "REASON_CHAIN_ID_UNRESOLVED",
    "REASON_INDEXER_NOT_CONFIGURED",
    "REASON_INDEXER_UNREACHABLE",
    "REASON_TOKEN_CONTRACT_NOT_CONFIGURED",
    "REASON_INVALID_CONTRACT_ADDRESS",
    "REASON_CONTRACT_READ_FAILED",
    "REASON_MAINNET_SEND_PAUSED",
    "build_health_envelope",
    "build_features_envelope",
]
