"""Exact public-chain intent binding for ciphertext-first PAXG/KAG drafts.

The SHA-256 commitment is NOT encryption or vault-name privacy. It binds the
complete reviewed public transaction tuple to a random, server-generated draft
ID and authenticated vault. Private metadata stays client-encrypted. A signed
transaction may supply the public fields again only after signer recovery and
constant-time commitment verification; no wallet secret is accepted here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from evm_signed_tx_verify import DecodedTx
from verified_assets import PAXG_ASSET, PAXG_CONTRACT, PAXG_NETWORK, KAG_ASSET, KAG_CONTRACT


_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_TRANSFER = re.compile(r"^0xa9059cbb0{24}([0-9a-f]{40})([0-9a-f]{64})$")
_DOMAIN = "svaultai.paxg.ciphertext-draft.intent.v1"


def _address(value: Any) -> str:
    normalized = str(value).strip().lower()
    if not _ADDRESS.fullmatch(normalized):
        raise ValueError("invalid_paxg_intent")
    return normalized


def _uint(value: Any, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid_paxg_intent")
    if value < (1 if positive else 0) or value >= 2**256:
        raise ValueError("invalid_paxg_intent")
    return value


def _registered_intent_commitment(
    *, draft_id: str, vault_id: str, network_id: str, asset: str,
    sender_address: str, destination_address: str, value_wei: int,
    data_hex: str, nonce: int, gas_limit: int, gas_price: int,
    chain_id: int, transaction_to: str,
) -> bytes:
    """Hash only a canonical, exact closed-issuer transfer reviewed by server."""
    if not draft_id or not vault_id or network_id != PAXG_NETWORK or asset not in {PAXG_ASSET, KAG_ASSET}:
        raise ValueError("invalid_paxg_intent")
    if _uint(chain_id) != 1 or _uint(value_wei) != 0:
        raise ValueError("invalid_paxg_intent")
    sender = _address(sender_address)
    destination = _address(destination_address)
    contract = _address(transaction_to)
    if contract != (PAXG_CONTRACT if asset == PAXG_ASSET else KAG_CONTRACT).lower():
        raise ValueError("invalid_paxg_intent")
    data = str(data_hex).strip().lower()
    transfer = _TRANSFER.fullmatch(data)
    if transfer is None or "0x" + transfer.group(1) != destination:
        raise ValueError("invalid_paxg_intent")
    amount = _uint(int(transfer.group(2), 16), positive=True)
    canonical = {
        "domain": _DOMAIN if asset == PAXG_ASSET else "svaultai.kag.ciphertext-draft.intent.v1",
        "tx_type": 0, "draft_id": str(draft_id), "vault_id": str(vault_id),
        "network_id": network_id, "asset": asset, "chain_id": 1, "decimals": 18,
        "sender": sender, "recipient": destination, "amount_base_units": str(amount),
        "transaction_to": contract, "value_wei": "0", "data_hex": data,
        "nonce": str(_uint(nonce)), "gas_limit": str(_uint(gas_limit, positive=True)),
        "gas_price": str(_uint(gas_price, positive=True)),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).digest()


def paxg_intent_commitment(**fields: Any) -> bytes:
    if fields.get("asset") != PAXG_ASSET:
        raise ValueError("invalid_paxg_intent")
    return _registered_intent_commitment(**fields)


def kag_intent_commitment(**fields: Any) -> bytes:
    if fields.get("asset") != KAG_ASSET:
        raise ValueError("invalid_kag_intent")
    try:
        return _registered_intent_commitment(**fields)
    except ValueError:
        raise ValueError("invalid_kag_intent") from None


def _bind_decoded_registered_draft(draft: dict[str, Any], decoded: DecodedTx, *, asset: str) -> dict[str, Any]:
    """Recover transient fields only when the signed tuple matches its binding.

    The caller must obtain ``decoded`` via cryptographic signature recovery.
    Persisted nonce/gas/chain fields are retained for the existing draft verifier
    to check independently. No field supplied by an unsigned request is trusted.
    """
    prefix = "paxg" if asset == PAXG_ASSET else "kag"
    if draft.get("asset") != asset or draft.get(prefix + "_ciphertext_bound") is not True:
        raise ValueError(prefix + "_encrypted_draft_binding_failed")
    raw_commitment = draft.get(prefix + "_intent_commitment")
    if not isinstance(raw_commitment, (bytes, bytearray, memoryview)) or len(raw_commitment) != 32:
        raise ValueError(prefix + "_encrypted_draft_binding_missing")
    transfer = _TRANSFER.fullmatch(decoded.data_hex.lower())
    if transfer is None:
        raise ValueError(prefix + "_encrypted_draft_binding_failed")
    recipient = "0x" + transfer.group(1)
    try:
        candidate = _registered_intent_commitment(
            draft_id=draft["draft_id"], vault_id=draft["vault_id"],
            network_id=draft["network_id"], asset=asset,
            sender_address=decoded.recovered_sender_lower, destination_address=recipient,
            value_wei=decoded.value_wei, data_hex=decoded.data_hex, nonce=decoded.nonce,
            gas_limit=decoded.gas_limit, gas_price=decoded.gas_price,
            chain_id=decoded.chain_id_from_v, transaction_to=decoded.to_lower,
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(prefix + "_encrypted_draft_binding_failed") from None
    if not hmac.compare_digest(bytes(raw_commitment), candidate):
        raise ValueError(prefix + "_encrypted_draft_binding_failed")
    return {
        **draft, "asset": asset,
        "sender_address": decoded.recovered_sender_lower,
        "destination_address": recipient, "value_wei": decoded.value_wei,
        "data_hex": decoded.data_hex, "transaction_to": decoded.to_lower,
    }


def bind_decoded_paxg_draft(draft: dict[str, Any], decoded: DecodedTx) -> dict[str, Any]:
    return _bind_decoded_registered_draft(draft, decoded, asset=PAXG_ASSET)


def bind_decoded_kag_draft(draft: dict[str, Any], decoded: DecodedTx) -> dict[str, Any]:
    return _bind_decoded_registered_draft(draft, decoded, asset=KAG_ASSET)
