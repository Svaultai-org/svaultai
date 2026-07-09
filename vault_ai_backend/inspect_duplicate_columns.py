from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'uploaded_files'
  AND column_name IN ('content_sha256', 'duplicate_of_file_id', 'version_number')
ORDER BY column_name
""")

print(cur.fetchall())

cur.close()
conn.close()
