

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from vault_config import ethereum_sepolia_rpc_url


logger = logging.getLogger("ethereum_sepolia_proxy")


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


ALLOWED_RPC_METHODS: frozenset[str] = frozenset({
    "eth_getBalance",
    "eth_getTransactionCount",
    "eth_gasPrice",
    "eth_estimateGas",
    "eth_sendRawTransaction",
    "eth_getTransactionReceipt",
                                                                
                                                                
    "eth_call",
})


SEPOLIA_CHAIN_ID: int = 11155111


_SIGNED_TX_RE = re.compile(r"^0x[0-9a-fA-F]{120,}$")


_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


import os
_TIMEOUT_SECS = max(1, min(60, int(
    os.getenv("ETHEREUM_SEPOLIA_RPC_TIMEOUT_SECONDS", "6"),
)))


class SepoliaProxyError(RuntimeError):


    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def is_valid_eth_address(addr: Optional[str]) -> bool:


    if not isinstance(addr, str):
        return False
    return bool(_ETH_ADDRESS_RE.match(addr))


def _emit_rpc(method: str, params: list) -> dict:


    if method not in ALLOWED_RPC_METHODS:
        raise SepoliaProxyError("method_forbidden")
    url = ethereum_sepolia_rpc_url()
    if not url:
        raise SepoliaProxyError("not_configured")

    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  method,
        "params":  params,
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_SECS) as client:
            resp = client.post(
                url, json=payload,
                headers={
                    "content-type": "application/json",
                    "accept":       "application/json",
                },
            )
    except httpx.TimeoutException:
                                                                  
        logger.warning(
            "[SEPOLIA-PROXY] upstream_timeout method=%s", method,
        )
        raise SepoliaProxyError("upstream_timeout")
    except (httpx.HTTPError, OSError):
        logger.warning(
            "[SEPOLIA-PROXY] upstream_io method=%s", method,
        )
        raise SepoliaProxyError("upstream_io")

    if resp.status_code != 200:
        logger.warning(
            "[SEPOLIA-PROXY] upstream_http method=%s status=%s",
            method, resp.status_code,
        )
        raise SepoliaProxyError("upstream_http")

    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "[SEPOLIA-PROXY] upstream_json method=%s", method,
        )
        raise SepoliaProxyError("upstream_json")

    if not isinstance(body, dict):
        raise SepoliaProxyError("upstream_json")

    if "error" in body:
                                                               
                                                              
        err = body["error"]
        if isinstance(err, dict):
            logger.warning(
                "[SEPOLIA-PROXY] upstream_rpc method=%s code=%s",
                method, err.get("code"),
            )
        raise SepoliaProxyError("upstream_rpc")

    return body


def _parse_hex_int(result: object) -> int:


    if not isinstance(result, str) or not result.startswith("0x"):
        raise SepoliaProxyError("upstream_json")
    try:
        return int(result, 16)
    except ValueError:
        raise SepoliaProxyError("upstream_json")


def is_valid_signed_tx_hex(payload: Optional[str]) -> bool:


    if not isinstance(payload, str):
        return False
    return bool(_SIGNED_TX_RE.match(payload))


def is_valid_tx_hash(tx_hash: Optional[str]) -> bool:

    if not isinstance(tx_hash, str):
        return False
    return bool(_TX_HASH_RE.match(tx_hash))


def eth_get_balance_wei(address: str) -> int:


    if not is_valid_eth_address(address):
        raise SepoliaProxyError("invalid_address")
    body = _emit_rpc("eth_getBalance", [address, "latest"])
    return _parse_hex_int(body.get("result"))


def eth_get_transaction_count(address: str) -> int:


    if not is_valid_eth_address(address):
        raise SepoliaProxyError("invalid_address")
    body = _emit_rpc("eth_getTransactionCount", [address, "pending"])
    return _parse_hex_int(body.get("result"))


def eth_gas_price_wei() -> int:

    body = _emit_rpc("eth_gasPrice", [])
    return _parse_hex_int(body.get("result"))


