"""Postgres-backed control store for Ethereum Mainnet send safety.

Three shared-state primitives that survive multi-worker and multi-
container deployments — Postgres row-level atomicity replaces the
process-local Python dicts of the pre-2026-07-13 design.

Draft state machine (every transition is atomic and owner-safe):

    ACTIVE  --claim-->  CLAIMED  --consume-->  CONSUMED
                            |                     |
                            +-- release --> ACTIVE +-- record_outcome -->
                                                       CONSUMED + outcome

  * ACTIVE   = row exists, `consumed_at IS NULL`, and no unexpired
                claim. `broadcast_outcome IS NULL`.
  * CLAIMED  = row exists, `consumed_at IS NULL`, `claim_token IS NOT
                NULL`, `claim_expires_at > NOW()`. A worker with the
                matching token has exclusive rights to verify + send.
                `broadcast_outcome IS NULL`.
  * CONSUMED (outcome pending) = `consumed_at IS NOT NULL`,
                `local_tx_hash IS NOT NULL`, `broadcast_outcome IS
                NULL`. This is the transient state between the
                CLAIMED->CONSUMED transition and the terminal outcome
                write. A process crash inside this window is answered
                CONSERVATIVELY on replay (submission_uncertain), not
                as `already_submitted`.
  * CONSUMED (terminal) = `consumed_at IS NOT NULL`, `local_tx_hash
                IS NOT NULL`, `broadcast_outcome IS NOT NULL` in the
                set {submitted, submission_uncertain, already_known,
                explicitly_rejected}, `outcome_recorded_at IS NOT
                NULL`. Replay dispatch is exact: the recorded outcome
                determines the envelope returned to the retrying
                client.

The `release_claimed_draft` transition exists specifically so that a
signed-transaction verification failure BEFORE the RPC broadcast
does NOT permanently burn a legitimate draft. Only a fresh CLAIMED
draft can be released; a CONSUMED draft is terminal.

The `claim_token` is retained after `consume_claimed_draft` so the
subsequent `record_broadcast_outcome` write can be owner-safe: only
the worker that consumed the draft can write its terminal outcome,
and only ONCE (`broadcast_outcome IS NULL` in the WHERE clause).

Wallet broadcast lock: per-(network, sender_lower) row with a lease
TTL. `INSERT ... ON CONFLICT ... WHERE expires_at < NOW()` gives
atomic acquire; owner-token release means one request cannot free
another request's lock; stale leases automatically clear.

Pause flag: single row in a control table. Missing row is
interpreted as PAUSED (defense in depth — a wiped-then-migrated
environment must default to blocking mainnet send until the operator
explicitly unpauses).
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

from vault_core import get_db


logger = logging.getLogger("crypto_mainnet_control_store")


_DRAFT_ID_LEN_BYTES: int = 24
_CLAIM_TOKEN_LEN_BYTES: int = 16
_LOCK_TOKEN_LEN_BYTES: int = 16
_PAUSE_CONTROL_KEY: str = "send_paused"


# Terminal broadcast outcomes -- exactly one is recorded per CONSUMED
# draft after the RPC call. The set is duplicated in the DB via a
# CHECK constraint on `crypto_mainnet_drafts.broadcast_outcome` so a
# typo here would fail at write time, not silently corrupt state.
BROADCAST_OUTCOME_SUBMITTED: str = "submitted"
BROADCAST_OUTCOME_SUBMISSION_UNCERTAIN: str = "submission_uncertain"
BROADCAST_OUTCOME_ALREADY_KNOWN: str = "already_known"
BROADCAST_OUTCOME_EXPLICITLY_REJECTED: str = "explicitly_rejected"
_ALLOWED_BROADCAST_OUTCOMES: frozenset[str] = frozenset({
    BROADCAST_OUTCOME_SUBMITTED,
    BROADCAST_OUTCOME_SUBMISSION_UNCERTAIN,
    BROADCAST_OUTCOME_ALREADY_KNOWN,
    BROADCAST_OUTCOME_EXPLICITLY_REJECTED,
})


def _addr_lower(addr: str) -> str:
    return (addr or "").strip().lower()



def register_draft(
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
    """Atomically register a fresh mainnet send-draft in ACTIVE state.

    Serialization: takes a Postgres **transaction-scoped** advisory
    lock (`pg_advisory_xact_lock`) keyed on
    `hashtextextended('mainnet:draft:<network>:<sender_lower>')` so
    two concurrent `register_draft` calls for the same wallet race
    deterministically. The lock is automatically released when the
    transaction commits or rolls back — it CANNOT leak into a pooled
    connection's future queries.

    Returns the new draft_id on success. Returns None when there is
    already an active draft for the same `(network_id,
    sender_address_lower)` — where "active" means BOTH:
      * `consumed_at IS NULL`, AND
      * either the draft is unclaimed OR its claim has not expired.
    """
    sender_lower = _addr_lower(sender_address)
    lock_seed = f"mainnet:draft:{network_id}:{sender_lower}"
    draft_id = secrets.token_urlsafe(_DRAFT_ID_LEN_BYTES)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_seed,),
        )
        cur.execute(
            """
            SELECT draft_id
              FROM crypto_mainnet_drafts
             WHERE network_id = %s
               AND sender_address_lower = %s
               AND consumed_at IS NULL
               AND expires_at > NOW()
             LIMIT 1
            """,
            (network_id, sender_lower),
        )
        if cur.fetchone() is not None:
            conn.rollback()
            return None
        cur.execute(
            """
            INSERT INTO crypto_mainnet_drafts (
                draft_id, vault_id, network_id, sender_address_lower,
                asset, destination_address, value_wei_str, data_hex,
                nonce, gas_limit, gas_price_str, chain_id,
                transaction_to, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                NOW() + (INTERVAL '1 second' * %s)
            )
            """,
            (
                draft_id, str(vault_id), network_id, sender_lower,
                asset, destination_address, str(int(value_wei)),
                data_hex, int(nonce), int(gas_limit),
                str(int(gas_price)), int(chain_id),
                transaction_to, int(ttl_secs),
            ),
        )
        conn.commit()
        return draft_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_draft_readonly(
    *, draft_id: str, vault_id: str, network_id: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """SELECT-only fetch — does not mutate draft state.

    Used by the broadcast route to load the draft's expected fields
    BEFORE running signed-transaction verification. Verification
    must succeed before any state-changing operation runs so a
    malformed / mismatched signed tx cannot burn a legitimate draft.

    Returns (draft_dict, None) if the draft is ACTIVE or CLAIMED-
    but-not-yet-expired-by-current-caller. Returns (None, code) if
    the draft is missing / expired / consumed / vault-mismatch /
    network-mismatch.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT draft_id, vault_id, network_id,
                   sender_address_lower AS sender_address, asset,
                   destination_address, value_wei_str, data_hex,
                   nonce, gas_limit, gas_price_str, chain_id,
                   transaction_to, consumed_at, local_tx_hash,
                   broadcast_outcome, outcome_recorded_at
              FROM crypto_mainnet_drafts
             WHERE draft_id = %s
               AND expires_at > NOW()
            """,
            (draft_id,),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:
            return None, "unknown_or_expired_draft"
        if row["vault_id"] != str(vault_id):
            return None, "draft_vault_mismatch"
        if row["network_id"] != network_id:
            return None, "draft_network_mismatch"
        if row["consumed_at"] is not None:
            return {
                "draft_id":            row["draft_id"],
                "vault_id":            row["vault_id"],
                "network_id":          row["network_id"],
                "sender_address":      row["sender_address"],
                "asset":               row["asset"],
                "destination_address": row["destination_address"],
                "value_wei":           int(row["value_wei_str"]),
                "data_hex":            row["data_hex"],
                "nonce":               int(row["nonce"]),
                "gas_limit":           int(row["gas_limit"]),
                "gas_price":           int(row["gas_price_str"]),
                "chain_id":            int(row["chain_id"]),
                "transaction_to":      row["transaction_to"],
                "consumed":            True,
                "local_tx_hash":       row["local_tx_hash"],
                "broadcast_outcome":   row["broadcast_outcome"],
            }, None
        return {
            "draft_id":            row["draft_id"],
            "vault_id":            row["vault_id"],
            "network_id":          row["network_id"],
            "sender_address":      row["sender_address"],
            "asset":               row["asset"],
            "destination_address": row["destination_address"],
            "value_wei":           int(row["value_wei_str"]),
            "data_hex":            row["data_hex"],
            "nonce":               int(row["nonce"]),
            "gas_limit":           int(row["gas_limit"]),
            "gas_price":           int(row["gas_price_str"]),
            "chain_id":            int(row["chain_id"]),
            "transaction_to":      row["transaction_to"],
            "consumed":            False,
            "local_tx_hash":       None,
            "broadcast_outcome":   None,
        }, None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_draft(
    *,
    draft_id: str,
    vault_id: str,
    network_id: str,
    lease_secs: int = 60,
) -> tuple[Optional[str], Optional[str]]:
    """Atomically transition ACTIVE → CLAIMED and return the claim
    token. Owner-safe: only the returned token can `consume` or
    `release`.

    Semantics of the atomic UPDATE:

        UPDATE ...
           SET claim_token = <new>, claim_expires_at = NOW() + lease
         WHERE draft_id = %s
           AND consumed_at IS NULL
           AND expires_at > NOW()
           AND (
               claim_token IS NULL
            OR claim_expires_at <= NOW()
           )

    In one statement this covers: fresh ACTIVE, previously CLAIMED
    but with an expired lease. It refuses: CONSUMED, expired,
    currently CLAIMED with valid lease (owned by another worker).

    Returns (claim_token, None) on success or (None, error_code).
    Postgres row-level locking during UPDATE means two workers
    racing on the same draft see exactly one succeed and the other
    receive an empty RETURNING (mapped to `draft_already_claimed`).
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, network_id, consumed_at, local_tx_hash,
                   expires_at
              FROM crypto_mainnet_drafts
             WHERE draft_id = %s
            """,
            (draft_id,),
        )
        row = cur.fetchone()
        if row is None:
            conn.commit()
            return None, "unknown_or_expired_draft"
        if row["vault_id"] != str(vault_id):
            conn.rollback()
            return None, "draft_vault_mismatch"
        if row["network_id"] != network_id:
            conn.rollback()
            return None, "draft_network_mismatch"
        if row["consumed_at"] is not None:
            conn.commit()
            return None, "draft_already_consumed"
        claim_token = secrets.token_urlsafe(_CLAIM_TOKEN_LEN_BYTES)
        cur.execute(
            """
            UPDATE crypto_mainnet_drafts
               SET claim_token = %s,
                   claim_expires_at = NOW() + (INTERVAL '1 second' * %s)
             WHERE draft_id = %s
               AND consumed_at IS NULL
               AND expires_at > NOW()
               AND (
                   claim_token IS NULL
                OR claim_expires_at <= NOW()
               )
             RETURNING draft_id
            """,
            (claim_token, int(lease_secs), draft_id),
        )
        if cur.fetchone() is None:
            conn.rollback()



            return None, "draft_already_claimed"
        conn.commit()
        return claim_token, None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_claimed_draft(
    *, draft_id: str, claim_token: str,
) -> bool:
    """Owner-safe transition CLAIMED → ACTIVE.

    Used ONLY on structural / cryptographic signed-transaction
    verification failure BEFORE any RPC call. A verification
    failure means the caller submitted a signed tx that doesn't
    match the drafted fields — the client can retry the same draft
    with the correct signature.

    Owner-safe: refuses to touch the row unless `claim_token`
    matches. This means a stale worker whose lease has already
    expired (and been reclaimed by another worker) cannot corrupt
    the fresh claim.
    """
    if not claim_token:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_mainnet_drafts
               SET claim_token = NULL,
                   claim_expires_at = NULL
             WHERE draft_id = %s
               AND claim_token = %s
               AND consumed_at IS NULL
             RETURNING draft_id
            """,
            (draft_id, claim_token),
        )
        released = cur.fetchone() is not None
        conn.commit()
        return released
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consume_claimed_draft(
    *, draft_id: str, claim_token: str, local_tx_hash: str,
) -> bool:
    """Owner-safe transition CLAIMED → CONSUMED (outcome pending).

    Records `local_tx_hash` (the keccak256 of the raw signed tx
    bytes) on the row. The tx hash is derived locally by the
    caller before any RPC call, so even if the RPC broadcast
    times out AFTER the transaction was accepted by the node, the
    server knows which transaction was potentially submitted and
    can report it to the client on retry.

    IMPORTANT: this transition leaves `claim_token` intact so the
    subsequent `record_broadcast_outcome` write can be owner-safe.
    A stale worker whose claim expired and was reclaimed cannot
    write an outcome on a draft they no longer own.

    Owner-safe: refuses to touch the row unless `claim_token`
    matches. Refuses on already-consumed draft too — a caller
    holding a stale token cannot overwrite `local_tx_hash` with
    a different value later.
    """
    if not claim_token:
        return False
    if not local_tx_hash:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_mainnet_drafts
               SET consumed_at = NOW(),
                   local_tx_hash = %s
             WHERE draft_id = %s
               AND claim_token = %s
               AND consumed_at IS NULL
             RETURNING draft_id
            """,
            (local_tx_hash, draft_id, claim_token),
        )
        consumed = cur.fetchone() is not None
        conn.commit()
        return consumed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_broadcast_outcome(
    *,
    draft_id: str,
    claim_token: str,
    outcome: str,
) -> bool:
    """Owner-safe TERMINAL write CONSUMED (pending) → CONSUMED
    (terminal, outcome known).

    Called EXACTLY ONCE per draft, immediately after the RPC call
    completes (or fails). Persists the true broadcast outcome
    (`submitted` / `submission_uncertain` / `already_known` /
    `explicitly_rejected`) so a subsequent replay of the same
    signed transaction returns the correct envelope, not just
    `already_submitted`.

    The write is guarded by:

      * `claim_token = %s`         — only the acquirer can write.
      * `consumed_at IS NOT NULL`  — must be in the CONSUMED state.
      * `broadcast_outcome IS NULL` — write ONCE; a stale worker
                                     cannot overwrite a terminal
                                     outcome recorded by a fresh
                                     worker.

    Returns True on the first successful write, False if:

      * the outcome value isn't in the allowed set,
      * the claim_token is empty,
      * the row's outcome was already recorded, or
      * the row's claim_token no longer matches (reclaimed).

    A False return does NOT trigger DB corruption; it just means
    the caller lost the race and the on-record outcome stands.

    Crash semantics: if the caller crashes between
    `consume_claimed_draft` and this call, the row is left in
    "CONSUMED, outcome NULL" state. On replay, the route treats
    `broadcast_outcome IS NULL` on a CONSUMED row as
    `submission_uncertain` -- the transaction MAY have been
    submitted; the client should poll the local hash before
    assuming failure.
    """
    if not claim_token:
        return False
    if outcome not in _ALLOWED_BROADCAST_OUTCOMES:
        # Belt-and-suspenders: the CHECK constraint on the column
        # would reject an out-of-set value; we reject earlier so a
        # caller bug is visible without a raised exception.
        logger.warning(
            "[MAINNET-CONTROL] record_outcome bad_value=%r draft=%s",
            outcome, str(draft_id)[:8] + "…",
        )
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_mainnet_drafts
               SET broadcast_outcome = %s,
                   outcome_recorded_at = NOW()
             WHERE draft_id = %s
               AND claim_token = %s
               AND consumed_at IS NOT NULL
               AND broadcast_outcome IS NULL
             RETURNING draft_id
            """,
            (outcome, draft_id, claim_token),
        )
        recorded = cur.fetchone() is not None
        conn.commit()
        return recorded
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def acquire_wallet_lock(
    *, network_id: str, sender_address: str, lease_secs: int = 60,
) -> Optional[str]:
    """Atomically acquire the (network, sender) broadcast slot.

    Returns a `lock_token` on success; None if another owner holds
    the slot with an unexpired lease. The returned token MUST be
    passed to `release_wallet_lock` — owner-safe release.

    Default lease: 60 seconds. Long enough to cover the 6-second
    httpx RPC timeout, DB queries, verification, and typical GC
    pauses. Short enough that a crashed worker's slot self-clears
    without operator intervention. Callers that expect the
    broadcast section to run under one second still get a strong
    guarantee — the lease only matters for the failure case.
    """
    sender_lower = _addr_lower(sender_address)
    if not sender_lower:
        return None
    token = secrets.token_urlsafe(_LOCK_TOKEN_LEN_BYTES)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crypto_mainnet_wallet_locks (
                network_id, sender_address_lower, lock_token,
                acquired_at, expires_at
            ) VALUES (
                %s, %s, %s, NOW(),
                NOW() + (INTERVAL '1 second' * %s)
            )
            ON CONFLICT (network_id, sender_address_lower) DO UPDATE
                SET lock_token   = EXCLUDED.lock_token,
                    acquired_at  = EXCLUDED.acquired_at,
                    expires_at   = EXCLUDED.expires_at
              WHERE crypto_mainnet_wallet_locks.expires_at < NOW()
            RETURNING lock_token
            """,
            (network_id, sender_lower, token, int(lease_secs)),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None or row[0] != token:
            return None
        return token
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_wallet_lock(
    *, network_id: str, sender_address: str, lock_token: str,
) -> bool:
    """Owner-safe release: DELETE only the row whose lock_token
    matches the caller's. A stale worker whose lease already
    expired and was reclaimed by a different worker cannot delete
    the fresh acquire.
    """
    sender_lower = _addr_lower(sender_address)
    if not sender_lower or not lock_token:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM crypto_mainnet_wallet_locks
             WHERE network_id = %s
               AND sender_address_lower = %s
               AND lock_token = %s
            """,
            (network_id, sender_lower, lock_token),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def is_mainnet_send_paused() -> bool:
    """Read the mainnet-send pause flag.

    Missing row → PAUSED. A freshly-migrated database with no
    `send_paused` row explicitly seeded returns True; the operator
    must call `set_mainnet_send_paused(False)` after smoke checks
    to actually enable mainnet send. Migration 0020 seeds
    `paused=true` for exactly this reason.

    DB read exception → PAUSED (fail-closed). An unreachable
    control store cannot accidentally un-pause mainnet send.
    """
    try:
        conn = get_db()
    except Exception:
        logger.warning(
            "[MAINNET-CONTROL] pause_read get_db_failed — fail-closed",
        )
        return True
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value_json FROM crypto_mainnet_control "
            "WHERE control_key = %s",
            (_PAUSE_CONTROL_KEY,),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:



            return True
        try:
            v = json.loads(row[0])
        except (TypeError, ValueError):
            return True
        if isinstance(v, dict):
            return bool(v.get("paused", True))
        return bool(v)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(
            "[MAINNET-CONTROL] pause_read failed — fail-closed",
        )
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def set_mainnet_send_paused(paused: bool) -> None:
    """Flip the DB-backed pause flag. Called from the ops runbook /
    admin CLI — never from a user-facing route.
    """
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crypto_mainnet_control
                (control_key, value_json, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (control_key) DO UPDATE
                SET value_json = EXCLUDED.value_json,
                    updated_at = NOW()
            """,
            (
                _PAUSE_CONTROL_KEY,
                json.dumps({"paused": bool(paused)}),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def reset_for_tests() -> None:
    """Test-only helper: truncate the three control tables.

    Skips silently if the DB is unreachable — production doesn't
    call this and test suites without a live Postgres monkey-patch
    the module-level functions instead of relying on the real
    tables.
    """
    try:
        conn = get_db()
    except Exception:
        return
    try:
        cur = conn.cursor()
        for tbl in (
            "crypto_mainnet_drafts",
            "crypto_mainnet_wallet_locks",
            "crypto_mainnet_control",
        ):
            try:
                cur.execute(f"TRUNCATE TABLE {tbl}")
            except Exception:
                conn.rollback()
                continue
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


__all__ = [
    "BROADCAST_OUTCOME_SUBMITTED",
    "BROADCAST_OUTCOME_SUBMISSION_UNCERTAIN",
    "BROADCAST_OUTCOME_ALREADY_KNOWN",
    "BROADCAST_OUTCOME_EXPLICITLY_REJECTED",
    "register_draft",
    "load_draft_readonly",
    "claim_draft",
    "release_claimed_draft",
    "consume_claimed_draft",
    "record_broadcast_outcome",
    "acquire_wallet_lock",
    "release_wallet_lock",
    "is_mainnet_send_paused",
    "set_mainnet_send_paused",
    "reset_for_tests",
]
