from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2
import stripe

ACCOUNT_ID = "8c4f3cc4-5f85-464f-b3cf-4cc8021a9d4b"
SUBSCRIPTION_ID = "sub_1TdYeCF0OoeJDRS1Cdvd9Ewf"

stripe.api_key = os.environ["STRIPE_API_KEY"]

print(f"[stripe] retrieving subscription {SUBSCRIPTION_ID}...")
sub = stripe.Subscription.retrieve(SUBSCRIPTION_ID)
print(f"[stripe] retrieve ok status={getattr(sub, 'status', None)!r}")

items = getattr(sub, "items", None)
data = getattr(items, "data", None) if items else None

if not data:
    raise SystemExit("[error] subscription has no items.data")

item = data[0]
item_id = getattr(item, "id", None)

if not item_id:
    raise SystemExit("[error] subscription item has no id")

print(f"[stripe] discovered item_id={item_id!r}")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
cur = conn.cursor()

cur.execute(
    """
    UPDATE account_subscriptions
    SET stripe_subscription_item_id = %s
    WHERE account_id = %s
      AND source_subscription_id = %s
      AND stripe_subscription_item_id IS NULL
    """,
    (item_id, ACCOUNT_ID, SUBSCRIPTION_ID),
)

print(f"[db] UPDATE rowcount={cur.rowcount}")

cur.execute(
    """
    SELECT account_id, source_subscription_id, stripe_subscription_item_id, block_count, status
    FROM account_subscriptions
    WHERE account_id = %s
      AND source_subscription_id = %s
    """,
    (ACCOUNT_ID, SUBSCRIPTION_ID),
)

print("[verify]", cur.fetchone())

cur.close()
conn.close()

print("[done] Backfill complete. Try upgrading to 200GB again.")
