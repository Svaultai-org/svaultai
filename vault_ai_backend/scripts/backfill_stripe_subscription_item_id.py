

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

                                                                      
_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv              

load_dotenv(_BACKEND_ROOT / ".env")
load_dotenv()

import stripe              
from psycopg2.extras import RealDictCursor              

from vault_core import get_db              
from stripe_service import (              
    StripeUnconfiguredError,
    _extract_subscription_item_id,
    _stripe_initialized,
)


def _resolve_subscription_id(account_id: str) -> Optional[str]:


    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT source_subscription_id,
                   stripe_subscription_item_id,
                   block_count,
                   status,
                   source
              FROM account_subscriptions
             WHERE account_id = %s
             LIMIT 1;
            """,
            (account_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        print(f"[lookup] no account_subscriptions row for "
              f"account_id={account_id!r}")
        return None
    if (row.get("source") or "").lower() != "stripe":
        print(f"[lookup] account_subscriptions.source = "
              f"{row.get('source')!r}, not 'stripe'. Refusing to backfill.")
        return None
    sub_id = row.get("source_subscription_id")
    if not sub_id:
        print("[lookup] account_subscriptions.source_subscription_id is "
              "NULL — there's no Stripe sub to backfill from.")
        return None
    print(
        "[lookup] account_subscriptions row found "
        f"account_id={account_id!r} "
        f"source_subscription_id={sub_id!r} "
        f"current_item_id={row.get('stripe_subscription_item_id')!r} "
        f"block_count={row.get('block_count')} "
        f"status={row.get('status')!r}"
    )
    return str(sub_id)


def _read_item_id_after_update(
    account_id: str, sub_id: str,
) -> Optional[str]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT stripe_subscription_item_id "
            "  FROM account_subscriptions "
            " WHERE account_id = %s AND source_subscription_id = %s;",
            (account_id, sub_id),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Populate account_subscriptions.stripe_subscription_item_id "
            "from Stripe for a single account."
        ),
    )
    parser.add_argument(
        "--account-id",
        required=True,
        help="VaultAI accounts.account_id (UUID).",
    )
    parser.add_argument(
        "--subscription-id",
        default=None,
        help=(
            "Stripe subscription id (sub_...). Optional — defaults to "
            "the value of account_subscriptions.source_subscription_id "
            "for the account."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch the subscription and print the discovered item id "
            "but do NOT touch the database."
        ),
    )
    args = parser.parse_args()

    if not _stripe_initialized():
        print(
            "[fatal] STRIPE_API_KEY not configured. Put it in the "
            "backend .env file."
        )
        return 2

                       
    sub_id = args.subscription_id or _resolve_subscription_id(args.account_id)
    if not sub_id:
        return 1

                             
    print(f"[stripe] retrieving subscription {sub_id}...")
    try:
        sub = stripe.Subscription.retrieve(sub_id)
    except stripe.StripeError as exc:
        print(f"[fatal] Stripe error: {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:
        print(f"[fatal] retrieve failed: {type(exc).__name__}: {exc}")
        return 1
    sub_status = getattr(sub, "status", None)
    print(f"[stripe] retrieve ok status={sub_status!r}")

                        
    item_id = _extract_subscription_item_id(sub)
    if not item_id:
        print("[fatal] subscription has no items.data[0].id — bailing.")
        return 1
    print(f"[stripe] discovered item_id={item_id!r}")

    if args.dry_run:
        print("[dry-run] would UPDATE account_subscriptions "
              f"SET stripe_subscription_item_id = {item_id!r} "
              f"WHERE account_id = {args.account_id!r} "
              f"AND source_subscription_id = {sub_id!r} "
              "AND stripe_subscription_item_id IS NULL")
        print("[dry-run] nothing was written.")
        return 0

               
    print("[db] applying UPDATE...")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE account_subscriptions
               SET stripe_subscription_item_id = %s,
                   updated_at                  = NOW()
             WHERE account_id                  = %s
               AND source_subscription_id      = %s
               AND stripe_subscription_item_id IS NULL;
            """,
            (item_id, args.account_id, sub_id),
        )
        rowcount = cur.rowcount
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[fatal] DB UPDATE failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        conn.close()
    print(f"[db] UPDATE committed (rowcount={rowcount})")
    if rowcount == 0:
        print(
            "[note] rowcount=0 means the row's stripe_subscription_item_id "
            "was already populated (race with webhook?) OR the "
            "(account_id, sub_id) pair did not match any row. Verifying..."
        )

               
    actual = _read_item_id_after_update(args.account_id, sub_id)
    if actual == item_id:
        print(f"[verify] OK — stripe_subscription_item_id = {actual!r}")
        print("[verify] Next click on 200 GB will skip backfill and go "
              "straight to SubscriptionItem.modify.")
        return 0
    print(
        f"[verify] MISMATCH — stripe_subscription_item_id = {actual!r} "
        f"(expected {item_id!r})."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
