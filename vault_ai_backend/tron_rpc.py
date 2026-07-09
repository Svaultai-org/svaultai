

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

import urllib.request
import urllib.error


TRON_MAINNET_CHAIN_LABEL: str = "tron_mainnet"

USDT_TRC20_DECIMALS: int = 6
USDT_TRC20_UNIT: str = "USDT"


REASON_RPC_NOT_CONFIGURED: str = "rpc_not_configured"
REASON_RPC_UNREACHABLE:    str = "rpc_unreachable"
REASON_RPC_ERROR:          str = "rpc_error"
REASON_INVALID_ADDRESS:    str = "invalid_address"
REASON_INVALID_CONTRACT:   str = "token_contract_not_configured"
REASON_CONTRACT_READ_FAILED: str = "contract_read_failed"
REASON_DRAFT_BUILD_FAILED: str = "draft_build_failed"
REASON_BROADCAST_FAILED:   str = "broadcast_failed"
REASON_INVALID_SIGNED_TX:  str = "invalid_signed_transaction"
REASON_INVALID_TXID:       str = "invalid_txid"




REASON_TRON_API_NOT_CONFIGURED:      str = "tron_api_not_configured"
REASON_TRON_API_KEY_MISSING:         str = "tron_api_key_missing"
REASON_TRON_API_UNAUTHORIZED:        str = "tron_api_unauthorized"
REASON_TRON_RATE_LIMITED:            str = "tron_rate_limited"
REASON_TRON_PROVIDER_UNREACHABLE:    str = "tron_provider_unreachable"
REASON_TRON_CONTRACT_NOT_CONFIGURED: str = "tron_contract_not_configured"
REASON_TRON_CONTRACT_READ_FAILED:    str = "tron_contract_read_failed"
REASON_TRON_INVALID_ADDRESS:         str = "tron_invalid_address"
REASON_TRON_PROVIDER_ERROR:          str = "tron_provider_error"

SUN_PER_TRX: int = 1_000_000
TRON_TXID_HEX_LEN: int = 64
TRON_SIGNATURE_HEX_LEN: int = 130


_BASE58_ALPHABET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


_TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")

TRON_MAINNET_PREFIX: int = 0x41


class TronRpcError(Exception):

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message


def _base58_decode(s: str) -> bytes:
    if not s:
        return b""
    n = 0
    for c in s:
        idx = _BASE58_INDEX.get(c)
        if idx is None:
            raise ValueError("invalid base58 character")
        n = n * 58 + idx
    if n == 0:
        body = b""
    else:
        body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    leading_ones = 0
    for c in s:
        if c == "1":
            leading_ones += 1
        else:
            break
    return b"\x00" * leading_ones + body


def _base58_encode(raw: bytes) -> str:
    if not raw:
        return ""
    n = 0
    for b in raw:
        n = (n << 8) | b
    encoded = ""
    while n > 0:
        n, rem = divmod(n, 58)
        encoded = _BASE58_ALPHABET[rem] + encoded
    leading_zeros = 0
    for b in raw:
        if b == 0:
            leading_zeros += 1
        else:
            break
    return _BASE58_ALPHABET[0] * leading_zeros + encoded


def _double_sha256(raw: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(raw).digest()).digest()


def is_valid_tron_address(raw: Optional[str]) -> bool:

    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if not _TRON_ADDRESS_RE.match(s):
        return False
    try:
        decoded = _base58_decode(s)
    except ValueError:
        return False
    if len(decoded) != 25:
        return False
    if decoded[0] != TRON_MAINNET_PREFIX:
        return False
    payload = decoded[:21]
    checksum = decoded[21:]
    if _double_sha256(payload)[:4] != checksum:
        return False
    return True


def tron_address_to_hex(raw: str) -> str:

    if not is_valid_tron_address(raw):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    decoded = _base58_decode(raw.strip())
    return decoded[:21].hex()


