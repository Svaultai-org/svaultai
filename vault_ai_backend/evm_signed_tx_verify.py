"""Structural + cryptographic binding of a signed Ethereum
transaction to a server-issued draft.

Refuses to relay an arbitrary correctly-formatted signed transaction
just because the caller holds a valid draftId. Every visible field
of the signed tx is decoded and compared to the drafted record; the
signer is recovered by ECDSA over secp256k1 and compared to the
server's on-record sender.

Scope: **only** the currently-supported EIP-155 legacy transaction
format (transaction type 0). The Flutter signer at
`vault_ai_frontend/lib/services/ethereum_transaction.dart` produces
exactly this format. Type-1 (EIP-2930 access lists) and type-2
(EIP-1559) transactions are refused with a specific error so a
future upgrade to EIP-1559 forces an explicit review of the draft
schema before those types can be broadcast.

Third-party dependencies — all Ethereum Foundation, all PUBLIC API:

  * `rlp.decode()` (from the `rlp` package) — for RLP-decoding the
    outer signed-transaction envelope into 9 fields. Public API.
  * `eth_utils.keccak(bytes)` — for deriving the local transaction
    hash (keccak256 of the raw signed bytes). Public API.
  * `eth_account.Account.recover_transaction(raw_hex)` — for
    secp256k1 signer recovery. Public API — the documented entry
    point. Pinned in `requirements.txt` with an upper bound so a
    minor-version bump cannot silently alter its contract.

This module does NOT reach into `eth_account._utils.*` — no private
API surface is imported. The pre-2026-07-13 revision imported
`eth_account._utils.legacy_transactions.Transaction`, which is a
private module path that could change without semver notice; this
revision removes that dependency entirely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import rlp
from eth_account import Account
from eth_utils import keccak


logger = logging.getLogger("evm_signed_tx_verify")


LEGACY_ETH_TX_TYPE: int = 0


@dataclass(frozen=True)
class DecodedTx:


    nonce:                  int
    gas_price:              int
    gas_limit:              int
    to_lower:               str
    value_wei:              int
    data_hex:               str
    v:                      int
    r:                      int
    s:                      int
    chain_id_from_v:        int
    recovered_sender_lower: str
    local_tx_hash:          str


@dataclass(frozen=True)
class VerifyResult:
    ok:          bool

    reason:      Optional[str]

    field:       Optional[str]

    decoded:     Optional[DecodedTx]

    expected:    Optional[Any] = None
    actual:      Optional[Any] = None


def _norm_hex_addr(raw: Any) -> str:
    if isinstance(raw, bytes):
        s = raw.hex()
    elif isinstance(raw, str):
        s = raw
    else:
        return ""
    s = s.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return "0x" + s


def _norm_hex_data(raw: Any) -> str:
    if isinstance(raw, bytes):
        s = raw.hex()
    elif isinstance(raw, str):
        s = raw
    else:
        return "0x"
    s = s.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return "0x" + s


def _chain_id_from_eip155_v(v: int) -> int:
    if v in (27, 28):
        return 0
    if v < 35:
        return -1
    return (v - 35) // 2


def _bytes_to_int(b: bytes) -> int:



    if not b:
        return 0
    return int.from_bytes(b, "big")


def _is_typed_transaction_prefix(raw_hex_body: str) -> bool:



    if len(raw_hex_body) < 2:
        return False
    try:
        first = bytes.fromhex(raw_hex_body[:2])[0]
    except ValueError:
        return False
    return first < 0xc0


def decode_and_recover(raw_signed_tx_hex: str) -> Optional[DecodedTx]:
    """Decode a raw EIP-155 legacy signed transaction + recover the
    signer address + derive the local keccak256 tx hash. Returns
    None if the payload cannot be parsed as a legacy tx.
    """
    s = raw_signed_tx_hex.strip()
    if not s.startswith("0x") and not s.startswith("0X"):
        s = "0x" + s
    body = s[2:]
    try:
        raw_bytes = bytes.fromhex(body)
    except ValueError:
        return None
    if not raw_bytes:
        return None

    if _is_typed_transaction_prefix(body):

        return None


    try:
        fields = rlp.decode(raw_bytes)
    except Exception as exc:
        logger.warning(
            "[TX-VERIFY] rlp_decode_failed err=%s",
            type(exc).__name__,
        )
        return None
    if not isinstance(fields, list) or len(fields) != 9:
        logger.warning(
            "[TX-VERIFY] rlp_shape_wrong len=%d",
            len(fields) if isinstance(fields, list) else -1,
        )
        return None
    try:
        nonce      = _bytes_to_int(fields[0])
        gas_price  = _bytes_to_int(fields[1])
        gas_limit  = _bytes_to_int(fields[2])
        to_bytes   = bytes(fields[3])
        value      = _bytes_to_int(fields[4])
        data_bytes = bytes(fields[5])
        v          = _bytes_to_int(fields[6])
        r          = _bytes_to_int(fields[7])
        sig_s      = _bytes_to_int(fields[8])
    except Exception as exc:
        logger.warning(
            "[TX-VERIFY] rlp_field_decode_failed err=%s",
            type(exc).__name__,
        )
        return None



    if len(to_bytes) != 20:



        return None

    try:
        recovered = Account.recover_transaction(s)
    except Exception as exc:
        logger.warning(
            "[TX-VERIFY] recover_failed err=%s",
            type(exc).__name__,
        )
        return None

    local_hash = "0x" + keccak(raw_bytes).hex()

    return DecodedTx(
        nonce=nonce,
        gas_price=gas_price,
        gas_limit=gas_limit,
        to_lower=_norm_hex_addr(to_bytes),
        value_wei=value,
        data_hex=_norm_hex_data(data_bytes),
        v=v,
        r=r,
        s=sig_s,
        chain_id_from_v=_chain_id_from_eip155_v(v),
        recovered_sender_lower=(recovered or "").strip().lower(),
        local_tx_hash=local_hash,
    )


def compute_local_tx_hash(raw_signed_tx_hex: str) -> Optional[str]:



    s = raw_signed_tx_hex.strip()
    if s.startswith("0x") or s.startswith("0X"):
        body = s[2:]
    else:
        body = s
    try:
        raw_bytes = bytes.fromhex(body)
    except ValueError:
        return None
    if not raw_bytes:
        return None
    return "0x" + keccak(raw_bytes).hex()


def verify_signed_tx_against_draft(
    *,
    raw_signed_tx_hex: str,
    draft: dict[str, Any],
) -> VerifyResult:
    """Compare a signed legacy transaction to a server-issued draft.

    All expected values come from `draft`, which the caller loaded
    from Postgres — nothing here trusts anything in the raw HTTP
    payload beyond the signed transaction itself.

    Returns a `VerifyResult` with `ok=True` only when EVERY field
    matches: transaction type is legacy; chain_id from v matches;
    nonce, gas_price, gas_limit, to, value_wei, data all match; and
    the recovered signer matches `draft.sender_address`.

    Any mismatch produces `ok=False` and the `field` naming the
    mismatched key plus `expected`/`actual`.
    """
    s = raw_signed_tx_hex.strip()
    if s.startswith("0x") or s.startswith("0X"):
        body = s[2:]
    else:
        body = s
    if _is_typed_transaction_prefix(body):
        return VerifyResult(
            ok=False, reason="unsupported_tx_type",
            field="tx_type", decoded=None,
            expected=LEGACY_ETH_TX_TYPE,
        )

    decoded = decode_and_recover(raw_signed_tx_hex)
    if decoded is None:
        return VerifyResult(
            ok=False, reason="decode_or_recover_failed",
            field=None, decoded=None,
        )

    expected_chain_id = int(draft.get("chain_id", 0))
    if decoded.chain_id_from_v != expected_chain_id:
        return VerifyResult(
            ok=False, reason="chain_id_mismatch",
            field="chain_id", decoded=decoded,
            expected=expected_chain_id,
            actual=decoded.chain_id_from_v,
        )

    checks = [
        ("nonce",     int(draft.get("nonce", 0)),     decoded.nonce),
        ("gas_price", int(draft.get("gas_price", 0)), decoded.gas_price),
        ("gas_limit", int(draft.get("gas_limit", 0)), decoded.gas_limit),
        ("value_wei", int(draft.get("value_wei", 0)), decoded.value_wei),
    ]
    for name, expected, actual in checks:
        if expected != actual:
            return VerifyResult(
                ok=False, reason=f"{name}_mismatch",
                field=name, decoded=decoded,
                expected=expected, actual=actual,
            )

    expected_to = _norm_hex_addr(str(draft.get("transaction_to", "")))
    if decoded.to_lower != expected_to:
        return VerifyResult(
            ok=False, reason="destination_mismatch",
            field="transaction_to", decoded=decoded,
            expected=expected_to, actual=decoded.to_lower,
        )

    expected_data = _norm_hex_data(str(draft.get("data_hex", "0x")))
    if decoded.data_hex != expected_data:
        if not (expected_data in ("0x", "") and decoded.data_hex == "0x"):
            return VerifyResult(
                ok=False, reason="calldata_mismatch",
                field="data_hex", decoded=decoded,
                expected=expected_data, actual=decoded.data_hex,
            )

    expected_sender = _norm_hex_addr(str(draft.get("sender_address", "")))
    if decoded.recovered_sender_lower != expected_sender:
        return VerifyResult(
            ok=False, reason="signer_mismatch",
            field="recovered_sender", decoded=decoded,
            expected=expected_sender,
            actual=decoded.recovered_sender_lower,
        )

    return VerifyResult(
        ok=True, reason=None, field=None, decoded=decoded,
    )


__all__ = [
    "LEGACY_ETH_TX_TYPE",
    "DecodedTx",
    "VerifyResult",
    "decode_and_recover",
    "compute_local_tx_hash",
    "verify_signed_tx_against_draft",
]
