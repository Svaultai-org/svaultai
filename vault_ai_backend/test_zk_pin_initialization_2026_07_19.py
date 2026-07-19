"""Corrective-release regression tests (2026-07-19).

Production incident recap
=========================

After deploying commit ``828ad4d`` the operator observed:

* A newly registered beneficiary hitting ``POST /beneficiary/link``
  received HTTP 400 with detail ``"PIN not initialized"``.

Root cause
==========

``POST /auth/zk-register-finalize`` previously wrote empty strings
into ``vaults.pin_salt`` and ``vaults.pin_verifier``. The legacy
``verify_vault_pin`` helper — still invoked defensively by
``/beneficiary/link`` — treats empty strings as unset and raises
``HTTP 400 "PIN not initialized"``. Every ZK-registered account was
therefore unable to pair as a beneficiary immediately after signup.

Fix
===

``ZkRegisterFinalizeRequest`` now REQUIRES three additional fields,
supplied by the client and derived locally under the same PIN the
user types:

  * ``pin_salt``       — base64(16 random bytes)
  * ``pin_verifier``   — base64(nonce || AES-GCM(PIN_VERIFIER_PLAINTEXT))
                         keyed by PBKDF2-HMAC-SHA256(pin, salt, N)
  * ``kdf_iterations`` — integer in [100_000, 2_000_000]

These are inserted into ``vaults`` verbatim. The plaintext PIN is
never sent — this preserves the ZK property while still populating
the legacy row shape the beneficiary-link path relies on.

Tests
=====

The suite exercises the actual FastAPI route with the DB seam and
OPAQUE primitive mocked (matching the existing pattern in
``test_auth_zk_finalize_issue_bug_2026_07_16.py``):

  * ``missing_pin_salt_is_422`` / ``missing_pin_verifier_is_422`` /
    ``missing_kdf_iterations_is_422`` — the new fields are required.
  * ``kdf_iterations_below_100k_rejected`` /
    ``kdf_iterations_above_2m_rejected`` — bounds enforced.
  * ``pin_state_reaches_vaults_insert`` — the exact values from the
    request body are the ones passed to the ``vaults`` INSERT.
  * ``zk_adopt_no_longer_wipes_pin_state`` — adoption preserves the
    legacy user's existing pin_salt / pin_verifier so beneficiary
    linking keeps working for adopted accounts.

No live Postgres or opaque wheel is required.
"""

from __future__ import annotations

import base64
import unittest
from typing import Any, Dict, List, Optional
from unittest import mock


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


# --- Fake DB shims (mirror the pattern from the sibling test file) ---


class _RecordingCursor:
    """Cursor that records the params passed to ``execute()``."""

    def __init__(
        self, fetchone_results: List[Optional[Dict[str, Any]]]
    ) -> None:
        self._queue = list(fetchone_results)
        self.calls: List[tuple] = []

    def execute(self, sql: str, params: Optional[tuple] = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def close(self) -> None:
        pass


class _RecordingConn:
    def __init__(
        self, fetchone_results: List[Optional[Dict[str, Any]]]
    ) -> None:
        self._results = fetchone_results
        self.cursors: List[_RecordingCursor] = []

    def cursor(self, cursor_factory: Any = None) -> _RecordingCursor:
        c = _RecordingCursor(self._results)
        self.cursors.append(c)
        return c

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _make_get_db(results: List[Optional[Dict[str, Any]]]):
    """Return (factory, conn_holder) — the factory hands out ONE conn."""
    conn = _RecordingConn(results)

    def factory() -> _RecordingConn:
        return conn

    return factory, conn


def _build_app():
    from fastapi import FastAPI
    from routes.auth_zk_routes import router
    app = FastAPI()
    app.include_router(router)
    return app


# --- Test constants ---


_VAULT_ID = "11111111-1111-1111-1111-111111111111"
_VAULT_NAME = "abc123def456abcd"
_ACCOUNT_ID = "33333333-3333-3333-3333-333333333333"


def _base_payload() -> Dict[str, Any]:
    from vault_handle import to_display
    return {
        "vault_handle":              to_display(bytes(range(15))),
        "ke3":                       _b64url_no_pad(b"fake-ke3"),
        "wrapped_mvk":               _b64url_no_pad(b"fake-mvk"),
        "wrapped_sk_vault":          _b64url_no_pad(b"fake-sk"),
        "pk_vault_public":           _b64url_no_pad(b"\x00" * 32),
        "display_name_ciphertext":   _b64url_no_pad(b"fake-display"),
        "acknowledged_irrecoverable": True,
        "pin_salt":     base64.b64encode(b"\x11" * 16).decode(),
        "pin_verifier": base64.b64encode(b"\x22" * 32).decode(),
        "kdf_iterations": 600000,
    }


def _issued_session() -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    return {
        "token":        "TOKEN123",
        "token_id":     "22222222-2222-2222-2222-222222222222",
        "expires_at":   datetime.now(timezone.utc) + timedelta(hours=1),
        "vault_id":     _VAULT_ID,
        "vault_name":   _VAULT_NAME,
        "client_label": "Firefox on Linux",
    }


def _run_register(payload: Dict[str, Any]):
    """Drive POST /auth/zk-register-finalize and return the response."""
    from fastapi.testclient import TestClient
    get_db, conn = _make_get_db([
        {"account_id": _ACCOUNT_ID},
        {"vault_id": _VAULT_ID, "vault_name": _VAULT_NAME},
    ])
    with (
        mock.patch(
            "routes.auth_zk_routes.get_db",
            side_effect=get_db,
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
        app = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/auth/zk-register-finalize",
            json=payload,
            headers={"User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Firefox/126.0"
            )},
        )
    return resp, conn


# ---------------------------------------------------------------------
# 1. Required-field validation
# ---------------------------------------------------------------------


class RequiredFieldTests(unittest.TestCase):
    """The three new fields are REQUIRED. Missing → HTTP 422."""

    def test_missing_pin_salt_is_422(self) -> None:
        p = _base_payload()
        p.pop("pin_salt")
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("pin_salt", resp.text)

    def test_missing_pin_verifier_is_422(self) -> None:
        p = _base_payload()
        p.pop("pin_verifier")
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("pin_verifier", resp.text)

    def test_missing_kdf_iterations_is_422(self) -> None:
        p = _base_payload()
        p.pop("kdf_iterations")
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("kdf_iterations", resp.text)


class BoundsTests(unittest.TestCase):
    """Iteration bounds guard against too-cheap or absurd values."""

    def test_kdf_iterations_below_100k_rejected(self) -> None:
        p = _base_payload()
        p["kdf_iterations"] = 50_000
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)

    def test_kdf_iterations_above_2m_rejected(self) -> None:
        p = _base_payload()
        p["kdf_iterations"] = 2_000_001
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)

    def test_kdf_iterations_at_100k_boundary_accepted(self) -> None:
        p = _base_payload()
        p["kdf_iterations"] = 100_000
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 200, resp.text)