def tron_address_to_evm_hex(raw: str) -> str:

    if not is_valid_tron_address(raw):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    decoded = _base58_decode(raw.strip())
    return decoded[1:21].hex()


def hex_to_tron_address(raw_hex: str) -> str:

    if not isinstance(raw_hex, str):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    s = raw_hex.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    try:
        raw = bytes.fromhex(s)
    except ValueError:
        raise TronRpcError(REASON_INVALID_ADDRESS)
    if len(raw) == 20:
        raw = bytes([TRON_MAINNET_PREFIX]) + raw
    if len(raw) != 21:
        raise TronRpcError(REASON_INVALID_ADDRESS)
    if raw[0] != TRON_MAINNET_PREFIX:
        raise TronRpcError(REASON_INVALID_ADDRESS)
    checksum = _double_sha256(raw)[:4]
    return _base58_encode(raw + checksum)


def _join_url(base: str, path: str) -> str:
    if not base:
        return path
    if base.endswith("/") and path.startswith("/"):
        return base[:-1] + path
    if not base.endswith("/") and not path.startswith("/"):
        return base + "/" + path
    return base + path


def _headers_with_key(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key
    return headers


def _post_tron_json(
    base_url: str,
    path: str,
    body: dict[str, Any],
    api_key: str,
    *,
    timeout: float = 8.0,
) -> Any:

    if not base_url:
        raise TronRpcError(REASON_TRON_API_NOT_CONFIGURED)
    url = _join_url(base_url, path)
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers=_headers_with_key(api_key),
        method="POST",
    )
    api_key_present = bool(api_key)
    try:
        with urllib.request.urlopen(
            request, timeout=timeout,
        ) as resp:
            raw = resp.read()

    except urllib.error.HTTPError as http_err:
        status = int(getattr(http_err, "code", 0) or 0)
        if status in (401, 403):




            if not api_key_present:
                raise TronRpcError(REASON_TRON_API_KEY_MISSING)
            raise TronRpcError(REASON_TRON_API_UNAUTHORIZED)
        if status == 429:



            if not api_key_present:
                raise TronRpcError(REASON_TRON_API_KEY_MISSING)
            raise TronRpcError(REASON_TRON_RATE_LIMITED)
        raise TronRpcError(REASON_TRON_PROVIDER_ERROR)

    except urllib.error.URLError:
        raise TronRpcError(REASON_TRON_PROVIDER_UNREACHABLE)
    except TimeoutError:
        raise TronRpcError(REASON_TRON_PROVIDER_UNREACHABLE)
    except Exception:
        raise TronRpcError(REASON_TRON_PROVIDER_ERROR)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise TronRpcError(REASON_TRON_PROVIDER_ERROR)
    return parsed


def tron_get_health_at_url(
    base_url: str, api_key: str = "",
) -> bool:

    try:
        parsed = _post_tron_json(
            base_url, "/wallet/getnowblock", {}, api_key,
        )
    except TronRpcError:
        return False
    if not isinstance(parsed, dict):
        return False
    if "blockID" in parsed and isinstance(parsed["blockID"], str):
        return len(parsed["blockID"]) > 0
    block_header = parsed.get("block_header")
    if isinstance(block_header, dict):
        raw_data = block_header.get("raw_data")
        if isinstance(raw_data, dict) and "number" in raw_data:
            return True
    return False


def _encode_address_for_call(address_b58: str) -> str:

    evm_hex = tron_address_to_evm_hex(address_b58)
    return evm_hex.zfill(64)


_PROVIDER_STATUS_FOR_REASON: dict[str, str] = {
    REASON_TRON_API_NOT_CONFIGURED:   "api_not_configured",
    REASON_TRON_API_KEY_MISSING:      "api_key_missing",
    REASON_TRON_API_UNAUTHORIZED:     "api_unauthorized",
    REASON_TRON_RATE_LIMITED:         "rate_limited",
    REASON_TRON_PROVIDER_UNREACHABLE: "provider_unreachable",
    REASON_TRON_PROVIDER_ERROR:       "provider_error",
    REASON_TRON_CONTRACT_NOT_CONFIGURED: "invalid_contract",
    REASON_TRON_INVALID_ADDRESS:      "invalid_address",
}


