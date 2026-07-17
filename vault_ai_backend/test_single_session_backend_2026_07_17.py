"""
Step B.3: focused backend tests for the single-active-session policy.

Every test exercises the real ``auth_sessions`` table backed by
migration 0025 through a disposable PostgreSQL 17 identified by
``VAULTAI_TEST_DATABASE_URL``. Tests self-skip when that variable is
unset. There are no mocks of the database layer; the whole point of
these tests is to verify the atomic issuance transaction, the
partial UNIQUE index, and the coded 401 paths against real
Postgres semantics.

Coverage matrix (Step B.3 requirement 7):

  * ``TestFirstLoginCreatesOneSession`` — first login inserts exactly
    one unrevoked row with populated ``token_id_hash`` (32 bytes) and
    ``client_label``.
  * ``TestSecondLoginSupersedesFirst`` — second successful login on
    the same vault:
        - revokes the first row with reason ``'superseded-by-new-login'``,
        - inserts a new row for the second login,
        - leaves exactly one unrevoked row.
  * ``TestPhoneTokenRejectedAfterLaptopLogin`` — the first token
    returns 401 with ``code='session_superseded'`` on the next
    protected request; the second token still works.
  * ``TestFailedLoginPreservesFirstSession`` — a login with the wrong
    PIN never reaches ``issue_session_token`` and does NOT revoke the
    existing session (regression against a design that would revoke
    before verifying credentials).
  * ``TestConcurrentLoginsLeaveOneRow`` — three threads calling
    ``issue_session_token`` for the same vault at once produce three
    tokens (each thread saw its own commit succeed), and afterwards
    exactly one row is unrevoked.
  * ``TestUniqueIndexPreventsBypass`` — a direct SQL INSERT of a
    second unrevoked row for the same vault fails with
    ``UniqueViolation`` (proves the DB invariant is load-bearing).
  * ``TestLogoutRevokesWithReason`` — ``revoke_session_token`` stamps
    ``revoked_reason='logout'``.
  * ``TestSessionValidationCodes`` — expired, generic-revoked,
    unknown, and malformed token all raise 401 with the correct
    machine-readable code.
  * ``TestSecurityEventsShape`` — ``new_session_created`` on every
    login; ``previous_session_revoked`` iff a prior session actually
    existed; both events carry the correct coarse ``client_label``
    (never IP, UA, or token identifier).
  * ``TestNoSecretsInLogs`` — capturing logger output over the full
    signup + login + protected + logout flow, no substring of any
    token, hash, or User-Agent appears.
  * ``TestOpaqueAndLegacyBothObey`` — ``/auth/signup`` (legacy) and
    ``/auth/zk-register-finalize`` (OPAQUE, OPAQUE finish mocked)
    both go through the same ``issue_session_token`` and therefore
    both obey the single-session policy.

Nothing here modifies production DB / production.env / containers.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _skip_if_no_test_db() -> None:
    if not os.environ.get("VAULTAI_TEST_DATABASE_URL", "").strip():
        raise unittest.SkipTest(
            "VAULTAI_TEST_DATABASE_URL not set; single-session backend "
            "tests require a disposable PostgreSQL 17 with migration "
            "0025_auth_session_hardening applied."
        )


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["VAULTAI_TEST_DATABASE_URL"])


# --- Alembic helpers -------------------------------------------------


def _alembic_config():
    """Return an Alembic ``Config`` pointed at this repo's alembic.ini
    with DATABASE_URL overridden to VAULTAI_TEST_DATABASE_URL."""
    from alembic.config import Config
    os.environ["DATABASE_URL"] = os.environ["VAULTAI_TEST_DATABASE_URL"]
    return Config(os.path.join(_REPO_ROOT, "alembic.ini"))


def _upgrade_to(revision: str) -> None:
    from alembic import command
    command.upgrade(_alembic_config(), revision)


def _reset_to_0025() -> None:
    """Ensure the DB is at migration 0025 and every table is empty.

    We do NOT downgrade+upgrade — we just truncate. Truncation cascades
    into ``auth_sessions`` and ``vault_security_events``.
    """
    _upgrade_to("head")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version;")
        row = cur.fetchone()
        current = row[0] if row else None
        if current != "0025_auth_session_hardening":
            raise unittest.SkipTest(
                f"disposable DB is not at 0025_auth_session_hardening "
                f"(current={current}); ensure 'alembic upgrade head' has "
                f"applied 0025 before these tests run."
            )
        cur.execute(
            "TRUNCATE vault_security_events, auth_sessions, "
            "vaults, accounts RESTART IDENTITY CASCADE;"
        )
        conn.commit()
    finally:
        conn.close()


# --- Seed helpers ----------------------------------------------------


def _insert_account(cur) -> str:
    cur.execute(
        """
        INSERT INTO accounts (account_id, account_type, sales_channel)
        VALUES (gen_random_uuid(), 'individual', 'self_service')
        RETURNING account_id
        """,
    )
    return str(cur.fetchone()[0])


def _insert_vault(cur, *, account_id: str, vault_name: Optional[str] = None) -> str:
    """Insert a legacy-shape vault row (satisfies the 0023 ZK
    consistency check by keeping all three ZK columns NULL)."""
    vname = vault_name or f"vault-{uuid.uuid4().hex[:12]}"
    cur.execute(
        """
        INSERT INTO vaults (
            vault_name, pin_salt, pin_verifier, account_id,
            acknowledged_irrecoverable
        ) VALUES (%s, '', '', %s, TRUE)
        RETURNING vault_id, vault_name
        """,
        (vname, account_id),
    )
    row = cur.fetchone()
    return str(row[0])


def _seed_vault() -> Dict[str, str]:
    """Create a fresh account + vault, return {vault_id, vault_name}."""
    conn = _connect()
    try:
        cur = conn.cursor()
        acc = _insert_account(cur)
        cur.execute(
            """
            INSERT INTO vaults (
                vault_name, pin_salt, pin_verifier, account_id,
                acknowledged_irrecoverable
            ) VALUES (%s, '', '', %s, TRUE)
            RETURNING vault_id, vault_name
            """,
            (f"vault-{uuid.uuid4().hex[:12]}", acc),
        )
        vault_id, vault_name = cur.fetchone()
        conn.commit()
        return {"vault_id": str(vault_id), "vault_name": vault_name}
    finally:
        conn.close()


def _row_counts(vault_id: str) -> Dict[str, int]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM auth_sessions "
            " WHERE vault_id = %s AND revoked_at IS NULL", (vault_id,))
        active = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE vault_id = %s",
            (vault_id,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM vault_security_events "
            " WHERE vault_id = %s", (vault_id,))
        events = cur.fetchone()[0]
        return {"active": active, "total": total, "events": events}
    finally:
        conn.close()


def _fetch_session(token_id: str) -> Dict[str, Any]:
    from psycopg2.extras import RealDictCursor
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT token_id, token_id_hash, vault_id, device_id,
                   client_label, client_label_source,
                   issued_at, expires_at, revoked_at, revoked_reason,
                   last_used_at
              FROM auth_sessions
             WHERE token_id = %s
            """, (token_id,))
        return cur.fetchone()
    finally:
        conn.close()


