from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name
""")

rows = cur.fetchall()

print("tables:")
for row in rows:
    print(row[0])

cur.close()
conn.close()
