

import os
from logging.config import fileConfig
from urllib.parse import urlparse

from sqlalchemy import engine_from_config, pool, text
from alembic import context
from dotenv import load_dotenv

load_dotenv()

config = context.config

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set; Alembic cannot connect to the database. "
        "Make sure your .env file is present in the backend directory."
    )

                                                                     
if database_url.startswith("postgres://"):
    database_url = "postgresql://" + database_url[len("postgres://"):]

config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

                                                                             
_VERSION_NUM_WIDTH = 128


_DEBUG = os.getenv("VAULTAI_ALEMBIC_DEBUG", "").strip() not in ("", "0", "false", "False")


def _log(label: str, **fields: object) -> None:
    if not _DEBUG:
        return
    payload = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[ALEMBIC] {label} {payload}", flush=True)


def _summarise_url(url: str) -> dict[str, str]:

    try:
        parsed = urlparse(url)
        return {
            "scheme":   parsed.scheme,
            "host":     parsed.hostname or "-",
            "port":     str(parsed.port or "-"),
            "database": (parsed.path or "/").lstrip("/") or "-",
            "user":     parsed.username or "-",
        }
    except Exception as exc:                
        return {"parse_error": type(exc).__name__}


_log("config", mode="offline" if context.is_offline_mode() else "online", **_summarise_url(database_url))


def _ensure_wide_version_table(connection) -> None:
                                                       
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR({_VERSION_NUM_WIDTH}) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
            """
        )
    )
                                                                          
                                                                           
    connection.execute(
        text(
            f"ALTER TABLE alembic_version "
            f"ALTER COLUMN version_num TYPE VARCHAR({_VERSION_NUM_WIDTH})"
        )
    )


def run_migrations_offline() -> None:

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
                                                                         
                                                          
    context.execute(
        f"CREATE TABLE IF NOT EXISTS alembic_version ("
        f"version_num VARCHAR({_VERSION_NUM_WIDTH}) NOT NULL, "
        f"CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:


    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _log("connect", in_transaction=connection.in_transaction())

                                                               
        raw = connection.connection
        try:
            old_autocommit = raw.autocommit
        except Exception:
            old_autocommit = False
        try:
            raw.autocommit = True
            with raw.cursor() as _setc:
                _setc.execute("SET statement_timeout = 0")
                _setc.execute("SET lock_timeout = 0")
                _setc.execute("SET idle_in_transaction_session_timeout = 0")
        finally:
            raw.autocommit = old_autocommit
        _log("timeouts_disabled")

                                                                     
        context.configure(connection=connection, target_metadata=target_metadata)
        _log("configured")

        with context.begin_transaction():
            _log("tx.open", in_transaction=connection.in_transaction())
            _ensure_wide_version_table(connection)
            _log("wide_version_table.ready")
            context.run_migrations()
            _log("run_migrations.done")
                                                                   
                                  
        _log("tx.committed", in_transaction=connection.in_transaction())

        if _DEBUG:
                                                                           
                                                    
            rows = connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
            ).fetchall()
            connection.commit()
            _log("post_migration_tables", count=len(rows), names=",".join(r[0] for r in rows))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
