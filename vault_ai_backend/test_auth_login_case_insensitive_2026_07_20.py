# Legacy /auth/login case-insensitive vault_name lookup (2026-07-20).
#
# ROOT CAUSE this suite locks in:
#
# Under migration 0031 the ``vault_name`` column carries the user-
# chosen product identity, case-preserved by tools.normalize_vault_name.
# ZK signup writes rows like ``vault_name = 'Alexa'``.
#
# The legacy /auth/login endpoint at
# vault_ai_backend/routes/auth_routes.py normalizes the incoming
# ``vault_name`` via ``_normalize_vault_name`` which lowercases,
# then runs ``SELECT ... WHERE vault_name = %s`` (case-sensitive
# equality). For a mixed-case ZK-signup row this query returns zero
# rows and the endpoint raises 401 "Vault name or PIN is incorrect".
#
# On the reload -> /pin path, ``AppState.verifyPin`` in
# vault_ai_frontend/lib/main.dart calls the legacy /auth/login. When
# the row is mixed-case, verifyPin sees the 401 as
# InvalidCredentialsException and returns false. PinGatePage stays on
# /pin and shows "Incorrect PIN. Try again." The user perceives this
# as a PIN loop because their correct PIN is being rejected.
#
# This suite:
#   1. Reproduces the bug against the CURRENT code — the first test
#      is expected to fail with 401 before the fix.
#   2. Adds the regression tests the fix must satisfy AFTER it lands:
#        - mixed-case vault_name + correct PIN succeeds
#        - lowercase legacy account still succeeds
#        - mixed-case + wrong PIN fails
#        - nonexistent vault fails
#        - case-collision preference is deterministic (exact case wins)
#        - case-collision AMBIGUITY (no exact match, multiple case-
#          insensitive candidates) refuses with the generic 401
#   3. Documents the collision-safety design so a future refactor
#      cannot silently regress it.
#
# The test builds an in-memory DB fake around the real /auth/login
# route via FastAPI TestClient. Real crypto (PBKDF2-HMAC-SHA256,
# AES-GCM encrypt/decrypt) runs end-to-end against synthetic
# pin_salt / pin_verifier rows so a genuine "correct PIN" is being
# verified.

from __future__ import annotations

import base64
import copy
import os
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import patch

# Test-only env before importing app code so module import succeeds.
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")
# Force the auth-login rate limit backend to allow everything during
# tests. The default in-memory backend also allows plenty of hits,
# but explicit is better than relying on defaults.
os.environ.setdefault("VAULTAI_AUTH_LOGIN_LIMIT", "10000")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth_local
from routes.auth_routes import router as auth_router, verify_session_token
from vault_handle import to_display as vault_handle_to_display
from vault_core import (
    KDF_LEGACY_ITERATIONS,
    PIN_VERIFIER_PLAINTEXT,
    derive_key,
    encrypt_message,
    generate_pin_salt,
)


