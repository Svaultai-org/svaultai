from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

url = os.environ["DATABASE_URL"]

conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()

print("[reset] dropping public schema...")
cur.execute("DROP SCHEMA public CASCADE;")

print("[reset] recreating public schema...")
cur.execute("CREATE SCHEMA public;")

print("[reset] granting permissions...")
cur.execute("GRANT ALL ON SCHEMA public TO public;")

cur.close()
conn.close()

print("[reset] done")
