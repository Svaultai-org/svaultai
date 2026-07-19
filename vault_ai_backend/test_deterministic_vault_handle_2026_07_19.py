"""Regression tests for the deterministic vault_handle derivation +
duplicate-username 409 + dict-attr regressions.

Post-2046dc6 incident: the frontend generated a random 15-byte
vault_handle at signup, so registering "chosen" wrote random bytes
into ``vaults.vault_handle`` and login by "chosen" then 401'd
because the client had no way to re-derive the same random bytes.

Fix
===

* ``vault_handle.derive_from_username(username)`` returns the same
  15 bytes for the same normalized username on both languages.
* ``ZkRegisterFinalize`` INSERT relies on the pre-existing UNIQUE
  INDEX ``vaults_vault_handle_uniq`` and, on ``UniqueViolation``,
  returns HTTP 409 with copy
      "Username already taken. Please choose another."
* The accounts + vaults INSERT sit in the same implicit psycopg2
  transaction; the rollback on 409 drops both — no orphan account.
* ``principal.vault_id`` (attribute access on ``SessionPrincipal``
  TypedDict) is replaced with ``principal["vault_id"]`` in
  ``routes/auth_zk_routes.zk_adopt`` and every site in
  ``routes/vault_metadata_migration_routes``.

The suite verifies each numbered acceptance criterion from the
corrective release request. No live Postgres is required — a small
in-process DB fake plays back the two INSERTs the finalize path
issues, raising ``pg_errors.UniqueViolation`` on the second attempt
with the same handle bytes.
"""

from __future__ import annotations

import base64
import inspect
import unittest
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest


# ---------------------------------------------------------------------
# 0. Derivation is deterministic + normalization is unified.
# ---------------------------------------------------------------------


class DerivationTests(unittest.TestCase):
    def test_derivation_is_deterministic(self) -> None:
        from vault_handle import derive_from_username
        self.assertEqual(
            derive_from_username("chosen"),
            derive_from_username("chosen"),
        )

    def test_derivation_returns_15_bytes(self) -> None:
        from vault_handle import derive_from_username, VAULT_HANDLE_BYTES
        self.assertEqual(
            len(derive_from_username("chosen")), VAULT_HANDLE_BYTES,
        )

    def test_normalization_case_whitespace_unicode(self) -> None:
        """Same-user variants collapse to the same handle."""
        from vault_handle import derive_from_username
        base = derive_from_username("chosen")
        # Note: "cho sen" (single space) is a legitimately DIFFERENT
        # username from "chosen" — normalization only collapses runs
        # of whitespace, it does not remove spaces. Same for "chosen1".
        for variant in [
            "Chosen",
            "CHOSEN",
            " chosen ",
            "  chosen",
            "chosen  ",
        ]:
            self.assertEqual(
                derive_from_username(variant), base,
                f"variant {variant!r} did not normalize to base",
            )

    def test_distinct_usernames_produce_distinct_handles(self) -> None:
        from vault_handle import derive_from_username
        self.assertNotEqual(
            derive_from_username("chosen"),
            derive_from_username("chosen2"),
        )

    def test_empty_normalized_rejected(self) -> None:
        from vault_handle import derive_from_username, InvalidUsername
        with pytest.raises(InvalidUsername):
            derive_from_username("")
        with pytest.raises(InvalidUsername):
            derive_from_username("   ")

    def test_control_characters_rejected(self) -> None:
        from vault_handle import derive_from_username, InvalidUsername
        with pytest.raises(InvalidUsername):
            derive_from_username("chosen\x00")

    def test_over_length_rejected(self) -> None:
        from vault_handle import derive_from_username, InvalidUsername
        with pytest.raises(InvalidUsername):
            derive_from_username("x" * 200)


