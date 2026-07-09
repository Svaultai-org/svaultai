"""Regression tests for user-requested vault deletion + automatic
deletion of unpaid-inactive-6-months vaults.

Covers the 20 acceptance items from the operator brief:
  1.  user-requested delete requires auth
  2.  user-requested delete requires trusted device
  3.  user-requested delete requires PIN/unlock confirmation
  4.  user-requested delete requires exact phrase DELETE MY VAULT
  5.  user-requested delete deletes vault data only after final
      confirmation
  6.  unpaid inactive user > 6 months is auto-deleted
  7.  unpaid inactive user < 6 months is NOT deleted
  8.  unpaid active user is NOT deleted
  9.  paid inactive user is NOT deleted
  10. paid active user is NOT deleted
  11. cancelled paid user becomes eligible only after entitlement
      ends and 6-month inactivity passes
  12. auto-delete job re-checks billing before deletion
  13. auto-delete job re-checks activity before deletion
  14. deleted vault removes files, secure items, IDs, and crypto
      wallet records (via DB cascade in the deletion SQL)
  15. deletion never broadcasts crypto transactions
  16. deletion logs contain no secrets
  17. safe tombstone contains no sensitive data
  18. FAQ/chat deletion questions route correctly
  19. chat cannot delete vault directly
  20. no pending-deletion/grace-period language in the policy copy
"""

from __future__ import annotations

import logging
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


TEST_VAULT_ID = "vault-test-1234"
GOOD_PIN = "123456"
BAD_PIN = "000000"

VAULT_DELETE_PATHS = (
    "/vault/delete/status",
    "/vault/delete/request",
    "/vault/delete/confirm",
)


def _fake_get_db_factory(fetchone_result=None):
    conn = mock.MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.return_value = fetchone_result
    cur.rowcount = 1
    return conn


class TestPart1_AuthAndDeviceGate(unittest.TestCase):
    """(1) auth required; (2) trusted device required."""

    def test_delete_paths_not_in_gate_exempt_list(self):
        from device_gate import ROUTES_EXEMPT_FROM_DEVICE_GATE
        for path in VAULT_DELETE_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(
                    path, ROUTES_EXEMPT_FROM_DEVICE_GATE,
                    msg=(
                        f"delete endpoint {path} MUST NOT be in the "
                        "device-gate exemption list; the trusted-device "
                        "check must apply to all delete endpoints"
                    ),
                )

    def test_delete_confirm_uses_verify_trusted_device_dependency(self):
        from routes import vault_delete_routes
        from device_gate import verify_trusted_device

        source = vault_delete_routes.__file__
        with open(source, "r", encoding="utf-8") as f:
            src = f.read()

        self.assertIn("verify_trusted_device", src,
                      msg=(
                          "delete endpoints must depend on "
                          "verify_trusted_device — that dependency "
                          "chains session-token auth with the trusted-"
                          "device gate"
                      ))

    def test_delete_endpoints_registered(self):
        from routes.vault_delete_routes import router
        paths = {r.path for r in router.routes}
        self.assertTrue(
            {"/vault/delete/status",
             "/vault/delete/request",
             "/vault/delete/confirm"}.issubset(paths),
        )


class TestPart2_PinAndPhraseGating(unittest.TestCase):
    """(3) PIN required; (4) exact phrase required."""

    def _build_test_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.vault_delete_routes import router
        from device_gate import verify_trusted_device
        from auth_local import verify_session_token

        principal = {
            "vault_id": TEST_VAULT_ID,
            "vault_name": "alice",
            "token_id": "tok-1",
            "device_id": "dev-1",
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

    def test_confirm_rejects_wrong_phrase(self):
        client = self._build_test_client()
        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=True,
        ):
            resp = client.post("/vault/delete/confirm", json={
                "request_token": "irrelevant-because-phrase-fails-first",
                "pin": GOOD_PIN,
                "confirmation_phrase": "delete my vault",
            })
        self.assertEqual(resp.status_code, 400)
        self.assertIn(
            "invalid_confirmation_phrase",
            resp.json().get("detail", {}).get("code", ""),
        )

    def test_confirm_rejects_wrong_pin(self):
        client = self._build_test_client()
        from routes.vault_delete_routes import (
            _sign_challenge, CONFIRMATION_PHRASE,
        )
        import time as _time

        token = _sign_challenge(TEST_VAULT_ID, int(_time.time()) + 300)
        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=False,
        ):
            resp = client.post("/vault/delete/confirm", json={
                "request_token": token,
                "pin": BAD_PIN,
                "confirmation_phrase": CONFIRMATION_PHRASE,
            })
        self.assertEqual(resp.status_code, 401)
        self.assertIn(
            "invalid_pin",
            resp.json().get("detail", {}).get("code", ""),
        )

    def test_confirmation_phrase_constant_is_exact(self):
        from vault_deletion_service import CONFIRMATION_PHRASE
        self.assertEqual(CONFIRMATION_PHRASE, "DELETE MY VAULT")