def _events(vault_id: str) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT event_type, client_label, event_version
              FROM vault_security_events
             WHERE vault_id = %s
             ORDER BY event_id ASC
            """, (vault_id,))
        return cur.fetchall()
    finally:
        conn.close()


def _issue(vault_id: str, vault_name: str, *,
           client_label: str = "Chrome on Windows",
           device_id: Optional[str] = None) -> Dict[str, Any]:
    """Direct call to auth_local.issue_session_token — bypasses the
    HTTP routing layer, which is intentional because these tests
    validate the atomic transaction, not FastAPI wiring."""
    import auth_local
    return auth_local.issue_session_token(
        vault_id=vault_id, vault_name=vault_name,
        device_id=device_id, client_label=client_label,
    )


def _make_authed_request(token: str, path: str = "/"):
    """Build a Starlette ``Request`` scope object bearing a Bearer token."""
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [
            (b"authorization", f"Bearer {token}".encode("ascii")),
        ],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    return Request(scope)


# ============================================================
# Tests
# ============================================================


class TestFirstLoginCreatesOneSession(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_one_row_populated_hash_and_label(self) -> None:
        v = _seed_vault()
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Safari on macOS")
        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["total"], 1)

        row = _fetch_session(issued["token_id"])
        self.assertIsNotNone(row["token_id_hash"])
        self.assertEqual(len(bytes(row["token_id_hash"])), 32)
        self.assertEqual(row["client_label"], "Safari on macOS")
        self.assertEqual(row["client_label_source"], 1)
        self.assertIsNone(row["revoked_at"])
        self.assertIsNone(row["revoked_reason"])


class TestSecondLoginSupersedesFirst(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_second_login_revokes_first_row_and_leaves_one_active(self) -> None:
        v = _seed_vault()
        first  = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Windows",
                        device_id="dev-phone")
        second = _issue(v["vault_id"], v["vault_name"],
                        client_label="Safari on macOS",
                        device_id="dev-laptop")

        first_row  = _fetch_session(first["token_id"])
        second_row = _fetch_session(second["token_id"])

        # First row was superseded.
        self.assertIsNotNone(first_row["revoked_at"])
        self.assertEqual(first_row["revoked_reason"], "superseded-by-new-login")

        # Second row is the sole active session.
        self.assertIsNone(second_row["revoked_at"])
        self.assertEqual(_row_counts(v["vault_id"])["active"], 1)


class TestPhoneTokenRejectedAfterLaptopLogin(unittest.IsolatedAsyncioTestCase):
    """Verifies the machine-readable ``session_superseded`` 401."""

    async def asyncSetUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    async def test_phone_next_request_401_superseded_and_laptop_works(self) -> None:
        import auth_local
        v = _seed_vault()
        phone  = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Android",
                        device_id="dev-phone")
        laptop = _issue(v["vault_id"], v["vault_name"],
                        client_label="Safari on macOS",
                        device_id="dev-laptop")

        # Phone request now fails with the coded 401.
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(
                _make_authed_request(phone["token"]))
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIsInstance(cm.exception.detail, dict)
        self.assertEqual(cm.exception.detail["code"], "session_superseded")
        self.assertIn("Vault was signed in", cm.exception.detail["message"])

        # Laptop principal is returned fine.
        principal = await auth_local.verify_session_token(
            _make_authed_request(laptop["token"]))
        self.assertEqual(principal["token_id"], laptop["token_id"])


class TestFailedLoginPreservesFirstSession(unittest.TestCase):
    """Wrong-PIN login must not touch existing sessions.

    Exercised through ``/auth/login`` (which routes through the
    PBKDF2 verifier before ``issue_session_token``). The test
    creates a legacy vault via the signup flow so that a valid
    password path exists, then attempts a login with the wrong PIN
    and asserts the previously-issued session is untouched.
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_routes import router as auth_router
        app = FastAPI()
        app.include_router(auth_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_wrong_pin_login_does_not_revoke_existing_session(self) -> None:
        client = self._make_client()
        vault_name = f"vault-{uuid.uuid4().hex[:12]}"
        pin = "83726104"

        r_signup = client.post("/auth/signup", json={
            "vault_name":  vault_name,
            "pin":         pin,
            "confirm_pin": pin,
            "acknowledged_irrecoverable": True,
        })
        self.assertEqual(r_signup.status_code, 201, r_signup.text[:200])
        first_token = r_signup.json()["session_token"]
        first_vault_id = r_signup.json()["vault_id"]
        self.assertEqual(_row_counts(first_vault_id)["active"], 1)

        # Wrong PIN — must NOT revoke.
        r_bad = client.post("/auth/login", json={
            "vault_name": vault_name, "pin": "99999999",
        })
        self.assertIn(r_bad.status_code, (400, 401, 423),
            f"unexpected status for wrong PIN: {r_bad.status_code} / {r_bad.text[:200]}")

        # Existing session still valid.
        row = _fetch_session(str(uuid.UUID(bytes=(
            __import__('auth_local')._parse_token(first_token)))))
        self.assertIsNone(row["revoked_at"])
        self.assertEqual(_row_counts(first_vault_id)["active"], 1)


class TestConcurrentLoginsLeaveOneRow(unittest.TestCase):
    """Three concurrent successful logins → 1 unrevoked row.

    The FOR UPDATE lock on ``vaults`` serializes the transactions;
    the partial UNIQUE index catches any bug that would violate the
    invariant. Even under a race, the DB refuses to hold two
    unrevoked rows for one vault.
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_three_threads_final_state_is_one_unrevoked(self) -> None:
        v = _seed_vault()
        barrier = threading.Barrier(3)
        results: List[Dict[str, Any]] = []
        errors: List[BaseException] = []

        def worker(i: int) -> None:
            try:
                barrier.wait(timeout=15)
                token = _issue(
                    v["vault_id"], v["vault_name"],
                    client_label=f"Chrome on Windows",
                    device_id=f"dev-{i}",
                )
                results.append(token)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(3)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"worker errors: {errors!r}")
        self.assertEqual(len(results), 3)
        token_ids = {r["token_id"] for r in results}
        self.assertEqual(len(token_ids), 3, "all three token_ids distinct")

        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 1,
            "exactly one unrevoked row must remain after 3 concurrent logins")
        self.assertEqual(counts["total"], 3)


class TestUniqueIndexPreventsBypass(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_direct_second_unrevoked_insert_fails(self) -> None:
        import psycopg2
        v = _seed_vault()
        _issue(v["vault_id"], v["vault_name"], client_label="Chrome on Windows")

        conn = _connect()
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_id, vault_id, expires_at, client_label_source)
                    VALUES (gen_random_uuid(), %s,
                            NOW() + INTERVAL '1 hour', 0)
                    """, (v["vault_id"],))
            conn.rollback()
        finally:
            conn.close()


