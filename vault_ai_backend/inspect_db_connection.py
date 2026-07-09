from dotenv import load_dotenv
load_dotenv(".env")

import os
import psycopg2

url = os.environ["DATABASE_URL"]
print("DATABASE_URL from .env:", url[:40] + "...")

conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute("select current_database(), current_schema(), inet_server_addr(), inet_server_port()")
print("connected to:", cur.fetchone())

cur.close()
conn.close()