def _log_tron_contract_call_shape(
    *,
    owner_hex_present: bool,
    contract_hex_present: bool,
    parameter_len: int,
    visible: bool,
    provider_status: str,
    result_present: bool,
    constant_result_present: bool,
) -> None:




    try:
        import logging
        logger = logging.getLogger("tron_rpc")
        logger.info(
            "tron_contract_call_shape owner_hex_present=%s "
            "contract_hex_present=%s parameter_len=%d "
            "function_selector=balanceOf(address) visible=%s "
            "provider_status=%s result_present=%s "
            "constant_result_present=%s",
            "true" if owner_hex_present else "false",
            "true" if contract_hex_present else "false",
            int(parameter_len),
            "true" if visible else "false",
            provider_status,
            "true" if result_present else "false",
            "true" if constant_result_present else "false",
        )
    except Exception:
        pass


def tron_get_trc20_balance_at_url(
    base_url: str,
    api_key: str,
    contract_address_b58: str,
    holder_address_b58: str,
) -> int:

    if not is_valid_tron_address(contract_address_b58):
        _log_tron_contract_call_shape(
            owner_hex_present=False,
            contract_hex_present=False,
            parameter_len=0,
            visible=False,
            provider_status="invalid_contract",
            result_present=False,
            constant_result_present=False,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_NOT_CONFIGURED)
    if not is_valid_tron_address(holder_address_b58):
        _log_tron_contract_call_shape(
            owner_hex_present=False,
            contract_hex_present=True,
            parameter_len=0,
            visible=False,
            provider_status="invalid_address",
            result_present=False,
            constant_result_present=False,
        )
        raise TronRpcError(REASON_TRON_INVALID_ADDRESS)

    contract_hex = tron_address_to_hex(contract_address_b58)
    owner_hex    = tron_address_to_hex(holder_address_b58)
    parameter    = _encode_address_for_call(holder_address_b58)

    body = {
        "owner_address":    owner_hex,
        "contract_address": contract_hex,
        "function_selector": "balanceOf(address)",
        "parameter":         parameter,
        "visible":           False,
    }
    try:
        parsed = _post_tron_json(
            base_url, "/wallet/triggerconstantcontract", body, api_key,
        )
    except TronRpcError as exc:
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status=_PROVIDER_STATUS_FOR_REASON.get(
                exc.code, "provider_error",
            ),
            result_present=False,
            constant_result_present=False,
        )
        raise




    if not isinstance(parsed, dict):
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status="response_not_dict",
            result_present=False,
            constant_result_present=False,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)

    result = parsed.get("result")
    result_present = isinstance(result, dict)
    if isinstance(result, dict):
        if result.get("result") is not True and "message" in result:
            _log_tron_contract_call_shape(
                owner_hex_present=bool(owner_hex),
                contract_hex_present=bool(contract_hex),
                parameter_len=len(parameter),
                visible=False,
                provider_status="provider_error_message",
                result_present=True,
                constant_result_present=(
                    "constant_result" in parsed
                ),
            )
            raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)

    constant_result = parsed.get("constant_result")
    constant_result_present = isinstance(constant_result, list)
    if not isinstance(constant_result, list) or not constant_result:
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status="constant_result_missing",
            result_present=result_present,
            constant_result_present=constant_result_present,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)

    first = constant_result[0]
    if not isinstance(first, str) or not first:
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status="constant_result_invalid_string",
            result_present=result_present,
            constant_result_present=True,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)

    try:
        value = int(first, 16)
    except ValueError:
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status="constant_result_non_hex",
            result_present=result_present,
            constant_result_present=True,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)
    if value < 0:
        _log_tron_contract_call_shape(
            owner_hex_present=bool(owner_hex),
            contract_hex_present=bool(contract_hex),
            parameter_len=len(parameter),
            visible=False,
            provider_status="negative_value",
            result_present=result_present,
            constant_result_present=True,
        )
        raise TronRpcError(REASON_TRON_CONTRACT_READ_FAILED)




    _log_tron_contract_call_shape(
        owner_hex_present=bool(owner_hex),
        contract_hex_present=bool(contract_hex),
        parameter_len=len(parameter),
        visible=False,
        provider_status="ok",
        result_present=result_present,
        constant_result_present=True,
    )
    return value


