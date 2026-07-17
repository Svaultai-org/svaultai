"""
Focused validation for migration ``0025_auth_session_hardening``.

Every test in this file requires a disposable PostgreSQL 17 available
at ``VAULTAI_TEST_DATABASE_URL``. Tests self-skip when the variable
is unset, so the file is safe to collect on Windows dev boxes.

Test coverage
-------------

Structure (item C of the Step B.2 acceptance):
  * ``TestSchemaStructure`` — every new column exists with the
    expected data type / nullability / default; both CHECK
    constraints installed on ``auth_sessions``; all three new
    indexes present with correct predicates; ``vault_security_events``
    exists with the expected columns, FK, defaults, and CHECKs.

Constraint enforcement (items G, H, I):
  * ``TestConstraintEnforcement`` — INSERTs with the illegal
    values fail with ``CheckViolation``; legal values succeed.

Single-session invariant (items E, F):
  * ``TestSingleSessionIndex`` — direct second unrevoked INSERT
    fails with ``UniqueViolation``; revoking then re-INSERTing works.

Deterministic backfill (item D):
  * ``TestBackfillScenarios`` — seeds five representative fixtures
    at 0024, runs the 0025 upgrade, asserts the resulting
    ``auth_sessions`` state for each fixture:
        (1) multi-unrevoked-per-vault → newest kept, others revoked
        (2) issued_at tie broken by token_id DESC
        (3) newest is already expired → all revoked
        (4) exactly one non-expired unrevoked row → kept as-is
        (5) only expired rows → all revoked

Security-events emission (item J):
  * ``TestMigrationEventEmission`` — exactly one event of type
    'single-session-migration' per affected vault; NO event for a
    vault that had zero active sessions to begin with; row content
    respects the length CHECKs.

Alembic surface (items A, B, K, L, M):
  * ``TestAlembicSurface``
        A: ``upgrade`` from 0024 → 0025 succeeds
        B: ``current`` returns exactly ``0025_auth_session_hardening``
        K: idempotency in the Alembic sense — a second
           ``upgrade head`` is a no-op that does not error
        L: ``downgrade`` back to 0024 succeeds structurally (all
           new objects gone, all pre-existing objects intact)
        M: re-``upgrade`` from 0024 → 0025 succeeds a second time
           and yields the same schema shape

Nothing in this file touches the production database, production.env,
or any container. Every DDL/DML runs against the disposable Postgres
identified by ``VAULTAI_TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import pathlib
import unittest
import uuid
from typing import List, Optional, Tuple

_REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parent

_MIGRATION_HEAD = "0025_auth_session_hardening"
_MIGRATION_PREV = "0024_vault_metadata_encryption"


def _skip_if_no_test_db() -> None:
    if not os.environ.get("VAULTAI_TEST_DATABASE_URL", "").strip():
        raise unittest.SkipTest(
            "VAULTAI_TEST_DATABASE_URL not set; migration 0025 tests require "
            "a disposable PostgreSQL 17."
        )


def _connect():
    """Return a fresh psycopg2 connection to VAULTAI_TEST_DATABASE_URL."""
    import psycopg2
    return psycopg2.connect(os.environ["VAULTAI_TEST_DATABASE_URL"])


def _alembic_config():
    """Return an Alembic ``Config`` pointed at this repo's alembic.ini
    with DATABASE_URL overridden to VAULTAI_TEST_DATABASE_URL so the
    project's ``env.py`` reads it correctly."""
    from alembic.config import Config
    os.environ["DATABASE_URL"] = os.environ["VAULTAI_TEST_DATABASE_URL"]
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    # env.py reads DATABASE_URL from os.environ.
    return cfg


def _upgrade_to(revision: str) -> None:
    from alembic import command
    command.upgrade(_alembic_config(), revision)


def _downgrade_to(revision: str) -> None:
    from alembic import command
    command.downgrade(_alembic_config(), revision)


