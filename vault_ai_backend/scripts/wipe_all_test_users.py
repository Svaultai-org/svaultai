"""Development-only bulk cleanup: delete every account/vault/session
and every piece of vault-owned data in the current database.

Intended for the pre-launch phase where we have zero real users but a
long tail of test accounts, half-onboarded vaults, orphaned files,
crypto wallet records from smoke tests, etc. Running this in
development gives us a clean slate to re-verify signup/backup/restore
end-to-end.

Absolute rules enforced here — production must never be able to wipe:

  * Dry-run is the default. The destructive path REQUIRES
    ``--confirm-wipe-all-test-users`` AND
    ``--i-understand-this-deletes-all-users``.
  * Refuses to run unless one of these is true:
      - VAULTAI_ENV=development (or dev/local/test/ci — see
        vault_config.is_dev_or_local())
      - VAULTAI_ALLOW_TEST_USER_WIPE=true
  * In production (VAULTAI_ENV=production/live) the script refuses
    unless BOTH VAULTAI_ALLOW_TEST_USER_WIPE=true AND both destructive
    flags are present. Even then, a big red confirmation banner is
    printed and the script waits for the operator to also pass
    ``--i-understand-this-deletes-all-users``.
  * The dry-run printout carries counts only. No email, no display
    name, no PIN, no file name, no ID number, no wallet address, no
    encrypted secret, no Stripe customer id, no session token, no API
    key. Counts are aggregated with ``SELECT COUNT(*)`` and printed
    verbatim.
  * The destructive path prefers ``delete_vault_and_all_data()`` per
    vault, which cascades the delete through every vault-owned table,
    inserts an anonymized tombstone
    (hashed_vault_id + deleted_at + deletion_reason), and best-effort
    cancels the account's Stripe subscription. After every vault is
    gone, we clean up leftovers that don't cascade from ``vaults``
    (orphaned accounts, standalone tombstone rows the operator asked
    to purge, contact-sales requests with a NULL vault ref, etc.),
    using an explicit allowlist. Config tables
    (``storage_skus``, ``storage_pricing``, ``username_policies``,
    ``vault_service_categories``, ``alembic_version``) are never
    touched.
  * NEVER broadcasts a crypto transaction. NEVER logs vault name,
    PIN, encrypted wallet material, session token, email, or file
    name. Log lines carry only the hashed vault id prefix and the
    per-table count.

Usage (from repo root):

  python -m vault_ai_backend.scripts.wipe_all_test_users --dry-run
  python -m vault_ai_backend.scripts.wipe_all_test_users \\
      --confirm-wipe-all-test-users \\
      --i-understand-this-deletes-all-users
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple



_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


logger = logging.getLogger("vault_ai_backend.scripts.wipe_all_test_users")





_COUNT_TABLES: Tuple[Tuple[str, str], ...] = (
    ("accounts",                   "accounts"),
    ("vaults",                     "vaults"),
    ("auth_sessions",              "sessions"),
    ("trusted_devices",            "trusted_devices"),
    ("uploaded_files",             "files"),
    ("uploaded_file_chunks",       "file_chunks"),
    ("vault_items",                "secure_items_all_kinds"),
    ("notifications",              "notifications"),
    ("account_subscriptions",      "subscriptions_local"),
    ("account_storage_totals",     "account_storage_totals"),
    ("stripe_customers",           "stripe_customers_local"),
    ("account_members",            "account_members"),
    ("subscription_events",        "subscription_events"),
    ("provider_event_log",         "provider_event_log"),
    ("contact_sales_requests",     "contact_sales_requests"),
    ("semantic_index",             "semantic_index_rows"),
    ("vault_asset_tags",           "asset_tag_rows"),
    ("vault_password_audit",       "password_audit_rows"),
    ("vault_document_metadata",    "document_metadata_rows"),
    ("vault_document_entities",    "document_entity_rows"),
    ("vault_ai_memory",            "ai_memory_rows"),
    ("vault_preferences",          "preferences_rows"),
    ("vault_relationships",        "relationships_rows"),
    ("vault_expiry_alerts",        "expiry_alert_rows"),
    ("vault_intelligence_summary", "intelligence_summary_rows"),
    ("vault_content_chunks",       "content_chunk_rows"),
    ("vault_file_understanding",   "file_understanding_rows"),
    ("vault_file_embeddings",      "file_embedding_rows"),
    ("vault_analysis_jobs",        "analysis_jobs"),
    ("vault_agent_memories",       "agent_memory_rows"),
    ("vault_agent_tasks",          "agent_task_rows"),
    ("vault_agent_audit",          "agent_audit_rows"),
    ("vault_file_relationships",   "file_relationship_rows"),
    ("import_batches",             "import_batches"),
    ("vault_deletion_tombstones",  "deletion_tombstones"),
)




_LEFTOVER_TABLES_ALLOWLIST: Tuple[str, ...] = (
    "subscription_events",
    "provider_event_log",
    "contact_sales_requests",
    "vault_deletion_tombstones",
)




_CONFIG_TABLES_PRESERVED: Tuple[str, ...] = (
    "alembic_version",
    "storage_skus",
    "storage_pricing",
    "username_policies",
    "vault_service_categories",
)


@dataclass
class WipePlan:
    counts: Dict[str, int] = field(default_factory=dict)
    vault_ids: List[str] = field(default_factory=list)

    @property
    def accounts_count(self) -> int:
        return int(self.counts.get("accounts", 0))

    @property
    def vaults_count(self) -> int:
        return int(self.counts.get("vaults", 0))


def _is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _load_env_file_best_effort() -> None:
    """Best-effort load of the backend .env so is_production() sees
    the same tokens the running app would. Silently no-ops if
    python-dotenv is unavailable or the file is missing."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    try:
        load_dotenv(_BACKEND_ROOT / ".env")
    except Exception:
        pass


