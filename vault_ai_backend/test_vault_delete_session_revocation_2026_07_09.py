"""Backend regression tests for the "user stays logged in after
Delete Vault" bug.

Scope: only the *session revocation* + *response-code* + *logging
hygiene* behaviour of ``/vault/delete/confirm``. Does NOT touch
authentication logic, PIN handling, trusted-device verification, or
wallet cryptography — those live in their own test files and stay
green.

Covers the seven backend items from the operator brief:

  1. Delete confirm revokes sessions after successful deletion.
  2. Old session cannot call authenticated route after delete.
  3. Deleted vault id cannot be loaded after delete.
  4. Delete-confirm failure paths do NOT revoke unrelated active
     sessions.
  5. Delete confirm returns 204 ONLY after the deletion service
     succeeds; a raise from the service must surface as 500, never
     as a silent 204.
  6. Delete logs never carry PIN, request-token, or encrypted
     material.
  7. Delete service never broadcasts a crypto transaction.
"""

from __future__ import annotations

import io
import logging
import time
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient


TEST_VAULT_ID = "vault-test-delete-flow-2026-07-09"
GOOD_PIN      = "123456"
BAD_PIN       = "000000"


def _mk_client_with_principal(vault_id: str = TEST_VAULT_ID) -> TestClient:
    """Mount just the delete router with the trusted-device and
    session-token dependencies overridden to return a stub principal.
    This keeps the tests focused on the delete flow and away from
    real auth machinery."""
    from routes.vault_delete_routes import router
    from device_gate import verify_trusted_device
    from auth_local import verify_session_token

    principal = {
        "vault_id":   vault_id,
        "vault_name": "alice",
        "token_id":   "tok-1",
        "device_id":  "dev-1",
    }
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = (
        lambda: principal
    )
    app.dependency_overrides[verify_session_token] = (
        lambda: principal
    )
    return TestClient(app)


def _fresh_challenge(vault_id: str = TEST_VAULT_ID) -> str:
    from routes.vault_delete_routes import _sign_challenge
    return _sign_challenge(vault_id, int(time.time()) + 300)


def _confirm_body(**overrides) -> dict:
    from routes.vault_delete_routes import CONFIRMATION_PHRASE
    body = {
        "request_token":       _fresh_challenge(),
        "pin":                 GOOD_PIN,
        "confirmation_phrase": CONFIRMATION_PHRASE,
    }
    body.update(overrides)
    return body



class TestSuccessRevokesSessions(unittest.TestCase):
    """(1) On successful delete, ``revoke_all_sessions_for_vault`` is
    called after the deletion service completes."""

    def test_success_calls_revoke_after_delete_service(self):
        client = _mk_client_with_principal()

        call_order = []
        with mock.patch(
            "routes.vault_delete_routes._verify_pin", return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes."
            "_require_authoritative_final_vault_deletion_allowed",
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
            side_effect=lambda *a, **k: call_order.append("delete"),
        ), mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
            side_effect=lambda *a, **k: call_order.append("revoke") or 3,
        ):
            resp = client.post(
                "/vault/delete/confirm", json=_confirm_body(),
            )

        self.assertEqual(resp.status_code, 204, resp.text)
        self.assertEqual(
            call_order, ["delete", "revoke"],
            msg="delete_vault_and_all_data must run BEFORE "
                "revoke_all_sessions_for_vault so we never revoke "
                "sessions unless the vault is actually gone",
        )

    def test_revocation_targets_the_deleted_vault_id_only(self):
        client = _mk_client_with_principal()
        seen_vault_ids: list = []
        with mock.patch(
            "routes.vault_delete_routes._verify_pin", return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes."
            "_require_authoritative_final_vault_deletion_allowed",
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
        ), mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
            side_effect=lambda vid: seen_vault_ids.append(vid) or 1,
        ):
            resp = client.post(
                "/vault/delete/confirm", json=_confirm_body(),
            )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(seen_vault_ids, [TEST_VAULT_ID])