def _reset_to_0024() -> None:
    """Bring the disposable DB to the 0024 head.

    * If the DB is empty, run ``upgrade 0024``.
    * If already at 0025 (from a prior test), ``downgrade 0024``.
    * If already at 0024, no-op.

    Also TRUNCATE any data in ``auth_sessions`` and ``vaults`` so
    each backfill test starts from a clean slate; the events table
    (if it exists — the 0025 downgrade drops it) is dropped as part
    of ``downgrade 0024``.
    """
    _upgrade_to("head")
    # If we're at 0025, roll back to 0024.
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version;")
        row = cur.fetchone()
        current = row[0] if row else None
    finally:
        conn.close()
    if current == _MIGRATION_HEAD:
        _downgrade_to(_MIGRATION_PREV)

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "TRUNCATE auth_sessions, vaults, accounts RESTART IDENTITY CASCADE;"
        )
        conn.commit()
    finally:
        conn.close()


def _insert_account(cur, *, account_id: Optional[str] = None) -> str:
    aid = account_id or str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO accounts (account_id, account_type, sales_channel)
        VALUES (%s, 'individual', 'self_service')
        RETURNING account_id
        """,
        (aid,),
    )
    return str(cur.fetchone()[0])


def _insert_vault(cur, *, account_id: str, vault_id: Optional[str] = None,
                  vault_name: Optional[str] = None) -> str:
    """Insert a minimal, constraint-valid vault row.

    Satisfies every CHECK on the `vaults` table at this point in the
    migration history (through 0024):

      * ``vault_name`` UNIQUE + length 1..200 — deterministic 18-char slug.
      * ``pin_salt`` / ``pin_verifier`` NOT NULL TEXT — empty strings.
      * ``kdf_iterations`` >= 100000 — default column value.
      * ``vaults_zk_state_consistency_check`` (added in 0023) — requires
        (vault_handle, opaque_registration_record, wrapped_mvk) all-NULL
        OR all-NON-NULL. This fixture picks the legacy shape (all NULL)
        because the migration tests only need the row to exist as an FK
        target for ``auth_sessions``; producing a ZK-adopted row would
        require inserting three additional byte blobs and would not
        exercise anything the tests care about. ``vault_handle`` etc.
        are therefore omitted so PostgreSQL defaults them to NULL.
    """
    vid = vault_id or str(uuid.uuid4())
    vname = vault_name or f"vault-{uuid.uuid4().hex[:12]}"
    cur.execute(
        """
        INSERT INTO vaults (
            vault_id, vault_name, pin_salt, pin_verifier,
            account_id, acknowledged_irrecoverable
        ) VALUES (
            %s, %s, '', '',
            %s, TRUE
        )
        RETURNING vault_id
        """,
        (vid, vname, account_id),
    )
    return str(cur.fetchone()[0])


def _insert_session(
    cur, *, vault_id: str,
    issued_at: str = "NOW()", expires_at: str = "NOW() + INTERVAL '1 hour'",
    revoked_at: Optional[str] = None, token_id: Optional[str] = None,
) -> str:
    """Insert an auth_sessions row via raw SQL (no client_label etc.
    because backfill tests seed at the 0024 schema shape)."""
    tid = token_id or str(uuid.uuid4())
    if revoked_at is None:
        cur.execute(
            f"""
            INSERT INTO auth_sessions
                (token_id, vault_id, issued_at, expires_at)
            VALUES (%s, %s, {issued_at}, {expires_at})
            RETURNING token_id::text
            """,
            (tid, vault_id),
        )
    else:
        cur.execute(
            f"""
            INSERT INTO auth_sessions
                (token_id, vault_id, issued_at, expires_at, revoked_at)
            VALUES (%s, %s, {issued_at}, {expires_at}, {revoked_at})
            RETURNING token_id::text
            """,
            (tid, vault_id),
        )
    return cur.fetchone()[0]


# ============================================================
# TestAlembicSurface  — items A, B, K, L, M
# ============================================================


class TestAlembicSurface(unittest.TestCase):
    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()

    def test_A_upgrade_from_0024_to_0025_succeeds(self) -> None:
        _upgrade_to(_MIGRATION_HEAD)
        # Reaches the DB without exception.

    def test_B_alembic_current_equals_0025(self) -> None:
        _upgrade_to(_MIGRATION_HEAD)
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version;")
            (version,) = cur.fetchone()
        finally:
            conn.close()
        self.assertEqual(version, _MIGRATION_HEAD)

    def test_K_second_upgrade_head_is_noop(self) -> None:
        _upgrade_to(_MIGRATION_HEAD)
        # Second upgrade must be a clean no-op (Alembic version check).
        _upgrade_to("head")
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version;")
            (version,) = cur.fetchone()
        finally:
            conn.close()
        self.assertEqual(version, _MIGRATION_HEAD)

    def test_L_downgrade_to_0024_is_structural(self) -> None:
        _upgrade_to(_MIGRATION_HEAD)
        _downgrade_to(_MIGRATION_PREV)
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version;")
            (version,) = cur.fetchone()
            self.assertEqual(version, _MIGRATION_PREV)

            # Every new object gone.
            for col in ("token_id_hash", "client_label",
                        "client_label_source", "revoked_reason"):
                cur.execute(
                    """SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'auth_sessions'
                          AND column_name = %s""",
                    (col,),
                )
                self.assertIsNone(cur.fetchone(),
                    f"column {col} should not exist after downgrade")

            for idx in ("uq_auth_sessions_one_unrevoked_per_vault",
                        "uq_auth_sessions_token_id_hash",
                        "idx_auth_sessions_vault_active",
                        "idx_vault_security_events_vault_time"):
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE indexname = %s", (idx,))
                self.assertIsNone(cur.fetchone(),
                    f"index {idx} should not exist after downgrade")

            for con in ("auth_sessions_token_id_hash_len_chk",
                        "auth_sessions_client_label_len_chk"):
                cur.execute(
                    "SELECT 1 FROM pg_constraint WHERE conname = %s", (con,))
                self.assertIsNone(cur.fetchone(),
                    f"constraint {con} should not exist after downgrade")

            cur.execute(
                """SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'vault_security_events'""")
            self.assertIsNone(cur.fetchone(),
                "vault_security_events table should be dropped by downgrade")

            # Pre-existing 0024 objects untouched.
            for tbl in ("auth_sessions", "vaults", "accounts"):
                cur.execute(
                    """SELECT 1 FROM information_schema.tables
                        WHERE table_name = %s""", (tbl,))
                self.assertIsNotNone(cur.fetchone(),
                    f"pre-existing table {tbl} must survive downgrade")
        finally:
            conn.close()

    def test_M_reupgrade_after_downgrade_succeeds(self) -> None:
        _upgrade_to(_MIGRATION_HEAD)
        _downgrade_to(_MIGRATION_PREV)
        _upgrade_to(_MIGRATION_HEAD)
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version;")
            (version,) = cur.fetchone()
        finally:
            conn.close()
        self.assertEqual(version, _MIGRATION_HEAD)


# ============================================================
# TestSchemaStructure — item C
# ============================================================


class TestSchemaStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()
        _upgrade_to(_MIGRATION_HEAD)

    def _column(self, conn, table: str, column: str) -> Optional[Tuple]:
        cur = conn.cursor()
        cur.execute(
            """SELECT column_name, data_type, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s""",
            (table, column),
        )
        return cur.fetchone()

    def test_auth_sessions_new_columns_types_and_defaults(self) -> None:
        conn = _connect()
        try:
            th = self._column(conn, "auth_sessions", "token_id_hash")
            self.assertIsNotNone(th)
            self.assertEqual(th[1], "bytea")
            self.assertEqual(th[2], "YES")   # nullable
            self.assertIsNone(th[3])

            cl = self._column(conn, "auth_sessions", "client_label")
            self.assertIsNotNone(cl)
            self.assertEqual(cl[1], "text")
            self.assertEqual(cl[2], "YES")
            self.assertIsNone(cl[3])

            cls_ = self._column(conn, "auth_sessions", "client_label_source")
            self.assertIsNotNone(cls_)
            self.assertEqual(cls_[1], "smallint")
            self.assertEqual(cls_[2], "NO")
            self.assertIn("0", (cls_[3] or ""))

            rr = self._column(conn, "auth_sessions", "revoked_reason")
            self.assertIsNotNone(rr)
            self.assertEqual(rr[1], "text")
            self.assertEqual(rr[2], "YES")
            self.assertIsNone(rr[3])
        finally:
            conn.close()

    def test_auth_sessions_check_constraints_installed(self) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            for con in ("auth_sessions_token_id_hash_len_chk",
                        "auth_sessions_client_label_len_chk"):
                cur.execute(
                    "SELECT 1 FROM pg_constraint WHERE conname = %s", (con,))
                self.assertIsNotNone(cur.fetchone(),
                    f"CHECK constraint {con} missing")
        finally:
            conn.close()

    def test_auth_sessions_new_indexes_and_predicates(self) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            for idx, needle in (
                ("uq_auth_sessions_one_unrevoked_per_vault",
                 "revoked_at IS NULL"),
                ("uq_auth_sessions_token_id_hash",
                 "token_id_hash IS NOT NULL"),
                ("idx_auth_sessions_vault_active",
                 "revoked_at IS NULL"),
            ):
                cur.execute(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
                    (idx,),
                )
                row = cur.fetchone()
                self.assertIsNotNone(row, f"index {idx} missing")
                self.assertIn(needle, row[0],
                    f"index {idx} missing predicate '{needle}'")
        finally:
            conn.close()

    def test_vault_security_events_table_shape(self) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            # event_id BIGSERIAL PK
            cur.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                  FROM information_schema.columns
                 WHERE table_name = 'vault_security_events'
                 ORDER BY ordinal_position
            """)
            cols = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
            self.assertEqual(cols["event_id"][0], "bigint")
            self.assertEqual(cols["event_id"][1], "NO")
            self.assertIn("nextval", (cols["event_id"][2] or ""))

            self.assertEqual(cols["vault_id"][0], "uuid")
            self.assertEqual(cols["vault_id"][1], "NO")

            self.assertEqual(cols["event_type"][0], "text")
            self.assertEqual(cols["event_type"][1], "NO")

            self.assertEqual(cols["client_label"][0], "text")
            self.assertEqual(cols["client_label"][1], "YES")

            self.assertEqual(cols["created_at"][0], "timestamp with time zone")
            self.assertEqual(cols["created_at"][1], "NO")
            self.assertIn("now()", (cols["created_at"][2] or "").lower())

            self.assertEqual(cols["event_version"][0], "smallint")
            self.assertEqual(cols["event_version"][1], "NO")
            self.assertIn("1", (cols["event_version"][2] or ""))

            # FK cascade to vaults.vault_id
            cur.execute("""
                SELECT rc.delete_rule
                  FROM information_schema.referential_constraints rc
                  JOIN information_schema.table_constraints tc
                    ON rc.constraint_name = tc.constraint_name
                 WHERE tc.table_name = 'vault_security_events'
            """)
            row = cur.fetchone()
            self.assertIsNotNone(row, "FK constraint from events → vaults missing")
            self.assertEqual(row[0], "CASCADE")

            # CHECK constraints installed
            for con in ("vault_security_events_event_type_len_chk",
                        "vault_security_events_client_label_len_chk"):
                cur.execute(
                    "SELECT 1 FROM pg_constraint WHERE conname = %s", (con,))
                self.assertIsNotNone(cur.fetchone(),
                    f"CHECK constraint {con} missing")

            # Time-ordered index
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
                ("idx_vault_security_events_vault_time",),
            )
            row = cur.fetchone()
            self.assertIsNotNone(row, "vault_security_events time index missing")
            self.assertIn("created_at DESC", row[0])
        finally:
            conn.close()


