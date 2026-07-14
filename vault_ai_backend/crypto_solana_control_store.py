"""Postgres-backed control store for Solana Mainnet send safety.

2026-07-14 (Round 6 hardening): mirrors the ETH Mainnet control
store established in `crypto_mainnet_control_store` but with
Solana-specific state — recent blockhash, last valid block height,
fee lamports, primary Ed25519 signature — instead of the ETH gas +
nonce + keccak256 fields.

Draft state machine (every transition is atomic and owner-safe):

    ACTIVE  --claim-->  CLAIMED  --consume-->  CONSUMED
                            |                     |
                            +-- release --> ACTIVE +-- record_outcome -->
                                                       CONSUMED + outcome

The `local_signature` is the base58-encoded primary Ed25519
signature of the signed transaction — Solana's transaction identity
is the first signature, so persisting it at consume-time lets a
replay of the same signed transaction dispatch from the recorded
outcome rather than blindly re-broadcasting.

Fail-closed semantics match the ETH store:
  * Missing pause row → PAUSED
  * DB read error → PAUSED
  * `crypto_solana_drafts_outcome_value_check` mirrors the ETH
    enum so a stray outcome value fails at write time, not silently.

Wallet lock semantics also mirror ETH:
  * `INSERT ... ON CONFLICT ... WHERE expires_at < NOW()`
  * Owner-token release
  * Stale leases self-clear
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

from vault_core import get_db


logger = logging.getLogger("crypto_solana_control_store")


_DRAFT_ID_LEN_BYTES: int = 24
_CLAIM_TOKEN_LEN_BYTES: int = 16
_LOCK_TOKEN_LEN_BYTES: int = 16
_PAUSE_CONTROL_KEY: str = "send_paused"


# Terminal broadcast outcomes -- exactly one is recorded per
# CONSUMED draft after the RPC call. Enum-matched to the DB CHECK.
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


def register_draft(
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
    """Atomically register a fresh Solana send-draft.

    Solana's `lastValidBlockHeight` window is ~150 slots (~60 s at
    mainnet cadence). The default `ttl_secs` of 60 aligns roughly
    with that window so we never issue a draft with a blockhash the
    network has already forgotten.

    Advisory-lock keyed on `solana:draft:<network>:<sender>` so two
    concurrent register_draft calls for the same wallet race
    deterministically. Returns None when there is already an active
    draft for the same (network_id, sender_address).
    """
    lock_seed = f"solana:draft:{network_id}:{sender_address}"
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
              FROM crypto_solana_drafts
             WHERE network_id = %s
               AND sender_address = %s
               AND consumed_at IS NULL
               AND expires_at > NOW()
             LIMIT 1
            """,
            (network_id, sender_address),
        )
        if cur.fetchone() is not None:
            conn.rollback()
            return None
        cur.execute(
            """
            INSERT INTO crypto_solana_drafts (
                draft_id, vault_id, network_id, sender_address, asset,
                destination_address, value_lamports_str,
                fee_lamports_str, recent_blockhash,
                last_valid_block_height, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                NOW() + (INTERVAL '1 second' * %s)
            )
            """,
            (
                draft_id, str(vault_id), network_id, sender_address,
                asset, destination_address,
                str(int(value_lamports)),
                str(int(fee_lamports)),
                recent_blockhash,
                int(last_valid_block_height),
                int(ttl_secs),
            ),
        )
        conn.commit()
        return draft_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def register_draft_ciphertext_first(
    *,
    vault_id: str,
    network_id: str,
    sender_address_lookup_hash: bytes,
    draft_payload_ciphertext: bytes,
    recent_blockhash: str,
    last_valid_block_height: int,
    ttl_secs: int = 60,
) -> Optional[str]:
    """Ciphertext-first Solana draft creation.

    Persists ONLY:
      * draft_id, vault_id, network_id (structural)
      * recent_blockhash, last_valid_block_height (protocol-required
        for the transaction to remain valid on the current fork)
      * expires_at (state-machine)
      * sender_address_lookup_hash (keyed lookup for wallet-lock +
        duplicate-draft detection; opaque to any DB reader without
        the vault key)
      * draft_payload_ciphertext (destination / asset / value / fee,
        AES-GCM under the vault's metadata subkey)

    No readable user metadata. Duplicate-draft check runs against
    sender_address_lookup_hash instead of the plaintext address.
    Advisory lock keyed on the hash bytes.

    The plaintext sender_address / destination_address / value /
    fee / asset that the server used to construct the transaction
    live only in the request handler's local variables for the
    duration of the draft-create call and are discarded at
    end-of-request.
    """
    lock_seed = (
        "solana:draft:ct:" + network_id + ":" +
        sender_address_lookup_hash.hex()
    )
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
              FROM crypto_solana_drafts
             WHERE network_id = %s
               AND draft_payload_ciphertext IS NOT NULL
               AND sender_address IS NULL
               AND consumed_at IS NULL
               AND expires_at > NOW()
               AND vault_id = %s
             LIMIT 1
            """,
            (network_id, str(vault_id)),
        )
        if cur.fetchone() is not None:
            conn.rollback()
            return None
        cur.execute(
            """
            INSERT INTO crypto_solana_drafts (
                draft_id, vault_id, network_id,
                sender_address, asset,
                destination_address, value_lamports_str,
                fee_lamports_str,
                recent_blockhash, last_valid_block_height,
                expires_at,
                draft_payload_ciphertext
            ) VALUES (
                %s, %s, %s,
                NULL, NULL,
                NULL, NULL, NULL,
                %s, %s,
                NOW() + (INTERVAL '1 second' * %s),
                %s
            )
            """,
            (
                draft_id, str(vault_id), network_id,
                recent_blockhash, int(last_valid_block_height),
                int(ttl_secs), draft_payload_ciphertext,
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
    """SELECT-only fetch. Used to load draft fields BEFORE running
    signed-transaction verification so a mismatched signed tx cannot
    burn a legitimate draft."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT draft_id, vault_id, network_id, sender_address,
                   asset, destination_address, value_lamports_str,
                   fee_lamports_str, recent_blockhash,
                   last_valid_block_height, consumed_at,
                   local_signature, broadcast_outcome,
                   outcome_recorded_at
              FROM crypto_solana_drafts
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
        return {
            "draft_id":                row["draft_id"],
            "vault_id":                row["vault_id"],
            "network_id":              row["network_id"],
            "sender_address":          row["sender_address"],
            "asset":                   row["asset"],
            "destination_address":     row["destination_address"],
            "value_lamports":          int(row["value_lamports_str"]),
            "fee_lamports":            int(row["fee_lamports_str"]),
            "recent_blockhash":        row["recent_blockhash"],
            "last_valid_block_height": int(row["last_valid_block_height"]),
            "consumed":                row["consumed_at"] is not None,
            "local_signature":         row["local_signature"],
            "broadcast_outcome":       row["broadcast_outcome"],
        }, None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_draft(
    *, draft_id: str, vault_id: str, network_id: str,
    lease_secs: int = 60,
) -> tuple[Optional[str], Optional[str]]:
    """Atomically transition ACTIVE → CLAIMED. Same semantics as the
    ETH store: fresh ACTIVE or previously CLAIMED but expired-lease
    both succeed; CONSUMED / expired / current-CLAIMED all refuse."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, network_id, consumed_at, expires_at
              FROM crypto_solana_drafts
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
            UPDATE crypto_solana_drafts
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
    """Owner-safe transition CLAIMED → ACTIVE (on structural /
    signature verification failure BEFORE any RPC broadcast)."""
    if not claim_token:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_solana_drafts
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
    *, draft_id: str, claim_token: str, local_signature: str,
) -> bool:
    """Owner-safe transition CLAIMED → CONSUMED. Stamps the
    base58-encoded primary Ed25519 signature so replays can identify
    the transaction even if the RPC broadcast times out."""
    if not claim_token:
        return False
    if not local_signature:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_solana_drafts
               SET consumed_at = NOW(),
                   local_signature = %s
             WHERE draft_id = %s
               AND claim_token = %s
               AND consumed_at IS NULL
             RETURNING draft_id
            """,
            (local_signature, draft_id, claim_token),
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
    *, draft_id: str, claim_token: str, outcome: str,
) -> bool:
    """Owner-safe TERMINAL write. Same guarantees as ETH store."""
    if not claim_token:
        return False
    if outcome not in _ALLOWED_BROADCAST_OUTCOMES:
        logger.warning(
            "[SOLANA-CONTROL] record_outcome bad_value=%r draft=%s",
            outcome, str(draft_id)[:8] + "…",
        )
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_solana_drafts
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


