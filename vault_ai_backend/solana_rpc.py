

from __future__ import annotations

import json
import re
from typing import Any, Optional

import urllib.request
import urllib.error


LAMPORTS_PER_SOL: int = 1_000_000_000
SOLANA_MAINNET_CHAIN_LABEL: str = "solana_mainnet"


REASON_RPC_NOT_CONFIGURED: str = "rpc_not_configured"
REASON_RPC_UNREACHABLE: str = "rpc_unreachable"
REASON_RPC_ERROR: str = "rpc_error"
REASON_INVALID_ADDRESS: str = "invalid_address"
REASON_INDEXER_NOT_CONFIGURED: str = "solana_activity_not_connected"


_BASE58_ALPHABET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)
_BASE58_CHARSET = set(_BASE58_ALPHABET)
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


_SOLANA_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
)


class SolanaRpcError(Exception):

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


def is_valid_solana_address(raw: Optional[str]) -> bool:
    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if not _SOLANA_ADDRESS_RE.match(s):
        return False
    try:
        decoded = _base58_decode(s)
    except ValueError:
        return False
    return len(decoded) == 32


def _post_json_rpc(
    rpc_url: str,
    method: str,
    params: Optional[list[Any]] = None,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    if not rpc_url:
        raise SolanaRpcError(REASON_RPC_NOT_CONFIGURED)
    body = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  method,
        "params":  params or [],
    }
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout,
        ) as resp:
            raw = resp.read()
    except urllib.error.URLError:
        raise SolanaRpcError(REASON_RPC_UNREACHABLE)
    except TimeoutError:
        raise SolanaRpcError(REASON_RPC_UNREACHABLE)
    except Exception:
        raise SolanaRpcError(REASON_RPC_UNREACHABLE)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise SolanaRpcError(REASON_RPC_ERROR)
    if not isinstance(parsed, dict):
        raise SolanaRpcError(REASON_RPC_ERROR)
    if "error" in parsed:
        raise SolanaRpcError(REASON_RPC_ERROR)
    return parsed


def sol_get_balance_lamports_at_url(
    rpc_url: str, address: str,
) -> int:
    if not is_valid_solana_address(address):
        raise SolanaRpcError(REASON_INVALID_ADDRESS)
    result = _post_json_rpc(rpc_url, "getBalance", [address])
    payload = result.get("result")
    if isinstance(payload, dict):
        value = payload.get("value")
    else:
        value = payload
    if not isinstance(value, int) or value < 0:
        raise SolanaRpcError(REASON_RPC_ERROR)
    return value


def sol_get_health_at_url(rpc_url: str) -> bool:
    try:
        result = _post_json_rpc(rpc_url, "getHealth")
    except SolanaRpcError:
        return False
    payload = result.get("result")
    if payload == "ok":
        return True
    if isinstance(payload, dict) and payload.get("status") == "ok":
        return True
    return False


def sol_get_latest_blockhash_at_url(rpc_url: str) -> dict:
    result = _post_json_rpc(rpc_url, "getLatestBlockhash")
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise SolanaRpcError(REASON_RPC_ERROR)
    value = payload.get("value")
    if not isinstance(value, dict):
        raise SolanaRpcError(REASON_RPC_ERROR)
    blockhash = value.get("blockhash")
    if not isinstance(blockhash, str) or len(blockhash) < 32:
        raise SolanaRpcError(REASON_RPC_ERROR)
    return {
        "blockhash": blockhash,
        "lastValidBlockHeight": value.get("lastValidBlockHeight"),
    }


REASON_INVALID_SIGNED_TX: str = "invalid_signed_transaction"


_SOL_SIGNATURE_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{64,90}$",
)


def is_valid_solana_signature(raw: Optional[str]) -> bool:
    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if not _SOL_SIGNATURE_RE.match(s):
        return False
    try:
        decoded = _base58_decode(s)
    except ValueError:
        return False
    return len(decoded) == 64


def sol_send_signed_transaction_at_url(
    rpc_url: str, signed_transaction_base64: str,
) -> str:
    if not isinstance(signed_transaction_base64, str) or not \
            signed_transaction_base64.strip():
        raise SolanaRpcError(REASON_INVALID_SIGNED_TX)
    payload = signed_transaction_base64.strip()
    result = _post_json_rpc(
        rpc_url,
        "sendTransaction",
        [
            payload,
            {"encoding": "base64", "skipPreflight": False},
        ],
    )
    signature = result.get("result")
    if not is_valid_solana_signature(signature):
        raise SolanaRpcError(REASON_RPC_ERROR)
    return signature


def sol_get_signature_status_at_url(
    rpc_url: str, signature_b58: str,
) -> dict:
    result = _post_json_rpc(
        rpc_url, "getSignatureStatuses", [[signature_b58]],
    )
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise SolanaRpcError(REASON_RPC_ERROR)
    value = payload.get("value")
    if not isinstance(value, list) or not value:
        return {"status": "pending"}
    entry = value[0]
    if entry is None:
        return {"status": "pending"}
    if not isinstance(entry, dict):
        raise SolanaRpcError(REASON_RPC_ERROR)
    if entry.get("err") is not None:
        return {
            "status":             "failed",
            "slot":               entry.get("slot"),
            "confirmations":      entry.get("confirmations"),
            "confirmationStatus": entry.get(
                "confirmationStatus",
            ),
        }
    confirmation = (
        entry.get("confirmationStatus") or "processed"
    )
    normalized = (
        "confirmed"
        if confirmation in ("confirmed", "finalized")
        else "pending"
    )
    return {
        "status":             normalized,
        "slot":               entry.get("slot"),
        "confirmations":      entry.get("confirmations"),
        "confirmationStatus": confirmation,
    }