# ============================================================
# TestConstraintEnforcement — items G, H, I
# ============================================================


class TestConstraintEnforcement(unittest.TestCase):
    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()
        _upgrade_to(_MIGRATION_HEAD)

    def _seed_vault(self) -> str:
        conn = _connect()
        try:
            cur = conn.cursor()
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            conn.commit()
            return vid
        finally:
            conn.close()

    def test_G_hash_length_check_rejects_31_bytes(self) -> None:
        import psycopg2
        vid = self._seed_vault()
        conn = _connect()
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_id, vault_id, expires_at, token_id_hash)
                    VALUES (
                        gen_random_uuid(), %s,
                        NOW() + INTERVAL '1 hour',
                        gen_random_bytes(31)
                    )
                    """,
                    (vid,),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_H_hash_length_check_accepts_32_bytes(self) -> None:
        vid = self._seed_vault()
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO auth_sessions
                    (token_id, vault_id, expires_at, token_id_hash)
                VALUES (
                    gen_random_uuid(), %s,
                    NOW() + INTERVAL '1 hour',
                    gen_random_bytes(32)
                )
                RETURNING token_id
                """,
                (vid,),
            )
            self.assertIsNotNone(cur.fetchone())
            conn.commit()
        finally:
            conn.close()

    def test_I_client_label_length_check(self) -> None:
        import psycopg2
        # Seed TWO vaults so the two successful INSERTs land on
        # different rows. Otherwise the second success collides with
        # uq_auth_sessions_one_unrevoked_per_vault (created by 0025)
        # and the test never reaches the client_label CHECK.
        #
        # The two rejected INSERTs are caught by assertRaises() and
        # rolled back, so they persist no state — either vault_id is
        # safe to reuse for the fail cases.
        vid_null = self._seed_vault()
        vid_max  = self._seed_vault()
        conn = _connect()
        try:
            cur = conn.cursor()

            # empty string rejected (BETWEEN 1 AND 64) — CHECK fires
            # before the partial UNIQUE index gets a chance.
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_id, vault_id, expires_at, client_label)
                    VALUES (
                        gen_random_uuid(), %s,
                        NOW() + INTERVAL '1 hour',
                        ''
                    )
                    """,
                    (vid_null,),
                )
            conn.rollback()

            # 65-char rejected — same shape as above.
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_id, vault_id, expires_at, client_label)
                    VALUES (
                        gen_random_uuid(), %s,
                        NOW() + INTERVAL '1 hour',
                        repeat('x', 65)
                    )
                    """,
                    (vid_null,),
                )
            conn.rollback()

            # NULL accepted → lives on vid_null.
            cur.execute(
                """
                INSERT INTO auth_sessions
                    (token_id, vault_id, expires_at, client_label)
                VALUES (
                    gen_random_uuid(), %s,
                    NOW() + INTERVAL '1 hour',
                    NULL
                )
                """,
                (vid_null,),
            )

            # 64-char boundary accepted → lives on vid_max, so the
            # single-session invariant is not violated (one active row
            # per vault, across two distinct vaults).
            cur.execute(
                """
                INSERT INTO auth_sessions
                    (token_id, vault_id, expires_at, client_label)
                VALUES (
                    gen_random_uuid(), %s,
                    NOW() + INTERVAL '1 hour',
                    repeat('y', 64)
                )
                """,
                (vid_max,),
            )
            conn.commit()
        finally:
            conn.close()

    def test_client_label_source_defaults_to_zero(self) -> None:
        vid = self._seed_vault()
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO auth_sessions (token_id, vault_id, expires_at)
                VALUES (gen_random_uuid(), %s, NOW() + INTERVAL '1 hour')
                RETURNING client_label_source
                """,
                (vid,),
            )
            self.assertEqual(cur.fetchone()[0], 0)
            conn.commit()
        finally:
            conn.close()

    def test_events_event_type_length_check(self) -> None:
        import psycopg2
        vid = self._seed_vault()
        conn = _connect()
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO vault_security_events (vault_id, event_type) "
                    "VALUES (%s, '')", (vid,))
            conn.rollback()

            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO vault_security_events (vault_id, event_type) "
                    "VALUES (%s, repeat('a', 65))", (vid,))
            conn.rollback()

            cur.execute(
                "INSERT INTO vault_security_events (vault_id, event_type) "
                "VALUES (%s, 'ok-event')", (vid,))
            conn.commit()
        finally:
            conn.close()


# ============================================================
# TestSingleSessionIndex — items E, F
# ============================================================


class TestSingleSessionIndex(unittest.TestCase):
    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()
        _upgrade_to(_MIGRATION_HEAD)

    def test_F_second_unrevoked_insert_fails(self) -> None:
        import psycopg2
        conn = _connect()
        try:
            cur = conn.cursor()
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            _insert_session(cur, vault_id=vid)
            conn.commit()

            with self.assertRaises(psycopg2.errors.UniqueViolation):
                _insert_session(cur, vault_id=vid)
            conn.rollback()
        finally:
            conn.close()

    def test_E_after_revoke_new_insert_ok(self) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            first = _insert_session(cur, vault_id=vid)
            cur.execute(
                "UPDATE auth_sessions SET revoked_at = NOW() WHERE token_id = %s",
                (first,),
            )
            _insert_session(cur, vault_id=vid)
            conn.commit()

            cur.execute(
                "SELECT COUNT(*) FROM auth_sessions "
                " WHERE vault_id = %s AND revoked_at IS NULL",
                (vid,),
            )
            self.assertEqual(cur.fetchone()[0], 1)
        finally:
            conn.close()

    def test_hash_unique_index_prevents_duplicates(self) -> None:
        import psycopg2
        conn = _connect()
        try:
            cur = conn.cursor()
            acc = _insert_account(cur)
            vid_a = _insert_vault(cur, account_id=acc)
            acc2 = _insert_account(cur)
            vid_b = _insert_vault(cur, account_id=acc2)
            cur.execute("SELECT gen_random_bytes(32)")
            same_hash = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO auth_sessions
                    (token_id, vault_id, expires_at, token_id_hash)
                VALUES (gen_random_uuid(), %s, NOW() + INTERVAL '1 hour', %s)
                """,
                (vid_a, same_hash),
            )
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_id, vault_id, expires_at, token_id_hash)
                    VALUES (gen_random_uuid(), %s,
                            NOW() + INTERVAL '1 hour', %s)
                    """,
                    (vid_b, same_hash),
                )
            conn.rollback()
        finally:
            conn.close()


# ============================================================
# TestBackfillScenarios — item D
# ============================================================


class TestBackfillScenarios(unittest.TestCase):
    """Seed synthetic state at 0024, then upgrade to 0025, and verify
    the deterministic backfill's outcome on each fixture.

    Each test resets to 0024, seeds independently, then upgrades. This
    is deliberately more work per test than sharing state across
    scenarios because clarity matters more than speed for a
    once-per-release migration.
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()

    def _seed_and_upgrade(self, seed_fn) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            seed_fn(cur)
            conn.commit()
        finally:
            conn.close()
        _upgrade_to(_MIGRATION_HEAD)

    def _rows(self, vault_id: str) -> List[Tuple[str, Optional[str]]]:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT token_id::text, revoked_reason
                     FROM auth_sessions
                    WHERE vault_id = %s
                    ORDER BY issued_at DESC, token_id DESC""",
                (vault_id,),
            )
            return cur.fetchall()
        finally:
            conn.close()

    def _unrevoked_count(self, vault_id: str) -> int:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM auth_sessions "
                " WHERE vault_id = %s AND revoked_at IS NULL",
                (vault_id,),
            )
            return cur.fetchone()[0]
        finally:
            conn.close()

    # (1) Multi-unrevoked-per-vault: newest kept, others revoked.
    def test_multiple_unrevoked_newest_kept(self) -> None:
        state = {}

        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            oldest = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW() - INTERVAL '2 days'",
                expires_at="NOW() + INTERVAL '2 hours'",
            )
            middle = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW() - INTERVAL '1 day'",
                expires_at="NOW() + INTERVAL '2 hours'",
            )
            newest = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW()",
                expires_at="NOW() + INTERVAL '2 hours'",
            )
            state["vid"] = vid
            state["oldest"] = oldest
            state["middle"] = middle
            state["newest"] = newest

        self._seed_and_upgrade(seed)

        rows = self._rows(state["vid"])
        # newest first
        self.assertEqual(rows[0][0], state["newest"])
        self.assertIsNone(rows[0][1], "newest should NOT be revoked")

        # older two are revoked with reason
        for tid in (state["middle"], state["oldest"]):
            (_, reason), = [r for r in rows if r[0] == tid]
            self.assertEqual(reason, "single-session-migration")

        self.assertEqual(self._unrevoked_count(state["vid"]), 1)

    # (2) issued_at tie broken by token_id DESC.
    def test_tie_break_by_token_id_desc(self) -> None:
        # Two token_ids differing only in the last hex nibble.
        # 'higher' UUID wins under ORDER BY token_id DESC.
        low_tid  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        high_tid = "ffffffff-ffff-ffff-ffff-ffffffffffff"

        state = {}

        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            same_ts = "TIMESTAMPTZ '2026-07-16 12:00:00+00'"
            _insert_session(
                cur, vault_id=vid,
                issued_at=same_ts,
                expires_at="NOW() + INTERVAL '1 hour'",
                token_id=low_tid,
            )
            _insert_session(
                cur, vault_id=vid,
                issued_at=same_ts,
                expires_at="NOW() + INTERVAL '1 hour'",
                token_id=high_tid,
            )
            state["vid"] = vid

        self._seed_and_upgrade(seed)

        rows = self._rows(state["vid"])
        # Only high_tid survives (ORDER BY token_id DESC picks it as rn=1)
        survivor = [r for r in rows if r[1] is None]
        loser    = [r for r in rows if r[1] == "single-session-migration"]
        self.assertEqual(len(survivor), 1)
        self.assertEqual(survivor[0][0], high_tid)
        self.assertEqual(len(loser), 1)
        self.assertEqual(loser[0][0], low_tid)

    # (3) Newest is already expired → all revoked.
    def test_expired_newest_gets_revoked(self) -> None:
        state = {}

        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            old = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW() - INTERVAL '2 days'",
                expires_at="NOW() - INTERVAL '1 day'",  # expired
            )
            newest_expired = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW() - INTERVAL '1 hour'",
                expires_at="NOW() - INTERVAL '1 minute'",  # expired
            )
            state["vid"] = vid

        self._seed_and_upgrade(seed)

        self.assertEqual(self._unrevoked_count(state["vid"]), 0)
        for _, reason in self._rows(state["vid"]):
            self.assertEqual(reason, "single-session-migration")

    # (4) Exactly one valid row → kept as-is.
    def test_one_valid_row_kept(self) -> None:
        state = {}

        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            only = _insert_session(
                cur, vault_id=vid,
                issued_at="NOW()",
                expires_at="NOW() + INTERVAL '1 hour'",
            )
            state["vid"] = vid
            state["only"] = only

        self._seed_and_upgrade(seed)

        rows = self._rows(state["vid"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], state["only"])
        self.assertIsNone(rows[0][1])

    # (5) Only expired rows → all revoked.
    def test_only_expired_rows_all_revoked(self) -> None:
        state = {}

        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            for i in range(3):
                _insert_session(
                    cur, vault_id=vid,
                    issued_at=f"NOW() - INTERVAL '{i+1} days'",
                    expires_at=f"NOW() - INTERVAL '{i+1} hours'",
                )
            state["vid"] = vid

        self._seed_and_upgrade(seed)

        self.assertEqual(self._unrevoked_count(state["vid"]), 0)
        for _, reason in self._rows(state["vid"]):
            self.assertEqual(reason, "single-session-migration")

    # Item E: after migration no vault has > 1 unrevoked row.
    def test_E_no_vault_has_more_than_one_unrevoked_row(self) -> None:
        state = {"vids": []}

        def seed(cur):
            for _ in range(4):
                acc = _insert_account(cur)
                vid = _insert_vault(cur, account_id=acc)
                state["vids"].append(vid)
                for i in range(3):
                    _insert_session(
                        cur, vault_id=vid,
                        issued_at=f"NOW() - INTERVAL '{i+1} hours'",
                        expires_at="NOW() + INTERVAL '1 hour'",
                    )

        self._seed_and_upgrade(seed)

        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT vault_id, COUNT(*) FROM auth_sessions
                    WHERE revoked_at IS NULL
                    GROUP BY vault_id
                   HAVING COUNT(*) > 1"""
            )
            offenders = cur.fetchall()
            self.assertEqual(offenders, [], f"vaults with >1 unrevoked: {offenders!r}")
        finally:
            conn.close()


