from vault_core import get_db

c = get_db()
cur = c.cursor()

cur.execute("""
SELECT
    pid,
    state,
    wait_event_type,
    wait_event,
    query
FROM pg_stat_activity
WHERE datname = current_database()
AND state != 'idle';
""")

rows = cur.fetchall()

for row in rows:
    print(row)

c.close()