def tron_get_trx_balance_sun_at_url(
    base_url: str,
    api_key: str,
    address_b58: str,
) -> int:

    if not is_valid_tron_address(address_b58):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    owner_hex = tron_address_to_hex(address_b58)
    parsed = _post_tron_json(
        base_url, "/wallet/getaccount",
        {"address": owner_hex, "visible": False},
        api_key,
    )
    if not isinstance(parsed, dict):
        raise TronRpcError(REASON_RPC_ERROR)
    balance = parsed.get("balance")
    if balance is None:
        return 0
    if not isinstance(balance, int) or balance < 0:
        raise TronRpcError(REASON_RPC_ERROR)
    return balance


def tron_get_account_resource_at_url(
    base_url: str,
    api_key: str,
    address_b58: str,
) -> dict:

    if not is_valid_tron_address(address_b58):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    owner_hex = tron_address_to_hex(address_b58)
    parsed = _post_tron_json(
        base_url, "/wallet/getaccountresource",
        {"address": owner_hex, "visible": False},
        api_key,
    )
    if not isinstance(parsed, dict):
        raise TronRpcError(REASON_RPC_ERROR)
    return {
        "freeNetLimit":  parsed.get("freeNetLimit"),
        "freeNetUsed":   parsed.get("freeNetUsed"),
        "NetLimit":      parsed.get("NetLimit"),
        "NetUsed":       parsed.get("NetUsed"),
        "EnergyLimit":   parsed.get("EnergyLimit"),
        "EnergyUsed":    parsed.get("EnergyUsed"),
    }


def _encode_address_parameter(address_b58: str) -> str:

    return _encode_address_for_call(address_b58)


def _encode_uint256_parameter(value: int) -> str:

    if value < 0:
        raise ValueError("uint256 must be non-negative")
    hex_value = format(value, "x")
    return hex_value.zfill(64)


def _extract_txid(parsed: dict) -> Optional[str]:
    tx = parsed.get("transaction")
    if isinstance(tx, dict):
        candidate = tx.get("txID")
        if isinstance(candidate, str) and len(candidate) == TRON_TXID_HEX_LEN:
            return candidate
    candidate = parsed.get("txID")
    if isinstance(candidate, str) and len(candidate) == TRON_TXID_HEX_LEN:
        return candidate
    return None


def _extract_raw_data_hex(parsed: dict) -> Optional[str]:
    tx = parsed.get("transaction")
    if isinstance(tx, dict):
        candidate = tx.get("raw_data_hex")
        if isinstance(candidate, str) and candidate:
            return candidate
    candidate = parsed.get("raw_data_hex")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _extract_unsigned_transaction(parsed: dict) -> Optional[dict]:
    tx = parsed.get("transaction")
    if isinstance(tx, dict):
        return tx
    return None


