"""Closed real-asset registry; this module never buys, trades or signs tokens.

PAXG's proxy and ERC20 specification are published by the issuer:
https://github.com/paxosglobal/paxos-gold-contract
The supported tuple is immutable. Operator configuration cannot substitute an
arbitrary contract, chain or decimal precision under the PAXG name.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

PAXG_ASSET = "PAXG_ERC20"
PAXG_CONTRACT = "0x45804880De22913dAFE09f4980848ECE6EcbAf78"
PAXG_NETWORK = "ethereum_mainnet"
PAXG_DECIMALS = 18
PAXG_SOURCE = "https://github.com/paxosglobal/paxos-gold-contract"
PAXG_TRANSFER_NOTE = (
    "Issuer rules may pause or freeze transfers. Token-level fees can reduce "
    "the received amount; ETH pays network fees."
)

CATEGORIES = (
    ("cryptocurrency", "Cryptocurrency"),
    ("digital_gold", "Digital Gold"),
    ("digital_silver", "Digital Silver"),
    ("tokenized_real_estate", "Tokenized Real Estate"),
    ("tokenized_diamonds_gemstones", "Tokenized Diamonds and Gemstones"),
    ("tokenized_artwork", "Tokenized Artwork"),
    ("tokenized_watches_collectibles", "Tokenized Watches and Collectibles"),
    ("tokenized_vehicles_equipment", "Tokenized Vehicles and Equipment"),
)


def paxg_amount_base_units(amount: str) -> int:
    """Exact ASCII decimal input; never silently truncate a reviewed send."""
    if not isinstance(amount, str) or len(amount) > 100:
        raise ValueError("amount_format")
    value = amount.strip()
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
        raise ValueError("amount_format")
    head, _, tail = value.partition(".")
    if len(tail) > PAXG_DECIMALS:
        raise ValueError("amount_precision_exceeded")
    units = int(head or "0") * 10 ** PAXG_DECIMALS + int(tail.ljust(PAXG_DECIMALS, "0") or "0")
    if units <= 0:
        raise ValueError("amount_must_be_positive")
    if units >= 2 ** 256:
        raise ValueError("amount_out_of_range")
    return units


def paxg_base_units_to_decimal(units: int) -> str:
    """String arithmetic preserves every digit of the uint256 token amount."""
    if not isinstance(units, int) or isinstance(units, bool) or not 0 <= units < 2 ** 256:
        raise ValueError("token_balance_invalid")
    head, tail = divmod(units, 10 ** PAXG_DECIMALS)
    fraction = str(tail).zfill(PAXG_DECIMALS).rstrip("0")
    return str(head) + ("." + fraction if fraction else "")

_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def paxg_enabled() -> bool:
    return os.getenv("VAULTAI_ASSETS_PAXG_ENABLED", "false").strip().lower() in {
        "true", "1", "yes", "on",
    }


def reset_verification_cache() -> None:
    """Test/reconfiguration helper; cached entries never contain private data."""
    with _probe_lock:
        _probe_cache.clear()


def _probe_paxg(rpc_url: str) -> dict[str, Any]:
    from evm_rpc import EvmRpcError, _emit_rpc_at_url, eth_chain_id_at_url

    try:
        if eth_chain_id_at_url(rpc_url) != 1:
            return {"verified": False, "reason": "chain_mismatch"}
        code = _emit_rpc_at_url(rpc_url, "eth_getCode", [PAXG_CONTRACT, "latest"]).get("result")
        if (not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code)
                or not any(c != "0" for c in code[2:])):
            return {"verified": False, "reason": "verified_token_contract_missing"}
        result = _emit_rpc_at_url(
            rpc_url, "eth_call", [{"to": PAXG_CONTRACT, "data": "0x313ce567"}, "latest"],
        ).get("result")
        if (not isinstance(result, str) or len(result) != 66
                or not result.startswith("0x") or int(result, 16) != PAXG_DECIMALS):
            return {"verified": False, "reason": "verified_token_decimals_mismatch"}
    except (EvmRpcError, ValueError, TypeError):
        # Never include RPC URLs, provider error bodies or credentials.
        return {"verified": False, "reason": "verified_token_provider_unavailable"}
    return {
        "verified": True,
        "reason": None,
        "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def verify_paxg_integration() -> dict[str, Any]:
    from vault_config import crypto_wallet_engine_enabled, ethereum_mainnet_rpc_url

    if not crypto_wallet_engine_enabled() or not paxg_enabled():
        return {"verified": False, "reason": "asset_integration_disabled"}
    rpc_url = ethereum_mainnet_rpc_url()
    if not rpc_url:
        return {"verified": False, "reason": "rpc_not_configured"}
    with _probe_lock:
        cached = _probe_cache.get(rpc_url)
        if cached is not None and cached[0] > time.monotonic():
            return dict(cached[1])
        result = _probe_paxg(rpc_url)
        _probe_cache[rpc_url] = (
            time.monotonic() + (60 if result["verified"] else 5), result,
        )
        return dict(result)


def paxg_capabilities() -> dict[str, Any]:
    from evm_networks import is_receive_enabled, is_send_enabled
    from vault_config import (
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_send_paused,
        ethereum_mainnet_tx_indexer_configured,
    )

    verification = verify_paxg_integration()
    verified = verification["verified"] is True
    receive = verified and is_receive_enabled(PAXG_NETWORK) and ethereum_mainnet_erc20_receive_enabled()
    return {
        **verification,
        "receiveEnabled": receive,
        "balanceEnabled": receive,
        "sendEnabled": verified and is_send_enabled(PAXG_NETWORK) and not ethereum_mainnet_send_paused(),
        "activityConnected": receive and ethereum_mainnet_tx_indexer_configured(),
    }


def build_asset_catalog() -> dict[str, Any]:
    from vault_config import crypto_wallet_engine_enabled

    capabilities = paxg_capabilities()
    categories = []
    for category_id, label in CATEGORIES:
        available = (crypto_wallet_engine_enabled() if category_id == "cryptocurrency"
                     else capabilities["verified"] if category_id == "digital_gold" else False)
        reason = None if available else (
            capabilities["reason"] if category_id == "digital_gold"
            else "wallet_engine_disabled" if category_id == "cryptocurrency"
            else "no_verified_token_integration"
        )
        categories.append({"id": category_id, "label": label, "available": available, "reason": reason})
    return {
        "schema": "svaultai_asset_catalog_v1",
        "categories": categories,
        "assets": [{
            "id": PAXG_ASSET, "category": "digital_gold", "symbol": "PAXG",
            "name": "PAX Gold", "standard": "ERC20", "network": PAXG_NETWORK,
            "chainId": 1, "contractAddress": PAXG_CONTRACT, "decimals": PAXG_DECIMALS,
            "verificationSource": PAXG_SOURCE, "transferNote": PAXG_TRANSFER_NOTE,
            **capabilities,
        }],
        "coverage": "Only listed, verified token/network integrations are supported. Unavailable categories cannot transfer assets.",
    }


def new_asset_gate(asset: str, network: str, capability: str) -> dict[str, Any] | None:
    """Only gates the new token. Existing cryptocurrency behavior is unchanged."""
    if asset != PAXG_ASSET:
        return None
    flags = paxg_capabilities() if network == PAXG_NETWORK else {
        "verified": False, "reason": "asset_network_unsupported",
    }
    key = {
        "receive": "receiveEnabled", "account_detail": "receiveEnabled",
        "create": "receiveEnabled", "balance": "balanceEnabled",
        "transactions": "activityConnected", "send_draft": "sendEnabled",
        "send_broadcast": "sendEnabled", "fee_estimate": "sendEnabled",
        "encrypted_secret": "sendEnabled",
    }.get(capability, "verified")
    if flags.get(key) is True:
        return None
    status = {
        "send_draft": "draft_unavailable", "send_broadcast": "broadcast_unavailable",
        "fee_estimate": "fee_estimate_unavailable",
    }.get(capability, "unavailable")
    return {
        "status": status, "wallet_engine": "asset_integration_unavailable",
        "asset": asset, "network": network, "networkId": network,
        "reason": flags.get("reason") or "asset_capability_unavailable",
        "balanceStatus": "unavailable", "availableAmount": None,
        "transactionsStatus": "unavailable", "transactions": [],
        "message": "This verified asset integration is unavailable for this network or action. No new transfer was initiated.",
    }
