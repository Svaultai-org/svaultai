from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

customers = [
    "cus_Ucng0adF3YSTbM",
    "cus_UcCU7DSogBfpnn",
    "cus_UcBrUGOdR2Nelg",
    "cus_UcAXiiSA5xWzLv",
]

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute(
    """
    SELECT
        sc.account_id,
        sc.stripe_customer_id,
        s.source_subscription_id,
        s.status,
        s.block_count,
        s.purchased_bytes,
        s.current_period_end
    FROM stripe_customers sc
    LEFT JOIN account_subscriptions s
        ON s.account_id = sc.account_id
    WHERE sc.stripe_customer_id = ANY(%s)
    ORDER BY s.block_count DESC NULLS LAST
    """,
    (customers,),
)

rows = cur.fetchall()

for row in rows:
    print(row)

cur.close()
conn.close()