def sol_get_signatures_for_address_at_url(
    rpc_url: str, address: str, limit: int = 20,
) -> list[dict]:
    if not is_valid_solana_address(address):
        raise SolanaRpcError(REASON_INVALID_ADDRESS)
    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50
    result = _post_json_rpc(
        rpc_url,
        "getSignaturesForAddress",
        [address, {"limit": limit}],
    )
    payload = result.get("result")
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise SolanaRpcError(REASON_RPC_ERROR)
    out: list[dict] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        sig = row.get("signature")
        if not is_valid_solana_signature(sig):
            continue
        out.append({
            "signature":          sig,
            "slot":               row.get("slot"),
            "blockTime":          row.get("blockTime"),
            "confirmationStatus": row.get("confirmationStatus"),
            "err":                row.get("err"),
            "memo":               row.get("memo"),
        })
    return out


_SYSTEM_PROGRAM_BYTES: bytes = b"\x00" * 32


def _base58_encode_bytes(raw: bytes) -> str:
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


def _write_compact_u16(out: bytearray, n: int) -> None:
    if n < 0 or n > 0xffff:
        raise ValueError("compact-u16 must be in [0, 65535]")
    v = n
    while True:
        byte = v & 0x7f
        v >>= 7
        if v == 0:
            out.append(byte)
            return
        out.append(byte | 0x80)


def build_sol_transfer_message_bytes(
    *,
    from_address_b58: str,
    to_address_b58:   str,
    lamports:         int,
    recent_blockhash_b58: str,
) -> bytes:
    if not is_valid_solana_address(from_address_b58):
        raise SolanaRpcError(REASON_INVALID_ADDRESS)
    if not is_valid_solana_address(to_address_b58):
        raise SolanaRpcError(REASON_INVALID_ADDRESS)
    if lamports <= 0:
        raise ValueError("lamports must be positive")
    from_pk = _base58_decode(from_address_b58)
    to_pk = _base58_decode(to_address_b58)
    try:
        blockhash = _base58_decode(recent_blockhash_b58)
    except ValueError:
        raise SolanaRpcError(REASON_RPC_ERROR)
    if len(blockhash) != 32:
        raise SolanaRpcError(REASON_RPC_ERROR)

    out = bytearray()
    out.append(1)
    out.append(0)
    out.append(1)

    _write_compact_u16(out, 3)
    out.extend(from_pk)
    out.extend(to_pk)
    out.extend(_SYSTEM_PROGRAM_BYTES)

    out.extend(blockhash)

    _write_compact_u16(out, 1)
    out.append(2)
    _write_compact_u16(out, 2)
    out.append(0)
    out.append(1)

    data = bytearray()
    data.extend((2).to_bytes(4, "little"))
    data.extend(int(lamports).to_bytes(8, "little"))
    _write_compact_u16(out, len(data))
    out.extend(data)

    return bytes(out)


def sol_get_fee_for_message_at_url(
    rpc_url: str, message_base64: str,
) -> int:
    if not isinstance(message_base64, str) or not \
            message_base64.strip():
        raise SolanaRpcError(REASON_INVALID_SIGNED_TX)
    result = _post_json_rpc(
        rpc_url, "getFeeForMessage", [message_base64.strip()],
    )
    payload = result.get("result")
    if isinstance(payload, dict):
        value = payload.get("value")
    else:
        value = payload
    if value is None:
        raise SolanaRpcError(REASON_RPC_ERROR)
    if not isinstance(value, int) or value < 0:
        raise SolanaRpcError(REASON_RPC_ERROR)
    return value


def lamports_to_sol_string(lamports: int) -> str:
    if lamports < 0:
        raise ValueError("lamports must be non-negative")
    whole, remainder = divmod(lamports, LAMPORTS_PER_SOL)
    if remainder == 0:
        return str(whole)
    frac = f"{remainder:09d}".rstrip("0")
    return f"{whole}.{frac}"


__all__ = [
    "LAMPORTS_PER_SOL",
    "SOLANA_MAINNET_CHAIN_LABEL",
    "REASON_RPC_NOT_CONFIGURED",
    "REASON_RPC_UNREACHABLE",
    "REASON_RPC_ERROR",
    "REASON_INVALID_ADDRESS",
    "REASON_INVALID_SIGNED_TX",
    "REASON_INDEXER_NOT_CONFIGURED",
    "SolanaRpcError",
    "is_valid_solana_address",
    "is_valid_solana_signature",
    "sol_get_balance_lamports_at_url",
    "sol_get_health_at_url",
    "sol_get_latest_blockhash_at_url",
    "sol_send_signed_transaction_at_url",
    "sol_get_signature_status_at_url",
    "sol_get_signatures_for_address_at_url",
    "sol_get_fee_for_message_at_url",
    "build_sol_transfer_message_bytes",
    "lamports_to_sol_string",
]