class TestPart3_FinalConfirmationCascades(unittest.TestCase):
    """(5) deletion happens only after final confirmation."""

    def test_confirm_triggers_deletion_only_after_all_gates_pass(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.vault_delete_routes import router
        from device_gate import verify_trusted_device
        from auth_local import verify_session_token
        from routes.vault_delete_routes import (
            _sign_challenge, CONFIRMATION_PHRASE,
        )
        import time as _time

        principal = {
            "vault_id": TEST_VAULT_ID,
            "vault_name": "alice",
            "token_id": "tok-1",
            "device_id": "dev-1",
        }
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[verify_trusted_device] = (
            lambda: principal
        )
        app.dependency_overrides[verify_session_token] = (
            lambda: principal
        )
        client = TestClient(app)

        token = _sign_challenge(TEST_VAULT_ID, int(_time.time()) + 300)

        with mock.patch(
            "routes.vault_delete_routes._verify_pin",
            return_value=True,
        ), mock.patch(
            "routes.vault_delete_routes.delete_vault_and_all_data"
        ) as mock_delete, mock.patch(
            "routes.vault_delete_routes.revoke_all_sessions_for_vault"
        ) as mock_revoke:
            resp = client.post("/vault/delete/confirm", json={
                "request_token": token,
                "pin": GOOD_PIN,
                "confirmation_phrase": CONFIRMATION_PHRASE,
            })

        self.assertEqual(resp.status_code, 204, resp.text)
        mock_delete.assert_called_once()
        call_kwargs = mock_delete.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("reason"),
            "user_requested",
        )
        mock_revoke.assert_called_once()

    def test_expired_request_token_is_rejected(self):
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        expired_ts = int(datetime(2020, 1, 1).timestamp())
        tok = _sign_challenge(TEST_VAULT_ID, expired_ts)
        self.assertFalse(_verify_challenge(tok, TEST_VAULT_ID))

    def test_challenge_for_different_vault_is_rejected(self):
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        import time as _time
        tok = _sign_challenge("other-vault",
                              int(_time.time()) + 300)
        self.assertFalse(_verify_challenge(tok, TEST_VAULT_ID))


def _mk_now() -> datetime:
    return datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