# ---------------------------------------------------------------------
# 2. Values reach the vaults INSERT
# ---------------------------------------------------------------------


class VaultsInsertTests(unittest.TestCase):
    """The exact ``pin_salt`` / ``pin_verifier`` / ``kdf_iterations``
    values from the request body must be passed to the ``vaults``
    INSERT. The old code hard-coded '' — this is the actual regression
    test.
    """

    def test_pin_state_reaches_vaults_insert(self) -> None:
        p = _base_payload()
        p["pin_salt"] = base64.b64encode(b"AA" * 8).decode()
        p["pin_verifier"] = base64.b64encode(b"BB" * 24).decode()
        p["kdf_iterations"] = 800000
        resp, conn = _run_register(p)
        self.assertEqual(resp.status_code, 200, resp.text)

        # Find the INSERT INTO vaults call.
        vault_insert = None
        for cur in conn.cursors:
            for sql, params in cur.calls:
                if "INSERT INTO vaults" in sql:
                    vault_insert = (sql, params)
                    break
            if vault_insert:
                break
        self.assertIsNotNone(
            vault_insert,
            "no INSERT INTO vaults recorded — route path changed?",
        )
        _sql, params = vault_insert
        # Positional order (see routes/auth_zk_routes.py finalize):
        #   %s pin_salt, %s pin_verifier, %s kdf_iterations, ...
        self.assertEqual(params[0], p["pin_salt"])
        self.assertEqual(params[1], p["pin_verifier"])
        self.assertEqual(params[2], p["kdf_iterations"])
        # And empty strings must NEVER be silently substituted.
        self.assertNotEqual(params[0], "")
        self.assertNotEqual(params[1], "")

    def test_no_empty_string_pin_state_falls_through(self) -> None:
        """Even if a caller sends an empty string (they can't; min_length=1
        blocks it), the endpoint must reject with 422 rather than
        silently storing empty state that would trip
        ``verify_vault_pin`` later.
        """
        p = _base_payload()
        p["pin_salt"] = ""
        resp, _ = _run_register(p)
        self.assertEqual(resp.status_code, 422, resp.text)


# ---------------------------------------------------------------------
# 3. Adoption preserves legacy PIN state
# ---------------------------------------------------------------------


class AdoptPreservesPinTests(unittest.TestCase):
    """``/auth/zk-adopt`` used to wipe pin_salt / pin_verifier to ''.
    That broke the beneficiary-link PIN check for legacy users who
    adopted ZK. Post-fix, the UPDATE must NOT touch either column.
    """

    def test_adopt_update_does_not_reset_pin_state(self) -> None:
        # Read the SQL source of the endpoint and confirm the UPDATE
        # no longer references pin_salt / pin_verifier. This is a
        # source-level guard because the row-level effect is a
        # non-write and would require a real DB round-trip to observe.
        import inspect
        from routes import auth_zk_routes as m
        src = inspect.getsource(m.zk_adopt)
        # The UPDATE block runs against the ``vaults`` row.
        self.assertNotIn("pin_salt                      = ''", src)
        self.assertNotIn("pin_verifier                  = ''", src)
        # The comment explaining why must be present as a permanent
        # forward-guard.
        self.assertIn("preserves the legacy pin_salt", src.lower(),
                      "the intent comment was removed — future refactor "
                      "may re-wipe pin_salt without realizing why")


if __name__ == "__main__":
    unittest.main()
