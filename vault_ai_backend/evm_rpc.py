

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx


logger = logging.getLogger("evm_rpc")


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


ALLOWED_RPC_METHODS: frozenset[str] = frozenset({
    "eth_getBalance",
    "eth_call",
    "eth_getTransactionCount",
    "eth_gasPrice",
    "eth_estimateGas",
    "eth_sendRawTransaction",
    "eth_getTransactionReceipt",
})


ERC20_SELECTOR_BALANCE_OF: str = "0x70a08231"

                                                                   
ERC20_SELECTOR_TRANSFER: str = "0xa9059cbb"


_SIGNED_TX_RE = re.compile(r"^0x[0-9a-fA-F]{120,}$")


_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def is_valid_signed_tx_hex(payload):
    if not isinstance(payload, str):
        return False
    return bool(_SIGNED_TX_RE.match(payload))


def is_valid_tx_hash(tx_hash):
    if not isinstance(tx_hash, str):
        return False
    return bool(_TX_HASH_RE.match(tx_hash))


_TIMEOUT_SECS = 6


class EvmRpcError(RuntimeError):


    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def is_valid_eth_address(addr: Optional[str]) -> bool:
    if not isinstance(addr, str):
        return False
    return bool(_ETH_ADDRESS_RE.match(addr))


def _emit_rpc_at_url(rpc_url: str, method: str, params: list) -> dict:


    if method not in ALLOWED_RPC_METHODS:
        raise EvmRpcError("method_forbidden")
    if not rpc_url:
        raise EvmRpcError("not_configured")
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  method,
        "params":  params,
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_SECS) as client:
            resp = client.post(
                rpc_url, json=payload,
                headers={
                    "content-type": "application/json",
                    "accept":       "application/json",
                },
            )
    except httpx.TimeoutException:
        logger.warning("[EVM-RPC] upstream_timeout method=%s", method)
        raise EvmRpcError("upstream_timeout")
    except (httpx.HTTPError, OSError):
        logger.warning("[EVM-RPC] upstream_io method=%s", method)
        raise EvmRpcError("upstream_io")
    if resp.status_code != 200:
        logger.warning(
            "[EVM-RPC] upstream_http method=%s status=%s",
            method, resp.status_code,
        )
        raise EvmRpcError("upstream_http")
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning("[EVM-RPC] upstream_json method=%s", method)
        raise EvmRpcError("upstream_json")
    if not isinstance(body, dict):
        raise EvmRpcError("upstream_json")
    if "error" in body:
        err = body["error"]
        if isinstance(err, dict):
            logger.warning(
                "[EVM-RPC] upstream_rpc method=%s code=%s",
                method, err.get("code"),
            )
        raise EvmRpcError("upstream_rpc")
    return body


def _parse_hex_int(result: object) -> int:
    if not isinstance(result, str) or not result.startswith("0x"):
        raise EvmRpcError("upstream_json")
    try:
        return int(result, 16)
    except ValueError:
        raise EvmRpcError("upstream_json")


def eth_get_balance_wei_at_url(rpc_url: str, address: str) -> int:


    if not is_valid_eth_address(address):
        raise EvmRpcError("invalid_address")
    body = _emit_rpc_at_url(rpc_url, "eth_getBalance", [address, "latest"])
    return _parse_hex_int(body.get("result"))


def _pad_address_to_32(address: str) -> str:


    if not is_valid_eth_address(address):
        raise EvmRpcError("invalid_address")
    return "000000000000000000000000" + address[2:].lower()


def encode_erc20_balance_of_calldata(holder_address: str) -> str:


    selector_hex = ERC20_SELECTOR_BALANCE_OF[2:]
    holder_hex = _pad_address_to_32(holder_address)
    return "0x" + selector_hex + holder_hex


def erc20_balance_of_at_url(
    rpc_url: str,
    *,
    token_contract_address: str,
    holder_address: str,
) -> int:


    if not is_valid_eth_address(token_contract_address):
        raise EvmRpcError("invalid_token_contract")
    if not is_valid_eth_address(holder_address):
        raise EvmRpcError("invalid_address")
    calldata = encode_erc20_balance_of_calldata(holder_address)
    params = [
        {"to": token_contract_address, "data": calldata},
        "latest",
    ]
    body = _emit_rpc_at_url(rpc_url, "eth_call", params)
    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise EvmRpcError("upstream_json")
                                                                   
                                                                    
    if len(result) < 2 + 64:
        raise EvmRpcError("upstream_json")
    try:
        return int(result, 16)
    except ValueError:
        raise EvmRpcError("upstream_json")