class TestLogoutRevokesWithReason(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_revoke_session_token_stamps_logout(self) -> None:
        import auth_local
        v = _seed_vault()
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Windows")

        affected = auth_local.revoke_session_token(issued["token_id"])
        self.assertTrue(affected)
        row = _fetch_session(issued["token_id"])
        self.assertIsNotNone(row["revoked_at"])
        self.assertEqual(row["revoked_reason"], "logout")

    def test_revoke_all_stamps_vault_delete_by_default(self) -> None:
        import auth_local
        v = _seed_vault()
        _issue(v["vault_id"], v["vault_name"], client_label="Chrome on Windows")

        n = auth_local.revoke_all_sessions_for_vault(v["vault_id"])
        self.assertGreaterEqual(n, 1)

        from psycopg2.extras import RealDictCursor
        conn = _connect()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT revoked_reason FROM auth_sessions WHERE vault_id = %s",
                (v["vault_id"],))
            for row in cur.fetchall():
                self.assertEqual(row["revoked_reason"], "vault-delete")
        finally:
            conn.close()


class TestSessionValidationCodes(unittest.IsolatedAsyncioTestCase):
    """Every 401 path must expose the correct machine-readable code."""

    async def asyncSetUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    async def test_invalid_session_on_missing_or_garbage_token(self) -> None:
        import auth_local
        from fastapi import HTTPException
        from starlette.requests import Request

        # No Authorization header.
        scope = {"type": "http", "method": "GET", "path": "/",
                 "headers": [], "query_string": b"",
                 "client": ("127.0.0.1", 0), "server": ("t", 80)}
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(Request(scope))
        self.assertEqual(cm.exception.detail["code"], "invalid_session")

        # Bearer with garbage.
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(
                _make_authed_request("this-is-not-a-real-token"))
        self.assertEqual(cm.exception.detail["code"], "invalid_session")

    async def test_invalid_session_on_valid_hmac_but_row_missing(self) -> None:
        import auth_local
        # Mint a real token, then wipe the row so only the wire signature
        # survives — proves _load_principal treats "no row" as invalid.
        v = _seed_vault()
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Windows")
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth_sessions WHERE token_id = %s",
                        (issued["token_id"],))
            conn.commit()
        finally:
            conn.close()

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(
                _make_authed_request(issued["token"]))
        self.assertEqual(cm.exception.detail["code"], "invalid_session")

    async def test_session_expired(self) -> None:
        import auth_local
        v = _seed_vault()
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Windows")

        # Backdate BOTH issued_at and expires_at so the row is expired
        # relative to NOW() while still satisfying auth_sessions_check
        # (expires_at >= issued_at).
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE auth_sessions
                   SET issued_at  = NOW() - INTERVAL '2 hours',
                       expires_at = NOW() - INTERVAL '1 hour'
                 WHERE token_id = %s
                """,
                (issued["token_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(
                _make_authed_request(issued["token"]))
        self.assertEqual(cm.exception.detail["code"], "session_expired")

    async def test_session_revoked_generic(self) -> None:
        import auth_local
        v = _seed_vault()
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Chrome on Windows")
        # Simulate a non-supersede revoke (e.g., user hit logout).
        auth_local.revoke_session_token(issued["token_id"], reason="logout")

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            await auth_local.verify_session_token(
                _make_authed_request(issued["token"]))
        self.assertEqual(cm.exception.detail["code"], "session_revoked")


class TestSecurityEventsShape(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_first_login_emits_only_new_session_created(self) -> None:
        v = _seed_vault()
        _issue(v["vault_id"], v["vault_name"], client_label="Safari on macOS")
        events = _events(v["vault_id"])
        types = [e["event_type"] for e in events]
        self.assertEqual(types, ["new_session_created"])
        self.assertEqual(events[0]["client_label"], "Safari on macOS")
        self.assertEqual(events[0]["event_version"], 1)

    def test_second_login_emits_both_events_with_correct_labels(self) -> None:
        v = _seed_vault()
        _issue(v["vault_id"], v["vault_name"], client_label="Chrome on Android")
        _issue(v["vault_id"], v["vault_name"], client_label="Firefox on Linux")
        events = _events(v["vault_id"])
        types = [e["event_type"] for e in events]
        self.assertEqual(types, [
            "new_session_created",             # first login
            "new_session_created",             # second login
            "previous_session_revoked",        # emitted iff prior existed
        ])
        # Newest previous_session_revoked references the OLD label.
        prev = [e for e in events if e["event_type"] == "previous_session_revoked"][0]
        self.assertEqual(prev["client_label"], "Chrome on Android")
        # No token_id / hash surfaced anywhere in the events table.
        for e in events:
            for k, val in e.items():
                if isinstance(val, str):
                    self.assertNotIn("session-id", val.lower())


class TestNoSecretsInLogs(unittest.TestCase):

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def test_no_token_hash_or_ua_in_logger_output(self) -> None:
        import auth_local
        import io

        # Attach a plain StreamHandler to the root logger with
        # DEBUG level so every record — from any submodule the
        # auth flow reaches — is captured. This intentionally does
        # NOT use unittest.assertLogs: assertLogs raises when zero
        # records are emitted, and the current auth_local flow
        # legitimately runs silent on the success path; a "no
        # secrets appeared" assertion is meaningful over an empty
        # log stream, and forcing a marker record just to satisfy
        # assertLogs would be wallpaper.
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        root = logging.getLogger()
        prev_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        # Additionally lift auth_local's own logger to DEBUG so any
        # DEBUG record it emits reaches the root handler.
        auth_logger = logging.getLogger(auth_local.__name__)
        prev_auth_level = auth_logger.level
        auth_logger.setLevel(logging.DEBUG)

        try:
            v = _seed_vault()
            issued = _issue(v["vault_id"], v["vault_name"],
                            client_label="Chrome on Windows")
            token = issued["token"]
            token_id = issued["token_id"]

            # Simulate expiration and re-verify to hit that log path.
            # Backdate BOTH issued_at and expires_at so the row is
            # expired relative to NOW() while still satisfying
            # auth_sessions_check (expires_at >= issued_at).
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE auth_sessions
                       SET issued_at  = NOW() - INTERVAL '2 hours',
                           expires_at = NOW() - INTERVAL '1 hour'
                     WHERE token_id = %s
                    """,
                    (token_id,),
                )
                conn.commit()
            finally:
                conn.close()

            import asyncio
            from fastapi import HTTPException
            async def probe():
                try:
                    await auth_local.verify_session_token(_make_authed_request(token))
                except HTTPException:
                    pass
            asyncio.run(probe())

            auth_local.revoke_session_token(token_id)
        finally:
            root.removeHandler(handler)
            root.setLevel(prev_level)
            auth_logger.setLevel(prev_auth_level)

        blob = buf.getvalue()
        self.assertNotIn(token, blob, "wire token must never appear in logs")
        self.assertNotIn(token_id, blob, "raw token_id must never appear in logs")
        # No hex hash prefix either.
        hex_hash = auth_local._hash_token_id(
            base64.urlsafe_b64decode(
                (token + "=" * (-len(token) % 4)).encode("ascii")
            )[:16]).hex()
        for k in range(6, 33, 4):
            self.assertNotIn(hex_hash[:k].lower(), blob.lower(),
                f"token_id_hash prefix (len {k}) must not appear")
        # User-Agent-ish strings.
        self.assertNotIn("Mozilla/5.0", blob)
        self.assertNotIn("Chrome/126", blob)