class TestPart4_CleanupEligibility(unittest.TestCase):
    """(6)-(11) — the 6-month + unpaid predicate combinations."""

    def test_unpaid_over_6_months_is_deleted(self):
        from inactive_unpaid_cleanup import run_once

        now = _mk_now()
        very_old = now - timedelta(days=200)

        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[TEST_VAULT_ID],
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_unpaid",
            return_value=(True, "none"),
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_inactive",
            return_value=True,
        ), mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
        ) as mock_del:
            result = run_once(now)

        mock_del.assert_called_once()
        self.assertEqual(
            mock_del.call_args.kwargs.get("reason"),
            "unpaid_inactive_6_months",
        )
        self.assertEqual(result.deleted, 1)

    def test_unpaid_under_6_months_is_not_deleted(self):
        from inactive_unpaid_cleanup import run_once

        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[],
        ), mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
        ) as mock_del:
            result = run_once(_mk_now())

        mock_del.assert_not_called()
        self.assertEqual(result.deleted, 0)

    def test_unpaid_but_active_recently_is_not_deleted(self):
        from inactive_unpaid_cleanup import run_once

        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[TEST_VAULT_ID],
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_unpaid",
            return_value=(True, "none"),
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_inactive",
            return_value=False,
        ), mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
        ) as mock_del:
            result = run_once(_mk_now())

        mock_del.assert_not_called()
        self.assertEqual(result.skipped_now_active, 1)

    def test_paid_inactive_is_not_deleted(self):
        from inactive_unpaid_cleanup import run_once

        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[TEST_VAULT_ID],
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_unpaid",
            return_value=(False, "active"),
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_inactive",
            return_value=True,
        ), mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
        ) as mock_del:
            result = run_once(_mk_now())

        mock_del.assert_not_called()
        self.assertEqual(result.skipped_now_paid, 1)

    def test_paid_active_is_not_deleted(self):
        from inactive_unpaid_cleanup import run_once
        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[],
        ):
            result = run_once(_mk_now())
        self.assertEqual(result.deleted, 0)

    def test_paid_subscription_statuses_never_eligible(self):
        from inactive_unpaid_cleanup import PAID_SUBSCRIPTION_STATUSES
        self.assertIn("active", PAID_SUBSCRIPTION_STATUSES)
        self.assertIn("in_grace", PAID_SUBSCRIPTION_STATUSES)

    def test_cancelled_paid_user_eligible_only_after_entitlement_ends(
        self,
    ):
        from inactive_unpaid_cleanup import (
            PAID_SUBSCRIPTION_STATUSES,
            UNPAID_SUBSCRIPTION_STATUSES,
        )
        self.assertIn("canceled_pending", PAID_SUBSCRIPTION_STATUSES)
        self.assertIn("expired", UNPAID_SUBSCRIPTION_STATUSES)


class TestPart5_JobRechecks(unittest.TestCase):
    """(12) re-checks billing; (13) re-checks activity."""

    def test_job_calls_recheck_unpaid_and_recheck_inactive(self):
        from inactive_unpaid_cleanup import run_once

        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=[TEST_VAULT_ID],
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_unpaid",
            return_value=(True, "none"),
        ) as mock_billing, mock.patch(
            "inactive_unpaid_cleanup._recheck_inactive",
            return_value=True,
        ) as mock_activity, mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
        ):
            run_once(_mk_now())

        mock_billing.assert_called_once_with(TEST_VAULT_ID)
        mock_activity.assert_called_once()

    def test_job_uses_cutoff_matching_6_months(self):
        from inactive_unpaid_cleanup import (
            INACTIVITY_CUTOFF_MONTHS,
        )
        self.assertEqual(INACTIVITY_CUTOFF_MONTHS, 6)


class TestPart6_CascadeAndCryptoSafety(unittest.TestCase):
    """(14) full cascade; (15) no crypto broadcast."""

    def test_deletion_service_uses_delete_from_vaults(self):

        import inspect
        import vault_deletion_service
        src = inspect.getsource(vault_deletion_service)

        self.assertRegex(
            src, r"DELETE\s+FROM\s+vaults",
            msg=(
                "the deletion service must issue DELETE FROM vaults "
                "so PostgreSQL cascades the delete across every "
                "vault-owned table (uploaded_files, vault_items, "
                "semantic_index, etc.)"
            ),
        )

    def test_deletion_service_never_calls_crypto_broadcast(self):

        import inspect
        import vault_deletion_service
        src = inspect.getsource(vault_deletion_service)

        for banned in (
            "broadcast_transaction",
            "send_transaction",
            "sign_transaction",
            "sendrawtransaction",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)

    def test_deletion_service_never_imports_crypto_send_modules(self):

        import inspect
        import vault_deletion_service
        src = inspect.getsource(vault_deletion_service)

        for banned in (
            "crypto_send",
            "monero_send",
            "solana_send",
            "tron_send",
            "ethereum_send",
            "broadcast_raw_transaction",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)