def eth_estimate_gas(
    *,
    from_address: str,
    to_address: str,
    value_wei: int,
    data_hex: str = "0x",
) -> int:


    if not is_valid_eth_address(from_address):
        raise SepoliaProxyError("invalid_address")
    if not is_valid_eth_address(to_address):
        raise SepoliaProxyError("invalid_address")
    if not isinstance(value_wei, int) or value_wei < 0:
        raise SepoliaProxyError("invalid_amount")
    if not isinstance(data_hex, str):
        raise SepoliaProxyError("invalid_data")
    if data_hex and not data_hex.startswith("0x"):
        raise SepoliaProxyError("invalid_data")
    params = [
        {
            "from":  from_address,
            "to":    to_address,
            "value": hex(value_wei),
            "data":  data_hex if data_hex else "0x",
        },
    ]
    body = _emit_rpc("eth_estimateGas", params)
    return _parse_hex_int(body.get("result"))


def eth_send_raw_transaction(signed_tx_hex: str) -> str:


    if not is_valid_signed_tx_hex(signed_tx_hex):
        raise SepoliaProxyError("invalid_signed_tx")
    body = _emit_rpc("eth_sendRawTransaction", [signed_tx_hex])
    result = body.get("result")
    if not is_valid_tx_hash(result):
        raise SepoliaProxyError("upstream_json")
    return result                              


ERC20_SELECTOR_BALANCE_OF: str = "0x70a08231"
ERC20_SELECTOR_TRANSFER:   str = "0xa9059cbb"


def _pad_address_to_32(address: str) -> str:


    if not is_valid_eth_address(address):
        raise SepoliaProxyError("invalid_address")
    return "000000000000000000000000" + address[2:].lower()


def _pad_uint256(value: int) -> str:


    if not isinstance(value, int):
        raise SepoliaProxyError("invalid_amount")
    if value < 0:
        raise SepoliaProxyError("invalid_amount")
    if value >= (1 << 256):
        raise SepoliaProxyError("invalid_amount")
    return format(value, "064x")


def encode_erc20_transfer_calldata(
    *, destination_address: str, amount_base_units: int,
) -> str:


    selector_hex = ERC20_SELECTOR_TRANSFER[2:]            
    dest_hex = _pad_address_to_32(destination_address)
    amount_hex = _pad_uint256(amount_base_units)
    return "0x" + selector_hex + dest_hex + amount_hex


def encode_erc20_balance_of_calldata(holder_address: str) -> str:

    selector_hex = ERC20_SELECTOR_BALANCE_OF[2:]
    holder_hex = _pad_address_to_32(holder_address)
    return "0x" + selector_hex + holder_hex


def erc20_balance_of(
    *, token_contract_address: str, holder_address: str,
) -> int:


    if not is_valid_eth_address(token_contract_address):
        raise SepoliaProxyError("invalid_token_contract")
    if not is_valid_eth_address(holder_address):
        raise SepoliaProxyError("invalid_address")
    calldata = encode_erc20_balance_of_calldata(holder_address)
    params = [
        {"to": token_contract_address, "data": calldata},
        "latest",
    ]
    body = _emit_rpc("eth_call", params)
    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise SepoliaProxyError("upstream_json")
                                                                   
                                                                    
    if len(result) < 2 + 64:
        raise SepoliaProxyError("upstream_json")
    try:
        return int(result, 16)
    except ValueError:
        raise SepoliaProxyError("upstream_json")


def eth_get_transaction_receipt(tx_hash: str) -> Optional[dict]:


    if not is_valid_tx_hash(tx_hash):
        raise SepoliaProxyError("invalid_tx_hash")
    body = _emit_rpc("eth_getTransactionReceipt", [tx_hash])
    result = body.get("result")
    if result is None:
        return None
    if not isinstance(result, dict):
        raise SepoliaProxyError("upstream_json")
    return result


__all__ = [
    "ALLOWED_RPC_METHODS",
    "SEPOLIA_CHAIN_ID",
    "SepoliaProxyError",
    "eth_get_balance_wei",
    "eth_get_transaction_count",
    "eth_gas_price_wei",
    "eth_estimate_gas",
    "eth_send_raw_transaction",
    "eth_get_transaction_receipt",
                            
    "ERC20_SELECTOR_BALANCE_OF",
    "ERC20_SELECTOR_TRANSFER",
    "encode_erc20_balance_of_calldata",
    "encode_erc20_transfer_calldata",
    "erc20_balance_of",
    "is_valid_eth_address",
    "is_valid_signed_tx_hex",
    "is_valid_tx_hash",
]
