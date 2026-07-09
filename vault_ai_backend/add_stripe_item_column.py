from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
ALTER TABLE account_subscriptions
ADD COLUMN IF NOT EXISTS stripe_subscription_item_id TEXT;
""")

print("Added/confirmed stripe_subscription_item_id column.")

cur.close()
conn.close()