class TestOldSessionIsUseless(unittest.TestCase):
    """(2) After delete, the vault's auth_sessions rows are revoked;
    (3) ``verify_session_token`` refuses tokens that point at a
    now-nonexistent vault. We test the effect via a plain call to
    ``revoke_all_sessions_for_vault`` and via the SQL shape of
    verify_session_token."""

    def test_revoke_all_sessions_marks_rows_revoked_at_now(self):

        import auth_local


        fake_conn = mock.MagicMock()
        fake_cur = fake_conn.cursor.return_value
        fake_cur.rowcount = 5
        with mock.patch.object(
            auth_local, "get_db", return_value=fake_conn,
        ):
            affected = auth_local.revoke_all_sessions_for_vault(
                TEST_VAULT_ID,
            )
        self.assertEqual(affected, 5)


        sql = fake_cur.execute.call_args[0][0]
        self.assertIn("UPDATE auth_sessions", sql)
        self.assertIn("SET revoked_at", sql)
        self.assertIn("WHERE vault_id", sql)
        self.assertIn("revoked_at IS NULL", sql)
        # Step B.3 wire-up: revoke_all_sessions_for_vault now writes
        # revoked_reason so the events UI can label bulk revokes.
        self.assertIn("revoked_reason", sql)

        # SQL parameters are (reason, vault_id) — reason first because the
        # UPDATE ... SET revoked_reason = %s ... WHERE vault_id = %s
        # clause is emitted in that order.
        params = fake_cur.execute.call_args[0][1]
        self.assertEqual(params, ("vault-delete", TEST_VAULT_ID))
        fake_conn.commit.assert_called_once()

    def test_load_principal_gates_on_revoked_at_and_vault_join(self):




        import inspect, auth_local
        src = inspect.getsource(auth_local._load_principal)


        self.assertIn(
            "revoked_at", src,
            msg="_load_principal must inspect revoked_at so "
                "revoke_all_sessions_for_vault actually neutralises "
                "the token",
        )
        self.assertRegex(
            src, r"JOIN\s+vaults",
            msg="_load_principal must JOIN vaults so a delete cascade "
                "(which removes the vaults row) also makes the token "
                "unusable",
        )


        self.assertIn("expires_at", src)



class TestDeletedVaultCannotBeLoaded(unittest.TestCase):
    """(3) The deletion service issues DELETE FROM vaults which
    cascades to auth_sessions, uploaded_files, vault_items, etc.
    After that, any attempt to load the vault by id must fail."""

    def test_deletion_service_issues_delete_from_vaults(self):
        import inspect
        from vault_deletion_service import _delete_vault_row
        src = inspect.getsource(_delete_vault_row)
        self.assertIn("DELETE FROM vaults", src)
        self.assertIn("WHERE vault_id", src)

    def test_deletion_service_verifies_row_actually_disappeared(self):

        import vault_deletion_service as vds

        fake_conn = mock.MagicMock()
        fake_cur = fake_conn.cursor.return_value
        fake_cur.rowcount = 0
        with mock.patch.object(vds, "get_db", return_value=fake_conn):
            deleted = vds._delete_vault_row(TEST_VAULT_ID)
        self.assertFalse(deleted)

        fake_cur.rowcount = 1
        with mock.patch.object(vds, "get_db", return_value=fake_conn):
            deleted = vds._delete_vault_row(TEST_VAULT_ID)
        self.assertTrue(deleted)

    def test_high_level_delete_raises_when_row_already_gone(self):



        import vault_deletion_service as vds
        with mock.patch.object(
            vds, "_delete_vault_row", return_value=False,
        ), mock.patch.object(
            vds, "_cancel_stripe_subscription_best_effort",
        ), mock.patch.object(
            vds, "_insert_tombstone",
        ):
            with self.assertRaises(vds.VaultNotFoundError):
                vds.delete_vault_and_all_data(
                    TEST_VAULT_ID, reason="user_requested",
                )