def tron_create_trc20_transfer_at_url(
    base_url: str,
    api_key: str,
    *,
    contract_address_b58: str,
    owner_address_b58: str,
    destination_address_b58: str,
    amount_base_units: int,
    fee_limit_sun: int,
) -> dict:

    if not is_valid_tron_address(contract_address_b58):
        raise TronRpcError(REASON_INVALID_CONTRACT)
    if not is_valid_tron_address(owner_address_b58):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    if not is_valid_tron_address(destination_address_b58):
        raise TronRpcError(REASON_INVALID_ADDRESS)
    if amount_base_units <= 0:
        raise ValueError("amount_base_units must be positive")
    if fee_limit_sun <= 0:
        raise ValueError("fee_limit_sun must be positive")

    contract_hex = tron_address_to_hex(contract_address_b58)
    owner_hex    = tron_address_to_hex(owner_address_b58)
    parameter    = (
        _encode_address_parameter(destination_address_b58)
        + _encode_uint256_parameter(amount_base_units)
    )

    body = {
        "owner_address":    owner_hex,
        "contract_address": contract_hex,
        "function_selector": "transfer(address,uint256)",
        "parameter":         parameter,
        "fee_limit":         int(fee_limit_sun),
        "call_value":        0,
        "visible":           False,
    }
    parsed = _post_tron_json(
        base_url, "/wallet/triggersmartcontract", body, api_key,
    )
    if not isinstance(parsed, dict):
        raise TronRpcError(REASON_DRAFT_BUILD_FAILED)
    result_field = parsed.get("result")
    if isinstance(result_field, dict):
        if result_field.get("result") is not True and \
                "message" in result_field:
            raise TronRpcError(REASON_DRAFT_BUILD_FAILED)
    unsigned = _extract_unsigned_transaction(parsed)
    tx_id = _extract_txid(parsed)
    raw_hex = _extract_raw_data_hex(parsed)
    if unsigned is None or tx_id is None or raw_hex is None:
        raise TronRpcError(REASON_DRAFT_BUILD_FAILED)
    return {
        "unsignedTransaction": unsigned,
        "txID":                tx_id,
        "rawDataHex":          raw_hex,
    }


def is_valid_txid_hex(raw: Optional[str]) -> bool:
    if not isinstance(raw, str):
        return False
    s = raw.strip().lower()
    if len(s) != TRON_TXID_HEX_LEN:
        return False
    try:
        bytes.fromhex(s)
    except ValueError:
        return False
    return True


def _looks_like_hex(raw: Optional[str]) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        bytes.fromhex(raw.strip())
    except ValueError:
        return False
    return True