# ---------------------------------------------------------------------------
# In-memory DB fake — models only the queries /auth/login issues.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, db: "_InMemoryVaults") -> None:
        self.db = db
        self._pending: list[dict[str, Any]] = []
        self._is_dict_cursor = False

    # Support both cursor(cursor_factory=RealDictCursor) and default.
    def _row(self, r: dict) -> Any:
        return r  # dict-shaped; our tests only inspect via .get/[]

    def execute(self, sql: str, params=None) -> None:
        params = params if params is not None else ()
        norm = " ".join(sql.split()).strip().lower()

        # ---- Legacy SELECT (current buggy shape) ---------------------
        # Exact-case equality lookup.
        if (
            norm.startswith("select vault_id, vault_name, pin_salt, pin_verifier")
            and "where vault_name = %s" in norm
            and "lower(" not in norm
        ):
            (vault_name,) = params
            row = None
            for r in self.db.rows.values():
                if r["vault_name"] == vault_name:
                    row = r
                    break
            self._pending = [self._project(row)] if row else []
            return

        # ---- New SELECT (post-fix shape) -----------------------------
        # Case-insensitive lookup with exact-match column.
        if (
            norm.startswith("select vault_id, vault_name, pin_salt, pin_verifier")
            and "lower(vault_name) = lower(" in norm
        ):
            # params is a dict here (named parameters).
            raw = None
            if isinstance(params, dict):
                raw = params.get("raw") or params.get("vault_name")
            elif isinstance(params, (list, tuple)) and params:
                raw = params[0]
            if raw is None:
                self._pending = []
                return
            raw_l = raw.lower()
            hits = []
            for r in self.db.rows.values():
                if r["vault_name"].lower() == raw_l:
                    projected = self._project(r)
                    projected["is_exact_match"] = (r["vault_name"] == raw)
                    hits.append(projected)
            self._pending = hits
            return

        if (
            norm.startswith("select vault_id, vault_name, display_username, vault_handle")
            and "where vault_id = %s" in norm
        ):
            (vault_id,) = params
            row = self.db.rows.get(str(vault_id))
            if row:
                projected = self._project(row)
                projected["created_at"] = row["created_at"]
                self._pending = [projected]
            else:
                self._pending = []
            return

        # ---- SELECT NOW() --------------------------------------------
        if norm.startswith("select now()"):
            self._pending = [{"now": datetime.now(timezone.utc)}]
            return

        # ---- UPDATE vaults SET failed_pin_attempts | last_login_at ---
        if norm.startswith("update vaults"):
            vault_id = params[-1]  # WHERE vault_id = %s is always last
            row = self.db.rows.get(str(vault_id))
            if row is None:
                self._pending = []
                return
            if "set failed_pin_attempts = 0" in norm and "last_login_at" in norm:
                # Successful login bookkeeping.
                row["failed_pin_attempts"] = 0
                row["locked_until"] = None
            elif "set failed_pin_attempts" in norm and "locked_until = null" in norm:
                # Failed attempt increment (< MAX).
                row["failed_pin_attempts"] = int(params[0])
                row["locked_until"] = None
            elif "locked_until = now()" in norm:
                # Lockout after MAX_PIN_ATTEMPTS.
                row["failed_pin_attempts"] = 0
                row["locked_until"] = datetime.now(timezone.utc)
            self._pending = []
            return

        # ---- trusted_devices SELECT ----------------------------------
        if (
            norm.startswith("select status from trusted_devices")
            and "vault_id = %s" in norm
            and "device_id = %s" in norm
        ):
            self._pending = []  # no existing row
            return

        # ---- trusted_devices INSERT (upsert) -------------------------
        if norm.startswith("insert into trusted_devices"):
            self._pending = []
            return

        raise AssertionError(
            f"unexpected SQL in fake cursor: {norm!r} params={params!r}"
        )

    def _project(self, r: dict) -> dict:
        return {
            "vault_id":            r["vault_id"],
            "vault_name":          r["vault_name"],
            "pin_salt":            r["pin_salt"],
            "pin_verifier":        r["pin_verifier"],
            "kdf_iterations":      r["kdf_iterations"],
            "failed_pin_attempts": r.get("failed_pin_attempts", 0),
            "locked_until":        r.get("locked_until"),
            "must_reset":          r.get("must_reset", False),
            "display_username":    r.get("display_username"),
            "vault_handle":        r.get("vault_handle"),
        }

    def fetchone(self) -> Optional[dict]:
        return self._pending.pop(0) if self._pending else None

    def fetchall(self) -> list[dict]:
        rows = list(self._pending)
        self._pending.clear()
        return rows


class _FakeConn:
    def __init__(self, db: "_InMemoryVaults") -> None:
        self.db = db
        self._cursor = _FakeCursor(db)

    def cursor(self, *_args, **_kwargs) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None: pass
    def rollback(self) -> None: pass
    def close(self) -> None: pass


class _InMemoryVaults:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def add_vault(
        self, *, vault_name: str, pin: str,
        iterations: int = KDF_LEGACY_ITERATIONS,
        display_username: Optional[str] = None,
        must_reset: bool = False,
        vault_handle: Optional[bytes] = None,
    ) -> str:
        pin_salt = generate_pin_salt()
        key = derive_key(pin, pin_salt, iterations=iterations)
        pin_verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, key)
        vault_id = str(uuid.uuid4())
        self.rows[vault_id] = {
            "vault_id":            vault_id,
            "vault_name":          vault_name,
            "pin_salt":            pin_salt,
            "pin_verifier":        pin_verifier,
            "kdf_iterations":      iterations,
            "failed_pin_attempts": 0,
            "locked_until":        None,
            "must_reset":          must_reset,
            "display_username":    display_username,
            "vault_handle":        vault_handle,
            "created_at":          datetime.now(timezone.utc),
        }
        return vault_id


# ---------------------------------------------------------------------------
# TestClient harness
# ---------------------------------------------------------------------------


def _make_client(db: _InMemoryVaults) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


