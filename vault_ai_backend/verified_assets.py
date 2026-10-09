"""Closed real-asset registry; this module never buys, trades or signs tokens.

PAXG's proxy and ERC20 specification are published by the issuer:
https://github.com/paxosglobal/paxos-gold-contract
The supported tuple is immutable. Operator configuration cannot substitute an
arbitrary contract, chain or decimal precision under the PAXG name.
"""
from __future__ import annotations

import os
import hashlib
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
    "Issuer rules may pause or freeze transfers. ETH pays network gas; "
    "separate issuer purchase or redemption fees may apply."
)
KAG_ASSET = "KAG_ERC20"
KAG_CONTRACT = "0x56Ba8B58B7d1f6d384A1C4dD553F39ebc8741B8e"
KAG_NETWORK = "ethereum_mainnet"
KAG_DECIMALS = 18
KAG_SOURCE = "https://kmslabs.money/documents/"
KAG_IMPLEMENTATION = "0x0f25045d15c163478bb67c56c5d9d602628f4f62"
KAG_ACCESS_REGISTRY = "0x25f604795215fc9468f8d2cc60e96330110b4861"
KAG_REGISTRY_IMPLEMENTATION = "0x0d7d2f28ab186cd706878c9943221b001bcfc3d7"
# Pinned runtime SHA-256 fingerprints, independently read at Ethereum block
# 0x18f2336 on 2026-10-09, are checked alongside EIP-1967 identity.
# These public-code fingerprints are not secrets or name/privacy identifiers.
KAG_CODE_SHA256: dict[str, str] = {
    KAG_CONTRACT.lower(): "944b876557c3f1e0a8db2ff5596fc3dc2bd88dd14aaca507c0b1abdc578db001",
    KAG_IMPLEMENTATION.lower(): "67b5282aa52d48b0156e2feb617b49bd2b2c4cd7fd3b98017c70533bcbeaa64d",
    KAG_ACCESS_REGISTRY.lower(): "944b876557c3f1e0a8db2ff5596fc3dc2bd88dd14aaca507c0b1abdc578db001",
    KAG_REGISTRY_IMPLEMENTATION.lower(): "c4019ce646ad26880dcd20c50a36911e1aa4d0b324d1d25518d1044ccce4da06",
}
_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
KAG_TRANSFER_NOTE = (
    "KMS Labs Ethereum KAG is distinct from native Kinesis-network KAG. "
    "Issuer controls can pause, restrict or recover tokens. ETH pays gas. "
    "These tokens do not provide direct title to silver bars; issuer terms apply."
)
REGISTERED_TOKEN_ASSETS = frozenset({PAXG_ASSET, KAG_ASSET})