# ============================================================
# TestMigrationEventEmission — item J
# ============================================================


class TestMigrationEventEmission(unittest.TestCase):
    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0024()

    def _seed_and_upgrade(self, seed_fn) -> None:
        conn = _connect()
        try:
            cur = conn.cursor()
            seed_fn(cur)
            conn.commit()
        finally:
            conn.close()
        _upgrade_to(_MIGRATION_HEAD)

    def test_J_one_event_per_affected_vault(self) -> None:
        state = {"affected": set(), "unaffected": None}

        def seed(cur):
            # Two vaults with 2 unrevoked rows each — both affected.
            for _ in range(2):
                acc = _insert_account(cur)
                vid = _insert_vault(cur, account_id=acc)
                _insert_session(cur, vault_id=vid,
                                issued_at="NOW() - INTERVAL '1 day'",
                                expires_at="NOW() + INTERVAL '1 hour'")
                _insert_session(cur, vault_id=vid,
                                issued_at="NOW()",
                                expires_at="NOW() + INTERVAL '1 hour'")
                state["affected"].add(vid)

            # A vault with only-expired-unrevoked rows — also affected.
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            _insert_session(cur, vault_id=vid,
                            issued_at="NOW() - INTERVAL '2 days'",
                            expires_at="NOW() - INTERVAL '1 day'")
            state["affected"].add(vid)

            # A vault with exactly one valid row — NOT affected.
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            _insert_session(cur, vault_id=vid,
                            issued_at="NOW()",
                            expires_at="NOW() + INTERVAL '1 hour'")
            state["unaffected"] = vid

        self._seed_and_upgrade(seed)

        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT vault_id::text, COUNT(*)
                  FROM vault_security_events
                 WHERE event_type = 'single-session-migration'
                 GROUP BY vault_id
            """)
            counts = dict(cur.fetchall())
        finally:
            conn.close()

        # Exactly one event for every affected vault.
        for vid in state["affected"]:
            self.assertEqual(counts.get(vid), 1,
                f"vault {vid} should have exactly 1 migration event, "
                f"got {counts.get(vid)}")

        # Zero events for the unaffected vault.
        self.assertNotIn(state["unaffected"], counts,
            "vault with pre-migration one-valid row must not get an event")

    def test_events_have_null_client_label_and_default_version(self) -> None:
        def seed(cur):
            acc = _insert_account(cur)
            vid = _insert_vault(cur, account_id=acc)
            _insert_session(cur, vault_id=vid,
                            issued_at="NOW() - INTERVAL '1 day'",
                            expires_at="NOW() + INTERVAL '1 hour'")
            _insert_session(cur, vault_id=vid,
                            issued_at="NOW()",
                            expires_at="NOW() + INTERVAL '1 hour'")

        self._seed_and_upgrade(seed)

        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT client_label, event_version
                  FROM vault_security_events
                 WHERE event_type = 'single-session-migration'
                 LIMIT 1
            """)
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row[0])
            self.assertEqual(row[1], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
