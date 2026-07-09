from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
SELECT
  vault_id,
  vault_name,
  display_username,
  failed_pin_attempts,
  locked_until,
  kdf_iterations,
  kdf_algorithm,
  acknowledged_irrecoverable,
  created_at
FROM vaults
ORDER BY created_at DESC
""")

rows = cur.fetchall()

print("vaults:")
for row in rows:
    print(row)

cur.close()
conn.close()