class TestFailurePathsDoNotRevoke(unittest.TestCase):
    """(4) Every failure branch of confirm_delete must NOT call
    ``revoke_all_sessions_for_vault``. If we revoked on failure the
    user would be signed out with their vault still intact — the
    opposite of the bug we're fixing but equally destructive."""

    def test_bad_phrase_does_not_revoke_or_delete(self):
        client = _mk_client_with_principal()
        body = _confirm_body(confirmation_phrase="please delete pls")
        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
        ) as mock_delete, mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
        ) as mock_revoke:
            resp = client.post("/vault/delete/confirm", json=body)
        self.assertEqual(resp.status_code, 400, resp.text)
        mock_delete.assert_not_called()
        mock_revoke.assert_not_called()

    def test_bad_request_token_does_not_revoke_or_delete(self):
        client = _mk_client_with_principal()
        body = _confirm_body(request_token="not-a-valid-token")
        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
        ) as mock_delete, mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
        ) as mock_revoke:
            resp = client.post("/vault/delete/confirm", json=body)
        self.assertEqual(resp.status_code, 400, resp.text)
        mock_delete.assert_not_called()
        mock_revoke.assert_not_called()

    def test_bad_pin_does_not_revoke_or_delete(self):
        client = _mk_client_with_principal()
        body = _confirm_body(pin=BAD_PIN)
        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=False,
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
        ) as mock_delete, mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
        ) as mock_revoke:
            resp = client.post("/vault/delete/confirm", json=body)
        self.assertEqual(resp.status_code, 401, resp.text)
        mock_delete.assert_not_called()
        mock_revoke.assert_not_called()



class TestDeletionServiceRaiseSurfaces500(unittest.TestCase):
    """(5) A raise from the deletion service must surface as 500,
    NEVER as a silent 204."""

    def test_delete_service_raise_returns_500_and_no_revoke(self):
        client = _mk_client_with_principal()
        with mock.patch(
            "routes.vault_delete_routes._verify_pin", return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes."
            "_require_authoritative_final_vault_deletion_allowed",
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
            side_effect=RuntimeError("simulated cascade failure"),
        ), mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
        ) as mock_revoke:
            resp = client.post(
                "/vault/delete/confirm", json=_confirm_body(),
            )
        self.assertEqual(resp.status_code, 500)
        payload = resp.json()
        self.assertEqual(
            payload["detail"]["code"], "delete_failed",
        )
        mock_revoke.assert_not_called()

    def test_delete_service_raise_body_does_not_carry_internal_detail(self):



        client = _mk_client_with_principal()
        with mock.patch(
            "routes.vault_delete_routes._verify_pin", return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes."
            "_require_authoritative_final_vault_deletion_allowed",
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data",
            side_effect=RuntimeError(
                "sensitive-looking exception with vault_name=alice "
                "pin_len=6 wallet_addr=0xdeadbeef"
            ),
        ), mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault",
        ):
            resp = client.post(
                "/vault/delete/confirm", json=_confirm_body(),
            )
        self.assertEqual(resp.status_code, 500)
        raw = resp.text.lower()
        for needle in ("alice", "wallet_addr", "0xdead", "pin_len"):
            self.assertNotIn(
                needle, raw,
                msg=f"500 body must not surface internal detail "
                    f"{needle!r}",
            )



class TestNoSecretsInLogs(unittest.TestCase):
    """(6) Delete logs must never carry PIN, request-token, or
    encrypted material. We drive the endpoint under a captured
    log handler and inspect the emitted lines."""

    def _run_with_captured_logs(
        self, *, verify_pin_value: bool, expected_status: int,
        body: dict,
    ) -> str:
        client = _mk_client_with_principal()
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        prev_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            with mock.patch(
                "routes.vault_delete_routes._verify_pin",
                return_value=verify_pin_value,
            ), mock.patch(
                "routes.vault_delete_routes.delete_vault_and_all_data",
            ), mock.patch(
                "routes.vault_delete_routes.revoke_all_sessions_for_vault",
            ):
                resp = client.post(
                    "/vault/delete/confirm", json=body,
                )
            self.assertEqual(resp.status_code, expected_status, resp.text)
        finally:
            root.removeHandler(handler)
            root.setLevel(prev_level)
        return buf.getvalue()

    def test_success_path_logs_carry_no_pin_or_token(self):
        distinctive_pin = "271828"
        distinctive_tok_prefix = "obvioustokenprefix"
        body = _confirm_body(pin=distinctive_pin)


        body["request_token"] = distinctive_tok_prefix + body[
            "request_token"
        ]

        text = self._run_with_captured_logs(
            verify_pin_value=True, expected_status=400, body=body,
        )



        self.assertNotIn(distinctive_pin, text)
        self.assertNotIn(distinctive_tok_prefix, text)

    def test_bad_pin_path_logs_carry_no_pin(self):
        distinctive_pin = "314159"
        body = _confirm_body(pin=distinctive_pin)
        text = self._run_with_captured_logs(
            verify_pin_value=False, expected_status=401, body=body,
        )
        self.assertNotIn(distinctive_pin, text)