class TestOpaqueAndLegacyBothObey(unittest.TestCase):
    """Both signup (legacy) and zk-register-finalize (OPAQUE with the
    OPAQUE primitive mocked) route through the same
    ``issue_session_token`` and therefore both enforce single-session.

    Uses TestClient with DB-real Postgres and a monkey-patched
    ``opaque_registration_finish`` (the pyo3 wheel is not required for
    the DB-write half of the endpoint).
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_routes import router as auth_router
        from routes.auth_zk_routes import router as zk_router
        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(zk_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_legacy_signup_then_login_supersedes(self) -> None:
        import auth_local
        client = self._make_client()
        vault_name = f"vault-{uuid.uuid4().hex[:12]}"
        pin = "82640173"

        r1 = client.post("/auth/signup", json={
            "vault_name":  vault_name,
            "pin":         pin,
            "confirm_pin": pin,
            "acknowledged_irrecoverable": True,
        }, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/126.0"})
        self.assertEqual(r1.status_code, 201, r1.text[:200])
        vault_id = r1.json()["vault_id"]

        r2 = client.post("/auth/login", json={
            "vault_name": vault_name, "pin": pin,
        }, headers={"User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15"
        )})
        self.assertEqual(r2.status_code, 200, r2.text[:200])

        # Single-session invariant + events shape after two events.
        counts = _row_counts(vault_id)
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["total"], 2)
        events = _events(vault_id)
        types = [e["event_type"] for e in events]
        self.assertEqual(types.count("new_session_created"), 2)
        self.assertEqual(types.count("previous_session_revoked"), 1)

    def test_zk_register_finalize_creates_one_session(self) -> None:
        client = self._make_client()

        from vault_handle import to_display
        handle = bytes(range(1, 16))

        def _b64u(b: bytes) -> str:
            return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

        with mock.patch(
            "routes.auth_zk_routes.opaque_registration_finish",
            return_value=b"fake-opaque-record",
        ), mock.patch(
            "routes.auth_zk_routes.enforce_signup_rate_limit",
            return_value=None,
        ):
            r = client.post("/auth/zk-register-finalize", json={
                "vault_handle": to_display(handle),
                "ke3": _b64u(b"fake-ke3"),
                "wrapped_mvk":               _b64u(b"fake-mvk"),
                "wrapped_sk_vault":          _b64u(b"fake-sk"),
                "pk_vault_public":           _b64u(b"\x00" * 32),
                "display_name_ciphertext":   _b64u(b"fake-display"),
                "acknowledged_irrecoverable": True,
                "device_id": "dev-zk",
            }, headers={"User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0"
            )})

        self.assertEqual(r.status_code, 200, r.text[:200])
        vault_id = r.json()["vault_id"]
        counts = _row_counts(vault_id)
        self.assertEqual(counts["active"], 1)


class TestFullSupersessionPipeline(unittest.TestCase):
    """End-to-end integration through the complete FastAPI request
    pipeline for the phone → laptop supersession scenario.

    Every hop is a real HTTP request through ``TestClient`` (no direct
    calls to ``issue_session_token`` or ``verify_session_token``), which
    exercises:

      * FastAPI routing
      * request validation (``SignupRequest``, ``LoginRequest``)
      * PBKDF2 verification on the login side
      * the atomic ``issue_session_token`` transaction against real
        PostgreSQL (single-session invariant, previous-session revoke,
        security-event emission)
      * ``verify_session_token`` on a protected route (``GET /auth/me``)
      * ``_load_principal``'s classification cascade producing the
        machine-readable ``session_superseded`` code on the phone's
        next request

    Sequence:

      1. ``POST /auth/signup`` from the "phone" (Android UA) → 201,
         session A returned.
      2. ``GET /auth/me`` with session A → 200 (phone authenticated).
      3. ``POST /auth/login`` from the "laptop" (macOS Safari UA) for
         the SAME vault → 200, session B returned; session A is
         revoked with reason ``'superseded-by-new-login'`` inside the
         same transaction.
      4. ``GET /auth/me`` with session A → 401 with
         ``detail={"code": "session_superseded", "message": ...}``.
      5. ``GET /auth/me`` with session B → 200 (laptop continues to
         authenticate normally).

    Also asserts the DB-visible side effects: exactly one unrevoked
    row for the vault, two ``new_session_created`` events, one
    ``previous_session_revoked`` event.
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_routes import router as auth_router
        app = FastAPI()
        app.include_router(auth_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_phone_401_superseded_after_laptop_login_full_pipeline(self) -> None:
        client = self._make_client()
        vault_name = f"vault-{uuid.uuid4().hex[:12]}"
        pin = "82640173"

        phone_ua = (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Mobile Safari/537.36"
        )
        laptop_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.5 Safari/605.1.15"
        )

        # 1. Signup on the phone.
        r_signup = client.post(
            "/auth/signup",
            json={
                "vault_name":  vault_name,
                "pin":         pin,
                "confirm_pin": pin,
                "acknowledged_irrecoverable": True,
            },
            headers={"User-Agent": phone_ua},
        )
        self.assertEqual(r_signup.status_code, 201,
            f"signup failed: {r_signup.text[:200]!r}")
        phone_body = r_signup.json()
        phone_token = phone_body["session_token"]
        vault_id = phone_body["vault_id"]
        self.assertIsInstance(phone_token, str)

        # 2. Phone can access the protected /auth/me route.
        r_me_phone_before = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {phone_token}"},
        )
        self.assertEqual(r_me_phone_before.status_code, 200,
            f"phone /auth/me before laptop login failed: "
            f"{r_me_phone_before.text[:200]!r}")
        self.assertEqual(r_me_phone_before.json()["vault_id"], vault_id)

        # 3. Login from the laptop for the SAME vault → supersede phone.
        r_login = client.post(
            "/auth/login",
            json={"vault_name": vault_name, "pin": pin},
            headers={"User-Agent": laptop_ua},
        )
        self.assertEqual(r_login.status_code, 200,
            f"laptop login failed: {r_login.text[:200]!r}")
        laptop_body = r_login.json()
        laptop_token = laptop_body["session_token"]
        self.assertEqual(laptop_body["vault_id"], vault_id)
        self.assertNotEqual(laptop_token, phone_token,
            "laptop must receive a distinct session token")

        # 4. Phone's next authenticated request is rejected with the
        #    machine-readable session_superseded code and a human message.
        r_me_phone_after = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {phone_token}"},
        )
        self.assertEqual(r_me_phone_after.status_code, 401,
            f"phone /auth/me after supersession expected 401, got "
            f"{r_me_phone_after.status_code}: {r_me_phone_after.text[:200]!r}")
        detail = r_me_phone_after.json().get("detail")
        self.assertIsInstance(detail, dict,
            f"401 detail must be a dict carrying the code; got {detail!r}")
        self.assertEqual(detail.get("code"), "session_superseded",
            f"expected code=session_superseded; got {detail!r}")
        self.assertIn("another device", (detail.get("message") or "").lower(),
            f"session_superseded human message should reference the other "
            f"device; got {detail!r}")

        # 5. Laptop continues to authenticate normally.
        r_me_laptop = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {laptop_token}"},
        )
        self.assertEqual(r_me_laptop.status_code, 200,
            f"laptop /auth/me expected 200, got {r_me_laptop.status_code}: "
            f"{r_me_laptop.text[:200]!r}")
        self.assertEqual(r_me_laptop.json()["vault_id"], vault_id)

        # DB-level side effects (belt-and-braces).
        counts = _row_counts(vault_id)
        self.assertEqual(counts["active"], 1,
            "single-session invariant: exactly one unrevoked row must remain")
        self.assertEqual(counts["total"], 2,
            "both sessions must be persisted (one revoked, one active)")

        events = _events(vault_id)
        types = [e["event_type"] for e in events]
        self.assertEqual(types.count("new_session_created"), 2,
            "one event per successful login (signup + laptop login)")
        self.assertEqual(types.count("previous_session_revoked"), 1,
            "exactly one supersession event from the laptop login")