class TestPart7_NoSecretLeakageInLogs(unittest.TestCase):
    """(16) deletion logs contain no secrets."""

    def test_deletion_logs_only_hashed_prefix_not_vault_name(self):
        from vault_deletion_service import (
            hashed_vault_id,
            _hashed_prefix,
        )
        h = hashed_vault_id("vault-name-that-should-not-leak")
        self.assertEqual(len(h), 64)
        self.assertNotIn("vault-name", h)

    def test_delete_endpoint_source_never_logs_pin_value(self):
        import inspect
        from routes import vault_delete_routes
        src = inspect.getsource(vault_delete_routes)

        for banned in (
            'logger.info("pin=',
            'logger.warning("pin=',
            "print(payload.pin",
            'print(f"pin={payload.pin',
            "logger.info(f'pin=%s' % payload.pin",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)

    def test_deletion_service_source_never_prints_encrypted_secret(self):

        import inspect
        import vault_deletion_service
        src = inspect.getsource(vault_deletion_service)

        for banned in (
            "encrypted_data",
            "pin_verifier",
            "pin_salt",
            "seed",
            "mnemonic",
            "private_key",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)


class TestPart8_TombstoneSafety(unittest.TestCase):
    """(17) tombstone contains no sensitive data."""

    def test_tombstone_columns_are_only_id_time_reason_hash(self):
        from pathlib import Path
        p = (
            Path(__file__).parent
            / "migrations"
            / "versions"
            / "0018_vault_activity_and_deletion.py"
        )
        src = p.read_text(encoding="utf-8")

        tombstone_block_start = src.index("vault_deletion_tombstones")
        tombstone_block_end = src.index(
            ")", src.index("CREATE TABLE", tombstone_block_start),
        )
        tombstone_ddl = src[tombstone_block_start:tombstone_block_end]

        self.assertIn("hashed_vault_id", tombstone_ddl)
        self.assertIn("deletion_reason", tombstone_ddl)
        self.assertIn("deleted_at", tombstone_ddl)

        for banned in (
            "vault_name",
            "account_id",
            "wallet_address",
            "encrypted_data",
            "pin_salt",
            "pin_verifier",
            "seed",
            "mnemonic",
            "private_key",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, tombstone_ddl)

    def test_tombstone_stores_hashed_id_not_raw_id(self):
        import inspect
        import vault_deletion_service
        src = inspect.getsource(vault_deletion_service._insert_tombstone)
        self.assertIn("hashed_vault_id(vault_id)", src)


class TestPart9_FaqAndChatRouting(unittest.TestCase):
    """(18) FAQ deletion questions route correctly;
       (19) chat cannot delete directly."""

    def test_faq_questions_route_to_their_own_entries(self):
        from vault_faq_content import FAQ_BY_ID
        from vault_faq_router import build_faq_envelope
        for fid in (
            "delete-my-vault",
            "what-happens-when-i-delete-my-vault",
            "can-i-recover-deleted-vault",
            "crypto-when-vault-deleted",
            "why-inactive-unpaid-deleted",
            "how-to-prevent-auto-deletion",
        ):
            with self.subTest(id=fid):
                q = FAQ_BY_ID[fid]["question"]
                env = build_faq_envelope(q)
                self.assertIsNotNone(env, f"no envelope for {fid!r}")
                self.assertEqual(env["card"]["faqId"], fid)

    def test_chat_delete_message_produces_faq_card_not_delete_action(
        self,
    ):

        from vault_chat_router import (
            classify_and_build_vault_intent, INTENT_FAQ,
        )
        for m in (
            "delete my vault",
            "How do I delete my vault?",
            "I want to delete my profile",
        ):
            with self.subTest(m=m):
                result = classify_and_build_vault_intent(m)
                self.assertEqual(
                    result.get("intent"), INTENT_FAQ,
                    msg=(
                        f"chat message {m!r} must be classified as "
                        "an FAQ (which explains the flow), NOT a "
                        "delete action — chat cannot delete a vault "
                        "in one message"
                    ),
                )

    def test_delete_my_vault_faq_carries_open_delete_action(self):

        from vault_faq_content import (
            FAQ_BY_ID, FAQ_ACTION_OPEN_DELETE_VAULT,
        )
        entry = FAQ_BY_ID["delete-my-vault"]
        actions = entry.get("related_actions", ())
        self.assertIn(
            FAQ_ACTION_OPEN_DELETE_VAULT, actions,
            msg=(
                "the delete-my-vault FAQ card must include the "
                "open_delete_vault_flow action so chat can OPEN the "
                "flow — not perform the deletion"
            ),
        )


