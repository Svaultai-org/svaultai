"""Operator-only repair for abandoned Ethereum Mainnet send drafts.

This is a local/VPS command, not an HTTP endpoint. It never signs,
never broadcasts, and never prints addresses, keys, ciphertext, raw
transactions, tokens, or PINs.

Usage:
  python ops/repair_mainnet_unsigned_drafts.py --vault-id <uuid>
  VAULTAI_MAINNET_REPAIR_ACK=expire-unsigned-mainnet-draft \
    python ops/repair_mainnet_unsigned_drafts.py \
      --vault-id <uuid> --draft-id <opaque-id> --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vault_core import get_db


NETWORK_ETHEREUM_MAINNET = "ethereum_mainnet"
_PRODUCTION_ACK_VALUE = "expire-unsigned-mainnet-draft"


def _draft_ref(draft_id: Any) -> str:
    text = str(draft_id or "")
    return text[:8] + "..." if len(text) > 8 else text


def _classify(row: dict[str, Any]) -> str:
    if row.get("consumed_at") is not None:
        if row.get("local_tx_hash") and row.get("broadcast_outcome") is None:
            return "broadcast_uncertain"
        outcome = row.get("broadcast_outcome")
        if outcome in ("submitted", "already_known"):
            return "submitted"
        if outcome == "submission_uncertain":
            return "broadcast_uncertain"
        if outcome == "explicitly_rejected":
            return "failed"
        return "malformed"
    if row.get("claim_token") and row.get("claim_expires_at_active"):
        return "signing"
    if row.get("claim_token"):
        return "abandoned_unsigned_draft"
    return "draft_created"


def _load_rows(
    vault_id: str,
    network_id: str,
    draft_id: str | None = None,
) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        draft_filter = "AND draft_id = %s" if draft_id else ""
        params: tuple[Any, ...] = (
            (str(vault_id), network_id, draft_id)
            if draft_id
            else (str(vault_id), network_id)
        )
        cur.execute(
            f"""
            SELECT draft_id,
                   network_id,
                   chain_id,
                   EXTRACT(EPOCH FROM created_at) AS created_at,
                   EXTRACT(EPOCH FROM expires_at) AS expires_at,
                   EXTRACT(EPOCH FROM consumed_at) AS consumed_at,
                   local_tx_hash,
                   nonce,
                   broadcast_outcome,
                   claim_token,
                   (claim_expires_at > NOW()) AS claim_expires_at_active
              FROM crypto_mainnet_drafts
             WHERE vault_id = %s
               AND network_id = %s
               {draft_filter}
               AND expires_at > NOW()
             ORDER BY created_at DESC, draft_id ASC
             LIMIT 50
            """,
            params,
        )
        rows = [dict(r) for r in (cur.fetchall() or [])]
        conn.commit()
        return rows
    finally:
        conn.close()


def _is_safe_unsigned_repair_candidate(row: dict[str, Any]) -> bool:
    return (
        row.get("network_id") == NETWORK_ETHEREUM_MAINNET
        and int(row.get("chain_id") or 0) == 1
        and row.get("consumed_at") is None
        and not row.get("local_tx_hash")
        and not (
            row.get("claim_token")
            and row.get("claim_expires_at_active")
        )
    )


def _repair_refusal_reason(
    rows: list[dict[str, Any]],
    *,
    draft_id: str | None,
    is_production: bool,
    ack_value: str,
) -> str:
    if not draft_id:
        return "apply_requires_exact_draft_id"
    if is_production and ack_value != _PRODUCTION_ACK_VALUE:
        return "production_ack_required"
    if len(rows) != 1:
        return "exact_draft_not_found"
    if not _is_safe_unsigned_repair_candidate(rows[0]):
        return "unsafe_draft_state"
    return ""


def _expire_unsigned(vault_id: str, network_id: str, draft_id: str) -> int:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crypto_mainnet_drafts
               SET expires_at = NOW()
             WHERE vault_id = %s
               AND network_id = %s
               AND draft_id = %s
               AND chain_id = 1
               AND consumed_at IS NULL
               AND local_tx_hash IS NULL
               AND expires_at > NOW()
               AND (
                    claim_token IS NULL
                 OR claim_expires_at <= NOW()
               )
            """,
            (str(vault_id), network_id, draft_id),
        )
        changed = int(cur.rowcount or 0)
        if changed:
            cur.execute("SELECT to_regclass('public.vault_security_events')")
            if cur.fetchone()[0] is not None:
                cur.execute(
                    """
                    INSERT INTO vault_security_events
                        (vault_id, event_type, client_label)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        str(vault_id),
                        "mainnet-draft-repair",
                        f"expired_unsigned:{_draft_ref(draft_id)}",
                    ),
                )
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_report(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def safe_epoch(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    def rpc_status(local_tx_hash: Any) -> str:
        if not local_tx_hash:
            return "not_applicable_unsigned"
        try:
            from vault_config import ethereum_mainnet_rpc_url
            from evm_rpc import (
                EvmRpcError,
                eth_get_transaction_by_hash_at_url,
                eth_get_transaction_receipt_at_url,
            )
            rpc_url = ethereum_mainnet_rpc_url()
            if not rpc_url:
                return "rpc_not_configured"
            receipt = eth_get_transaction_receipt_at_url(
                rpc_url, str(local_tx_hash),
            )
            if receipt is not None:
                if receipt.get("status") == "0x1":
                    return "confirmed"
                if receipt.get("status") == "0x0":
                    return "failed"
                return "receipt_unknown"
            by_hash = eth_get_transaction_by_hash_at_url(
                rpc_url, str(local_tx_hash),
            )
            return "pending" if by_hash is not None else "not_found"
        except EvmRpcError as exc:
            return f"rpc_error:{exc.code}"
        except Exception:
            return "rpc_error"

    out: list[dict[str, Any]] = []
    for row in rows:
        local_hash = row.get("local_tx_hash")
        status = rpc_status(local_hash)
        out.append({
            "draftRef": _draft_ref(row.get("draft_id")),
            "status": _classify(row),
            "network": row.get("network_id"),
            "chainId": int(row.get("chain_id") or 0),
            "createdAt": safe_epoch(row.get("created_at")),
            "expiresAt": safe_epoch(row.get("expires_at")),
            "hasNonce": row.get("nonce") is not None,
            "hasSignedTxHash": bool(local_hash),
            "hasRpcTxHash": status in (
                "pending", "confirmed", "failed", "receipt_unknown",
            ),
            "rpcStatus": status,
            "broadcastAttempted": row.get("consumed_at") is not None,
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-id", required=True)
    parser.add_argument("--draft-id")
    parser.add_argument("--network-id", default=NETWORK_ETHEREUM_MAINNET)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.network_id != NETWORK_ETHEREUM_MAINNET:
        raise SystemExit("only ethereum_mainnet is supported")

    load_dotenv(".env")
    before = _load_rows(args.vault_id, args.network_id, args.draft_id)
    refused = ""
    expired = 0
    if args.apply:
        refused = _repair_refusal_reason(
            before,
            draft_id=args.draft_id,
            is_production=(
                os.getenv("VAULTAI_ENV", "development").lower()
                == "production"
            ),
            ack_value=os.getenv("VAULTAI_MAINNET_REPAIR_ACK", ""),
        )
        if not refused:
            expired = _expire_unsigned(
                args.vault_id,
                args.network_id,
                args.draft_id,
            )
    after = _load_rows(args.vault_id, args.network_id, args.draft_id)
    print(json.dumps({
        "status": "ok",
        "apply": bool(args.apply),
        "refused": refused,
        "expiredUnsignedDrafts": expired,
        "before": _safe_report(before),
        "after": _safe_report(after),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