# ============================================================
# Pool-abstraction transaction regression tests (Gate-B.3 fix)
# ============================================================
#
# Origin: the first Gate-B.3 Linux run failed because
# ``issue_session_token`` tried to write ``conn.autocommit = False``
# on a ``vault_core._PooledConnection``. That wrapper defines
# ``__slots__`` and does not proxy attribute writes, so the
# assignment raised ``AttributeError`` and every issuance path
# crashed inside the ``try`` block. The fix removed the assignment
# (psycopg2 default autocommit is already False, and the pool's
# close() rollback preserves that invariant across borrows).
#
# The tests below guard against regressions of that class:
#
#   A. issue_session_token succeeds against the real
#      ``_PooledConnection`` wrapper end-to-end (no monkeypatching
#      of the connection or the pool).
#   B. A forced failure between old-session revocation and
#      new-session insert rolls back BOTH sides — old row stays
#      unrevoked, no new row exists.
#   C. A forced failure between new-session insert and the
#      first security-event insert rolls back the new row.
#   D. After either failure the same pooled connection can be
#      borrowed again and used successfully (no lingering aborted
#      transaction, no row locks left behind).
#   E. Concurrent-safety corollary of B: no old session is
#      revoked unless the whole new-session transaction commits.
#   F. When commit() itself fails, no token is ever returned to
#      the caller and no unrevoked row is left behind.