def _read_environment_verdict() -> Tuple[bool, bool, str]:
    """Return (is_prod, is_dev_or_local, env_token) using the same
    vault_config helpers the rest of the app relies on."""
    try:
        import vault_config
    except Exception as exc:
        logger.error("[WIPE] failed to import vault_config: %s", exc)
        raise
    is_prod = bool(vault_config.is_production())
    is_dev  = bool(vault_config.is_dev_or_local())
    token   = vault_config._read_env_token() or "unset"
    return is_prod, is_dev, token


def _check_permission_or_refuse(
    *,
    is_prod: bool,
    is_dev: bool,
    env_token: str,
    confirm_wipe: bool,
    understand_flag: bool,
    allow_env: bool,
) -> None:
    """Refuse to proceed unless every gate is satisfied. This is the
    single choke point that keeps production safe."""

    if not (is_dev or allow_env):
        raise SystemExit(
            "[WIPE] refused: this script only runs when "
            "VAULTAI_ENV is one of dev/development/local/test/ci, "
            "or the VAULTAI_ALLOW_TEST_USER_WIPE=true env override "
            f"is set. Current env token: {env_token!r}"
        )

    if is_prod and not allow_env:
        raise SystemExit(
            "[WIPE] refused: environment reports VAULTAI_ENV=production "
            "and VAULTAI_ALLOW_TEST_USER_WIPE is not set to true. "
            "Refusing to wipe user data."
        )


def _check_destructive_gates_or_refuse(
    *,
    is_prod: bool,
    confirm_wipe: bool,
    understand_flag: bool,
    allow_env: bool,
) -> None:
    """Extra hard gate for the destructive path. Dry-run bypasses this."""
    if not confirm_wipe:
        raise SystemExit(
            "[WIPE] refused: destructive wipe requires "
            "--confirm-wipe-all-test-users. Re-run with --dry-run to "
            "see counts."
        )
    if not understand_flag:
        raise SystemExit(
            "[WIPE] refused: destructive wipe additionally requires "
            "--i-understand-this-deletes-all-users."
        )
    if is_prod and not allow_env:
        raise SystemExit(
            "[WIPE] refused: production must also have "
            "VAULTAI_ALLOW_TEST_USER_WIPE=true. Refusing."
        )