def is_valid_tron_signed_transaction(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    tx_id = payload.get("txID")
    if not is_valid_txid_hex(tx_id):
        return False
    raw_hex = payload.get("raw_data_hex")
    if not _looks_like_hex(raw_hex):
        return False
    signature = payload.get("signature")
    if not isinstance(signature, list) or not signature:
        return False
    for sig in signature:
        if not isinstance(sig, str):
            return False
        if not _looks_like_hex(sig):
            return False
        if len(sig) < TRON_SIGNATURE_HEX_LEN:
            return False
    return True


def tron_broadcast_signed_transaction_at_url(
    base_url: str,
    api_key: str,
    signed_transaction: dict,
) -> str:

    if not is_valid_tron_signed_transaction(signed_transaction):
        raise TronRpcError(REASON_INVALID_SIGNED_TX)
    parsed = _post_tron_json(
        base_url, "/wallet/broadcasttransaction", signed_transaction,
        api_key,
    )
    if not isinstance(parsed, dict):
        raise TronRpcError(REASON_BROADCAST_FAILED)
    if parsed.get("result") is True or parsed.get("code") == "SUCCESS":
        tx_id = signed_transaction.get("txID")
        if not is_valid_txid_hex(tx_id):
            raise TronRpcError(REASON_BROADCAST_FAILED)
        return tx_id.lower()
    raise TronRpcError(REASON_BROADCAST_FAILED)


def tron_get_transaction_info_at_url(
    base_url: str,
    api_key: str,
    txid_hex: str,
) -> dict:

    if not is_valid_txid_hex(txid_hex):
        raise TronRpcError(REASON_INVALID_TXID)
    parsed_info = _post_tron_json(
        base_url, "/wallet/gettransactioninfobyid",
        {"value": txid_hex},
        api_key,
    )
    parsed_tx = _post_tron_json(
        base_url, "/wallet/gettransactionbyid",
        {"value": txid_hex},
        api_key,
    )

    if not isinstance(parsed_info, dict):
        parsed_info = {}
    if not isinstance(parsed_tx, dict):
        parsed_tx = {}

    if not parsed_info and not parsed_tx:
        return {"status": "pending"}

    receipt = parsed_info.get("receipt") if isinstance(
        parsed_info.get("receipt"), dict,
    ) else None
    result = parsed_info.get("result")
    contract_ret = None
    if receipt is not None:
        contract_ret = receipt.get("result")
    if not contract_ret:
        ret_list = parsed_tx.get("ret") if isinstance(
            parsed_tx.get("ret"), list,
        ) else None
        if ret_list and isinstance(ret_list[0], dict):
            contract_ret = ret_list[0].get("contractRet")

    block_number = parsed_info.get("blockNumber")
    if not isinstance(block_number, int):
        block_number = None
    block_ts = parsed_info.get("blockTimeStamp")
    if not isinstance(block_ts, int):
        block_ts = None

    if not parsed_info and parsed_tx:
        return {"status": "pending"}

    if result == "FAILED" or (
        contract_ret and contract_ret != "SUCCESS"
    ):
        return {
            "status":       "failed",
            "blockNumber":  block_number,
            "blockTimeStamp": block_ts,
            "contractResult": contract_ret,
        }
    if contract_ret == "SUCCESS" or block_number is not None:
        return {
            "status":         "confirmed",
            "blockNumber":    block_number,
            "blockTimeStamp": block_ts,
            "contractResult": contract_ret,
        }
    return {"status": "pending"}


def sun_to_trx_string(sun: int) -> str:

    if sun < 0:
        raise ValueError("sun must be non-negative")
    whole, remainder = divmod(sun, SUN_PER_TRX)
    if remainder == 0:
        return str(whole)
    frac = f"{remainder:06d}".rstrip("0")
    return f"{whole}.{frac}"


def base_units_to_decimal_string(base_units: int, decimals: int) -> str:

    if base_units < 0:
        raise ValueError("base_units must be non-negative")
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    if decimals == 0:
        return str(base_units)
    scale = 10 ** decimals
    whole, remainder = divmod(base_units, scale)
    if remainder == 0:
        return str(whole)
    frac = f"{remainder:0{decimals}d}".rstrip("0")
    return f"{whole}.{frac}"


__all__ = [
    "TRON_MAINNET_CHAIN_LABEL",
    "USDT_TRC20_DECIMALS",
    "USDT_TRC20_UNIT",
    "SUN_PER_TRX",
    "TRON_TXID_HEX_LEN",
    "TRON_SIGNATURE_HEX_LEN",
    "REASON_RPC_NOT_CONFIGURED",
    "REASON_RPC_UNREACHABLE",
    "REASON_RPC_ERROR",
    "REASON_INVALID_ADDRESS",
    "REASON_INVALID_CONTRACT",
    "REASON_CONTRACT_READ_FAILED",
    "REASON_DRAFT_BUILD_FAILED",
    "REASON_BROADCAST_FAILED",
    "REASON_INVALID_SIGNED_TX",
    "REASON_INVALID_TXID",
    "TronRpcError",
    "is_valid_tron_address",
    "is_valid_txid_hex",
    "is_valid_tron_signed_transaction",
    "tron_address_to_hex",
    "tron_address_to_evm_hex",
    "hex_to_tron_address",
    "tron_get_health_at_url",
    "tron_get_trc20_balance_at_url",
    "tron_get_trx_balance_sun_at_url",
    "tron_get_account_resource_at_url",
    "tron_create_trc20_transfer_at_url",
    "tron_broadcast_signed_transaction_at_url",
    "tron_get_transaction_info_at_url",
    "sun_to_trx_string",
    "base_units_to_decimal_string",
]
