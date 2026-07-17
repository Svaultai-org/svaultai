"""
Regression tests for the missing ``vault_name`` kwarg in both ZK
finalize paths (Step B.1 of the single-session hardening plan).

At HEAD (production commit 506563a), the two OPAQUE finalize routes
call ``issue_session_token(vault_id=..., device_id=...)`` and omit the
required keyword-only argument ``vault_name`` declared at
``auth_local.issue_session_token``. Python raises

    TypeError: issue_session_token() missing 1 required keyword-only
    argument: 'vault_name'

at the call site, which FastAPI surfaces as HTTP 500. The two
endpoints are unusable in production. Step B.1 fixes both call sites
and, in the same diff, adds a required ``client_label`` kwarg that
must be derived server-side from the HTTP User-Agent so every
issuance path is forced to supply a normalized audit label.

**This file exercises RUNTIME BEHAVIOR only. It does not inspect
Python source, does not use ``inspect.getsource``, and does not
grep call sites for literal argument spellings.**

Sections
--------

1. ``IssueSessionTokenSignatureContractTests``
   The function refuses calls missing ``vault_name`` or
   ``client_label`` at the signature level. These calls raise
   ``TypeError`` naming the missing kwarg. Permanent guards; pass
   before and after the fix.

2. ``NormalizeClientLabelTests``
   The server-side User-Agent normalizer. Coarse allow-list, length
   capped, "Unknown device" default, full UA never returned.

3. ``ZkRegisterFinalizeBehavioralTests``
4. ``ZkLoginFinalizeBehavioralTests``
   Both ZK finalize routes are invoked via ``fastapi.testclient.
   TestClient`` with dependency-isolated fakes for the DB, OPAQUE
   primitive, and rate limiter. ``issue_session_token`` is patched
   with a recording ``MagicMock`` that returns a valid
   ``IssuedSession`` shape. Assertions cover:
     * response status is 200
     * response ``session_token`` is a STRING (not the full
       ``IssuedSession`` dict — regression against the pre-fix bug
       where the whole dict was passed to a Pydantic string field)
     * the recorded call kwargs contain ``vault_id``, ``vault_name``,
       ``device_id``, and a normalized ``client_label``
     * no ``TypeError`` propagates through the FastAPI stack
     * captured logs at INFO+ contain neither the raw User-Agent
       nor the derived ``client_label`` value

5. ``SignupBehavioralWiringTest`` / ``LegacyLoginBehavioralWiringTest``
   Same patch pattern for the two ``auth_routes.py`` issuance sites
   (signup, legacy login). Verifies ``client_label`` reaches
   ``issue_session_token``. These routes are exercised via a direct
   invocation of a stubbed request rather than TestClient because the
   surrounding PBKDF2/DB machinery is heavier than the assertion
   requires; the point is only that the wiring passes the right
   kwarg through.

6. ``ZkFinalizeRealDbIntegrationTests``
   Real Postgres round-trip. Gated on ``VAULTAI_TEST_DATABASE_URL``
   AND the ``vaultai_opaque_server`` pyo3 wheel. Executes the actual
   INSERT into ``auth_sessions`` via a monkey-patched OPAQUE finalize
   primitive (so we can run the DB path without a Rust build). When
   both prerequisites are present:
     * ZK register-finalize creates exactly one ``auth_sessions``
       row for the returned vault_id
     * ZK login-finalize creates a fresh ``auth_sessions`` row after
       a synthetic prior registration
     * the returned ``session_token`` parses back via
       ``auth_local._parse_token`` and its 16-byte token_id maps to
       the SAME row that was just INSERTed
   These tests SKIP when either prerequisite is missing. Skips are
   NOT completion evidence — they must actually run in a Linux CI
   with the Docker builder stage prerequisites installed.

No secrets, tokens, or hashes are captured or logged. UA strings used
in tests are synthetic well-known patterns. Vault handles and IDs
used in mocks are deterministic UUID literals.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

import auth_local


# ============================================================
# 1. Signature contract — permanent behavioral guards
# ============================================================


class IssueSessionTokenSignatureContractTests(unittest.TestCase):
    """
    ``issue_session_token`` must reject any call that omits the
    required identity/context kwargs. Exercises the actual callable;
    no source inspection.
    """

    _DUMMY_VAULT_ID = "00000000-0000-0000-0000-000000000001"

    def test_missing_vault_name_raises_type_error(self) -> None:
        with self.assertRaises(TypeError) as cm:
            auth_local.issue_session_token(
                vault_id=self._DUMMY_VAULT_ID,
                device_id=None,
            )
        self.assertIn("vault_name", str(cm.exception))

    def test_missing_client_label_raises_type_error(self) -> None:
        with self.assertRaises(TypeError) as cm:
            auth_local.issue_session_token(
                vault_id=self._DUMMY_VAULT_ID,
                vault_name="test-vault",
                device_id=None,
            )
        self.assertIn("client_label", str(cm.exception))


# ============================================================
# 2. Normalize client label — behavioral
# ============================================================


class NormalizeClientLabelTests(unittest.TestCase):
    """
    ``normalize_client_label(user_agent)`` returns a coarse label
    from a fixed allow-list. Empty/unknown returns ``"Unknown
    device"``. Full UA never returned; result never exceeds 64 chars.
    """

    def test_none_input_returns_unknown_device(self) -> None:
        self.assertEqual(auth_local.normalize_client_label(None), "Unknown device")

    def test_empty_string_returns_unknown_device(self) -> None:
        self.assertEqual(auth_local.normalize_client_label(""), "Unknown device")

    def test_whitespace_only_returns_unknown_device(self) -> None:
        self.assertEqual(auth_local.normalize_client_label("   "), "Unknown device")

    def test_gibberish_returns_unknown_device(self) -> None:
        self.assertEqual(auth_local.normalize_client_label("XXXXXXXX"), "Unknown device")

    def test_chrome_on_windows(self) -> None:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        self.assertEqual(auth_local.normalize_client_label(ua), "Chrome on Windows")

    def test_edge_on_windows_beats_chrome(self) -> None:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
        )
        self.assertEqual(auth_local.normalize_client_label(ua), "Edge on Windows")

    def test_firefox_on_linux(self) -> None:
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
        self.assertEqual(auth_local.normalize_client_label(ua), "Firefox on Linux")

    def test_safari_on_ios_beats_macos(self) -> None:
        ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
            "Mobile/15E148 Safari/604.1"
        )
        self.assertEqual(auth_local.normalize_client_label(ua), "Safari on iOS")

    def test_chrome_on_android(self) -> None:
        ua = (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
        )
        self.assertEqual(auth_local.normalize_client_label(ua), "Chrome on Android")

    def test_safari_on_macos(self) -> None:
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
            "Safari/605.1.15"
        )
        self.assertEqual(auth_local.normalize_client_label(ua), "Safari on macOS")

    def test_length_capped_at_64_chars(self) -> None:
        result = auth_local.normalize_client_label(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0"
        )
        self.assertLessEqual(len(result), 64)

    def test_ten_kilobyte_ua_does_not_crash_and_does_not_leak(self) -> None:
        big = "X" * (10 * 1024)
        self.assertEqual(auth_local.normalize_client_label(big), "Unknown device")

    def test_full_ua_never_appears_in_result(self) -> None:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0"
        )
        result = auth_local.normalize_client_label(ua)
        self.assertNotIn("Mozilla", result)
        self.assertNotIn("AppleWebKit", result)
        self.assertNotIn("Win64", result)
        self.assertNotIn("126.0.0.0", result)

    def test_non_string_input_returns_unknown_device(self) -> None:
        self.assertEqual(auth_local.normalize_client_label(12345), "Unknown device")   # type: ignore[arg-type]
        self.assertEqual(auth_local.normalize_client_label([]), "Unknown device")      # type: ignore[arg-type]


# ============================================================
# 3+4. TestClient behavioral fixtures for the ZK finalize routes.
#
# Structure: a small ``_FakeConn`` / ``_FakeCursor`` pair plays back a
# preset sequence of ``fetchone()`` results. The route code executes
# unchanged; only its I/O boundaries (DB, OPAQUE, rate limit,
# ``issue_session_token``) are stubbed.
# ============================================================


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class _FakeCursor:
    """Playback cursor. ``fetchone`` pops from a preset list."""

    def __init__(self, fetchone_results: List[Optional[Dict[str, Any]]]) -> None:
        self._queue = list(fetchone_results)
        self.executed: List[str] = []

    def execute(self, sql: str, params: Optional[tuple] = None) -> None:
        self.executed.append(sql)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = list(self._queue)
        self._queue.clear()
        return rows

    def close(self) -> None:
        pass


class _FakeConn:
    """Playback connection. Yields fresh ``_FakeCursor`` copies."""

    def __init__(self, fetchone_results: List[Optional[Dict[str, Any]]]) -> None:
        self._results = fetchone_results
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, cursor_factory: Any = None) -> _FakeCursor:
        return _FakeCursor(self._results)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _make_get_db_playback(*conn_result_sequences: List[Optional[Dict[str, Any]]]):
    """
    Return a callable suitable for ``mock.patch(...).side_effect`` that
    hands out a fresh ``_FakeConn`` on each ``get_db()`` invocation,
    each with its own preset ``fetchone`` sequence.
    """
    conns = [_FakeConn(list(seq)) for seq in conn_result_sequences]
    it = iter(conns)

    def factory() -> _FakeConn:
        return next(it)

    factory.conns = conns  # attach for post-run inspection
    return factory


def _build_zk_test_app():
    from fastapi import FastAPI
    from routes.auth_zk_routes import router as zk_router

    app = FastAPI()
    app.include_router(zk_router)
    return app


class _ZkRouteHarness(unittest.TestCase):
    """Base helpers shared by both finalize behavioral tests."""

    _VALID_HANDLE_BYTES = bytes(range(15))       # deterministic 15-byte handle
    _VAULT_ID = "11111111-1111-1111-1111-111111111111"
    _VAULT_NAME = "abc123def456abcd"
    _DEVICE_ID = "device-42"

    _CHROME_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    _EXPECTED_LABEL = "Chrome on Windows"

    def _mock_issued_session(self, token_str: str = "FAKESIGNEDTOKEN") -> Dict[str, Any]:
        return {
            "token":        token_str,
            "token_id":     "22222222-2222-2222-2222-222222222222",
            "expires_at":   datetime.now(timezone.utc) + timedelta(hours=1),
            "vault_id":     self._VAULT_ID,
            "vault_name":   self._VAULT_NAME,
            "client_label": self._EXPECTED_LABEL,
        }


# ------------------------------------------------------------
# 3. ZK REGISTER FINALIZE
# ------------------------------------------------------------


class ZkRegisterFinalizeBehavioralTests(_ZkRouteHarness):
    """
    Invokes ``POST /auth/zk-register-finalize`` through TestClient with
    dependency-isolated fakes. Asserts the call kwargs into
    ``issue_session_token`` and the response shape.
    """

    def _valid_payload(self) -> Dict[str, Any]:
        from vault_handle import to_display
        return {
            "vault_handle":              to_display(self._VALID_HANDLE_BYTES),
            "ke3":                       _b64url_no_pad(b"fake-ke3-payload"),
            "wrapped_mvk":               _b64url_no_pad(b"fake-wrapped-mvk-bytes"),
            "wrapped_sk_vault":          _b64url_no_pad(b"fake-wrapped-sk-vault-bytes"),
            "pk_vault_public":           _b64url_no_pad(b"\x00" * 32),
            "display_name_ciphertext":   _b64url_no_pad(b"fake-display-name-ciphertext"),
            "acknowledged_irrecoverable": True,
            "device_id":                 self._DEVICE_ID,
        }

    def _run_route(self, mock_issue_return: Dict[str, Any]) -> tuple:
        """Return (response, issue_session_token_mock)."""
        from fastapi.testclient import TestClient

        # get_db() is called ONCE by zk_register_finalize.
        # Cursor fetchone sequence:
        #   1) INSERT INTO accounts RETURNING account_id
        #   2) INSERT INTO vaults RETURNING vault_id, vault_name
        get_db = _make_get_db_playback([
            {"account_id": "33333333-3333-3333-3333-333333333333"},
            {"vault_id": self._VAULT_ID, "vault_name": self._VAULT_NAME},
        ])

        with mock.patch("routes.auth_zk_routes.get_db", side_effect=get_db), \
             mock.patch(
                 "routes.auth_zk_routes.opaque_registration_finish",
                 return_value=b"fake-opaque-record",
             ), \
             mock.patch(
                 "routes.auth_zk_routes.enforce_signup_rate_limit",
                 return_value=None,
             ), \
             mock.patch(
                 "routes.auth_zk_routes.issue_session_token",
                 return_value=mock_issue_return,
             ) as m_issue:
            app = _build_zk_test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/auth/zk-register-finalize",
                json=self._valid_payload(),
                headers={"User-Agent": self._CHROME_UA},
            )
        return resp, m_issue

    def test_happy_path_returns_200_no_typeerror(self) -> None:
        resp, _ = self._run_route(self._mock_issued_session())
        self.assertEqual(
            resp.status_code, 200,
            f"expected 200 (fix in place); got {resp.status_code} body={resp.text[:200]!r}",
        )

    def test_response_session_token_is_string_not_dict(self) -> None:
        """
        Regression: pre-fix, the route was passing the whole
        ``IssuedSession`` dict as ``session_token=token``. After the
        fix (``session_token=token["token"]``), the response body's
        ``session_token`` field must be a bare string equal to the
        token returned by ``issue_session_token``.
        """
        resp, _ = self._run_route(self._mock_issued_session(token_str="ABCDEFGH"))
        body = resp.json()
        self.assertIsInstance(body.get("session_token"), str,
            f"session_token must be a string; got {type(body.get('session_token')).__name__}")
        self.assertEqual(body["session_token"], "ABCDEFGH")
        # If a dict ever slipped through the Pydantic response model,
        # a full serialized shape would appear; assert none of its keys leak.
        self.assertNotIn("token_id", body)
        self.assertNotIn("expires_at", body)
        self.assertNotIn("client_label", body)

    def test_issue_session_token_receives_vault_name_device_and_client_label(self) -> None:
        _, m_issue = self._run_route(self._mock_issued_session())
        self.assertEqual(m_issue.call_count, 1, "issue_session_token called exactly once")
        _, kwargs = m_issue.call_args
        self.assertEqual(kwargs["vault_id"], self._VAULT_ID)
        self.assertEqual(kwargs["vault_name"], self._VAULT_NAME)
        self.assertEqual(kwargs["device_id"], self._DEVICE_ID)
        self.assertEqual(kwargs["client_label"], self._EXPECTED_LABEL)

    def test_client_label_derived_from_user_agent_header(self) -> None:
        """
        Route must ONLY use the incoming HTTP User-Agent to derive
        client_label — never an arbitrary client field. Sending
        different UA headers yields different (normalized) labels.
        """
        from fastapi.testclient import TestClient

        def run_with_ua(ua: str) -> str:
            get_db = _make_get_db_playback([
                {"account_id": "33333333-3333-3333-3333-333333333333"},
                {"vault_id": self._VAULT_ID, "vault_name": self._VAULT_NAME},
            ])
            with mock.patch("routes.auth_zk_routes.get_db", side_effect=get_db), \
                 mock.patch(
                     "routes.auth_zk_routes.opaque_registration_finish",
                     return_value=b"fake-opaque-record",
                 ), \
                 mock.patch(
                     "routes.auth_zk_routes.enforce_signup_rate_limit",
                     return_value=None,
                 ), \
                 mock.patch(
                     "routes.auth_zk_routes.issue_session_token",
                     return_value=self._mock_issued_session(),
                 ) as m_issue:
                app = _build_zk_test_app()
                client = TestClient(app, raise_server_exceptions=False)
                client.post(
                    "/auth/zk-register-finalize",
                    json=self._valid_payload(),
                    headers={"User-Agent": ua},
                )
            return m_issue.call_args.kwargs["client_label"]

        self.assertEqual(run_with_ua(self._CHROME_UA), "Chrome on Windows")
        self.assertEqual(
            run_with_ua(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                "Safari/605.1.15"
            ),
            "Safari on macOS",
        )
        # Missing UA → "Unknown device".
        get_db = _make_get_db_playback([
            {"account_id": "33333333-3333-3333-3333-333333333333"},
            {"vault_id": self._VAULT_ID, "vault_name": self._VAULT_NAME},
        ])
        with mock.patch("routes.auth_zk_routes.get_db", side_effect=get_db), \
             mock.patch("routes.auth_zk_routes.opaque_registration_finish",
                        return_value=b"fake-opaque-record"), \
             mock.patch("routes.auth_zk_routes.enforce_signup_rate_limit",
                        return_value=None), \
             mock.patch("routes.auth_zk_routes.issue_session_token",
                        return_value=self._mock_issued_session()) as m_issue:
            from fastapi.testclient import TestClient
            app = _build_zk_test_app()
            client = TestClient(app, raise_server_exceptions=False)
            # TestClient forces a default UA; override with empty explicitly.
            client.post(
                "/auth/zk-register-finalize",
                json=self._valid_payload(),
                headers={"User-Agent": ""},
            )
            self.assertEqual(
                m_issue.call_args.kwargs["client_label"],
                "Unknown device",
            )

    def test_no_client_label_or_ua_in_captured_logs(self) -> None:
        """
        Neither the raw User-Agent nor the derived client_label may
        appear in any log record emitted during the request. Captured
        at INFO+ from the auth_zk_routes logger.
        """
        route_logger = logging.getLogger("routes.auth_zk_routes")
        with self.assertLogs(route_logger, level="DEBUG") as cm:
            # emit at least one record so assertLogs doesn't crash on empty
            route_logger.info("[test] harness marker — pre-request")
            self._run_route(self._mock_issued_session())
        blob = " ".join(cm.output)
        self.assertNotIn(self._CHROME_UA, blob)
        self.assertNotIn(self._EXPECTED_LABEL, blob)
        self.assertNotIn("Mozilla", blob)
        self.assertNotIn("Chrome/126", blob)


# ------------------------------------------------------------
# 4. ZK LOGIN FINALIZE
# ------------------------------------------------------------


class ZkLoginFinalizeBehavioralTests(_ZkRouteHarness):
    """
    Invokes ``POST /auth/zk-login-finalize`` through TestClient with
    dependency-isolated fakes. Asserts the call kwargs into
    ``issue_session_token`` and the response shape.
    """

    def _payload(self) -> Dict[str, Any]:
        return {
            "slot_id":   "slot-abc",
            "ke3":       _b64url_no_pad(b"fake-ke3-payload"),
            "device_id": self._DEVICE_ID,
        }

    def _run_route(self, mock_issue_return: Dict[str, Any]) -> tuple:
        """Return (response, issue_session_token_mock)."""
        from fastapi.testclient import TestClient

        # get_db() is called TWICE by zk_login_finalize:
        #   1) DELETE FROM vault_zk_login_slots RETURNING vault_id, server_state
        #   2) UPDATE vaults RETURNING vault_id, vault_name, wrapped_mvk, ...
        get_db = _make_get_db_playback(
            [{"vault_id": self._VAULT_ID, "server_state": b"fake-server-state"}],
            [
                {
                    "vault_id":                self._VAULT_ID,
                    "vault_name":              self._VAULT_NAME,
                    "wrapped_mvk":             b"fake-wrapped-mvk",
                    "wrapped_sk_vault":        b"fake-wrapped-sk-vault",
                    "display_name_ciphertext": b"fake-display-name",
                }
            ],
        )
        with mock.patch("routes.auth_zk_routes.get_db", side_effect=get_db), \
             mock.patch(
                 "routes.auth_zk_routes.opaque_login_finish",
                 return_value=b"fake-session-key",
             ), \
             mock.patch(
                 "routes.auth_zk_routes.issue_session_token",
                 return_value=mock_issue_return,
             ) as m_issue:
            app = _build_zk_test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/auth/zk-login-finalize",
                json=self._payload(),
                headers={"User-Agent": self._CHROME_UA},
            )
        return resp, m_issue

    def test_happy_path_returns_200_no_typeerror(self) -> None:
        resp, _ = self._run_route(self._mock_issued_session())
        self.assertEqual(
            resp.status_code, 200,
            f"expected 200 (fix in place); got {resp.status_code} body={resp.text[:200]!r}",
        )

    def test_response_session_token_is_string_not_dict(self) -> None:
        resp, _ = self._run_route(self._mock_issued_session(token_str="XYZWIRETOKEN"))
        body = resp.json()
        self.assertIsInstance(body.get("session_token"), str)
        self.assertEqual(body["session_token"], "XYZWIRETOKEN")
        self.assertNotIn("token_id", body)
        self.assertNotIn("expires_at", body)
        self.assertNotIn("client_label", body)

    def test_issue_session_token_receives_vault_name_device_and_client_label(self) -> None:
        _, m_issue = self._run_route(self._mock_issued_session())
        self.assertEqual(m_issue.call_count, 1)
        _, kwargs = m_issue.call_args
        self.assertEqual(kwargs["vault_id"], self._VAULT_ID)
        self.assertEqual(kwargs["vault_name"], self._VAULT_NAME)
        self.assertEqual(kwargs["device_id"], self._DEVICE_ID)
        self.assertEqual(kwargs["client_label"], self._EXPECTED_LABEL)

    def test_no_client_label_or_ua_in_captured_logs(self) -> None:
        route_logger = logging.getLogger("routes.auth_zk_routes")
        with self.assertLogs(route_logger, level="DEBUG") as cm:
            route_logger.info("[test] harness marker — pre-request")
            self._run_route(self._mock_issued_session())
        blob = " ".join(cm.output)
        self.assertNotIn(self._CHROME_UA, blob)
        self.assertNotIn(self._EXPECTED_LABEL, blob)
        self.assertNotIn("Mozilla", blob)
        self.assertNotIn("Chrome/126", blob)


# ============================================================
# 5. Signup / legacy login — client_label wiring smoke tests
#
# These use ``mock.patch.object`` to intercept ``issue_session_token``
# at the auth_routes import site and record its kwargs. The DB
# machinery around signup/login is deliberately NOT round-tripped —
# we only need to observe that when the route body reaches
# ``issue_session_token``, it passes ``client_label`` derived from
# the User-Agent. Full end-to-end coverage of signup/login belongs
# in test_auth_routes.py's real-DB integration suite.
# ============================================================


def _skip_if_no_test_db() -> None:
    if not os.environ.get("VAULTAI_TEST_DATABASE_URL", "").strip():
        raise unittest.SkipTest(
            "VAULTAI_TEST_DATABASE_URL not set; signup/login DB round-trip requires "
            "a disposable Postgres. See file docstring."
        )


class SignupBehavioralWiringTest(unittest.TestCase):
    """
    Exercises ``POST /auth/signup`` end-to-end (real DB) and asserts
    ``issue_session_token`` receives ``client_label`` derived from the
    request User-Agent. Skips without ``VAULTAI_TEST_DATABASE_URL``.
    """

    def test_signup_passes_client_label_to_issue_session_token(self) -> None:
        _skip_if_no_test_db()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_routes import router as auth_router

        app = FastAPI()
        app.include_router(auth_router)

        original = auth_local.issue_session_token
        recorded: List[Dict[str, Any]] = []

        def recorder(**kwargs: Any) -> Any:
            recorded.append(dict(kwargs))
            return original(**kwargs)

        # Patch at the auth_routes import site (name resolved at call time
        # via the import block).
        with mock.patch("routes.auth_routes.issue_session_token",
                        side_effect=recorder):
            client = TestClient(app, raise_server_exceptions=False)
            vault_name = f"vault-{uuid.uuid4().hex[:12]}"
            # SignupRequest schema (auth_routes.py:118-123) requires:
            #   vault_name, pin, confirm_pin (must equal pin),
            #   optional display_username, acknowledged_irrecoverable.
            # PIN shape validator (auth_routes.py:61-77) enforces:
            #   digits only, >= MIN_PIN_LENGTH_NEW_VAULT (6), <= 64.
            _test_pin = "82640173"
            resp = client.post(
                "/auth/signup",
                json={
                    "vault_name":  vault_name,
                    "pin":         _test_pin,
                    "confirm_pin": _test_pin,
                    "display_username": "tester",
                    "acknowledged_irrecoverable": True,
                },
                headers={"User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) "
                    "Gecko/20100101 Firefox/126.0"
                )},
            )

        self.assertEqual(resp.status_code, 201,
            f"signup failed; body={resp.text[:200]!r}")
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["client_label"], "Firefox on Linux")


class LegacyLoginBehavioralWiringTest(unittest.TestCase):
    """
    Exercises ``POST /auth/login`` (real DB) after a signup. Asserts
    ``issue_session_token`` receives ``client_label`` from the login
    request's User-Agent (may differ from the signup UA). Skips
    without ``VAULTAI_TEST_DATABASE_URL``.
    """

    def test_login_passes_client_label_to_issue_session_token(self) -> None:
        _skip_if_no_test_db()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_routes import router as auth_router

        app = FastAPI()
        app.include_router(auth_router)

        original = auth_local.issue_session_token
        recorded: List[Dict[str, Any]] = []

        def recorder(**kwargs: Any) -> Any:
            recorded.append(dict(kwargs))
            return original(**kwargs)

        with mock.patch("routes.auth_routes.issue_session_token",
                        side_effect=recorder):
            client = TestClient(app, raise_server_exceptions=False)
            vault_name = f"vault-{uuid.uuid4().hex[:12]}"
            # SignupRequest requires confirm_pin (auth_routes.py:121) and
            # PIN must be digits >=6 (auth_routes.py:61-77).
            _test_pin = "82640173"
            # Signup with UA A
            r1 = client.post(
                "/auth/signup",
                json={
                    "vault_name":  vault_name,
                    "pin":         _test_pin,
                    "confirm_pin": _test_pin,
                    "display_username": "tester",
                    "acknowledged_irrecoverable": True,
                },
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/126.0"},
            )
            self.assertEqual(r1.status_code, 201, f"signup failed: {r1.text[:200]!r}")

            # Login with UA B — should record a distinct client_label.
            # LoginRequest (auth_routes.py:126-128) only requires
            # vault_name + pin; no confirm_pin on this endpoint.
            r2 = client.post(
                "/auth/login",
                json={"vault_name": vault_name, "pin": _test_pin},
                headers={"User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                    "Safari/605.1.15"
                )},
            )
            self.assertEqual(r2.status_code, 200, f"login failed: {r2.text[:200]!r}")

        self.assertEqual(len(recorded), 2, "expected one signup + one login issuance")
        self.assertEqual(recorded[0]["client_label"], "Chrome on Windows")
        self.assertEqual(recorded[1]["client_label"], "Safari on macOS")


# ============================================================
# 6. Real-Postgres integration for the ZK finalize routes.
#
# These tests execute the actual auth_sessions INSERT and prove that
# the returned session_token parses back to the SAME token_id that
# now lives in the DB. When VAULTAI_TEST_DATABASE_URL is unset, or the
# vaultai_opaque_server pyo3 wheel is missing (Windows dev),
# they SKIP with a clear reason. Skips are NOT completion evidence;
# see the file docstring — these must run in a Linux CI with the
# Docker builder stage prerequisites installed.
# ============================================================


def _skip_if_no_opaque_wheel() -> None:
    try:
        import vaultai_opaque_server   # noqa: F401
    except Exception as exc:
        raise unittest.SkipTest(
            f"vaultai_opaque_server pyo3 wheel unavailable ({exc}); ZK-integration "
            f"requires the Docker builder stage. Skipping."
        )


class ZkFinalizeRealDbIntegrationTests(unittest.TestCase):
    """
    Runs against a disposable Postgres (VAULTAI_TEST_DATABASE_URL) with
    all Alembic migrations applied through HEAD. Verifies:

      * ZK register-finalize inserts exactly one ``auth_sessions`` row
        for the returned vault_id;
      * ZK login-finalize inserts a fresh row on top of a synthetic
        prior registration;
      * the returned ``session_token`` string parses via
        ``auth_local._parse_token`` and its 16-byte token_id equals
        the row's PK.

    OPAQUE is monkey-patched at the primitive layer so the DB path
    runs without a full Rust round-trip. This still exercises the
    fixed ``issue_session_token`` call (which is the sole thing the
    B.1 fix changes on the DB side).
    """

    def setUp(self) -> None:
        _skip_if_no_test_db()
        # Note: we do NOT require the pyo3 wheel here because we mock
        # opaque_registration_finish / opaque_login_finish directly.
        # A separate suite (test_opaque_wire_interop.py) covers the
        # cryptographic handshake in a Linux CI with the wheel present.
        import psycopg2  # noqa: F401  (surface an ImportError early)

    def _connect(self):
        import psycopg2
        return psycopg2.connect(os.environ["VAULTAI_TEST_DATABASE_URL"])

    def _reset_state(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth_sessions;")
            cur.execute("DELETE FROM account_members;")
            cur.execute("DELETE FROM vault_zk_login_slots;")
            cur.execute("DELETE FROM vaults;")
            cur.execute("DELETE FROM accounts;")
            conn.commit()
        finally:
            conn.close()

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.auth_zk_routes import router as zk_router
        app = FastAPI()
        app.include_router(zk_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_zk_register_finalize_writes_auth_sessions_row(self) -> None:
        from vault_handle import to_display

        self._reset_state()
        handle = bytes(range(1, 16))  # deterministic 15 bytes

        with mock.patch(
            "routes.auth_zk_routes.opaque_registration_finish",
            return_value=b"fake-opaque-registration-record",
        ), mock.patch(
            "routes.auth_zk_routes.enforce_signup_rate_limit",
            return_value=None,
        ):
            client = self._make_client()
            resp = client.post(
                "/auth/zk-register-finalize",
                json={
                    "vault_handle": to_display(handle),
                    "ke3":                       _b64url_no_pad(b"fake-ke3"),
                    "wrapped_mvk":               _b64url_no_pad(b"fake-mvk"),
                    "wrapped_sk_vault":          _b64url_no_pad(b"fake-sk"),
                    "pk_vault_public":           _b64url_no_pad(b"\x00" * 32),
                    "display_name_ciphertext":   _b64url_no_pad(b"fake-display"),
                    "acknowledged_irrecoverable": True,
                    "device_id": "device-integration-reg",
                },
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0"},
            )

        self.assertEqual(resp.status_code, 200, f"body={resp.text[:200]!r}")
        body = resp.json()
        self.assertIsInstance(body["session_token"], str)

        # Parse the wire token back to its 16-byte token_id.
        token_id_bytes = auth_local._parse_token(body["session_token"])
        self.assertIsNotNone(token_id_bytes,
            "returned session_token failed HMAC parse — token is malformed")
        parsed_token_id = str(uuid.UUID(bytes=token_id_bytes))

        # Verify auth_sessions row exists for the returned vault_id.
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT token_id::text, vault_id::text, device_id, revoked_at "
                "FROM auth_sessions WHERE vault_id = %s",
                (body["vault_id"],),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        self.assertEqual(len(rows), 1, f"expected 1 auth_sessions row, got {rows!r}")
        row_token_id, row_vault_id, row_device_id, row_revoked_at = rows[0]
        self.assertEqual(row_token_id, parsed_token_id,
            "returned token parses to a token_id that does NOT match the DB row")
        self.assertEqual(row_vault_id, body["vault_id"])
        self.assertEqual(row_device_id, "device-integration-reg")
        self.assertIsNone(row_revoked_at)

    def test_zk_login_finalize_writes_auth_sessions_row(self) -> None:
        # Uses the same setup: pre-register a vault via the register endpoint
        # (also mocked), then log in on top of it.
        from vault_handle import to_display

        self._reset_state()
        handle = bytes(range(1, 16))
        display_handle = to_display(handle)

        with mock.patch(
            "routes.auth_zk_routes.opaque_registration_finish",
            return_value=b"fake-opaque-registration-record",
        ), mock.patch(
            "routes.auth_zk_routes.enforce_signup_rate_limit",
            return_value=None,
        ):
            client = self._make_client()
            r_reg = client.post(
                "/auth/zk-register-finalize",
                json={
                    "vault_handle": display_handle,
                    "ke3":                       _b64url_no_pad(b"fake-ke3"),
                    "wrapped_mvk":               _b64url_no_pad(b"fake-mvk"),
                    "wrapped_sk_vault":          _b64url_no_pad(b"fake-sk"),
                    "pk_vault_public":           _b64url_no_pad(b"\x00" * 32),
                    "display_name_ciphertext":   _b64url_no_pad(b"fake-display"),
                    "acknowledged_irrecoverable": True,
                    "device_id": "device-integration-pre-login",
                },
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0"},
            )
        self.assertEqual(r_reg.status_code, 200,
            f"prep register failed: {r_reg.text[:200]!r}")
        registered_vault_id = r_reg.json()["vault_id"]

        # Prime a login slot manually — we don't want to route through
        # zk-login-init because that requires opaque_login_start (real
        # crypto). Insert a synthetic slot row and monkey-patch
        # opaque_login_finish.
        slot_id = "int-slot-abc"
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_zk_login_slots
                  (slot_id, vault_id, server_state, expires_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '90 seconds')
                """,
                (slot_id, registered_vault_id, b"fake-server-state"),
            )
            conn.commit()
        finally:
            conn.close()

        with mock.patch(
            "routes.auth_zk_routes.opaque_login_finish",
            return_value=b"fake-session-key",
        ):
            client = self._make_client()
            r_login = client.post(
                "/auth/zk-login-finalize",
                json={
                    "slot_id":   slot_id,
                    "ke3":       _b64url_no_pad(b"fake-ke3-login"),
                    "device_id": "device-integration-login",
                },
                headers={"User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15"
                )},
            )

        self.assertEqual(r_login.status_code, 200, f"body={r_login.text[:200]!r}")
        login_body = r_login.json()
        self.assertIsInstance(login_body["session_token"], str)

        token_id_bytes = auth_local._parse_token(login_body["session_token"])
        self.assertIsNotNone(token_id_bytes)
        parsed_login_token_id = str(uuid.UUID(bytes=token_id_bytes))

        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT token_id::text, device_id "
                "FROM auth_sessions "
                "WHERE vault_id = %s "
                "ORDER BY issued_at DESC",
                (registered_vault_id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        # Expect two rows: one from registration, one from login. The
        # newest (login) must match the parsed token_id.
        self.assertEqual(len(rows), 2, f"expected 2 sessions; got {rows!r}")
        newest_token_id, newest_device_id = rows[0]
        self.assertEqual(newest_token_id, parsed_login_token_id)
        self.assertEqual(newest_device_id, "device-integration-login")


if __name__ == "__main__":
    unittest.main()