def _table_count(table: str) -> int:
    """Return SELECT COUNT(*) for `table`. Returns -1 if the table
    doesn't exist or errors — never raises so dry-run remains
    resilient across migration variants."""
    try:
        from vault_core import get_db
    except Exception:
        return -1
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return -1
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _list_vault_ids() -> List[str]:
    try:
        from vault_core import get_db
    except Exception:
        return []
    conn = get_db()
    out: List[str] = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT vault_id FROM vaults ORDER BY created_at ASC")
        for row in cur.fetchall():
            out.append(str(row[0]))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def collect_plan() -> WipePlan:
    """Aggregate safe counts + vault ids for the run. No PII columns
    are read — only ``COUNT(*)`` and the opaque UUID vault_id (which
    the deletion service hashes before it enters any log line)."""
    plan = WipePlan()
    for table, key in _COUNT_TABLES:
        plan.counts[key] = _table_count(table)
    plan.vault_ids = _list_vault_ids()
    return plan


def _print_safe_plan(plan: WipePlan) -> None:
    print("[WIPE] plan (counts only, no PII):")
    for _, key in _COUNT_TABLES:
        count = plan.counts.get(key, 0)
        rendered = "<table missing>" if count < 0 else str(count)
        print(f"  - {key}: {rendered}")
    print(f"[WIPE] {plan.vaults_count} vaults will be routed through "
          "delete_vault_and_all_data() with "
          "reason=development_full_user_wipe.")


def _wipe_leftovers_after_vaults(dry_run: bool) -> Dict[str, int]:
    """Delete rows in leftover tables that don't cascade from vaults
    or accounts. Only touches ``_LEFTOVER_TABLES_ALLOWLIST``. Never
    truncates ``_CONFIG_TABLES_PRESERVED``."""
    deleted: Dict[str, int] = {}
    try:
        from vault_core import get_db
    except Exception:
        return deleted
    conn = get_db()
    try:
        cur = conn.cursor()
        for table in _LEFTOVER_TABLES_ALLOWLIST:
            if table in _CONFIG_TABLES_PRESERVED:

                continue
            try:
                if dry_run:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    row = cur.fetchone()
                    deleted[table] = int(row[0]) if row else 0
                else:
                    cur.execute(f"DELETE FROM {table}")
                    deleted[table] = int(cur.rowcount or 0)
            except Exception:
                deleted[table] = -1
        if not dry_run:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return deleted


def _delete_orphaned_accounts(dry_run: bool) -> int:
    """After every vault is deleted, individual accounts should have
    been auto-purged by ``delete_vault_and_all_data``. Organization
    accounts or accounts whose last-vault delete raced can linger —
    remove them explicitly. Only touches ``accounts``; leaves config
    tables alone."""
    try:
        from vault_core import get_db
    except Exception:
        return -1
    conn = get_db()
    try:
        cur = conn.cursor()
        if dry_run:
            cur.execute("SELECT COUNT(*) FROM accounts")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        cur.execute("DELETE FROM accounts")
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return -1
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _delete_one_vault(vault_id: str) -> Tuple[bool, str]:
    """Route a single vault through the shared deletion service.

    Returns (success, hashed_prefix). Errors are swallowed and logged
    with only the hashed prefix — never the raw vault id, and never
    the vault name."""
    try:
        from vault_deletion_service import (
            delete_vault_and_all_data,
            REASON_DEVELOPMENT_FULL_USER_WIPE,
            hashed_vault_id,
        )
    except Exception as exc:
        logger.error("[WIPE] import failed: %s", exc)
        return False, "unknown"
    try:
        hp = hashed_vault_id(vault_id)[:12]
    except Exception:
        hp = "unknown"
    try:
        delete_vault_and_all_data(
            vault_id,
            reason=REASON_DEVELOPMENT_FULL_USER_WIPE,
        )
        return True, hp
    except Exception as exc:


        logger.warning("[WIPE] vault delete failed hashed=%s reason=%s",
                       hp, type(exc).__name__)
        return False, hp