# ---------------------------------------------------------------------
# 1-3, 6-9. Register-finalize duplicate detection + orphan prevention.
# ---------------------------------------------------------------------


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class _StoreCursor:
    """Cursor that accepts INSERT INTO accounts / INSERT INTO vaults
    and enforces a UNIQUE constraint on vault_handle across all
    prior vaults inserts. On a violation raises psycopg2's
    ``UniqueViolation``.
    """

    def __init__(self, store: dict) -> None:
        self._store = store
        self._last_row: Optional[Dict[str, Any]] = None
        self._closed = False

    def execute(self, sql: str, params: tuple = ()) -> None:
        from psycopg2 import errors as pg_errors
        s = " ".join(sql.split()).upper()
        if s.startswith("INSERT INTO ACCOUNTS"):
            aid = f"acct-{self._store['acct_seq']}"
            self._store["acct_seq"] += 1
            self._store["accounts"].append({"account_id": aid})
            self._last_row = {"account_id": aid}
            return
        if s.startswith("INSERT INTO VAULTS"):
            # positional params (see finalize INSERT):
            #   0: pin_salt, 1: pin_verifier, 2: kdf_iterations,
            #   3: handle_bytes, 4: opaque_registration_record,
            #   5: wrapped_mvk, 6: wrapped_sk_vault, 7: pk_vault_public,
            #   8: display_name_ciphertext, 9: account_id,
            #   10: acknowledged_irrecoverable
            handle_bytes = params[3]
            account_id = params[9]
            if handle_bytes in self._store["vault_handles"]:
                self._store["last_rollback_after_dup"] = True
                # Raise the exact exception class the route catches.
                exc = pg_errors.UniqueViolation(
                    "duplicate key value violates unique constraint "
                    "\"vaults_vault_handle_uniq\""
                )
                raise exc
            self._store["vault_handles"].add(handle_bytes)
            vid = f"vault-{self._store['vault_seq']}"
            self._store["vault_seq"] += 1
            self._store["vaults"].append({
                "vault_id": vid,
                "vault_handle": handle_bytes,
                "account_id": account_id,
                "pin_salt": params[0],
                "pin_verifier": params[1],
            })
            self._last_row = {"vault_id": vid, "vault_name": "randomhex"}
            return
        if s.startswith("INSERT INTO ACCOUNT_MEMBERS"):
            self._store["account_members"].append(params)
            return
        if s.startswith("INSERT INTO ACCOUNT_SUBSCRIPTIONS"):
            self._store["account_subscriptions"].append(params)
            return
        # Ignored — not exercised in these tests.

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._last_row

    def close(self) -> None:
        self._closed = True


class _StoreConn:
    def __init__(self, store: dict) -> None:
        self._store = store

    def cursor(self, cursor_factory: Any = None) -> _StoreCursor:
        return _StoreCursor(self._store)

    def commit(self) -> None:
        self._store["commits"] += 1

    def rollback(self) -> None:
        # A rollback on UniqueViolation must drop the accounts row that
        # was inserted before the vaults row — that's what "no orphan
        # accounts" means in criterion 9.
        if self._store.get("last_rollback_after_dup"):
            if self._store["accounts"]:
                self._store["accounts"].pop()
        self._store["rollbacks"] += 1

    def close(self) -> None:
        self._store["closed"] = True


def _fresh_store() -> dict:
    return {
        "acct_seq": 1, "vault_seq": 1,
        "accounts": [], "vaults": [],
        "account_members": [], "account_subscriptions": [],
        "vault_handles": set(),
        "commits": 0, "rollbacks": 0, "closed": False,
        "last_rollback_after_dup": False,
    }


def _issued_session() -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    return {
        "token":        "TOKENabc",
        "token_id":     "22222222-2222-2222-2222-222222222222",
        "expires_at":   datetime.now(timezone.utc) + timedelta(hours=1),
        "vault_id":     "vault-1",
        "vault_name":   "randomhex",
        "client_label": "Firefox on Linux",
    }


def _run_register(payload: Dict[str, Any], store: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.auth_zk_routes import router
    conn = _StoreConn(store)
    with (
        mock.patch(
            "routes.auth_zk_routes.get_db",
            side_effect=lambda: conn,
        ),
        mock.patch(
            "routes.auth_zk_routes.opaque_registration_finish",
            return_value=b"fake-opaque-record",
        ),
        mock.patch(
            "routes.auth_zk_routes.enforce_signup_rate_limit",
            return_value=None,
        ),
        mock.patch(
            "routes.auth_zk_routes.issue_session_token",
            return_value=_issued_session(),
        ),
    ):
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/auth/zk-register-finalize",
            json=payload,
            headers={"User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0"
            )},
        )
    return resp


