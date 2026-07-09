from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'account_subscriptions'
ORDER BY ordinal_position
""")

print("account_subscriptions columns:")
for row in cur.fetchall():
    print(row[0])

cur.close()
conn.close()