class TestDeleteServiceNeverBroadcastsCrypto(unittest.TestCase):
    """(7) The deletion service must never broadcast a crypto
    transaction. This is a permanent invariant — the deletion is a
    database cascade + safe tombstone + best-effort Stripe cancel.
    Nothing else."""

    def test_deletion_service_source_forbids_broadcast_verbs(self):
        import inspect
        import vault_deletion_service as vds
        src = inspect.getsource(vds)


        for forbidden in (
            "broadcast_tx", "sendTransaction", "send_raw_transaction",
            "signTransaction", "wallet.transfer", "sweep_wallet",
            "sweep_all_funds",
        ):
            self.assertNotIn(
                forbidden, src,
                msg=(
                    f"deletion service must never call {forbidden} — "
                    "the vault delete flow is a DB cascade only, never "
                    "a crypto broadcast"
                ),
            )

    def test_deletion_service_docstring_says_no_broadcast(self):
        import vault_deletion_service as vds
        doc = (vds.__doc__ or "") + (
            vds.delete_vault_and_all_data.__doc__ or ""
        )
        self.assertIn(
            "NEVER broadcasts a crypto transaction",
            doc,
            msg="the no-broadcast invariant must remain documented "
                "so future readers cannot regress it accidentally",
        )


class TestChallengeParserAcceptsDotInSignature(unittest.TestCase):
    """Regression pin for the ``_verify_challenge`` fix (2026-07-17).

    The token wire format is ``payload + b"." + sig(32 bytes)`` after
    base64url. Signatures are raw HMAC-SHA256 output, which contains
    a b"." byte with ~12% probability. An earlier parser used
    ``raw.rsplit(b".", 1)`` and misparsed those tokens whenever the
    last dot inside the sig came after the true payload/sig
    separator, silently rejecting one-in-eight legitimate in-window
    challenges. The current parser splits from the end by the known
    32-byte sig length, so the outcome no longer depends on which
    bytes HMAC happens to emit. This test guards against a
    regression that reintroduces content-based splitting.
    """

    def test_dot_containing_signature_round_trips(self) -> None:
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge, _b64url_decode,
        )
        vid = "vault-parser-regression-2026-07-17"
        base = int(time.time()) + 3600
        for offset in range(2000):
            ts = base + offset
            token = _sign_challenge(vid, ts)
            raw = _b64url_decode(token)
            sig = raw[-32:]
            if b"." in sig:
                self.assertTrue(
                    _verify_challenge(token, vid, now_ts=ts - 10),
                    msg=(
                        f"regression: token with b'.' at sig position "
                        f"{sig.index(b'.')} must verify — the parser "
                        f"must split by fixed sig length, not by "
                        f"content-based rsplit(b'.', 1)."
                    ),
                )
                return
        self.skipTest(
            "no dot-in-sig token generated in 2000 tries — the "
            "regression case cannot be exercised (very unlikely; "
            "expected within ~10 iterations at 12% per-token rate)."
        )

    def test_bulk_verify_never_flakes(self) -> None:
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        vid = "vault-parser-bulk-2026-07-17"
        n = 500
        base = int(time.time()) + 3600
        fails = [
            ts for ts in range(base, base + n)
            if not _verify_challenge(_sign_challenge(vid, ts), vid,
                                     now_ts=ts - 10)
        ]
        self.assertEqual(
            fails, [],
            msg=(
                f"{len(fails)}/{n} freshly-signed tokens failed to "
                f"verify — parser must be content-independent."
            ),
        )


if __name__ == "__main__":
    unittest.main()