class _AuthLoginTestBase(unittest.TestCase):
    def setUp(self) -> None:
        auth_local.reset_secret_for_tests()
        self.db = _InMemoryVaults()
        self.client = _make_client(self.db)
        # Patch get_db everywhere the /auth/login path reads it.
        # We stub issue_session_token — the endpoint's session-issuance
        # code path is tested elsewhere; this suite only exercises the
        # vault_name lookup + PIN-verifier decrypt logic and asserts on
        # the response shape.
        def _fake_issue(*, vault_id, vault_name, device_id=None,
                        client_label, ttl_hours=None):
            return {
                "token":      "test-token-" + vault_id[:8],
                "vault_id":   vault_id,
                "vault_name": vault_name,
                "expires_at": datetime.now(timezone.utc),
            }
        self._patches = [
            patch("routes.auth_routes.get_db", lambda: _FakeConn(self.db)),
            patch("vault_core.get_db", lambda: _FakeConn(self.db)),
            patch("routes.auth_routes.issue_session_token",
                  side_effect=_fake_issue),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()


# ---------------------------------------------------------------------------
# 1. Reproduction test — FAILS on the buggy code, PASSES on the fixed code.
# ---------------------------------------------------------------------------


class MixedCaseVaultNameLoginReproTests(_AuthLoginTestBase):
    """Reproduces the production PIN-loop RC.

    Before the fix:  test_mixed_case_login_succeeds fails with 401.
    After  the fix:  it passes with 200.
    """

    def test_mixed_case_login_succeeds(self) -> None:
        # Precisely models a ZK-adopted account whose product-facing
        # vault_name was stored case-preserved (see
        # tools.normalize_vault_name and routes/auth_zk_routes.py:420).
        self.db.add_vault(vault_name="Alexa", pin="123456")

        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "Alexa", "pin": "123456"},
        )
        self.assertEqual(
            resp.status_code, 200,
            f"mixed-case vault_name+correct PIN must authenticate; "
            f"got {resp.status_code} {resp.text}",
        )
        body = resp.json()
        self.assertTrue(body["session_token"])
        # The response echoes the row's stored value (case-preserved).
        self.assertEqual(body["vault_name"], "Alexa")


class ZkHandleAuthResponseTests(_AuthLoginTestBase):
    def test_auth_login_returns_vault_handle_for_zk_adopted_row(self) -> None:
        handle = bytes(range(15))
        expected = vault_handle_to_display(handle)
        self.db.add_vault(
            vault_name="Chosen",
            pin="123456",
            vault_handle=handle,
        )

        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "Chosen", "pin": "123456"},
        )

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["vault_handle"], expected)
        self.assertTrue(body["zk"])

    def test_auth_me_returns_vault_handle_for_authenticated_zk_row(self) -> None:
        handle = bytes(range(15))
        expected = vault_handle_to_display(handle)
        vault_id = self.db.add_vault(
            vault_name="Chosen",
            pin="123456",
            vault_handle=handle,
        )
        self.client.app.dependency_overrides[verify_session_token] = lambda: {
            "vault_id": vault_id,
            "vault_name": "Chosen",
        }

        try:
            resp = self.client.get(
                "/auth/me",
                headers={"Authorization": "Bearer test-token"},
            )
        finally:
            self.client.app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["vault_handle"], expected)
        self.assertTrue(body["zk"])


# ---------------------------------------------------------------------------
# 2. Regression suite — must all pass after the fix.
# ---------------------------------------------------------------------------


