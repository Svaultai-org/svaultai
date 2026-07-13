"""In-process fake for `crypto_mainnet_control_store`.

Same public surface as the Postgres-backed real store — every
method matches the real store's kwarg names, return shape, and
error codes. Used by every backend test file so they exercise the
real routing / binding / lock-ordering paths without needing a
live Postgres.

Cross-worker / cross-container behaviors are genuinely exercised by
the test files that specifically instantiate TWO independent fakes
sharing one underlying state dict — see
`test_mainnet_shared_state_2026_07_13.py`. The **real** Postgres
semantics (advisory-lock scoping, transaction rollback behavior,
etc.) are exercised by `test_mainnet_control_store_postgres_2026_07_13.py`
which skips unless `VAULTAI_TEST_DATABASE_URL` is set.
"""

from __future__ import annotations

import secrets
import threading
import time as _time
from typing import Any, Optional


class FakeMainnetStore:


    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._drafts: dict[str, dict[str, Any]] = {}
        self._wallet_locks: dict[tuple[str, str], dict[str, Any]] = {}



        self._pause: Optional[bool] = False

        self.fail_pause_read: bool = False
        self.fail_register: bool = False
        self.fail_consume: bool = False
        self.fail_lock: bool = False


    def clear(self) -> None:
        with self._lock:
            self._drafts.clear()
            self._wallet_locks.clear()
            self._pause = False
            self.fail_pause_read = False
            self.fail_register = False
            self.fail_consume = False
            self.fail_lock = False


    def seed_draft(
        self,
        draft_id: str,
        *,
        vault_id: str,
        network_id: str,
        sender_address: str,
        asset: str = "ETH",
        destination_address: str = "",
        value_wei: int = 0,
        data_hex: str = "0x",
        nonce: int = 0,
        gas_limit: int = 21000,
        gas_price: int = 1_000_000_000,
        chain_id: int = 1,
        transaction_to: Optional[str] = None,
        ttl_secs: int = 10 ** 8,
    ) -> None:



        sender_lower = (sender_address or "").strip().lower()
        now = _time.time()
        with self._lock:
            self._drafts[draft_id] = {
                "draft_id":             draft_id,
                "vault_id":             str(vault_id),
                "network_id":           network_id,
                "sender_address_lower": sender_lower,
                "sender_address":       sender_lower,
                "asset":                asset,
                "destination_address":  destination_address,
                "value_wei":            int(value_wei),
                "data_hex":             data_hex,
                "nonce":                int(nonce),
                "gas_limit":            int(gas_limit),
                "gas_price":            int(gas_price),
                "chain_id":             int(chain_id),
                "transaction_to":       (transaction_to
                                          if transaction_to is not None
                                          else destination_address),
                "created_at":           now,
                "expires_at":           now + int(ttl_secs),
                "claim_token":          None,
                "claim_expires_at":     None,
                "consumed_at":          None,
                "local_tx_hash":        None,
                "broadcast_outcome":    None,
                "outcome_recorded_at":  None,
            }


    def register_draft(
        self,
        *,
        vault_id: str,
        network_id: str,
        sender_address: str,
        asset: str,
        destination_address: str,
        value_wei: int,
        data_hex: str,
        nonce: int,
        gas_limit: int,
        gas_price: int,
        chain_id: int,
        transaction_to: str,
        ttl_secs: int = 300,
    ) -> Optional[str]:
        if self.fail_register:
            raise RuntimeError("simulated register-draft DB failure")
        sender_lower = (sender_address or "").strip().lower()
        now = _time.time()
        with self._lock:

            for did, d in list(self._drafts.items()):
                if d.get("expires_at", 0) <= now:
                    self._drafts.pop(did, None)
            for d in self._drafts.values():
                if (
                    d.get("network_id") == network_id
                    and d.get("sender_address_lower") == sender_lower
                    and d.get("consumed_at") is None
                    and d.get("expires_at", 0) > now
                ):
                    return None
            draft_id = secrets.token_urlsafe(24)
            self._drafts[draft_id] = {
                "draft_id":             draft_id,
                "vault_id":             str(vault_id),
                "network_id":           network_id,
                "sender_address_lower": sender_lower,
                "sender_address":       sender_lower,
                "asset":                asset,
                "destination_address":  destination_address,
                "value_wei":            int(value_wei),
                "data_hex":             data_hex,
                "nonce":                int(nonce),
                "gas_limit":            int(gas_limit),
                "gas_price":            int(gas_price),
                "chain_id":             int(chain_id),
                "transaction_to":       transaction_to,
                "created_at":           now,
                "expires_at":           now + int(ttl_secs),
                "claim_token":          None,
                "claim_expires_at":     None,
                "consumed_at":          None,
                "local_tx_hash":        None,
                "broadcast_outcome":    None,
                "outcome_recorded_at":  None,
            }
            return draft_id

    def load_draft_readonly(
        self, *, draft_id: str, vault_id: str, network_id: str,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        if self.fail_consume:
            raise RuntimeError("simulated readonly-load DB failure")
        now = _time.time()
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return None, "unknown_or_expired_draft"
            if d.get("expires_at", 0) <= now:
                return None, "unknown_or_expired_draft"
            if d.get("vault_id") != str(vault_id):
                return None, "draft_vault_mismatch"
            if d.get("network_id") != network_id:
                return None, "draft_network_mismatch"
            consumed = d.get("consumed_at") is not None
            return {
                "draft_id":            d["draft_id"],
                "vault_id":            d["vault_id"],
                "network_id":          d["network_id"],
                "sender_address":      d["sender_address_lower"],
                "asset":               d["asset"],
                "destination_address": d["destination_address"],
                "value_wei":           int(d["value_wei"]),
                "data_hex":            d["data_hex"],
                "nonce":               int(d["nonce"]),
                "gas_limit":           int(d["gas_limit"]),
                "gas_price":           int(d["gas_price"]),
                "chain_id":            int(d["chain_id"]),
                "transaction_to":      d["transaction_to"],
                "consumed":            consumed,
                "local_tx_hash":       d.get("local_tx_hash"),
                "broadcast_outcome":   d.get("broadcast_outcome"),
            }, None

    def claim_draft(
        self, *, draft_id: str, vault_id: str,
        network_id: str, lease_secs: int = 60,
    ) -> tuple[Optional[str], Optional[str]]:
        if self.fail_consume:
            raise RuntimeError("simulated claim-draft DB failure")
        now = _time.time()
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return None, "unknown_or_expired_draft"
            if d.get("expires_at", 0) <= now:
                return None, "unknown_or_expired_draft"
            if d.get("vault_id") != str(vault_id):
                return None, "draft_vault_mismatch"
            if d.get("network_id") != network_id:
                return None, "draft_network_mismatch"
            if d.get("consumed_at") is not None:
                return None, "draft_already_consumed"


            existing_token = d.get("claim_token")
            existing_expires = d.get("claim_expires_at", 0) or 0
            if existing_token and existing_expires > now:
                return None, "draft_already_claimed"
            claim_token = secrets.token_urlsafe(16)
            d["claim_token"] = claim_token
            d["claim_expires_at"] = now + int(lease_secs)
            return claim_token, None

    def release_claimed_draft(
        self, *, draft_id: str, claim_token: str,
    ) -> bool:
        if not claim_token:
            return False
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return False
            if d.get("consumed_at") is not None:
                return False
            if d.get("claim_token") != claim_token:
                return False
            d["claim_token"] = None
            d["claim_expires_at"] = None
            return True

    def consume_claimed_draft(
        self, *, draft_id: str, claim_token: str,
        local_tx_hash: str,
    ) -> bool:
        # 2026-07-13: does NOT clear claim_token. Kept for the
        # subsequent owner-safe `record_broadcast_outcome` write.
        if not claim_token or not local_tx_hash:
            return False
        now = _time.time()
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return False
            if d.get("consumed_at") is not None:
                return False
            if d.get("claim_token") != claim_token:
                return False
            d["consumed_at"] = now
            d["local_tx_hash"] = local_tx_hash
            return True

    def record_broadcast_outcome(
        self, *, draft_id: str, claim_token: str, outcome: str,
    ) -> bool:
        # Owner-safe, write-once. Mirrors the real store's CHECK-
        # constraint-enforced value set.
        if not claim_token:
            return False
        allowed = {
            "submitted", "submission_uncertain",
            "already_known", "explicitly_rejected",
        }
        if outcome not in allowed:
            return False
        now = _time.time()
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return False
            if d.get("consumed_at") is None:
                return False
            if d.get("claim_token") != claim_token:
                return False
            if d.get("broadcast_outcome") is not None:
                return False
            d["broadcast_outcome"] = outcome
            d["outcome_recorded_at"] = now
            return True


    def list_outgoing_history(
        self, *, vault_id: str, network_id: str, limit: int = 100,
    ) -> list[dict[str, Any]]:
        # Same field shape and same filter/order rules as the real
        # Postgres-backed `list_outgoing_history` — CONSUMED drafts
        # (local_tx_hash is not None) belonging to the vault + network,
        # most-recent consumed_at first, ties broken by draft_id ASC.
        if limit < 1:
            limit = 1
        if limit > 500:
            limit = 500
        with self._lock:
            candidates: list[dict[str, Any]] = []
            for d in self._drafts.values():
                if d.get("vault_id") != str(vault_id):
                    continue
                if d.get("network_id") != network_id:
                    continue
                if d.get("local_tx_hash") in (None, ""):
                    continue
                candidates.append(d)
            candidates.sort(
                key=lambda r: (
                    -(r.get("consumed_at") or 0.0),
                    r.get("draft_id") or "",
                ),
            )
            out: list[dict[str, Any]] = []
            for r in candidates[:limit]:
                out.append({
                    "draft_id":            r["draft_id"],
                    "network_id":          r["network_id"],
                    "asset":               r["asset"],
                    "sender_address":      r["sender_address_lower"],
                    "destination_address": r["destination_address"],
                    "value_wei":           int(r["value_wei"]),
                    "data_hex":            r["data_hex"],
                    "gas_limit":           int(r["gas_limit"]),
                    "gas_price":           int(r["gas_price"]),
                    "chain_id":            int(r["chain_id"]),
                    "transaction_to":      r["transaction_to"],
                    "local_tx_hash":       r["local_tx_hash"],
                    "broadcast_outcome":   r.get("broadcast_outcome"),
                    "created_at":          r.get("created_at"),
                    "consumed_at":         r.get("consumed_at"),
                    "outcome_recorded_at": r.get("outcome_recorded_at"),
                })
            return out


    def acquire_wallet_lock(
        self, *, network_id: str, sender_address: str,
        lease_secs: int = 30,
    ) -> Optional[str]:
        if self.fail_lock:
            raise RuntimeError("simulated acquire-lock DB failure")
        sender_lower = (sender_address or "").strip().lower()
        if not sender_lower:
            return None
        token = secrets.token_urlsafe(16)
        now = _time.time()
        with self._lock:
            key = (network_id, sender_lower)
            existing = self._wallet_locks.get(key)
            if existing and existing["expires_at"] > now:
                return None
            self._wallet_locks[key] = {
                "lock_token":  token,
                "acquired_at": now,
                "expires_at":  now + int(lease_secs),
            }
            return token

    def release_wallet_lock(
        self, *, network_id: str, sender_address: str, lock_token: str,
    ) -> bool:
        sender_lower = (sender_address or "").strip().lower()
        if not sender_lower or not lock_token:
            return False
        with self._lock:
            key = (network_id, sender_lower)
            existing = self._wallet_locks.get(key)
            if existing and existing["lock_token"] == lock_token:
                del self._wallet_locks[key]
                return True
            return False


    def is_mainnet_send_paused(self) -> bool:
        if self.fail_pause_read:
            raise RuntimeError("simulated pause-read DB failure")
        with self._lock:



            if self._pause is None:
                return True
            return bool(self._pause)

    def set_mainnet_send_paused(self, paused: bool) -> None:
        with self._lock:
            self._pause = bool(paused)

    def clear_pause_row(self) -> None:



        with self._lock:
            self._pause = None


    def reset_for_tests(self) -> None:
        self.clear()








_TEST_PRIVATE_KEY_HEX: str = "0x" + "11" * 32
_TEST_SENDER_ADDRESS: str = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"


def make_signed_tx_and_matching_draft(
    *,
    priv_key_hex: Optional[str] = None,
    nonce: int = 0,
    gas_price: int = 1_000_000_000,
    gas_limit: int = 21_000,
    to_addr: str = "0x" + "22" * 20,
    value_wei: int = 0,
    data: bytes = b"",
    chain_id: int = 1,
) -> dict[str, Any]:
    """Generate a real EIP-155-signed legacy transaction plus the
    matching draft-dict shape that `verify_signed_tx_against_draft`
    expects.

    Every broadcast-path test that isn't specifically probing the
    binding failure modes uses this to make sure the verifier does
    not reject the fixture. Deterministic across runs.
    """
    from eth_account import Account
    priv = priv_key_hex or _TEST_PRIVATE_KEY_HEX
    tx = {
        "nonce":    int(nonce),
        "gasPrice": int(gas_price),
        "gas":      int(gas_limit),
        "to":       to_addr,
        "value":    int(value_wei),
        "data":     data,
        "chainId":  int(chain_id),
    }
    signed = Account.sign_transaction(tx, priv)
    sender_addr = Account.from_key(priv).address
    data_hex = data.hex() if isinstance(data, (bytes, bytearray)) else str(data)
    if not data_hex.startswith("0x"):
        data_hex = "0x" + data_hex
    raw_hex = signed.raw_transaction.hex()
    if not raw_hex.startswith("0x"):
        raw_hex = "0x" + raw_hex
    # 2026-07-13 canary hardening: `_broadcast_mainnet_signed_transaction`
    # rejects an RPC-echoed hash that does not match the locally derived
    # `keccak256(raw)`. Expose the local hash so tests that mock the
    # RPC can return the exact value the broadcast handler will compare
    # against — the alternative is a hard-coded stub that no longer
    # passes the mismatch guard.
    from evm_signed_tx_verify import compute_local_tx_hash
    local_hash = compute_local_tx_hash(raw_hex)
    return {
        "signed_tx_hex":      raw_hex,
        "sender_address":     sender_addr.lower(),
        "nonce":              int(nonce),
        "gas_price":          int(gas_price),
        "gas_limit":          int(gas_limit),
        "transaction_to":     to_addr.lower(),
        "value_wei":          int(value_wei),
        "data_hex":           data_hex.lower(),
        "chain_id":           int(chain_id),
        "local_tx_hash":      local_hash,
    }


_GLOBAL_FAKE: Optional[FakeMainnetStore] = None


def get_shared_fake() -> FakeMainnetStore:



    global _GLOBAL_FAKE
    if _GLOBAL_FAKE is None:
        _GLOBAL_FAKE = FakeMainnetStore()
    return _GLOBAL_FAKE


def reset_shared_fake() -> None:
    global _GLOBAL_FAKE
    if _GLOBAL_FAKE is not None:
        _GLOBAL_FAKE.clear()


__all__ = [
    "FakeMainnetStore",
    "get_shared_fake",
    "reset_shared_fake",
    "make_signed_tx_and_matching_draft",
]