CATEGORIES = (
    ("cryptocurrency", "Cryptocurrency"),
    ("digital_gold", "Digital Gold"),
    ("digital_silver", "Digital Silver"),
    ("tokenized_real_estate", "Tokenized Real Estate"),
    ("tokenized_diamonds_gemstones", "Tokenized Diamonds and Gemstones"),
    ("tokenized_artwork", "Tokenized Artwork"),
    ("tokenized_watches_collectibles", "Tokenized Watches and Collectibles"),
    ("tokenized_vehicles_equipment", "Tokenized Vehicles and Equipment"),
    ("tokenized_inventory_supply_chain", "Tokenized Inventory and Supply Chain Goods"),
    ("tokenized_securities_equities", "Tokenized Securities and Equities"),
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


def kag_amount_base_units(amount: str) -> int:
    # Both closed issuer tuples have exactly 18 decimals; no ambient rounding.
    return paxg_amount_base_units(amount)


def kag_base_units_to_decimal(units: int) -> str:
    return paxg_base_units_to_decimal(units)


def kag_enabled() -> bool:
    return os.getenv("VAULTAI_ASSETS_KAG_ENABLED", "false").strip().lower() in {
        "true", "1", "yes", "on",
    }


def _abi_word(result: Any) -> int:
    if not isinstance(result, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", result):
        raise ValueError("invalid_issuer_response")
    return int(result, 16)


def _abi_address(result: Any) -> str:
    value = _abi_word(result)
    if not 0 < value < 2**160:
        raise ValueError("invalid_issuer_address")
    return "0x" + format(value, "040x")


def _abi_bool(result: Any) -> bool:
    value = _abi_word(result)
    if value not in (0, 1):
        raise ValueError("invalid_issuer_boolean")
    return bool(value)


def _probe_kag(rpc_url: str, *, sender: str | None = None,
               recipient: str | None = None, data_hex: str = "0x") -> dict[str, Any]:
    """Fresh, same-block issuer identity/control checks; never cache access.

    The pinned deployed Fireblocks ERC20F invokes DenyList.hasAccess for both
    transfer parties. We repeat that exact ABI and simulate the exact transfer
    at quote/draft time. Unknown implementations or registry changes suspend
    this integration rather than silently accepting changed issuer rules.
    """
    from evm_rpc import EvmRpcError, emit_readonly_rpc_batch_at_url
    try:
        initial = emit_readonly_rpc_batch_at_url(rpc_url, [("eth_chainId", []), ("eth_blockNumber", [])])
        if initial[0].get("result") != "0x1":
            return {"verified": False, "reason": "chain_mismatch"}
        block = initial[1].get("result")
        if not isinstance(block, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", block):
            raise ValueError("invalid_issuer_block")
        addresses = (KAG_CONTRACT, KAG_IMPLEMENTATION, KAG_ACCESS_REGISTRY, KAG_REGISTRY_IMPLEMENTATION)
        calls = [("eth_getCode", [address, block]) for address in addresses]
        calls.extend([("eth_getStorageAt", [proxy, _IMPLEMENTATION_SLOT, block])
                      for proxy in (KAG_CONTRACT, KAG_ACCESS_REGISTRY)])
        calls.extend([("eth_call", [{"to": to, "data": selector}, block]) for to, selector in (
            (KAG_CONTRACT, "0x313ce567"), (KAG_CONTRACT, "0xe6f29b05"),
            (KAG_CONTRACT, "0x5c975abb"), (KAG_ACCESS_REGISTRY, "0x5c975abb"),
        )])
        caller = sender or recipient
        if caller is not None:
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", caller):
                raise ValueError("invalid_transfer_party")
            if (not isinstance(data_hex, str) or len(data_hex) > 138
                    or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", data_hex)):
                raise ValueError("invalid_transfer_data")
            data = data_hex[2:]
            for account in (sender, recipient):
                if account is None:
                    continue
                if not re.fullmatch(r"0x[0-9a-fA-F]{40}", account):
                    raise ValueError("invalid_transfer_party")
                encoded = ("0xeefb7e9a" + account[2:].lower().rjust(64, "0")
                           + caller[2:].lower().rjust(64, "0") + format(96, "064x")
                           + format(len(data) // 2, "064x")
                           + data.ljust(((len(data) + 63) // 64) * 64, "0"))
                calls.append(("eth_call", [{"to": KAG_ACCESS_REGISTRY, "data": encoded,
                                            "from": KAG_CONTRACT}, block]))
        results = emit_readonly_rpc_batch_at_url(rpc_url, calls)
        for address, reply in zip(addresses, results[:4]):
            code = reply.get("result")
            if (not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code)
                    or not any(c != "0" for c in code[2:])):
                return {"verified": False, "reason": "verified_token_contract_missing"}
            expected = KAG_CODE_SHA256.get(address.lower())
            if not expected or hashlib.sha256(bytes.fromhex(code[2:])).hexdigest() != expected:
                return {"verified": False, "reason": "issuer_code_fingerprint_mismatch"}
        for reply, expected in zip(results[4:6], (KAG_IMPLEMENTATION, KAG_REGISTRY_IMPLEMENTATION)):
            result = reply.get("result")
            if _abi_address(result) != expected.lower():
                return {"verified": False, "reason": "issuer_implementation_changed"}

        if _abi_word(results[6].get("result")) != KAG_DECIMALS:
            return {"verified": False, "reason": "verified_token_decimals_mismatch"}
        if _abi_address(results[7].get("result")) != KAG_ACCESS_REGISTRY.lower():
            return {"verified": False, "reason": "issuer_access_registry_changed"}
        if _abi_bool(results[8].get("result")) or _abi_bool(results[9].get("result")):
            return {"verified": True, "transfersAllowed": False, "reason": "issuer_paused"}
        for reply in results[10:]:
            if not _abi_bool(reply.get("result")):
                return {"verified": True, "transfersAllowed": False, "reason": "issuer_address_restricted"}
    except (EvmRpcError, ValueError, TypeError, AttributeError):
        return {"verified": False, "reason": "verified_token_provider_unavailable"}
    return {"verified": True, "transfersAllowed": True, "reason": None,
            "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def verify_kag_integration(*, sender: str | None = None, recipient: str | None = None,
                           data_hex: str = "0x") -> dict[str, Any]:
    from vault_config import crypto_wallet_engine_enabled, ethereum_mainnet_rpc_url
    if not crypto_wallet_engine_enabled() or not kag_enabled():
        return {"verified": False, "reason": "asset_integration_disabled"}
    url = ethereum_mainnet_rpc_url()
    if not url:
        return {"verified": False, "reason": "rpc_not_configured"}
    return _probe_kag(url, sender=sender, recipient=recipient, data_hex=data_hex)

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


def kag_capabilities() -> dict[str, Any]:
    from evm_networks import is_receive_enabled, is_send_enabled
    from vault_config import (ethereum_mainnet_erc20_receive_enabled,
                              ethereum_mainnet_send_paused,
                              ethereum_mainnet_tx_indexer_configured)
    verification = verify_kag_integration()
    readable = (verification["verified"] is True and is_receive_enabled(KAG_NETWORK)
                and ethereum_mainnet_erc20_receive_enabled())
    transfers = verification.get("transfersAllowed") is True
    return {**verification, "receiveEnabled": readable and transfers,
            "balanceEnabled": readable,
            "sendEnabled": verification["verified"] is True and transfers
                           and is_send_enabled(KAG_NETWORK) and not ethereum_mainnet_send_paused(),
            "activityConnected": readable and ethereum_mainnet_tx_indexer_configured()}


def kag_address_gate(asset: str, capability: str, *, sender: str | None = None,
                     recipient: str | None = None, data_hex: str = "0x") -> dict[str, Any] | None:
    if asset != KAG_ASSET:
        return None
    if (not sender and not recipient) or (capability in {"send_draft", "send_broadcast", "fee_estimate"}
                                          and (not sender or not recipient)):
        return _asset_unavailable(asset, KAG_NETWORK, capability, "invalid_address")
    result = verify_kag_integration(sender=sender, recipient=recipient, data_hex=data_hex)
    if result.get("verified") is True and result.get("transfersAllowed") is True:
        return None
    return _asset_unavailable(asset, KAG_NETWORK, capability, result.get("reason"))


def build_asset_catalog() -> dict[str, Any]:
    from vault_config import crypto_wallet_engine_enabled

    capabilities = paxg_capabilities()
    silver = kag_capabilities()
    categories = []
    for category_id, label in CATEGORIES:
        available = (crypto_wallet_engine_enabled() if category_id == "cryptocurrency"
                     else capabilities["verified"] if category_id == "digital_gold"
                     else silver["balanceEnabled"] if category_id == "digital_silver" else False)
        reason = None if available else (
            capabilities["reason"] if category_id == "digital_gold"
            else silver["reason"] if category_id == "digital_silver"
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
        }, {
            "id": KAG_ASSET, "category": "digital_silver", "symbol": "KAG",
            "name": "KMS Labs KAG Silver", "standard": "ERC20", "network": KAG_NETWORK,
            "chainId": 1, "contractAddress": KAG_CONTRACT, "decimals": KAG_DECIMALS,
            "verificationSource": KAG_SOURCE, "transferNote": KAG_TRANSFER_NOTE,
            "issuerTerms": "https://kmslabs.money/kms-labs-tcs/",
            "eligibilityNote": "Issuer eligibility and jurisdiction restrictions apply. Support here is wallet custody/transfer only, not buying, trading or redemption.",
            **silver,
        }],
        "coverage": "Only listed, verified token/network integrations are supported. Unavailable categories cannot transfer assets.",
    }


def new_asset_gate(asset: str, network: str, capability: str) -> dict[str, Any] | None:
    """Only gates the closed new tokens. Existing cryptocurrency is unchanged."""
    if asset not in REGISTERED_TOKEN_ASSETS:
        return None
    flags = (paxg_capabilities() if asset == PAXG_ASSET else kag_capabilities()) if network == PAXG_NETWORK else {
        "verified": False, "reason": "asset_network_unsupported",
    }
    key = {
        "receive": "receiveEnabled", "account_detail": "receiveEnabled",
        "create": "receiveEnabled", "balance": "balanceEnabled",
        "transactions": "activityConnected", "send_draft": "sendEnabled",
        "send_broadcast": "sendEnabled", "fee_estimate": "sendEnabled",
        "encrypted_secret": "sendEnabled",
    }.get(capability, "verified")
    if asset == KAG_ASSET and capability == "account_detail":
        key = "balanceEnabled"
    if flags.get(key) is True:
        return None
    return _asset_unavailable(asset, network, capability, flags.get("reason"))


def _asset_unavailable(asset: str, network: str, capability: str, reason: Any) -> dict[str, Any]:
    status = {
        "send_draft": "draft_unavailable", "send_broadcast": "broadcast_unavailable",
        "fee_estimate": "fee_estimate_unavailable",
    }.get(capability, "unavailable")
    return {
        "status": status, "wallet_engine": "asset_integration_unavailable",
        "asset": asset, "network": network, "networkId": network,
        "reason": reason or "asset_capability_unavailable",
        "balanceStatus": "unavailable", "availableAmount": None,
        "transactionsStatus": "unavailable", "transactions": [],
        "message": "This verified asset integration is unavailable for this network or action. No new transfer was initiated.",
    }