class LoginRegressionSuite(_AuthLoginTestBase):
    def test_lowercase_legacy_account_still_succeeds(self) -> None:
        # Legacy accounts (pre-migration 0031) were validated with
        # VAULT_NAME_PATTERN = ^[a-z0-9][a-z0-9_-]{2,49}$, so all live
        # legacy rows are lowercase-only. The fix must not regress
        # this path.
        self.db.add_vault(vault_name="alice-legacy", pin="654321")

        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "alice-legacy", "pin": "654321"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_mixed_case_wrong_pin_still_401(self) -> None:
        self.db.add_vault(vault_name="Alexa", pin="123456")

        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "Alexa", "pin": "000000"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_nonexistent_vault_still_401(self) -> None:
        # No rows in the DB at all — must not authenticate anything.
        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "Ghost", "pin": "123456"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_case_variant_of_lowercase_account_succeeds(self) -> None:
        # Legacy lowercase row + user types uppercase. Should still
        # find the vault (case-insensitive fallback). If the ONLY
        # row for LOWER("alice") is "alice", that IS the row we
        # want — no ambiguity.
        self.db.add_vault(vault_name="alice-legacy", pin="654321")

        resp = self.client.post(
            "/auth/login",
            json={"vault_name": "ALICE-LEGACY", "pin": "654321"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)


class CaseCollisionPreferenceTests(_AuthLoginTestBase):
    """Case-collision safety.

    If two rows exist that only differ by case (e.g. legacy "alice" +
    ZK-adopted "Alice"), the endpoint must:

      * Return the EXACT case match when one exists (deterministic;
        never authenticates the wrong row).
      * Refuse with the same generic 401 when NO exact match exists
        and multiple case-insensitive candidates do (never falls
        back to an arbitrary tiebreak that could authenticate the
        wrong vault).
    """

    def test_exact_case_wins_when_collision_exists(self) -> None:
        # Two vaults with case-collided names, DIFFERENT pin_verifiers.
        # A login for "Alice" with Alice's PIN must succeed as Alice.
        # A login for "alice" with alice's PIN must succeed as alice.
        # A login for "Alice" with alice's PIN must NOT succeed.
        self.db.add_vault(vault_name="alice", pin="000001")
        self.db.add_vault(vault_name="Alice", pin="999999")

        r1 = self.client.post(
            "/auth/login",
            json={"vault_name": "Alice", "pin": "999999"},
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r1.json()["vault_name"], "Alice",
            "exact-case match must be selected — never the case-collided row")

        r2 = self.client.post(
            "/auth/login",
            json={"vault_name": "alice", "pin": "000001"},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["vault_name"], "alice")

        # Cross-PIN attempt: Alice's typed casing + alice's PIN.
        # The exact-case match "Alice" is selected first; its
        # pin_verifier does not match alice's PIN -> 401. This
        # proves the exact-case row is used (else alice's PIN
        # would have matched alice's verifier and yielded 200).
        r3 = self.client.post(
            "/auth/login",
            json={"vault_name": "Alice", "pin": "000001"},
        )
        self.assertEqual(r3.status_code, 401,
            "case-collided PIN must NOT authenticate the other vault")

    def test_ambiguous_case_lookup_refuses_with_401(self) -> None:
        # Two rows differ only in case, but the client types a THIRD
        # casing that matches NEITHER exactly. The endpoint MUST NOT
        # arbitrarily pick one (that could authenticate the wrong
        # vault). It must refuse with the same generic 401 that a
        # nonexistent vault produces.
        self.db.add_vault(vault_name="alice", pin="000001")
        self.db.add_vault(vault_name="Alice", pin="999999")

        r = self.client.post(
            "/auth/login",
            json={"vault_name": "ALICE", "pin": "000001"},
        )
        self.assertEqual(r.status_code, 401,
            "ambiguous case-insensitive lookup with no exact match must "
            "refuse to authenticate; NEVER silently pick one row")
        # The response must not leak WHICH row would have matched.
        self.assertIn("Vault name or PIN is incorrect", r.text)


class CollisionSchemaAuditTests(unittest.TestCase):
    """Prove where case-colliding vault_name rows can and cannot
    arise. If a future migration adds case-insensitive uniqueness at
    the schema level, the ``test_ambiguous_case_lookup_refuses_with_401``
    guard becomes belt-and-suspenders."""

    def test_legacy_signup_pattern_forces_lowercase(self) -> None:
        # Legacy signup's VAULT_NAME_PATTERN cannot produce two
        # rows that differ by case for the same canonical name —
        # both would normalize to the same lowercase string and
        # the UNIQUE(vault_name) index would refuse the second
        # insert. So legacy signup ALONE cannot produce a
        # case-collision.
        import re
        from routes.auth_routes import VAULT_NAME_PATTERN
        for lowered in ("alice", "bob-2", "carla_v3"):
            self.assertTrue(VAULT_NAME_PATTERN.match(lowered))
        for mixed in ("Alice", "Bob-2", "CARLA_V3"):
            self.assertIsNone(VAULT_NAME_PATTERN.match(mixed))

    def test_zk_signup_normalizer_preserves_case(self) -> None:
        # ZK signup uses tools.normalize_vault_name which preserves
        # case. Combined with the case-sensitive UNIQUE(vault_name)
        # index this MEANS: two rows can differ by case ONLY IF a
        # legacy account was created first ("alice") AND a ZK signup
        # then created "Alice" (or vice versa). ZK signup's own
        # ``username_lookup_v1`` uniqueness collides both, so two
        # ZK-signed-up rows cannot case-collide. But legacy + ZK
        # cross-collision IS reachable and is what the ambiguous-
        # lookup guard protects against.
        from tools import normalize_vault_name
        self.assertEqual(normalize_vault_name("Alexa"), "Alexa")
        self.assertEqual(normalize_vault_name("  Alexa  "), "Alexa")
        self.assertEqual(normalize_vault_name("alice"), "alice")


if __name__ == "__main__":
    unittest.main()
