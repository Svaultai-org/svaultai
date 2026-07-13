"""Test helpers for the ETH mainnet broadcast path.

2026-07-13 (canary hardening): the broadcast handler now REJECTS an
RPC-echoed hash that does not match the locally derived
`keccak256(raw_signed_tx)`, and REQUIRES a post-broadcast visibility
observation (`eth_getTransactionByHash` returning a non-null envelope
OR `eth_getTransactionReceipt` returning a non-null envelope) before
recording the `submitted` outcome.

Before the hardening, tests could simply
`mock.patch(eth_send_raw_transaction_at_url, return_value="0x0f...")`
and the broadcast handler would rubber-stamp `submitted`. That is
exactly the failure mode the canary revealed (RPC returned a valid
hash, the tx was never on-chain, and the backend still persisted
`submitted`).

This helper models a "the tx was really broadcast" scenario for tests
that only care about the state-machine mechanics (draft consumption,
wallet lock, idempotency cache) and not about the visibility gate
itself. Tests that specifically probe the visibility gate should
mock `eth_send_raw_transaction_at_url` and
`eth_get_transaction_by_hash_at_url` themselves.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable, Iterator, Optional
from unittest import mock


@contextmanager
def mock_successful_broadcast(
    fixtures: Iterable[dict],
) -> Iterator[None]:
    """Patch the broadcast RPC helpers so that any signed_tx_hex from
    one of the given fixtures resolves to a "network accepted this,
    the tx is visible" outcome.

    Each fixture must contain `signed_tx_hex` and `local_tx_hash`
    (populated by `make_signed_tx_and_matching_draft` since the
    canary hardening).
    """
    import evm_rpc
    signed_to_local: dict[str, str] = {}
    for f in fixtures:
        signed_to_local[f["signed_tx_hex"].lower()] = f["local_tx_hash"]

    def _send(rpc_url: str, signed_tx_hex: str) -> str:
        return signed_to_local[signed_tx_hex.lower()]

    def _by_hash(rpc_url: str, tx_hash: str) -> Optional[dict]:
        return {"hash": tx_hash, "blockNumber": None}

    with mock.patch.object(
        evm_rpc, "eth_send_raw_transaction_at_url",
        side_effect=_send,
    ), mock.patch.object(
        evm_rpc, "eth_get_transaction_by_hash_at_url",
        side_effect=_by_hash,
    ):
        yield


@contextmanager
def mock_broadcast_returning(
    signed_tx_hex_to_returned_hash: dict,
    *,
    by_hash_visible: bool = True,
) -> Iterator[None]:
    """Explicit form of `mock_successful_broadcast` for tests that
    want to control the exact hash the mocked provider echoes back.
    Used e.g. by the canary regression test that models "provider
    returns a valid-shaped hash but the tx is NOT visible" — pass
    `by_hash_visible=False` to model that case.
    """
    import evm_rpc

    lowered = {
        k.lower(): v
        for k, v in signed_tx_hex_to_returned_hash.items()
    }

    def _send(rpc_url: str, signed_tx_hex: str) -> str:
        return lowered[signed_tx_hex.lower()]

    def _by_hash(rpc_url: str, tx_hash: str) -> Optional[dict]:
        return {"hash": tx_hash, "blockNumber": None} if by_hash_visible \
            else None

    def _receipt(rpc_url: str, tx_hash: str) -> Optional[dict]:
        return None

    with mock.patch.object(
        evm_rpc, "eth_send_raw_transaction_at_url",
        side_effect=_send,
    ), mock.patch.object(
        evm_rpc, "eth_get_transaction_by_hash_at_url",
        side_effect=_by_hash,
    ), mock.patch.object(
        evm_rpc, "eth_get_transaction_receipt_at_url",
        side_effect=_receipt,
    ):
        yield


# --- module-level side_effect callables for use inside existing
#     `mock.patch(..., side_effect=X)` sites --------------------------
#
# These let tests written before the canary hardening keep their
# structure (one `with mock.patch(...)` block per RPC call), just
# swap `return_value=_TX_HASH` → `side_effect=echo_local_hash` and
# ADD a nested `mock.patch(...eth_get_transaction_by_hash_at_url,
# side_effect=visible_by_hash)`.

def echo_local_hash(rpc_url: str, signed_tx_hex: str) -> str:
    """side_effect that echoes keccak256(raw) — the exact hash the
    broadcast handler expects the RPC to return."""
    from evm_signed_tx_verify import compute_local_tx_hash
    return compute_local_tx_hash(signed_tx_hex)


def visible_by_hash(rpc_url: str, tx_hash: str) -> dict:
    """side_effect that makes `eth_getTransactionByHash` report the
    transaction as visible on the network. Non-None envelope shape
    is what `_mainnet_visibility_after_broadcast` checks for."""
    return {"hash": tx_hash, "blockNumber": None}


def invisible_by_hash(rpc_url: str, tx_hash: str):
    """side_effect that makes `eth_getTransactionByHash` report the
    transaction as NOT visible. This is the exact canary shape —
    the RPC accepted the raw tx but no node ever named it."""
    return None


def invisible_receipt(rpc_url: str, tx_hash: str):
    """side_effect for `eth_getTransactionReceipt` returning null."""
    return None


@contextmanager
def visible_visibility_patches() -> Iterator[None]:
    """Convenience: patch both visibility helpers to "visible"."""
    import evm_rpc
    with mock.patch.object(
        evm_rpc, "eth_get_transaction_by_hash_at_url",
        side_effect=visible_by_hash,
    ):
        yield


__all__ = [
    "echo_local_hash",
    "visible_by_hash",
    "invisible_by_hash",
    "invisible_receipt",
    "visible_visibility_patches",
    "mock_successful_broadcast",
    "mock_broadcast_returning",
]
