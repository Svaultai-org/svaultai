"""In-process fake for `crypto_solana_control_store`.

Same public surface as the Postgres-backed real store — every
method matches the real store's kwarg names, return shape, and
error codes. Used by tests that exercise the Solana routing /
binding / state-machine ordering without a live Postgres.
"""

from __future__ import annotations

import secrets
import threading
import time as _time
from typing import Any, Optional


class FakeSolanaStore:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._drafts: dict[str, dict[str, Any]] = {}
        self._wallet_locks: dict[tuple[str, str], dict[str, Any]] = {}
        # Same default posture as the real store: FALSE (not paused)
        # so tests that unpause SOL do not need to seed the row
        # first. Individual tests that want to exercise the fail-
        # closed path can call clear_pause_row().
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
        asset: str = "SOL",
        destination_address: str = "",
        value_lamports: int = 0,
        fee_lamports: int = 5000,
        recent_blockhash: str = "GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cUKQwT8b9DhP7A",
        last_valid_block_height: int = 250_000_000,
        ttl_secs: int = 10 ** 8,
    ) -> None:
        now = _time.time()
        with self._lock:
            self._drafts[draft_id] = {
                "draft_id":                draft_id,
                "vault_id":                str(vault_id),
                "network_id":              network_id,
                "sender_address":          sender_address,
                "asset":                   asset,
                "destination_address":     destination_address,
                "value_lamports":          int(value_lamports),
                "fee_lamports":            int(fee_lamports),
                "recent_blockhash":        recent_blockhash,
                "last_valid_block_height": int(last_valid_block_height),
                "created_at":              now,
                "expires_at":              now + int(ttl_secs),
                "claim_token":             None,
                "claim_expires_at":        None,
                "consumed_at":             None,
                "local_signature":         None,
                "broadcast_outcome":       None,
                "outcome_recorded_at":     None,
            }

    def register_draft(
        self,
        *,
        vault_id: str,
        network_id: str,
        sender_address: str,
        asset: str,
        destination_address: str,
        value_lamports: int,
        fee_lamports: int,
        recent_blockhash: str,
        last_valid_block_height: int,
        ttl_secs: int = 60,
    ) -> Optional[str]:
        if self.fail_register:
            raise RuntimeError("simulated register-draft DB failure")
        now = _time.time()
        with self._lock:
            for did, d in list(self._drafts.items()):
                if d.get("expires_at", 0) <= now:
                    self._drafts.pop(did, None)
            for d in self._drafts.values():
                if (
                    d.get("network_id") == network_id
                    and d.get("sender_address") == sender_address
                    and d.get("consumed_at") is None
                    and d.get("expires_at", 0) > now
                ):
                    return None
            draft_id = secrets.token_urlsafe(24)
            self._drafts[draft_id] = {
                "draft_id":                draft_id,
                "vault_id":                str(vault_id),
                "network_id":              network_id,
                "sender_address":          sender_address,
                "asset":                   asset,
                "destination_address":     destination_address,
                "value_lamports":          int(value_lamports),
                "fee_lamports":            int(fee_lamports),
                "recent_blockhash":        recent_blockhash,
                "last_valid_block_height": int(last_valid_block_height),
                "created_at":              now,
                "expires_at":              now + int(ttl_secs),
                "claim_token":             None,
                "claim_expires_at":        None,
                "consumed_at":             None,
                "local_signature":         None,
                "broadcast_outcome":       None,
                "outcome_recorded_at":     None,
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
            return {
                "draft_id":                d["draft_id"],
                "vault_id":                d["vault_id"],
                "network_id":              d["network_id"],
                "sender_address":          d["sender_address"],
                "asset":                   d["asset"],
                "destination_address":     d["destination_address"],
                "value_lamports":          int(d["value_lamports"]),
                "fee_lamports":            int(d["fee_lamports"]),
                "recent_blockhash":        d["recent_blockhash"],
                "last_valid_block_height": int(d["last_valid_block_height"]),
                "consumed":                d.get("consumed_at") is not None,
                "local_signature":         d.get("local_signature"),
                "broadcast_outcome":       d.get("broadcast_outcome"),
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
        local_signature: str,
    ) -> bool:
        if not claim_token or not local_signature:
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
            d["local_signature"] = local_signature
            return True

    def record_broadcast_outcome(
        self, *, draft_id: str, claim_token: str, outcome: str,
    ) -> bool:
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
        if limit < 1:
            limit = 1
        if limit > 500:
            limit = 500
        with self._lock:
            cands = []
            for d in self._drafts.values():
                if d.get("vault_id") != str(vault_id):
                    continue
                if d.get("network_id") != network_id:
                    continue
                if d.get("local_signature") in (None, ""):
                    continue
                cands.append(d)
            cands.sort(
                key=lambda r: (
                    -(r.get("consumed_at") or 0.0),
                    r.get("draft_id") or "",
                ),
            )
            out = []
            for r in cands[:limit]:
                out.append({
                    "draft_id":                r["draft_id"],
                    "network_id":              r["network_id"],
                    "asset":                   r["asset"],
                    "sender_address":          r["sender_address"],
                    "destination_address":     r["destination_address"],
                    "value_lamports":          int(r["value_lamports"]),
                    "fee_lamports":            int(r["fee_lamports"]),
                    "recent_blockhash":        r["recent_blockhash"],
                    "last_valid_block_height": int(r["last_valid_block_height"]),
                    "local_signature":         r["local_signature"],
                    "broadcast_outcome":       r.get("broadcast_outcome"),
                    "created_at":              r.get("created_at"),
                    "consumed_at":             r.get("consumed_at"),
                    "outcome_recorded_at":     r.get("outcome_recorded_at"),
                })
            return out

    def acquire_wallet_lock(
        self, *, network_id: str, sender_address: str,
        lease_secs: int = 30,
    ) -> Optional[str]:
        if self.fail_lock:
            raise RuntimeError("simulated acquire-lock DB failure")
        if not sender_address:
            return None
        token = secrets.token_urlsafe(16)
        now = _time.time()
        with self._lock:
            key = (network_id, sender_address)
            existing = self._wallet_locks.get(key)
            if existing and existing["expires_at"] > now:
                return None
            self._wallet_locks[key] = {
                "lock_token": token,
                "acquired_at": now,
                "expires_at": now + int(lease_secs),
            }
            return token

    def release_wallet_lock(
        self, *, network_id: str, sender_address: str, lock_token: str,
    ) -> bool:
        if not sender_address or not lock_token:
            return False
        with self._lock:
            key = (network_id, sender_address)
            existing = self._wallet_locks.get(key)
            if existing and existing["lock_token"] == lock_token:
                del self._wallet_locks[key]
                return True
            return False

    def is_solana_send_paused(self) -> bool:
        if self.fail_pause_read:
            raise RuntimeError("simulated pause-read DB failure")
        with self._lock:
            if self._pause is None:
                return True
            return bool(self._pause)

    def set_solana_send_paused(self, paused: bool) -> None:
        with self._lock:
            self._pause = bool(paused)

    def clear_pause_row(self) -> None:
        with self._lock:
            self._pause = None

    def reset_for_tests(self) -> None:
        self.clear()


_GLOBAL_FAKE: Optional[FakeSolanaStore] = None


def get_shared_fake() -> FakeSolanaStore:
    global _GLOBAL_FAKE
    if _GLOBAL_FAKE is None:
        _GLOBAL_FAKE = FakeSolanaStore()
    return _GLOBAL_FAKE


def reset_shared_fake() -> None:
    global _GLOBAL_FAKE
    if _GLOBAL_FAKE is not None:
        _GLOBAL_FAKE.clear()


__all__ = [
    "FakeSolanaStore",
    "get_shared_fake",
    "reset_shared_fake",
]