def eth_get_transaction_count_at_url(rpc_url: str, address: str) -> int:


    if not is_valid_eth_address(address):
        raise EvmRpcError("invalid_address")
    body = _emit_rpc_at_url(
        rpc_url, "eth_getTransactionCount", [address, "pending"],
    )
    return _parse_hex_int(body.get("result"))


def eth_gas_price_wei_at_url(rpc_url: str) -> int:

    body = _emit_rpc_at_url(rpc_url, "eth_gasPrice", [])
    return _parse_hex_int(body.get("result"))


def eth_estimate_gas_at_url(
    rpc_url: str,
    *,
    from_address: str,
    to_address: str,
    value_wei: int,
    data_hex: str = "0x",
) -> int:


    if not is_valid_eth_address(from_address):
        raise EvmRpcError("invalid_address")
    if not is_valid_eth_address(to_address):
        raise EvmRpcError("invalid_address")
    if not isinstance(value_wei, int) or value_wei < 0:
        raise EvmRpcError("invalid_amount")
    if not isinstance(data_hex, str):
        raise EvmRpcError("invalid_data")
    if data_hex and not data_hex.startswith("0x"):
        raise EvmRpcError("invalid_data")
    params = [
        {
            "from":  from_address,
            "to":    to_address,
            "value": hex(value_wei),
            "data":  data_hex if data_hex else "0x",
        },
    ]
    body = _emit_rpc_at_url(rpc_url, "eth_estimateGas", params)
    return _parse_hex_int(body.get("result"))


def eth_send_raw_transaction_at_url(rpc_url: str, signed_tx_hex: str) -> str:


    if not is_valid_signed_tx_hex(signed_tx_hex):
        raise EvmRpcError("invalid_signed_tx")
    body = _emit_rpc_at_url(
        rpc_url, "eth_sendRawTransaction", [signed_tx_hex],
    )
    result = body.get("result")
    if not is_valid_tx_hash(result):
        raise EvmRpcError("upstream_json")
    return result                              


def eth_get_transaction_receipt_at_url(
    rpc_url: str, tx_hash: str,
) -> Optional[dict]:


    if not is_valid_tx_hash(tx_hash):
        raise EvmRpcError("invalid_tx_hash")
    body = _emit_rpc_at_url(
        rpc_url, "eth_getTransactionReceipt", [tx_hash],
    )
    result = body.get("result")
    if result is None:
        return None
    if not isinstance(result, dict):
        raise EvmRpcError("upstream_json")
    return result


def _pad_uint256(value: int) -> str:


    if not isinstance(value, int):
        raise EvmRpcError("invalid_amount")
    if value < 0:
        raise EvmRpcError("invalid_amount")
    if value >= (1 << 256):
        raise EvmRpcError("invalid_amount")
    return format(value, "064x")


def encode_erc20_transfer_calldata(
    *, destination_address: str, amount_base_units: int,
) -> str:


    selector_hex = ERC20_SELECTOR_TRANSFER[2:]
    dest_hex = _pad_address_to_32(destination_address)
    amount_hex = _pad_uint256(amount_base_units)
    return "0x" + selector_hex + dest_hex + amount_hex


__all__ = [
    "ALLOWED_RPC_METHODS",
    "ERC20_SELECTOR_BALANCE_OF",
    "ERC20_SELECTOR_TRANSFER",
    "EvmRpcError",
    "is_valid_eth_address",
    "is_valid_signed_tx_hex",
    "is_valid_tx_hash",
    "eth_get_balance_wei_at_url",
    "encode_erc20_balance_of_calldata",
    "erc20_balance_of_at_url",
    "eth_get_transaction_count_at_url",
    "eth_gas_price_wei_at_url",
    "eth_estimate_gas_at_url",
    "eth_send_raw_transaction_at_url",
    "eth_get_transaction_receipt_at_url",
    "encode_erc20_transfer_calldata",
]