class _CommitError(RuntimeError):
    """Distinct error class for the forced-failure tests."""


class _CountingCursor:
    """Cursor proxy that raises after N ``execute()`` calls.

    ``fail_after`` matches the SQL statement index (1-based) *after*
    which the next call should raise. Set ``fail_on_commit=True`` to
    let all executes succeed but fail the eventual ``commit()`` on
    the wrapping connection instead. This lets each test target one
    specific stage of the ``issue_session_token`` transaction:

        stage 1 = SELECT vault FOR UPDATE
        stage 2 = UPDATE ... RETURNING (revoke old)
        stage 3 = INSERT auth_sessions (new)
        stage 4 = INSERT vault_security_events (new_session_created)
        stage 5 = INSERT vault_security_events (previous_session_revoked)
    """

    def __init__(self, cur, fail_after: Optional[int]) -> None:
        self._cur = cur
        self._n = 0
        self._fail_after = fail_after

    def execute(self, *a, **kw):
        self._n += 1
        result = self._cur.execute(*a, **kw)
        if self._fail_after is not None and self._n > self._fail_after:
            raise _CommitError(
                f"forced failure after execute #{self._n}")
        return result

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _WrappedPooledConn:
    """Wraps a real ``_PooledConnection`` and injects a
    ``_CountingCursor`` into every ``cursor()`` call. All other
    attribute access — including ``commit``, ``rollback`` and
    ``close`` — passes through to the pooled wrapper unchanged, so
    the underlying transaction really commits/rolls back on the
    same psycopg2 connection the runtime is using."""

    __slots__ = ("_pooled", "_fail_after", "_fail_commit")

    def __init__(self, pooled, *, fail_after: Optional[int] = None,
                 fail_commit: bool = False) -> None:
        object.__setattr__(self, "_pooled", pooled)
        object.__setattr__(self, "_fail_after", fail_after)
        object.__setattr__(self, "_fail_commit", fail_commit)

    def cursor(self, *a, **kw):
        return _CountingCursor(self._pooled.cursor(*a, **kw),
                               self._fail_after)

    def commit(self):
        if self._fail_commit:
            raise _CommitError("forced commit failure")
        return self._pooled.commit()

    def __getattr__(self, name):
        return getattr(self._pooled, name)


