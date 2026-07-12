

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

    # 2026-07-13: rework: an RPC failure is only "definitely not
    # submitted to the network" when we successfully parsed a valid
    # JSON-RPC error object from the provider. Any transport or
    # protocol ambiguity (timeout, connection reset after write,
    # HTTP 5xx, HTTP 4xx from the gateway, malformed JSON body,
    # missing result envelope) leaves the request status unknown --
    # the raw transaction MAY have reached and been accepted by the
    # provider before the response was lost. Callers doing a state-
    # changing broadcast MUST treat is_ambiguous=True as "submission
    # uncertain" and preserve the draft's consumed state, not as
    # "rejected".
    #
    # If `is_ambiguous` is not explicitly passed we DERIVE it from
    # `code` so legacy call sites (tests that only pass the code)
    # keep working correctly. Only `upstream_rpc` -- the explicit
    # JSON-RPC error path -- is treated as non-ambiguous by default.
    _AMBIGUOUS_CODES = frozenset({
        "upstream_timeout",
        "upstream_io",
        "upstream_http",
        "upstream_json",
    })

    def __init__(
        self,
        code,
        *,
        is_ambiguous=None,
        rpc_error_code=None,
        rpc_error_message=None,
    ):
        self.code = code
        if is_ambiguous is None:
            is_ambiguous = code in EvmRpcError._AMBIGUOUS_CODES
        self.is_ambiguous = bool(is_ambiguous)
        self.rpc_error_code = rpc_error_code
        self.rpc_error_message = rpc_error_message
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
        # Timeouts split into two cases: pre-request (connect timeout,
        # write timeout mid-payload -> theoretically not delivered)
        # and post-request (read timeout -> upstream may already have
        # accepted). httpx doesn't cleanly distinguish these in a
        # portable way and the write-half completing does NOT prove
        # non-delivery. Conservative: treat every timeout as ambiguous.
        logger.warning("[EVM-RPC] upstream_timeout method=%s", method)
        raise EvmRpcError("upstream_timeout", is_ambiguous=True)
    except (httpx.HTTPError, OSError):
        # Includes ConnectionError, ProtocolError, ReadError,
        # ConnectionResetError. The request bytes may have been
        # written to the socket and received by the upstream before
        # the response was lost -- ambiguous.
        logger.warning("[EVM-RPC] upstream_io method=%s", method)
        raise EvmRpcError("upstream_io", is_ambiguous=True)
    if resp.status_code != 200:
        # HTTP != 200: the upstream (or an intermediary) responded with
        # a non-success status. 5xx especially can happen AFTER the
        # request reached the RPC node -- we cannot prove the node
        # did not process the raw tx. Conservative: ambiguous.
        logger.warning(
            "[EVM-RPC] upstream_http method=%s status=%s",
            method, resp.status_code,
        )
        raise EvmRpcError("upstream_http", is_ambiguous=True)
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        # HTTP 200 + unparseable body. Node responded but the body is
        # corrupt/truncated -- we don't know the outcome.
        logger.warning("[EVM-RPC] upstream_json method=%s", method)
        raise EvmRpcError("upstream_json", is_ambiguous=True)
    if not isinstance(body, dict):
        raise EvmRpcError("upstream_json", is_ambiguous=True)
    if "error" in body:
        # Explicit JSON-RPC error object -- the node processed the
        # request and returned a structured rejection. NOT ambiguous.
        err = body["error"]
        rpc_code = None
        rpc_msg = None
        if isinstance(err, dict):
            rpc_code = err.get("code") if isinstance(
                err.get("code"), int
            ) else None
            rpc_msg_raw = err.get("message")
            if isinstance(rpc_msg_raw, str):
                rpc_msg = rpc_msg_raw
            logger.warning(
                "[EVM-RPC] upstream_rpc method=%s code=%s",
                method, rpc_code,
            )
        raise EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=rpc_code,
            rpc_error_message=rpc_msg,
        )
    # Missing result field (and no error field either) -- unexpected
    # envelope shape; treat as ambiguous since we can't confirm outcome.
    if "result" not in body:
        logger.warning(
            "[EVM-RPC] upstream_json_missing_result method=%s", method,
        )
        raise EvmRpcError("upstream_json", is_ambiguous=True)
    return body


def _parse_hex_int(result: object) -> int:
    if not isinstance(result, str) or not result.startswith("0x"):
        raise EvmRpcError("upstream_json")
    try:
        return int(result, 16)
    except ValueError:
        raise EvmRpcError("upstream_json")


_ALLOWED_BLOCK_TAGS: frozenset[str] = frozenset({"latest", "pending"})


def eth_get_balance_wei_at_url(
    rpc_url: str,
    address: str,
    *,
    block_tag: str = "latest",
) -> int:










    if not is_valid_eth_address(address):
        raise EvmRpcError("invalid_address")
    if block_tag not in _ALLOWED_BLOCK_TAGS:
        raise EvmRpcError("invalid_block_tag")
    body = _emit_rpc_at_url(rpc_url, "eth_getBalance", [address, block_tag])
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
    block_tag: str = "latest",
) -> int:










    if not is_valid_eth_address(token_contract_address):
        raise EvmRpcError("invalid_token_contract")
    if not is_valid_eth_address(holder_address):
        raise EvmRpcError("invalid_address")
    if block_tag not in _ALLOWED_BLOCK_TAGS:
        raise EvmRpcError("invalid_block_tag")
    calldata = encode_erc20_balance_of_calldata(holder_address)
    params = [
        {"to": token_contract_address, "data": calldata},
        block_tag,
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
