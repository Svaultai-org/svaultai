"""Shared draft-expiry boundary helpers for the crypto wallet
engine (2026-07-14, Round 9 hardening).

The `/crypto/wallet/network/{network}/draft/{draft_id}/expiry`
endpoint and the SOL / TRON broadcast dispatchers both need to
answer the same yes/no question: "is this persisted draft still
valid to sign / broadcast?" If those two paths drift, the
endpoint could green-light a draft that the broadcast state
machine then rejects — or worse, vice versa — and the client's
fail-closed pre-sign check would be a lie.

This module owns the canonical boundary rules. Both call sites
import from here. There is no second implementation anywhere in
the codebase.

Rules
-----

SOLANA:
  A Solana transaction is valid on the network as long as the
  observed chain block height is <= `last_valid_block_height`
  (Solana's own consensus rule — the last-valid slot IS still a
  valid inclusion slot). Therefore expiry is:

      expired  iff  current_block_height > last_valid_block_height

  Boundary case `current == last_valid` → NOT expired.
  First-invalid case `current == last_valid + 1` → expired.

TRON:
  A TRON transaction carries an in-network `expiration_ms`. The
  network refuses to include it at or after that instant. So
  expiry is:

      expired  iff  now_ms >= expiration_ms

  Boundary case `now_ms == expiration_ms` → expired (network
  refuses on the boundary; matches TRON's own reference client).
  First-still-valid case `now_ms == expiration_ms - 1` → NOT
  expired.

Both helpers are pure integer comparisons — no I/O, no clocks,
no exceptions. The route layer fetches the observed values
(chain block height / server clock) and passes them in; this
module answers only the boundary question.
"""

from __future__ import annotations


__all__ = [
    "solana_draft_expired_by_blockheight",
    "tron_draft_expired_by_expiration_ms",
    "SOLANA_EXPIRY_REASON_STILL_VALID",
    "SOLANA_EXPIRY_REASON_EXCEEDED",
    "TRON_EXPIRY_REASON_STILL_VALID",
    "TRON_EXPIRY_REASON_EXPIRATION_PASSED",
]


SOLANA_EXPIRY_REASON_STILL_VALID: str = "still_valid"
SOLANA_EXPIRY_REASON_EXCEEDED: str = "blockheight_exceeded"

TRON_EXPIRY_REASON_STILL_VALID: str = "still_valid"
TRON_EXPIRY_REASON_EXPIRATION_PASSED: str = "expiration_passed"


def solana_draft_expired_by_blockheight(
    *, current_block_height: int, last_valid_block_height: int,
) -> bool:
    """Return True iff `current_block_height > last_valid_block_height`.

    This is Solana's own network validity rule for a recent-blockhash
    reference. The last-valid slot is still a valid inclusion slot;
    only the first slot BEYOND it makes the transaction impossible
    to include.

    Callers MUST coerce to int before calling — the endpoint validates
    the persisted `last_valid_block_height` and the RPC response
    upstream. Passing anything other than a non-negative int is a
    programmer error and will raise TypeError.
    """
    if not isinstance(current_block_height, int):
        raise TypeError("current_block_height must be int")
    if not isinstance(last_valid_block_height, int):
        raise TypeError("last_valid_block_height must be int")
    if current_block_height < 0:
        raise ValueError("current_block_height must be >= 0")
    if last_valid_block_height < 0:
        raise ValueError("last_valid_block_height must be >= 0")
    return current_block_height > last_valid_block_height


def tron_draft_expired_by_expiration_ms(
    *, now_ms: int, expiration_ms: int,
) -> bool:
    """Return True iff `now_ms >= expiration_ms`.

    Matches TRON's on-chain expiration semantics — the network
    refuses to include a transaction whose expiration instant has
    been reached OR passed.

    `expiration_ms <= 0` means the persisted draft never had a
    valid expiration attached; the caller MUST treat that as an
    already-expired / re-draft signal separately (this helper
    reports it as expired for safety, since a zero expiration is
    not a green light).
    """
    if not isinstance(now_ms, int):
        raise TypeError("now_ms must be int")
    if not isinstance(expiration_ms, int):
        raise TypeError("expiration_ms must be int")
    if now_ms < 0:
        raise ValueError("now_ms must be >= 0")
    if expiration_ms <= 0:
        return True
    return now_ms >= expiration_ms