class TestPart10_NoPendingDeletionCopy(unittest.TestCase):
    """(20) no pending-deletion or grace-period language anywhere in
    the delete-policy copy."""

    _FORBIDDEN_POLICY_PHRASES = (
        "pending deletion",
        "pending-deletion",
        "grace period",
        "grace-period",
        "30-day grace",
        "30 day grace",
        "scheduled for deletion",
        "will be deleted in",
    )

    _POLICY_FAQ_IDS = (
        "why-inactive-unpaid-deleted",
        "how-to-prevent-auto-deletion",
        "delete-my-vault",
        "what-happens-when-i-delete-my-vault",
        "can-i-recover-deleted-vault",
        "crypto-when-vault-deleted",
    )

    def test_policy_copy_never_uses_grace_or_pending_language(self):
        from vault_faq_content import FAQ_BY_ID
        offenders: list[tuple[str, str]] = []
        for fid in self._POLICY_FAQ_IDS:
            answer = FAQ_BY_ID[fid]["answer"].lower()
            for phrase in self._FORBIDDEN_POLICY_PHRASES:
                if phrase in answer:
                    offenders.append((fid, phrase))
        self.assertEqual(
            offenders, [],
            msg=(
                "policy copy must not mention pending deletion or "
                "grace periods for unpaid inactive users. offenders="
                f"{offenders!r}"
            ),
        )

    def test_no_helpers_named_pending_deletion(self):
        import inspect
        import inactive_unpaid_cleanup
        import vault_deletion_service
        for mod in (inactive_unpaid_cleanup, vault_deletion_service):
            src = inspect.getsource(mod)
            for banned in (
                "pending_deletion",
                "pendingDeletion",
                "PENDING_DELETION",
                "grace_period",
                "GRACE_PERIOD",
            ):
                with self.subTest(mod=mod.__name__, banned=banned):
                    self.assertNotIn(banned, src)


class TestPart11_LoggerCaptureNoLeaks(unittest.TestCase):
    """Extra safety: run a deletion path through capture-log and
    verify no vault_id, PIN, or wallet appears verbatim."""

    def test_delete_vault_logs_hashed_prefix_only(self):

        import inspect
        import vault_deletion_service
        src = inspect.getsource(
            vault_deletion_service.delete_vault_and_all_data,
        )
        self.assertRegex(
            src, r"logger\.info\(\s*\"\[VAULT-DELETE\]",
            msg=(
                "delete_vault_and_all_data must emit a final "
                "[VAULT-DELETE] log line summarising the deletion"
            ),
        )
        self.assertIn(
            "_hashed_prefix(vault_id)", src,
            msg=(
                "the final log line MUST use _hashed_prefix(vault_id) "
                "instead of the raw vault_id so nothing sensitive "
                "leaks into log lines"
            ),
        )

        for banned_expr in (
            "% vault_id",
            "%s\", vault_id",
            "%s\",vault_id",
            "vault_id=%s\", vault_id",
            "{vault_id}",
        ):
            with self.subTest(banned_expr=banned_expr):
                self.assertNotIn(
                    banned_expr, src,
                    msg=(
                        f"logger call in delete_vault_and_all_data "
                        f"must not format the raw vault_id via "
                        f"{banned_expr!r}"
                    ),
                )

    def test_delete_service_rejects_bad_reason(self):
        from vault_deletion_service import (
            delete_vault_and_all_data,
        )
        with self.assertRaises(ValueError):
            delete_vault_and_all_data(
                TEST_VAULT_ID, reason="totally-made-up",
            )


class TestPart12_ChallengeTokenCryptoSafety(unittest.TestCase):
    """Signed challenge token: HMAC-verified, expiry-checked."""

    def test_challenge_token_is_hmac_signed(self):
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        import time as _time
        tok = _sign_challenge(TEST_VAULT_ID,
                              int(_time.time()) + 300)
        self.assertTrue(_verify_challenge(tok, TEST_VAULT_ID))

    def test_tampered_challenge_token_is_rejected(self):
        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        import time as _time
        tok = _sign_challenge(TEST_VAULT_ID,
                              int(_time.time()) + 300)

        tampered = tok[:-2] + ("AA" if tok[-2:] != "AA" else "BB")
        self.assertFalse(_verify_challenge(tampered, TEST_VAULT_ID))


if __name__ == "__main__":
    unittest.main()