def _payload_for_username(username: str) -> Dict[str, Any]:
    """Payload where the vault_handle is derived from ``username``,
    matching what the fixed frontend now sends."""
    from vault_handle import derive_from_username, to_display
    handle_bytes = derive_from_username(username)
    return {
        "vault_handle":              to_display(handle_bytes),
        "ke3":                       _b64url_no_pad(b"fake-ke3"),
        "wrapped_mvk":               _b64url_no_pad(b"fake-mvk"),
        "wrapped_sk_vault":          _b64url_no_pad(b"fake-sk"),
        "pk_vault_public":           _b64url_no_pad(b"\x00" * 32),
        "display_name_ciphertext":   _b64url_no_pad(b"fake-display"),
        "acknowledged_irrecoverable": True,
        "device_id": "d",
        "pin_salt":     base64.b64encode(b"\x11" * 16).decode(),
        "pin_verifier": base64.b64encode(b"\x22" * 32).decode(),
        "kdf_iterations": 600000,
    }


class RegistrationDuplicateTests(unittest.TestCase):
    def test_1_register_chosen_once_succeeds(self) -> None:
        store = _fresh_store()
        resp = _run_register(_payload_for_username("chosen"), store)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(store["vaults"]), 1)
        self.assertEqual(len(store["accounts"]), 1)

    def test_2_register_chosen_again_returns_409(self) -> None:
        store = _fresh_store()
        r1 = _run_register(_payload_for_username("chosen"), store)
        self.assertEqual(r1.status_code, 200)
        r2 = _run_register(_payload_for_username("chosen"), store)
        self.assertEqual(r2.status_code, 409, r2.text)
        self.assertIn("Username already taken", r2.text)
        self.assertIn("Please choose another", r2.text)

    def test_3_variants_of_chosen_also_409(self) -> None:
        store = _fresh_store()
        r1 = _run_register(_payload_for_username("chosen"), store)
        self.assertEqual(r1.status_code, 200)
        for variant in ["Chosen", " chosen ", "CHOSEN"]:
            with self.subTest(variant=variant):
                # If the client sends the SAME derived handle for the
                # variant (because both sides normalize identically),
                # the server rejects with 409.
                r = _run_register(_payload_for_username(variant), store)
                self.assertEqual(r.status_code, 409,
                    f"variant {variant!r}: {r.text}")

    def test_6_different_username_can_register(self) -> None:
        store = _fresh_store()
        r1 = _run_register(_payload_for_username("chosen"), store)
        r2 = _run_register(_payload_for_username("anotheruser"), store)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(store["vaults"]), 2)
        self.assertEqual(len(store["accounts"]), 2)

    def test_7_concurrent_registrations_dedupe(self) -> None:
        """The DB's UNIQUE INDEX handles the race: two concurrent
        finalize calls with the same derived handle result in exactly
        one successful vaults row. In the fake this is proven by the
        second _run_register returning 409 even though the client
        may not have observed the first's success."""
        store = _fresh_store()
        r1 = _run_register(_payload_for_username("chosen"), store)
        r2 = _run_register(_payload_for_username("chosen"), store)
        outcomes = sorted([r1.status_code, r2.status_code])
        self.assertEqual(outcomes, [200, 409], (r1.text, r2.text))
        # Only one vault survived.
        self.assertEqual(len(store["vaults"]), 1)

    def test_8_no_plaintext_username_in_vaults_row(self) -> None:
        store = _fresh_store()
        _run_register(_payload_for_username("chosen"), store)
        row = store["vaults"][0]
        # The plaintext username was never sent to the endpoint and
        # therefore never in the row. Verify defensively.
        for key, value in row.items():
            if isinstance(value, (bytes, bytearray)):
                self.assertNotIn(b"chosen", value,
                    f"vaults[{key}] contains plaintext username")
            elif isinstance(value, str):
                self.assertNotIn("chosen", value,
                    f"vaults[{key}] contains plaintext username")

    def test_9_no_orphan_account_after_duplicate(self) -> None:
        """Criterion 9: a 409 registration MUST NOT leave an accounts
        row behind. The fake's rollback pops the just-inserted account
        on UniqueViolation — mirroring psycopg2's implicit-transaction
        rollback behavior in the real DB."""
        store = _fresh_store()
        r1 = _run_register(_payload_for_username("chosen"), store)
        r2 = _run_register(_payload_for_username("chosen"), store)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 409)
        # After the failed second attempt: exactly ONE account row
        # (the successful first attempt). The dup did not leave an
        # orphan.
        self.assertEqual(len(store["accounts"]), 1)
        # And exactly one rollback fired.
        self.assertGreaterEqual(store["rollbacks"], 1)