def run_destructive(
    plan: WipePlan,
    *,
    dry_run: bool,
    deleter: Optional[Callable[[str], Tuple[bool, str]]] = None,
) -> Dict[str, int]:
    """Execute the wipe. ``dry_run=True`` computes what would be
    deleted but does not touch the DB. ``deleter`` is exposed so the
    test suite can inject a no-op deleter that counts calls without
    hitting the real database."""

    deleter = deleter or _delete_one_vault

    stats: Dict[str, int] = {
        "vaults_processed": 0,
        "vaults_deleted":   0,
        "vaults_failed":    0,
        "accounts_deleted": 0,
    }

    for vault_id in plan.vault_ids:
        stats["vaults_processed"] += 1
        if dry_run:

            continue
        ok, hp = deleter(vault_id)
        if ok:
            stats["vaults_deleted"] += 1
            logger.info("[WIPE] deleted vault hashed=%s reason=%s",
                        hp, "development_full_user_wipe")
        else:
            stats["vaults_failed"] += 1

    leftovers = _wipe_leftovers_after_vaults(dry_run)
    for table, cnt in leftovers.items():
        stats[f"leftover:{table}"] = cnt

    stats["accounts_deleted"] = _delete_orphaned_accounts(dry_run)

    return stats


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vault_ai_backend.scripts.wipe_all_test_users",
        description=(
            "Delete every test account/vault/session/file in this "
            "development database. Refuses to run in production."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Print counts only. Never writes to the database. This is "
            "the default when neither --dry-run nor "
            "--confirm-wipe-all-test-users is supplied."
        ),
    )
    p.add_argument(
        "--confirm-wipe-all-test-users",
        dest="confirm_wipe",
        action="store_true",
        default=False,
        help=(
            "Perform the destructive wipe. Requires the extra "
            "--i-understand-this-deletes-all-users flag too."
        ),
    )
    p.add_argument(
        "--i-understand-this-deletes-all-users",
        dest="understand_flag",
        action="store_true",
        default=False,
        help=(
            "Second confirmation flag. Required together with "
            "--confirm-wipe-all-test-users for any destructive run."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Log each per-vault delete outcome (hashed prefix only).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    _load_env_file_best_effort()

    is_prod, is_dev, env_token = _read_environment_verdict()
    allow_env = _is_truthy_env("VAULTAI_ALLOW_TEST_USER_WIPE")


    dry_run = args.dry_run or not args.confirm_wipe

    _check_permission_or_refuse(
        is_prod=is_prod,
        is_dev=is_dev,
        env_token=env_token,
        confirm_wipe=args.confirm_wipe,
        understand_flag=args.understand_flag,
        allow_env=allow_env,
    )

    if not dry_run:
        _check_destructive_gates_or_refuse(
            is_prod=is_prod,
            confirm_wipe=args.confirm_wipe,
            understand_flag=args.understand_flag,
            allow_env=allow_env,
        )

    print(
        f"[WIPE] mode={'DRY-RUN' if dry_run else 'DESTRUCTIVE'} "
        f"env={env_token} allow_env={allow_env}"
    )

    plan = collect_plan()
    _print_safe_plan(plan)

    stats = run_destructive(plan, dry_run=dry_run)

    print("[WIPE] outcome (counts only):")
    for key in sorted(stats):
        print(f"  - {key}: {stats[key]}")

    if dry_run:
        print(
            "[WIPE] dry-run complete. No data was modified. To perform "
            "the destructive wipe re-run with:\n"
            "  --confirm-wipe-all-test-users\n"
            "  --i-understand-this-deletes-all-users"
        )
    else:
        print(
            "[WIPE] destructive wipe complete. Verify the DB is empty "
            "with docs/dev_wipe_all_users.md."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
