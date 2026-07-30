

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


NETWORK_ETHEREUM_SEPOLIA: str = "ethereum_sepolia"
NETWORK_ETHEREUM_MAINNET: str = "ethereum_mainnet"

ALL_EVM_NETWORKS: tuple[str, ...] = (
    NETWORK_ETHEREUM_SEPOLIA,
    NETWORK_ETHEREUM_MAINNET,
)


@dataclass(frozen=True)
class EvmNetworkConfig:


    id:                       str
    display_name:             str
    chain_id:                 int
    native_asset:             str
    native_unit:              str
    rpc_env_var:              str
    token_contract_env_prefix: str
    is_testnet:               bool
    receive_enabled_env_var:  str
    send_enabled_env_var:     str
    receive_enabled_default:  bool
    send_enabled_default:     bool


_REGISTRY: dict[str, EvmNetworkConfig] = {
    NETWORK_ETHEREUM_SEPOLIA: EvmNetworkConfig(
        id=NETWORK_ETHEREUM_SEPOLIA,
        display_name="Ethereum Sepolia",
        chain_id=11155111,
        native_asset="ETH",
        native_unit="ETH",
        rpc_env_var="ETHEREUM_SEPOLIA_RPC_URL",
        token_contract_env_prefix="ETHEREUM_SEPOLIA",
        is_testnet=True,
        receive_enabled_env_var="VAULTAI_CRYPTO_ETH_SEPOLIA_RECEIVE_ENABLED",
        send_enabled_env_var="VAULTAI_CRYPTO_ETH_SEPOLIA_SEND_ENABLED",
                                                          
                                                                   
        receive_enabled_default=True,
        send_enabled_default=True,
    ),
    NETWORK_ETHEREUM_MAINNET: EvmNetworkConfig(
        id=NETWORK_ETHEREUM_MAINNET,
        display_name="Ethereum Mainnet",
        chain_id=1,
        native_asset="ETH",
        native_unit="ETH",
        rpc_env_var="ETHEREUM_MAINNET_RPC_URL",
        token_contract_env_prefix="ETHEREUM_MAINNET",
        is_testnet=False,
        receive_enabled_env_var="VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
        send_enabled_env_var="VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
                                                                    
                                                               
        receive_enabled_default=False,
        send_enabled_default=False,
    ),
}


_ASSET_NETWORKS: dict[str, frozenset[str]] = {
    "ETH":        frozenset({NETWORK_ETHEREUM_SEPOLIA, NETWORK_ETHEREUM_MAINNET}),
    "USDT_ERC20": frozenset({NETWORK_ETHEREUM_SEPOLIA, NETWORK_ETHEREUM_MAINNET}),
    "USDC_ERC20": frozenset({NETWORK_ETHEREUM_SEPOLIA, NETWORK_ETHEREUM_MAINNET}),
}


_TOKEN_CONTRACT_SUFFIX: dict[str, str] = {
    "USDT_ERC20": "USDT_CONTRACT_ADDRESS",
    "USDC_ERC20": "USDC_CONTRACT_ADDRESS",
}


DEFAULT_TOKEN_DECIMALS: dict[str, int] = {
    "USDT_ERC20": 6,
    "USDC_ERC20": 6,
}


_NETWORK_ALIASES: dict[str, str] = {
    "ethereum": NETWORK_ETHEREUM_MAINNET,
    "ethereum mainnet": NETWORK_ETHEREUM_MAINNET,
    "mainnet": NETWORK_ETHEREUM_MAINNET,
    "ethereum sepolia": NETWORK_ETHEREUM_SEPOLIA,
    "ethereum sepolia testnet": NETWORK_ETHEREUM_SEPOLIA,
    "ethereum testnet": NETWORK_ETHEREUM_SEPOLIA,
    "sepolia": NETWORK_ETHEREUM_SEPOLIA,
}


def _display_alias_key(network_id: str) -> str:
    return re.sub(r"\s+", " ", network_id.strip()).lower()


def normalize_network_id(network_id: Optional[str]) -> str:


    if not isinstance(network_id, str):
        return ""
    raw = network_id.strip()
    if raw in _REGISTRY:
        return raw
    return _NETWORK_ALIASES.get(_display_alias_key(raw), "")


def is_known_network(network_id: Optional[str]) -> bool:
    return normalize_network_id(network_id) in _REGISTRY


def network_config(network_id: str) -> Optional[EvmNetworkConfig]:


    return _REGISTRY.get(normalize_network_id(network_id))


def normalize_network_config(
    network_id: Optional[str],
) -> Optional[EvmNetworkConfig]:


    if not isinstance(network_id, str):
        return None
    return network_config(network_id)


def asset_is_supported_on_network(asset: str, network_id: str) -> bool:


    nid = normalize_network_id(network_id)
    if nid not in _REGISTRY:
        return False
    return asset in _ASSET_NETWORKS.get(asset, frozenset())


def networks_for_asset(asset: str) -> tuple[str, ...]:


    nets = _ASSET_NETWORKS.get(asset, frozenset())
    return tuple(sorted(nets))


def rpc_url_for(network_id: str) -> str:


    cfg = network_config(network_id)
    if cfg is None:
        return ""
    return os.getenv(cfg.rpc_env_var, "").strip()


def token_contract_for(network_id: str, asset: str) -> str:


    cfg = network_config(network_id)
    if cfg is None:
        return ""
    suffix = _TOKEN_CONTRACT_SUFFIX.get(asset)
    if not suffix:
        return ""
    env_var = f"{cfg.token_contract_env_prefix}_{suffix}"
    return os.getenv(env_var, "").strip()


def _flag(env_var: str, default: bool) -> bool:


    raw = os.getenv(env_var, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y"}


def is_receive_enabled(network_id: str) -> bool:


    cfg = network_config(network_id)
    if cfg is None:
        return False
    return _flag(cfg.receive_enabled_env_var, cfg.receive_enabled_default)


def is_send_enabled(network_id: str) -> bool:


    cfg = network_config(network_id)
    if cfg is None:
        return False
    return _flag(cfg.send_enabled_env_var, cfg.send_enabled_default)


def network_display_name(network_id: str) -> str:


    cfg = network_config(network_id)
    if cfg is None:
        return network_id
    return cfg.display_name


def chain_id_for(network_id: str) -> Optional[int]:


    cfg = network_config(network_id)
    if cfg is None:
        return None
    return cfg.chain_id


__all__ = [
    "NETWORK_ETHEREUM_SEPOLIA",
    "NETWORK_ETHEREUM_MAINNET",
    "ALL_EVM_NETWORKS",
    "EvmNetworkConfig",
    "DEFAULT_TOKEN_DECIMALS",
    "normalize_network_id",
    "is_known_network",
    "network_config",
    "normalize_network_config",
    "asset_is_supported_on_network",
    "networks_for_asset",
    "rpc_url_for",
    "token_contract_for",
    "is_receive_enabled",
    "is_send_enabled",
    "network_display_name",
    "chain_id_for",
]