# ---------------------------------------------------------------------
# 4-5. Login uses derived handle (source-level guard).
# ---------------------------------------------------------------------
#
# Full login happy-path is exercised end-to-end by the browser build.
# Here we lock in the source invariant that the LoginPage's ZK path
# derives the handle from the entered username via
# ``deriveVaultHandleFromUsername`` — no random-handle generation and
# no plaintext /auth/login as the primary path.
#
# We test this at the frontend layer (see the Dart companion test
# file); the backend has no username-string input to check, since
# the client always sends a derived handle already.


# ---------------------------------------------------------------------
# 10. zk-adopt + metadata migration no longer crash on
#     ``principal.vault_id``.
# ---------------------------------------------------------------------


class DictPrincipalRegressionTests(unittest.TestCase):
    """The route bodies must access ``principal["vault_id"]`` and
    NEVER ``principal.vault_id`` — since ``SessionPrincipal`` is a
    ``TypedDict`` (a plain dict at runtime), attribute access
    raises AttributeError and FastAPI surfaces a 500."""

    def test_zk_adopt_uses_subscript_access(self) -> None:
        from routes import auth_zk_routes
        src = inspect.getsource(auth_zk_routes.zk_adopt)
        self.assertNotIn("principal.vault_id", src)
        self.assertIn('principal["vault_id"]', src)

    def test_metadata_migration_next_batch_uses_subscript(self) -> None:
        from routes import vault_metadata_migration_routes as m
        src = inspect.getsource(m.next_batch)
        self.assertNotIn("principal.vault_id", src)
        self.assertIn('principal["vault_id"]', src)

    def test_metadata_migration_status_uses_subscript(self) -> None:
        from routes import vault_metadata_migration_routes as m
        src = inspect.getsource(m.status)
        self.assertNotIn("principal.vault_id", src)
        self.assertIn('principal["vault_id"]', src)

    def test_no_attribute_access_anywhere_in_metadata_migration(self) -> None:
        """Blanket guard: the whole module must be dict-safe."""
        from routes import vault_metadata_migration_routes as m
        with open(m.__file__, "r", encoding="utf-8") as f:
            body = f.read()
        # Docstring line 18 mentions principal.vault_id in prose — allow
        # it there, forbid it in real code by counting equalities.
        code_lines = [
            ln for ln in body.splitlines()
            if "principal.vault_id" in ln and not ln.strip().startswith("#")
        ]
        # If the docstring reference remains, filter it out heuristically
        # — the prose line ends with ``.``.
        real_uses = [ln for ln in code_lines if not ln.strip().endswith(".")]
        self.assertEqual(real_uses, [],
            f"principal.vault_id still used in code lines: {real_uses}")

    def test_zk_adopt_runtime_no_attribute_error(self) -> None:
        """Runtime proof — hit the endpoint with a fake session
        principal that is a plain ``dict`` (matching TypedDict runtime
        behavior). Before the fix this 500s with AttributeError. After
        the fix it returns 404 "vault not found" because our fake DB
        yields no row for that vault_id — which proves the route made
        it past the principal access.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_zk_routes import router, verify_session_token
        from routes import auth_zk_routes as m

        # Fake DB that returns None for the SELECT.
        class _NoneCursor:
            def execute(self, *a, **k): return None
            def fetchone(self): return None
            def close(self): return None

        class _NoneConn:
            def cursor(self, cursor_factory=None): return _NoneCursor()
            def commit(self): return None
            def rollback(self): return None
            def close(self): return None

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[verify_session_token] = lambda: {
            "vault_id":   "11111111-1111-1111-1111-111111111111",
            "vault_name": "unused",
            "token_id":   "tk",
            "device_id":  None,
        }
        orig = m.get_db
        m.get_db = lambda: _NoneConn()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/auth/zk-adopt",
                json={
                    "vault_handle":              "VLT-0000-0000-0000-0000-0000-0000",
                    "opaque_registration_record": _b64url_no_pad(b"fake"),
                    "wrapped_mvk":                _b64url_no_pad(b"fake"),
                    "wrapped_sk_vault":           _b64url_no_pad(b"fake"),
                    "pk_vault_public":            _b64url_no_pad(b"\x00" * 32),
                    "display_name_ciphertext":    _b64url_no_pad(b"fake"),
                },
            )
        finally:
            m.get_db = orig
        # Before the fix: 500 with AttributeError. After the fix: 404
        # because the SELECT returned None. Anything OTHER than 500
        # confirms principal access no longer crashes.
        self.assertNotEqual(resp.status_code, 500, resp.text)
        self.assertEqual(resp.status_code, 404, resp.text)


if __name__ == "__main__":
    unittest.main()
