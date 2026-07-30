"""Grant or revoke a short-lived QA Crypto Vault entitlement.

This is an operator-only CLI, not an HTTP endpoint. It uses the same
account_subscriptions row that production billing uses, targets only an
opaque account_id, and writes subscription_events for audit.

Usage:
    python scripts/grant_qa_crypto_entitlement.py --account-id UUID --ttl-minutes 120 --apply
    python scripts/grant_qa_crypto_entitlement.py --account-id UUID --revoke --apply

In production, --apply also requires:
    VAULTAI_ALLOW_PRODUCTION_QA_CRYPTO_ENTITLEMENT=true
    --i-understand-production-qa-entitlement
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from billing import block_bytes  # noqa: E402
from vault_config import is_production  # noqa: E402
from vault_core import get_db  # noqa: E402


QA_REASON = "qa_crypto_canary"
PRODUCTION_ACK_ENV = "VAULTAI_ALLOW_PRODUCTION_QA_CRYPTO_ENTITLEMENT"


def _parse_account_id(raw: str) -> str:
    try:
        return str(uuid.UUID(str(raw).strip()))
    except Exception as exc:
        raise argparse.ArgumentTypeError("account_id must be a UUID") from exc


def _short(value: str) -> str:
    return f"{value[:8]}..."


def _env_truthy(name: str) -> bool:
    import os
    return os.getenv(name, "").strip().lower() in {
        "1", "true", "yes", "on", "y",
    }


def _check_operator_gate(*, apply: bool, production_ack: bool) -> None:
    if not apply:
        return
    if not is_production():
        return
    if not production_ack or not _env_truthy(PRODUCTION_ACK_ENV):
        raise PermissionError(
            "production_apply_requires_explicit_qa_entitlement_ack"
        )


def grant(account_id: str, ttl_minutes: int, *, apply: bool) -> dict:
    if ttl_minutes < 5 or ttl_minutes > 24 * 60:
        raise ValueError("ttl_minutes must be between 5 and 1440")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT account_id FROM accounts WHERE account_id = %s",
            (account_id,),
        )
        if cur.fetchone() is None:
            raise LookupError("account_not_found")

        cur.execute(
            """
            SELECT status, source, block_count, purchased_bytes,
                   metadata_jsonb
              FROM account_subscriptions
             WHERE account_id = %s
             FOR UPDATE
            """,
            (account_id,),
        )
        before = cur.fetchone() or {}
        before_source = str(before.get("source") or "none")
        before_blocks = int(before.get("block_count") or 0)
        before_bytes = int(before.get("purchased_bytes") or 0)

        if before_source not in ("none", "admin_grant") and before_blocks > 0:
            raise PermissionError("refusing_to_overwrite_non_qa_subscription")

        source_subscription_id = (
            f"qa_crypto_canary:{account_id[:8]}:"
            f"{uuid.uuid4().hex[:16]}"
        )
        bytes_per_block = int(block_bytes())
        payload = {
            "reason": QA_REASON,
            "ttl_minutes": int(ttl_minutes),
            "script": "grant_qa_crypto_entitlement",
        }

        if apply:
            cur.execute(
                """
                INSERT INTO account_subscriptions (
                    account_id, status, source, source_subscription_id,
                    stripe_subscription_item_id, billing_period,
                    block_count, purchased_bytes, storage_bytes_grant,
                    storage_bytes_grant_expires_at,
                    current_period_start, current_period_end,
                    cancel_at_period_end, canceled_at,
                    grace_period_ends_at, over_quota_grace_ends_at,
                    metadata_jsonb, updated_at
                )
                VALUES (
                    %s, 'active', 'admin_grant', %s,
                    NULL, 'monthly',
                    1, %s, 0,
                    NULL,
                    NOW(), NOW() + (%s * INTERVAL '1 minute'),
                    FALSE, NULL,
                    NULL, NULL,
                    %s, NOW()
                )
                ON CONFLICT (account_id) DO UPDATE
                  SET status                         = EXCLUDED.status,
                      source                         = EXCLUDED.source,
                      source_subscription_id         = EXCLUDED.source_subscription_id,
                      stripe_subscription_item_id    = NULL,
                      billing_period                 = EXCLUDED.billing_period,
                      block_count                    = EXCLUDED.block_count,
                      purchased_bytes                = EXCLUDED.purchased_bytes,
                      storage_bytes_grant            = 0,
                      storage_bytes_grant_expires_at = NULL,
                      current_period_start           = EXCLUDED.current_period_start,
                      current_period_end             = EXCLUDED.current_period_end,
                      cancel_at_period_end           = FALSE,
                      canceled_at                    = NULL,
                      grace_period_ends_at           = NULL,
                      over_quota_grace_ends_at       = NULL,
                      metadata_jsonb                 = EXCLUDED.metadata_jsonb,
                      updated_at                     = NOW()
                RETURNING current_period_start, current_period_end;
                """,
                (
                    account_id,
                    source_subscription_id,
                    bytes_per_block,
                    int(ttl_minutes),
                    Json(payload),
                ),
            )
            period = cur.fetchone() or {}
            cur.execute(
                """
                INSERT INTO subscription_events (
                    account_id, event_type, source, source_event_id,
                    sales_channel, from_block_count, to_block_count,
                    from_purchased_bytes, to_purchased_bytes,
                    occurred_at, payload_jsonb
                )
                VALUES (
                    %s, 'qa_crypto_entitlement_granted', 'admin_grant',
                    %s, 'self_service', %s, 1, %s, %s, NOW(), %s
                )
                """,
                (
                    account_id,
                    source_subscription_id,
                    before_blocks,
                    before_bytes,
                    bytes_per_block,
                    Json(payload),
                ),
            )
            conn.commit()
        else:
            period = {"current_period_start": None, "current_period_end": None}
            conn.rollback()

        return {
            "action": "grant",
            "applied": bool(apply),
            "account_id_prefix": _short(account_id),
            "entitlement_type": "admin_grant_storage_block",
            "block_count": 1,
            "grant_time": (
                period.get("current_period_start").isoformat()
                if period.get("current_period_start") else None
            ),
            "expiry_time": (
                period.get("current_period_end").isoformat()
                if period.get("current_period_end") else None
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke(account_id: str, *, apply: bool) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT status, source, block_count, purchased_bytes,
                   metadata_jsonb
              FROM account_subscriptions
             WHERE account_id = %s
             FOR UPDATE
            """,
            (account_id,),
        )
        before = cur.fetchone()
        if before is None:
            raise LookupError("subscription_row_not_found")
        metadata = before.get("metadata_jsonb") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if (
            str(before.get("source") or "") != "admin_grant"
            or metadata.get("reason") != QA_REASON
        ):
            raise PermissionError("refusing_to_revoke_non_qa_grant")

        before_blocks = int(before.get("block_count") or 0)
        before_bytes = int(before.get("purchased_bytes") or 0)
        source_event_id = f"qa_crypto_canary_revoke:{account_id[:8]}:{uuid.uuid4().hex[:16]}"
        payload = {
            "reason": QA_REASON,
            "script": "grant_qa_crypto_entitlement",
        }

        if apply:
            cur.execute(
                """
                UPDATE account_subscriptions
                   SET status                         = 'none',
                       source                         = 'none',
                       source_subscription_id         = NULL,
                       stripe_subscription_item_id    = NULL,
                       billing_period                 = NULL,
                       block_count                    = 0,
                       purchased_bytes                = 0,
                       storage_bytes_grant            = 0,
                       storage_bytes_grant_expires_at = NULL,
                       current_period_start           = NULL,
                       current_period_end             = NULL,
                       cancel_at_period_end           = FALSE,
                       canceled_at                    = NULL,
                       grace_period_ends_at           = NULL,
                       over_quota_grace_ends_at       = NULL,
                       metadata_jsonb                 = '{}'::jsonb,
                       updated_at                     = NOW()
                 WHERE account_id = %s
                """,
                (account_id,),
            )
            cur.execute(
                """
                INSERT INTO subscription_events (
                    account_id, event_type, source, source_event_id,
                    sales_channel, from_block_count, to_block_count,
                    from_purchased_bytes, to_purchased_bytes,
                    occurred_at, payload_jsonb
                )
                VALUES (
                    %s, 'qa_crypto_entitlement_revoked', 'admin_grant',
                    %s, 'self_service', %s, 0, %s, 0, NOW(), %s
                )
                """,
                (
                    account_id,
                    source_event_id,
                    before_blocks,
                    before_bytes,
                    Json(payload),
                ),
            )
            conn.commit()
        else:
            conn.rollback()

        return {
            "action": "revoke",
            "applied": bool(apply),
            "account_id_prefix": _short(account_id),
            "revocation_result": "revoked" if apply else "dry_run",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True, type=_parse_account_id)
    parser.add_argument("--ttl-minutes", type=int, default=120)
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--i-understand-production-qa-entitlement",
        action="store_true",
        help=(
            "Required with --apply when VAULTAI_ENV is production/live. "
            "This confirms an operator is intentionally granting or "
            "revoking a short-lived QA entitlement for one account UUID."
        ),
    )
    args = parser.parse_args()

    _check_operator_gate(
        apply=args.apply,
        production_ack=bool(args.i_understand_production_qa_entitlement),
    )

    result = (
        revoke(args.account_id, apply=args.apply)
        if args.revoke
        else grant(args.account_id, args.ttl_minutes, apply=args.apply)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
