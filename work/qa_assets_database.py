"""Migrate/inspect ONLY the explicitly disposable loopback Assets QA database."""
import json
import os
from pathlib import Path
import secrets
import sys

BACKEND = Path(__file__).resolve().parents[1] / "vault_ai_backend"
DATABASE = "svaultai_paxg_transaction_qa"
DSN = "postgresql://svaultai_concierge_tests@127.0.0.1:55438/" + DATABASE
if len(sys.argv) != 2 or sys.argv[1] not in ("migrate", "metadata"):
    raise SystemExit("Use migrate or metadata; no production target is accepted")
safe_environment = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")}
os.environ.clear()
os.environ.update(safe_environment)
os.environ.update({"DATABASE_URL": DSN, "VAULTAI_ENV": "test", "PYTHON_DOTENV_DISABLED": "1",
                   "VAULT_SESSION_SECRET": secrets.token_urlsafe(48), "OPENAI_API_KEY": "isolated-qa-only",
                   "VAULTAI_INTELLIGENCE_UPDATER_ENABLED": "false", "RUN_MIGRATIONS_ON_STARTUP": "false"})
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, "/private/tmp/svaultai-qa-native.hDoW21/python-modules")
os.chdir(BACKEND)
import psycopg2
with psycopg2.connect(DSN) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()")
        assert cursor.fetchone() == (DATABASE, "svaultai_concierge_tests", "127.0.0.1", 55438)
if sys.argv[1] == "migrate":
    from alembic import command
    from alembic.config import Config
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(config, "head")
    print("ISOLATED_ASSETS_MIGRATIONS_COMPLETED")
else:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            head = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM vaults")
            vault_count = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM crypto_mainnet_drafts")
            drafts = cursor.fetchone()[0]
    print(json.dumps({"isolated_local_qa": True, "production": False, "migration_head": head,
                      "vault_count": vault_count, "draft_count": drafts}))