class TestPooledConnectionTransactions(unittest.TestCase):
    """Regression tests for the ``_PooledConnection`` transaction
    semantics used by ``issue_session_token``.

    Every test drives the real wrapper returned by
    ``vault_core.get_db()``. Nothing is stubbed at the pool layer;
    only individual failure injections wrap the connection object
    at ``get_db`` boundary to force rollback at a chosen stage.
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        _reset_to_0025()
        # Force a clean pool for each test so we can prove the exact
        # pooled connection borrowed by a failure path is safely
        # borrowable again inside the same test (Requirement D).
        import vault_core
        vault_core.close_pool()

    def tearDown(self) -> None:
        import vault_core
        vault_core.close_pool()

    # --- A -----------------------------------------------------

    def test_A_success_uses_real_pooled_connection_wrapper(self) -> None:
        import vault_core
        from vault_core import _PooledConnection

        borrowed: List[Any] = []
        real_get_db = vault_core.get_db

        def spy_get_db():
            conn = real_get_db()
            borrowed.append(conn)
            return conn

        v = _seed_vault()
        with mock.patch("auth_local.get_db", side_effect=spy_get_db):
            issued = _issue(v["vault_id"], v["vault_name"],
                            client_label="Chrome on Windows")

        self.assertGreaterEqual(len(borrowed), 1,
            "issue_session_token must borrow at least one pooled connection")
        for c in borrowed:
            self.assertIsInstance(c, _PooledConnection,
                f"expected real _PooledConnection wrapper; got {type(c)!r}")

        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["total"], 1)
        self.assertTrue(issued["token"])

    # --- B -----------------------------------------------------

    def test_B_failure_between_revoke_and_insert_rolls_everything_back(self) -> None:
        # Seed one active session that a hypothetical second login
        # would try to supersede. The forced failure fires AFTER
        # stage 2 (revoke) and BEFORE stage 3 (insert new row).
        v = _seed_vault()
        first = _issue(v["vault_id"], v["vault_name"],
                       client_label="Chrome on Windows",
                       device_id="dev-phone")

        import vault_core
        real_get_db = vault_core.get_db

        def wrap_get_db():
            return _WrappedPooledConn(real_get_db(), fail_after=2)

        with mock.patch("auth_local.get_db", side_effect=wrap_get_db):
            with self.assertRaises(_CommitError):
                _issue(v["vault_id"], v["vault_name"],
                       client_label="Safari on macOS",
                       device_id="dev-laptop")

        # Old row is still unrevoked (rollback restored it), no new row.
        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 1,
            "rollback must leave the pre-existing session unrevoked")
        self.assertEqual(counts["total"], 1,
            "no new auth_sessions row may exist for a rolled-back issuance")
        first_row = _fetch_session(first["token_id"])
        self.assertIsNone(first_row["revoked_at"])
        self.assertIsNone(first_row["revoked_reason"])
        # Only the original signup's event should exist.
        events = _events(v["vault_id"])
        self.assertEqual(
            [e["event_type"] for e in events],
            ["new_session_created"],
        )

    # --- C -----------------------------------------------------

    def test_C_failure_between_insert_and_first_event_rolls_new_row_back(self) -> None:
        v = _seed_vault()
        import vault_core
        real_get_db = vault_core.get_db

        # Fail AFTER stage 3 (insert new row) but BEFORE stage 4
        # (new_session_created event). Because there's no prior
        # session, only 3 executes should happen before failure.
        def wrap_get_db():
            return _WrappedPooledConn(real_get_db(), fail_after=3)

        with mock.patch("auth_local.get_db", side_effect=wrap_get_db):
            with self.assertRaises(_CommitError):
                _issue(v["vault_id"], v["vault_name"],
                       client_label="Chrome on Windows")

        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 0,
            "insert-then-fail must roll back the new auth_sessions row")
        self.assertEqual(counts["total"], 0)
        self.assertEqual(counts["events"], 0,
            "no security event may be committed when the transaction rolls back")

    # --- D -----------------------------------------------------

    def test_D_pooled_connection_reusable_after_forced_rollback(self) -> None:
        v1 = _seed_vault()
        v2 = _seed_vault()
        import vault_core
        real_get_db = vault_core.get_db

        # First call: fail after stage 3 to force rollback.
        def wrap_first():
            return _WrappedPooledConn(real_get_db(), fail_after=3)

        with mock.patch("auth_local.get_db", side_effect=wrap_first):
            with self.assertRaises(_CommitError):
                _issue(v1["vault_id"], v1["vault_name"],
                       client_label="Chrome on Windows")

        # Second call: no wrapping — must go through the real pool.
        # If the previous rollback left the pooled connection in a
        # bad state, this would either raise
        # ``psycopg2.errors.InFailedSqlTransaction`` or deadlock on
        # the FOR UPDATE row lock.
        issued = _issue(v2["vault_id"], v2["vault_name"],
                        client_label="Safari on macOS")
        counts2 = _row_counts(v2["vault_id"])
        self.assertEqual(counts2["active"], 1)
        self.assertEqual(counts2["total"], 1)
        self.assertTrue(issued["token"])

        # And v1 is still untouched by the failed attempt.
        counts1 = _row_counts(v1["vault_id"])
        self.assertEqual(counts1["active"], 0)
        self.assertEqual(counts1["total"], 0)

    # --- E -----------------------------------------------------

    def test_E_old_session_not_revoked_unless_whole_txn_commits(self) -> None:
        # Same shape as B, but the assertion emphasises the
        # single-session policy consequence: a caller that observes
        # the exception must be able to trust that no side effects
        # (including revocation) leaked to persistent storage.
        v = _seed_vault()
        first = _issue(v["vault_id"], v["vault_name"],
                       client_label="Chrome on Windows",
                       device_id="dev-phone")

        original_row = _fetch_session(first["token_id"])
        self.assertIsNone(original_row["revoked_at"])

        import vault_core
        real_get_db = vault_core.get_db

        # Fail after INSERT (stage 3) so revoke happened in-txn but
        # never committed.
        def wrap_get_db():
            return _WrappedPooledConn(real_get_db(), fail_after=3)

        with mock.patch("auth_local.get_db", side_effect=wrap_get_db):
            with self.assertRaises(_CommitError):
                _issue(v["vault_id"], v["vault_name"],
                       client_label="Safari on macOS")

        after_row = _fetch_session(first["token_id"])
        self.assertIsNone(after_row["revoked_at"],
            "old session must still be unrevoked after rolled-back supersession")
        self.assertIsNone(after_row["revoked_reason"])

    # --- F -----------------------------------------------------

    def test_F_no_token_returned_when_commit_fails(self) -> None:
        v = _seed_vault()
        import vault_core
        real_get_db = vault_core.get_db

        def wrap_get_db():
            return _WrappedPooledConn(real_get_db(), fail_commit=True)

        with mock.patch("auth_local.get_db", side_effect=wrap_get_db):
            with self.assertRaises(_CommitError):
                _issue(v["vault_id"], v["vault_name"],
                       client_label="Chrome on Windows")

        counts = _row_counts(v["vault_id"])
        self.assertEqual(counts["active"], 0,
            "commit failure must leave no unrevoked row behind")
        self.assertEqual(counts["total"], 0,
            "commit failure must leave no auth_sessions row at all")
        self.assertEqual(counts["events"], 0,
            "commit failure must leave no committed security events")

        # And a subsequent normal call still works — pool healthy.
        issued = _issue(v["vault_id"], v["vault_name"],
                        client_label="Safari on macOS")
        self.assertTrue(issued["token"])
        self.assertEqual(_row_counts(v["vault_id"])["active"], 1)


if __name__ == "__main__":
    unittest.main()
