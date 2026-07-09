

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Optional

from psycopg2.extras import RealDictCursor


def _get_conn():
    from vault_core import get_db
    return get_db()


logger = logging.getLogger("backfill_billing_p0")


GRANDFATHER_DAYS = 90


def _load_included_bytes(cur) -> int:


    cur.execute(
        "SELECT value FROM storage_pricing WHERE key = 'included_bytes';"
    )
    row = cur.fetchone()
    return int(row["value"]) if row else 1_073_741_824


def _find_users_needing_account(cur) -> list[str]:


    cur.execute(
        """
        SELECT DISTINCT vn.user_id
        FROM vault_names vn
        WHERE NOT EXISTS (
          SELECT 1 FROM account_members am
          WHERE am.user_id = vn.user_id
        )
        ORDER BY vn.user_id ASC;
        """
    )
    return [str(row["user_id"]) for row in (cur.fetchall() or [])]


def _create_account_for_user(cur, user_id: str) -> str:


    account_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO accounts (
            account_id, account_type, sales_channel,
            billing_owner_user_id
        ) VALUES (%s, 'individual', 'self_service', %s);
        """,
        (account_id, user_id),
    )
    cur.execute(
        """
        INSERT INTO account_members (
            account_id, user_id, role, status
        ) VALUES (%s, %s, 'owner', 'active');
        """,
        (account_id, user_id),
    )
    cur.execute(
        """
        INSERT INTO account_subscriptions (account_id)
        VALUES (%s)
        ON CONFLICT (account_id) DO NOTHING;
        """,
        (account_id,),
    )
    cur.execute(
        """
        INSERT INTO account_storage_totals (account_id, encrypted_bytes)
        VALUES (%s, 0)
        ON CONFLICT (account_id) DO NOTHING;
        """,
        (account_id,),
    )
    return account_id


def _user_total_bytes(cur, user_id: str) -> int:


    cur.execute(
        """
        SELECT COALESCE(SUM(total_bytes), 0)::bigint AS s
        FROM vault_names
        WHERE user_id = %s;
        """,
        (user_id,),
    )
    row = cur.fetchone()
    return int(row["s"]) if row else 0


def _backfill_vault_account_ids(cur, user_id: str, account_id: str) -> int:


    cur.execute(
        """
        UPDATE vault_names
           SET account_id = %s
         WHERE user_id    = %s
           AND account_id IS NULL;
        """,
        (account_id, user_id),
    )
    return cur.rowcount or 0


def _set_account_storage_total(cur, account_id: str, total_bytes: int) -> None:
    cur.execute(
        """
        UPDATE account_storage_totals
           SET encrypted_bytes = %s,
               last_recomputed = NOW()
         WHERE account_id = %s;
        """,
        (max(0, int(total_bytes)), account_id),
    )


def _set_grandfather_grant(
    cur, account_id: str, user_id: str, grant_bytes: int,
) -> None:


    if grant_bytes <= 0:
        return
    cur.execute(
        f"""
        UPDATE account_subscriptions
           SET storage_bytes_grant            = %s,
               storage_bytes_grant_expires_at = NOW() + INTERVAL '{GRANDFATHER_DAYS} days',
               updated_at                     = NOW()
         WHERE account_id = %s;
        """,
        (int(grant_bytes), account_id),
    )
    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, sales_channel,
            from_block_count, to_block_count,
            from_purchased_bytes, to_purchased_bytes,
            occurred_at, payload_jsonb
        )
        VALUES (
            %s, 'admin_grant_added', 'admin_grant', 'self_service',
            0, 0, 0, 0,
            NOW(), %s::jsonb
        );
        """,
        (
            account_id,
                                                                       
                                                                 
            (
                '{"reason":"billing_rollout_grandfather",'
                f'"grant_bytes":{int(grant_bytes)},'
                f'"window_days":{GRANDFATHER_DAYS},'
                f'"user_id":"{user_id}"}}'
            ),
        ),
    )


def run_backfill(*, dry_run: bool = False) -> dict:


    summary = {
        "accounts_created":    0,
        "vaults_repointed":    0,
        "grandfather_grants":  0,
        "total_grant_bytes":   0,
    }
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        included = _load_included_bytes(cur)
        logger.info("included_bytes=%d (1 GB free tier)", included)

        user_ids = _find_users_needing_account(cur)
        logger.info("found %d users without accounts", len(user_ids))

        for user_id in user_ids:
            account_id = _create_account_for_user(cur, user_id)
            summary["accounts_created"] += 1

            repointed = _backfill_vault_account_ids(cur, user_id, account_id)
            summary["vaults_repointed"] += repointed

            used = _user_total_bytes(cur, user_id)
            _set_account_storage_total(cur, account_id, used)

            if used > included:
                grant = used - included
                _set_grandfather_grant(cur, account_id, user_id, grant)
                summary["grandfather_grants"] += 1
                summary["total_grant_bytes"] += grant
                logger.info(
                    "user=%s account=%s used=%d grant=%d (%.2f GB)",
                    user_id, account_id, used, grant, grant / (1024**3),
                )
            else:
                logger.info(
                    "user=%s account=%s used=%d (within free tier)",
                    user_id, account_id, used,
                )

        if dry_run:
            conn.rollback()
            logger.warning("dry-run: rolled back all changes")
        else:
            conn.commit()
            logger.info("backfill committed: %s", summary)
    finally:
        conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot account + subscription backfill for the storage "
            "billing rollout. Idempotent; safe to re-run."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute deltas and log intent without committing.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose per-user logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    summary = run_backfill(dry_run=args.dry_run)
    print(
        "backfill summary: "
        f"accounts_created={summary['accounts_created']} "
        f"vaults_repointed={summary['vaults_repointed']} "
        f"grandfather_grants={summary['grandfather_grants']} "
        f"total_grant_bytes={summary['total_grant_bytes']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