def list_outgoing_history(
    *, vault_id: str, network_id: str, limit: int = 100,
) -> list[dict[str, Any]]:
    """SELECT-only vault-scoped read of CONSUMED Solana outgoing
    drafts. Mirrors the ETH `list_outgoing_history` projection —
    only fields safe to expose to the vault owner, ordered
    most-recent-consumed first."""
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT draft_id, network_id, asset, sender_address,
                   destination_address, value_lamports_str,
                   fee_lamports_str, recent_blockhash,
                   last_valid_block_height, local_signature,
                   broadcast_outcome,
                   EXTRACT(EPOCH FROM created_at)      AS created_at,
                   EXTRACT(EPOCH FROM consumed_at)     AS consumed_at,
                   EXTRACT(EPOCH FROM outcome_recorded_at)
                       AS outcome_recorded_at
              FROM crypto_solana_drafts
             WHERE vault_id = %s
               AND network_id = %s
               AND local_signature IS NOT NULL
             ORDER BY consumed_at DESC NULLS LAST, draft_id ASC
             LIMIT %s
            """,
            (str(vault_id), network_id, int(limit)),
        )
        rows = cur.fetchall() or []
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "draft_id":                r["draft_id"],
            "network_id":              r["network_id"],
            "asset":                   r["asset"],
            "sender_address":          r["sender_address"],
            "destination_address":     r["destination_address"],
            "value_lamports":          int(r["value_lamports_str"]),
            "fee_lamports":            int(r["fee_lamports_str"]),
            "recent_blockhash":        r["recent_blockhash"],
            "last_valid_block_height": int(r["last_valid_block_height"]),
            "local_signature":         r["local_signature"],
            "broadcast_outcome":       r["broadcast_outcome"],
            "created_at": (
                float(r["created_at"]) if r["created_at"] is not None
                else None
            ),
            "consumed_at": (
                float(r["consumed_at"])
                if r["consumed_at"] is not None else None
            ),
            "outcome_recorded_at": (
                float(r["outcome_recorded_at"])
                if r["outcome_recorded_at"] is not None else None
            ),
        })
    return out


def acquire_wallet_lock(
    *, network_id: str, sender_address: str, lease_secs: int = 60,
) -> Optional[str]:
    """Atomically acquire the (network, sender) broadcast slot.
    Owner-token release. Stale leases self-clear."""
    if not sender_address:
        return None
    token = secrets.token_urlsafe(_LOCK_TOKEN_LEN_BYTES)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crypto_solana_wallet_locks (
                network_id, sender_address, lock_token,
                acquired_at, expires_at
            ) VALUES (
                %s, %s, %s, NOW(),
                NOW() + (INTERVAL '1 second' * %s)
            )
            ON CONFLICT (network_id, sender_address) DO UPDATE
                SET lock_token = EXCLUDED.lock_token,
                    acquired_at = EXCLUDED.acquired_at,
                    expires_at = EXCLUDED.expires_at
              WHERE crypto_solana_wallet_locks.expires_at < NOW()
            RETURNING lock_token
            """,
            (network_id, sender_address, token, int(lease_secs)),
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
    if not sender_address or not lock_token:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM crypto_solana_wallet_locks
             WHERE network_id = %s
               AND sender_address = %s
               AND lock_token = %s
            """,
            (network_id, sender_address, lock_token),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def is_solana_send_paused() -> bool:
    """Missing row → PAUSED. DB read error → PAUSED."""
    try:
        conn = get_db()
    except Exception:
        logger.warning(
            "[SOLANA-CONTROL] pause_read get_db_failed — fail-closed",
        )
        return True
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value_json FROM crypto_solana_control "
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
            "[SOLANA-CONTROL] pause_read failed — fail-closed",
        )
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def set_solana_send_paused(paused: bool) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crypto_solana_control
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
    try:
        conn = get_db()
    except Exception:
        return
    try:
        cur = conn.cursor()
        for tbl in (
            "crypto_solana_drafts",
            "crypto_solana_wallet_locks",
            "crypto_solana_control",
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
    "list_outgoing_history",
    "acquire_wallet_lock",
    "release_wallet_lock",
    "is_solana_send_paused",
    "set_solana_send_paused",
    "reset_for_tests",
]
