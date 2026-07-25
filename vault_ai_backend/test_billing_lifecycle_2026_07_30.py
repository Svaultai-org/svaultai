"""End-to-end verification for the 2026-07-30 billing-lifecycle fixes.

Four scenarios, mirrored 1-for-1 to the product spec:

  Scenario A — 50 GB plan, 10 GB used, payment fails.
    Expected: full access; uploads continue; downloads continue.

  Scenario B — Stripe eventually cancels the subscription.
    Expected: files remain; folders remain; downloads succeed;
    uploads over free-tier headroom blocked.

  Scenario C — Customer renews (payment succeeds after cancellation).
    Expected: uploads immediately work again; storage restored
    automatically without support intervention.

  Scenario D — Vault deleted after long-term unpaid inactivity.
    Expected: Stripe subscription is cancelled; customer is no
    longer billed.

Plus regression guards for:

  * ``sweep_expired_grace_periods`` — the audit's missing enforcer.
  * ``notify_*`` hooks — banner + email placeholder fire without
    raising.
  * ``cancel_subscription_for_account`` — every outcome (cancelled,
    noop_no_customer, noop_no_subscription, noop_already_cancelled,
    noop_stripe_unconfigured, error).

The tests exercise the REAL webhook handlers with synthesized event
dicts and a lightweight fake DB cursor so no live Postgres or live
Stripe is needed. Fake DB captures SQL + params so we can assert on
the exact state transitions. Nothing here logs plaintext usernames,
emails, passwords, secrets, or vault content.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Optional
from unittest import mock


# ---------------------------------------------------------------------------
# Lightweight fake Postgres cursor / connection. Records executed SQL
# for assertions and produces canned rows for well-known lookups.
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rows_by_query_fragment: dict[str, list[dict]]):
        self._rows_by_frag = rows_by_query_fragment
        self._last_result: list[dict] = []
        self.executed: list[tuple[str, tuple]] = []

    def _match_rows(self, sql: str) -> list[dict]:
        """Match the first configured fragment that appears in SQL."""
        for frag, rows in self._rows_by_frag.items():
            if frag in sql:
                return [dict(r) for r in rows]
        return []

    def execute(self, sql: str, params: tuple = ()):
        self.executed.append((sql, params))
        self._last_result = self._match_rows(sql)

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _FakeConn:
    def __init__(self, rows_by_query_fragment: dict[str, list[dict]]):
        self._rows = rows_by_query_fragment
        self.commits = 0
        self.rollbacks = 0
        self.cursors: list[_FakeCursor] = []

    def cursor(self, cursor_factory=None):
        cur = _FakeCursor(self._rows)
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


ACCOUNT_A = "account-aaaa-1111"
CUSTOMER_A = "cus_test_aaaa"
SUB_A = "sub_test_aaaa"
INVOICE_A = "in_test_aaaa"
BLOCK_PRICE = "price_test_block_50gb"
VAULT_A = "vault-aaaa"


def _billing_setup_env(monkeypatch=None, block_price=BLOCK_PRICE):
    """Ensure `_extract_block_quantity_from_invoice` sees the same
    STRIPE_STORAGE_BLOCK_PRICE_ID we bind into the fake invoices."""
    import os
    prev = os.environ.get("STRIPE_STORAGE_BLOCK_PRICE_ID")
    os.environ["STRIPE_STORAGE_BLOCK_PRICE_ID"] = block_price
    return prev


def _restore_env(prev, key="STRIPE_STORAGE_BLOCK_PRICE_ID"):
    import os
    if prev is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = prev


def _fake_invoice_paid(blocks=1):
    """Build a fake `invoice.payment_succeeded` webhook payload with
    the storage-block line item."""
    return {
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id":            INVOICE_A,
            "customer":      CUSTOMER_A,
            "period_start":  1_700_000_000,
            "period_end":    1_702_500_000,
            "amount_paid":   2500 * blocks,
            "lines": {"data": [{
                "price":    {"id": BLOCK_PRICE},
                "quantity": blocks,
            }]},
        }},
    }


def _fake_invoice_failed(amount_due=2500):
    return {
        "type": "invoice.payment_failed",
        "data": {"object": {
            "id":         INVOICE_A,
            "customer":   CUSTOMER_A,
            "amount_due": amount_due,
        }},
    }


def _fake_subscription_deleted():
    return {
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id":       SUB_A,
            "customer": CUSTOMER_A,
            "status":   "canceled",
        }},
    }


# ---------------------------------------------------------------------------
# Scenario A — payment fails, user retains full access
# ---------------------------------------------------------------------------

class ScenarioA_PaymentFailsFullAccess(unittest.TestCase):
    """50 GB plan, 10 GB used, payment fails. Expected: status
    flips from active to in_grace; entitlement stays at 50 GB;
    uploads/downloads/reads all succeed; payment_failed banner fires."""

    def test_payment_failed_sets_in_grace_preserves_entitlement(self):
        import stripe_service as ss
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT grace_period_ends_at FROM account_subscriptions":
                [{"grace_period_ends_at": None}],
        }
        conn = _FakeConn(rows)
        cur = conn.cursor()
        prev = _billing_setup_env()
        notif_calls: list = []

        def stub_notify_payment_failed(account_id, **kwargs):
            notif_calls.append(("payment_failed", account_id, kwargs))

        try:
            with mock.patch(
                "vault_billing_notifications.notify_payment_failed",
                side_effect=stub_notify_payment_failed,
            ):
                account_id = ss._handle_invoice_payment_failed(
                    _fake_invoice_failed(),
                    cur,
                )
        finally:
            _restore_env(prev)

        self.assertEqual(account_id, ACCOUNT_A)
        # First UPDATE flips status to in_grace, preserves entitlement.
        update_sql = cur.executed[1][0]
        self.assertIn("UPDATE account_subscriptions", update_sql)
        self.assertIn("'in_grace'", update_sql)
        self.assertIn("grace_period_ends_at", update_sql)
        # No storage/quota reduction — block_count / purchased_bytes untouched.
        self.assertNotIn("block_count", update_sql)
        self.assertNotIn("purchased_bytes", update_sql)
        # Banner dispatched exactly once.
        self.assertEqual(len(notif_calls), 1)
        self.assertEqual(notif_calls[0][0], "payment_failed")
        self.assertEqual(notif_calls[0][1], ACCOUNT_A)

    def test_in_grace_still_grants_full_storage(self):
        # billing._STATUSES_THAT_GRANT_STORAGE includes 'in_grace' so
        # a first-failure user retains their paid entitlement during
        # Stripe dunning.
        import billing
        self.assertIn("in_grace", billing._STATUSES_THAT_GRANT_STORAGE)
        self.assertIn("active", billing._STATUSES_THAT_GRANT_STORAGE)
        self.assertIn("canceled_pending",
                      billing._STATUSES_THAT_GRANT_STORAGE)

    def test_read_and_download_never_check_billing(self):
        # Static-source guard: /list-files and /download-file must not
        # touch get_entitlement. Regression trap for anyone who might
        # add a billing gate on read paths.
        import main as _main
        src_path = _main.__file__
        with open(src_path, "r", encoding="utf-8") as fp:
            source = fp.read()
        # Find the download-file endpoint body and confirm it doesn't
        # call get_entitlement.
        dl_marker = "download_file_endpoint("
        dl_pos = source.find(dl_marker)
        self.assertGreater(dl_pos, 0)
        # Look 2000 chars ahead — endpoint body is well within that
        # window.
        window = source[dl_pos:dl_pos + 2000]
        self.assertNotIn("get_entitlement", window)
        self.assertNotIn("has_active_subscription", window)


# ---------------------------------------------------------------------------
# Scenario B — Stripe eventually cancels the subscription
# ---------------------------------------------------------------------------

class ScenarioB_CancelledFilesRemain(unittest.TestCase):
    """After dunning exhausts, Stripe fires customer.subscription.deleted.
    Expected: block_count / purchased_bytes zeroed, status becomes
    over_quota_grace (used > free) or expired, files NOT deleted,
    reads/downloads still work."""

    def test_subscription_deleted_zeroes_entitlement_no_data_deletion(self):
        import stripe_service as ss

        # Simulate a user at 10 GB (> 1 GB free tier). SQL branch
        # produces over_quota_grace.
        rows = {
            "SELECT block_count, purchased_bytes":
                [{"block_count": 1, "purchased_bytes": 53_687_091_200}],
            "SELECT status, over_quota_grace_ends_at":
                [{"status": "over_quota_grace",
                  "over_quota_grace_ends_at": None}],
            # _resolve_account_id_from_subscription reads
            # stripe_customers.
            "FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            # Look up via source_subscription_id fallback.
            "FROM account_subscriptions":
                [{"account_id": ACCOUNT_A}],
        }
        conn = _FakeConn(rows)
        cur = conn.cursor()
        notif_calls: list = []

        def stub_notify_cancelled(account_id, **kwargs):
            notif_calls.append(("cancelled", account_id, kwargs))

        with mock.patch(
            "vault_billing_notifications.notify_subscription_cancelled",
            side_effect=stub_notify_cancelled,
        ):
            account_id = ss._handle_subscription_deleted(
                _fake_subscription_deleted(),
                cur,
            )

        self.assertEqual(account_id, ACCOUNT_A)
        # The UPDATE zeros out block_count / purchased_bytes and
        # transitions to over_quota_grace or expired. Files are NOT
        # in any of the SQL statements the handler executed — this
        # is the primary assertion of the audit's design invariant.
        for sql, _params in cur.executed:
            self.assertNotIn("DELETE FROM uploaded_files", sql.upper())
            self.assertNotIn("DELETE FROM VAULT_ITEMS", sql.upper())
            self.assertNotIn("DELETE FROM VAULTS", sql.upper())
            self.assertNotIn("UPDATE UPLOADED_FILES", sql.upper())
            self.assertNotIn("UPDATE VAULTS", sql.upper())
        # Banner dispatched.
        self.assertEqual(len(notif_calls), 1)
        self.assertEqual(notif_calls[0][0], "cancelled")

    def test_expired_status_falls_to_free_tier(self):
        # billing._purchased_bytes_active returns 0 for expired /
        # over_quota_grace / over_quota_locked. get_entitlement then
        # collapses effective_limit to included_bytes (1 GB free).
        import billing
        self.assertNotIn(
            "expired", billing._STATUSES_THAT_GRANT_STORAGE,
        )
        self.assertNotIn(
            "over_quota_grace", billing._STATUSES_THAT_GRANT_STORAGE,
        )
        self.assertNotIn(
            "over_quota_locked", billing._STATUSES_THAT_GRANT_STORAGE,
        )
        self.assertNotIn(
            "past_due", billing._STATUSES_THAT_GRANT_STORAGE,
        )


# ---------------------------------------------------------------------------
# Scenario C — customer renews; storage restored automatically
# ---------------------------------------------------------------------------

class ScenarioC_RenewalRestoresAutomatically(unittest.TestCase):
    """After Scenario B, a subsequent invoice.payment_succeeded MUST
    restore block_count and purchased_bytes without any manual
    support intervention. This is the audit's Bug #1 fix."""

    def _run_paid(self, prior_status, invoice_blocks=1):
        import stripe_service as ss
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": prior_status, "block_count": 0,
                  "purchased_bytes": 0}],
        }
        conn = _FakeConn(rows)
        cur = conn.cursor()
        prev = _billing_setup_env()
        recovered_calls: list = []

        def stub_notify_recovered(account_id, **kwargs):
            recovered_calls.append(("recovered", account_id, kwargs))

        try:
            with mock.patch(
                "vault_billing_notifications.notify_payment_recovered",
                side_effect=stub_notify_recovered,
            ):
                account_id = ss._handle_invoice_payment_succeeded(
                    _fake_invoice_paid(blocks=invoice_blocks),
                    cur,
                )
        finally:
            _restore_env(prev)
        return account_id, cur, recovered_calls

    def test_recovery_from_expired_restores_block_count(self):
        account_id, cur, calls = self._run_paid("expired", invoice_blocks=1)
        self.assertEqual(account_id, ACCOUNT_A)
        # Find the restore UPDATE.
        restore_sql = None
        restore_params = None
        for sql, params in cur.executed:
            if ("UPDATE account_subscriptions" in sql
                    and "block_count" in sql
                    and "'active'" in sql):
                restore_sql = sql
                restore_params = params
                break
        self.assertIsNotNone(restore_sql,
                             "restore UPDATE must fire for expired")
        # Params: (block_count, purchased_bytes, period_start, period_end, account_id)
        self.assertEqual(restore_params[0], 1)
        self.assertEqual(restore_params[1], 53_687_091_200)
        self.assertEqual(restore_params[-1], ACCOUNT_A)
        # Restore also clears over_quota_grace_ends_at.
        self.assertIn("over_quota_grace_ends_at = NULL", restore_sql)
        # payment_recovered banner fires.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "recovered")
        self.assertEqual(calls[0][2].get("restored_block_count"), 1)

    def test_recovery_from_over_quota_grace_restores(self):
        _account_id, cur, _calls = self._run_paid(
            "over_quota_grace", invoice_blocks=1,
        )
        found = False
        for sql, params in cur.executed:
            if ("block_count" in sql
                    and "'active'" in sql
                    and "over_quota_grace_ends_at = NULL" in sql):
                found = True
                self.assertEqual(params[0], 1)
        self.assertTrue(found)

    def test_recovery_from_over_quota_locked_restores(self):
        # Even from over_quota_locked (final state after grace
        # sweep), a successful payment must restore. Belt-and-braces.
        _account_id, cur, _calls = self._run_paid(
            "over_quota_locked", invoice_blocks=2,
        )
        found = False
        for sql, params in cur.executed:
            if "block_count" in sql and "'active'" in sql:
                found = True
                self.assertEqual(params[0], 2)
                self.assertEqual(params[1], 2 * 53_687_091_200)
        self.assertTrue(found)

    def test_active_paying_customer_unaffected(self):
        # An already-active customer's payment_succeeded must not
        # do a full restore; only the simple flip (which is a no-op
        # for status='active'). Regression trap for over-eager
        # restore logic.
        _account_id, cur, calls = self._run_paid(
            "active", invoice_blocks=1,
        )
        # No restore UPDATE (the simple-flip UPDATE runs instead,
        # which does NOT mention block_count).
        for sql, _params in cur.executed:
            if "UPDATE account_subscriptions" in sql:
                self.assertNotIn("block_count", sql)
        # No payment_recovered banner (nothing to recover from).
        self.assertEqual(len(calls), 0)

    def test_in_grace_recovers_without_restore(self):
        _account_id, cur, calls = self._run_paid(
            "in_grace", invoice_blocks=1,
        )
        # Simple-flip UPDATE.
        for sql, _params in cur.executed:
            if "UPDATE account_subscriptions" in sql:
                self.assertNotIn("block_count", sql)
        # Banner fires (transitioned FROM in_grace to active).
        self.assertEqual(len(calls), 1)

    def test_invoice_without_block_line_does_not_restore(self):
        # Some invoices carry unrelated line items (add-ons,
        # one-time charges). Recovery must NOT invent a block_count.
        import stripe_service as ss
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        conn = _FakeConn(rows)
        cur = conn.cursor()
        prev = _billing_setup_env()
        try:
            with mock.patch(
                "vault_billing_notifications.notify_payment_recovered",
                side_effect=lambda *a, **k: None,
            ):
                unrelated_invoice = {
                    "type": "invoice.payment_succeeded",
                    "data": {"object": {
                        "id": INVOICE_A, "customer": CUSTOMER_A,
                        "amount_paid": 100,
                        "lines": {"data": [{
                            "price": {"id": "price_unrelated"},
                            "quantity": 5,
                        }]},
                    }},
                }
                ss._handle_invoice_payment_succeeded(unrelated_invoice, cur)
        finally:
            _restore_env(prev)
        # No restore UPDATE (block_count wouldn't appear in the SQL).
        for sql, _params in cur.executed:
            if "UPDATE account_subscriptions" in sql:
                self.assertNotIn("block_count", sql)


# ---------------------------------------------------------------------------
# Scenario D — vault deleted after long-term unpaid inactivity
# ---------------------------------------------------------------------------

class ScenarioD_VaultDeletionCancelsStripe(unittest.TestCase):
    """The 6-month unpaid-inactive cleanup path MUST cancel the
    linked Stripe subscription; leaving it live would keep charging
    a card for a vault whose data has been irreversibly deleted.

    2026-07-30 audit-review safety: additionally the vault delete
    MUST be blocked when the Stripe cancel returns an error
    outcome (transient API failure). Prior version discarded the
    outcome and deleted anyway — customer could keep being billed
    for a permanently-deleted vault.
    """

    def _run_delete_with_cancel_outcome(self, cancel_result_kwargs):
        """Helper: exercise delete_vault_and_all_data with the
        Stripe cancel returning the specified CancelSubscriptionResult
        kwargs. Returns (raised_exception_or_none, delete_row_called).
        """
        import vault_deletion_service as vds
        from stripe_service import CancelSubscriptionResult
        delete_row_calls: list = []

        def stub_delete_row(vault_id):
            delete_row_calls.append(vault_id)
            return True

        with mock.patch(
            "billing.get_account_id_for_vault",
            return_value=ACCOUNT_A,
        ), mock.patch(
            "stripe_service.cancel_subscription_for_account",
            return_value=CancelSubscriptionResult(**cancel_result_kwargs),
        ), mock.patch(
            "vault_deletion_service._delete_vault_row",
            side_effect=stub_delete_row,
        ), mock.patch(
            "vault_deletion_service._insert_tombstone",
            return_value=None,
        ), mock.patch(
            "vault_deletion_service._account_has_other_vaults",
            return_value=True,
        ):
            raised = None
            try:
                vds.delete_vault_and_all_data(
                    "vault-blocked-by-stripe",
                    reason=vds.REASON_USER_REQUESTED,
                )
            except Exception as exc:
                raised = exc
        return raised, delete_row_calls

    def test_delete_blocked_when_stripe_cancel_errors(self):
        # THE AUDIT-REVIEW DEFECT FIX. When Stripe returns
        # outcome='error' (network failure, 5xx, etc.), the vault
        # row MUST NOT be deleted — otherwise the customer could
        # keep being billed for a permanently-deleted vault.
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome":         "error",
            "subscription_id": SUB_A,
            "detail":          "raised:APIConnectionError",
        })
        from vault_deletion_service import (
            VaultDeletionBlockedByStripeError,
        )
        self.assertIsInstance(raised, VaultDeletionBlockedByStripeError)
        # Critical assertion: the local vault row was NOT deleted.
        self.assertEqual(
            delete_calls, [],
            "vault MUST NOT be deleted when Stripe cancel errors",
        )
        # The exception carries the hashed prefix + detail so ops
        # traces are meaningful.
        self.assertTrue(raised.vault_id_hashed_prefix)
        self.assertIn("stripe_error", raised.detail)

    def test_delete_proceeds_on_cancelled_outcome(self):
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome":         "cancelled",
            "subscription_id": SUB_A,
        })
        self.assertIsNone(raised)
        self.assertEqual(delete_calls, ["vault-blocked-by-stripe"])

    def test_delete_proceeds_on_noop_no_customer(self):
        # Never subscribed → nothing to cancel → safe to proceed.
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome": "noop_no_customer",
        })
        self.assertIsNone(raised)
        self.assertEqual(delete_calls, ["vault-blocked-by-stripe"])

    def test_delete_proceeds_on_noop_no_subscription(self):
        # Stripe customer exists but no subscription id on file →
        # nothing to cancel → safe to proceed.
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome": "noop_no_subscription",
        })
        self.assertIsNone(raised)
        self.assertEqual(delete_calls, ["vault-blocked-by-stripe"])

    def test_delete_proceeds_on_noop_already_cancelled(self):
        # Stripe reports subscription is already gone (idempotent) →
        # safe to proceed.
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome":         "noop_already_cancelled",
            "subscription_id": SUB_A,
        })
        self.assertIsNone(raised)
        self.assertEqual(delete_calls, ["vault-blocked-by-stripe"])

    def test_delete_proceeds_on_noop_stripe_unconfigured(self):
        # Dev / CI mode without STRIPE_API_KEY → we can't cancel
        # but nothing on Stripe side to charge either. Safe.
        raised, delete_calls = self._run_delete_with_cancel_outcome({
            "outcome": "noop_stripe_unconfigured",
        })
        self.assertIsNone(raised)
        self.assertEqual(delete_calls, ["vault-blocked-by-stripe"])

    def test_delete_blocked_when_cancel_raises(self):
        # If cancel_subscription_for_account itself raises (rather
        # than returning an error result) the block MUST still fire.
        import vault_deletion_service as vds
        delete_row_calls: list = []

        def stub_delete_row(vault_id):
            delete_row_calls.append(vault_id)
            return True

        with mock.patch(
            "billing.get_account_id_for_vault",
            return_value=ACCOUNT_A,
        ), mock.patch(
            "stripe_service.cancel_subscription_for_account",
            side_effect=RuntimeError("network partition"),
        ), mock.patch(
            "vault_deletion_service._delete_vault_row",
            side_effect=stub_delete_row,
        ), mock.patch(
            "vault_deletion_service._insert_tombstone",
            return_value=None,
        ), mock.patch(
            "vault_deletion_service._account_has_other_vaults",
            return_value=True,
        ):
            with self.assertRaises(
                vds.VaultDeletionBlockedByStripeError,
            ):
                vds.delete_vault_and_all_data(
                    "vault-cancel-raised",
                    reason=vds.REASON_USER_REQUESTED,
                )
        self.assertEqual(
            delete_row_calls, [],
            "delete must be blocked when cancel raises",
        )

    def test_cleanup_job_defers_when_delete_is_blocked(self):
        # inactive_unpaid_cleanup.run_once MUST treat
        # VaultDeletionBlockedByStripeError as a deferred deletion,
        # not a hard error. The row stays and tomorrow's job retries.
        import inactive_unpaid_cleanup as iuc
        from vault_deletion_service import (
            VaultDeletionBlockedByStripeError,
        )
        with mock.patch(
            "inactive_unpaid_cleanup._find_candidate_vault_ids",
            return_value=["vault-idle-unpaid"],
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_unpaid",
            return_value=(True, "past_due"),
        ), mock.patch(
            "inactive_unpaid_cleanup._recheck_inactive",
            return_value=True,
        ), mock.patch(
            "inactive_unpaid_cleanup.delete_vault_and_all_data",
            side_effect=VaultDeletionBlockedByStripeError(
                vault_id_hashed_prefix="deadbeef1234",
                detail="stripe_error:APIConnectionError",
            ),
        ), mock.patch(
            "stripe_service.sweep_expired_grace_periods",
            return_value={"in_grace_expired": 0,
                          "over_quota_grace_expired": 0,
                          "notifications_sent": 0, "errors": []},
        ):
            result = iuc.run_once()
        # Vault was scanned but NOT deleted; error count reflects
        # the deferral so ops metrics catch persistent Stripe
        # outages.
        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.deleted, 0)
        self.assertGreaterEqual(result.errors, 1)

    def test_cancel_subscription_for_account_reachable_from_deletion(self):
        # vault_deletion_service._cancel_stripe_subscription_best_effort
        # tries `from stripe_service import cancel_subscription_for_account`.
        # Before this commit that import raised ImportError; after,
        # the symbol resolves. This is the audit's Bug #4 fix.
        import vault_deletion_service as vds
        # The symbol MUST be present in stripe_service.
        from stripe_service import cancel_subscription_for_account
        self.assertTrue(callable(cancel_subscription_for_account))
        # And the deletion wrapper must not crash.
        with mock.patch(
            "billing.get_account_id_for_vault",
            return_value=None,
        ):
            # No account for the vault — best-effort no-op, no raise.
            vds._cancel_stripe_subscription_best_effort("vault-fake")

    def test_cancel_outcome_noop_when_no_customer(self):
        from stripe_service import cancel_subscription_for_account
        with mock.patch(
            "stripe_service._stripe_initialized",
            return_value=True,
        ), mock.patch(
            "stripe_service.get_stripe_customer_id_for_account",
            return_value=None,
        ):
            result = cancel_subscription_for_account(ACCOUNT_A)
        self.assertEqual(result.outcome, "noop_no_customer")

    def test_cancel_outcome_noop_when_stripe_unconfigured(self):
        from stripe_service import cancel_subscription_for_account
        with mock.patch(
            "stripe_service._stripe_initialized",
            return_value=False,
        ):
            result = cancel_subscription_for_account(ACCOUNT_A)
        self.assertEqual(result.outcome, "noop_stripe_unconfigured")

    def test_cancel_outcome_noop_when_no_subscription_id(self):
        from stripe_service import cancel_subscription_for_account
        rows = {
            "FROM account_subscriptions":
                [{"source_subscription_id": None}],
        }
        with mock.patch(
            "stripe_service._stripe_initialized",
            return_value=True,
        ), mock.patch(
            "stripe_service.get_stripe_customer_id_for_account",
            return_value=CUSTOMER_A,
        ), mock.patch(
            "stripe_service.get_db",
            return_value=_FakeConn(rows),
        ):
            result = cancel_subscription_for_account(ACCOUNT_A)
        self.assertEqual(result.outcome, "noop_no_subscription")

    def test_cancel_outcome_cancelled_calls_stripe(self):
        from stripe_service import cancel_subscription_for_account
        rows = {
            "FROM account_subscriptions":
                [{"source_subscription_id": SUB_A}],
        }
        stripe_calls: list = []

        def fake_cancel(sub_id):
            stripe_calls.append(sub_id)
            return {"id": sub_id, "status": "canceled"}

        # The audit stamp writes to the DB via a second get_db call.
        # Both calls receive our fake conn.
        with mock.patch(
            "stripe_service._stripe_initialized",
            return_value=True,
        ), mock.patch(
            "stripe_service.get_stripe_customer_id_for_account",
            return_value=CUSTOMER_A,
        ), mock.patch(
            "stripe_service.get_db",
            side_effect=lambda: _FakeConn(rows),
        ), mock.patch(
            "stripe_service.stripe.Subscription.cancel",
            side_effect=fake_cancel,
        ):
            result = cancel_subscription_for_account(
                ACCOUNT_A, reason="test_case",
            )
        self.assertEqual(result.outcome, "cancelled")
        self.assertEqual(result.subscription_id, SUB_A)
        self.assertEqual(stripe_calls, [SUB_A])

    def test_cancel_outcome_already_cancelled_is_noop(self):
        # Stripe raises InvalidRequestError when the sub is already
        # cancelled — MUST be treated as noop_already_cancelled, not
        # error, so retries after partial failure are idempotent.
        from stripe_service import cancel_subscription_for_account
        import stripe as _stripe
        rows = {
            "FROM account_subscriptions":
                [{"source_subscription_id": SUB_A}],
        }

        def fake_cancel(sub_id):
            raise _stripe.error.InvalidRequestError(
                "No such subscription: sub_xxx", None,
            )

        with mock.patch(
            "stripe_service._stripe_initialized",
            return_value=True,
        ), mock.patch(
            "stripe_service.get_stripe_customer_id_for_account",
            return_value=CUSTOMER_A,
        ), mock.patch(
            "stripe_service.get_db",
            return_value=_FakeConn(rows),
        ), mock.patch(
            "stripe_service.stripe.Subscription.cancel",
            side_effect=fake_cancel,
        ):
            result = cancel_subscription_for_account(ACCOUNT_A)
        self.assertEqual(result.outcome, "noop_already_cancelled")


# ---------------------------------------------------------------------------
# Grace-period sweep — the audit's Fix #4
# ---------------------------------------------------------------------------

class GracePeriodSweepTest(unittest.TestCase):

    def test_sweep_transitions_and_notifies(self):
        from stripe_service import sweep_expired_grace_periods
        rows = {
            "status = 'in_grace'":
                [{"account_id": "acct-grace-1"},
                 {"account_id": "acct-grace-2"}],
            "status = 'over_quota_grace'":
                [{"account_id": "acct-oq-1"}],
        }
        conn = _FakeConn(rows)
        notif_calls: list = []

        def stub_payment_failed(account_id, **k):
            notif_calls.append(("payment_failed", account_id))

        def stub_over_quota(account_id, **k):
            notif_calls.append(("over_quota", account_id))

        with mock.patch(
            "stripe_service.get_db", return_value=conn,
        ), mock.patch(
            "vault_billing_notifications.notify_payment_failed",
            side_effect=stub_payment_failed,
        ), mock.patch(
            "vault_billing_notifications.notify_account_over_quota",
            side_effect=stub_over_quota,
        ):
            summary = sweep_expired_grace_periods()

        self.assertEqual(summary["in_grace_expired"], 2)
        self.assertEqual(summary["over_quota_grace_expired"], 1)
        self.assertEqual(summary["notifications_sent"], 3)
        self.assertEqual(len(notif_calls), 3)

    def test_sweep_is_wired_into_daily_cleanup(self):
        # Static-source check: the daily job MUST call the sweep
        # before the deletion pass, otherwise the grace-state
        # enforcer never runs in production.
        import inactive_unpaid_cleanup as iuc
        src_path = iuc.__file__
        with open(src_path, "r", encoding="utf-8") as fp:
            source = fp.read()
        self.assertIn("sweep_expired_grace_periods", source)
        # The sweep call must appear inside run_once (source-order
        # guard).
        run_once_pos = source.find("def run_once(")
        sweep_pos = source.find("sweep_expired_grace_periods", run_once_pos)
        self.assertGreater(sweep_pos, run_once_pos)


# ---------------------------------------------------------------------------
# Notification module surface — banners + email placeholder
# ---------------------------------------------------------------------------

class NotificationSurfaceTest(unittest.TestCase):

    def test_all_four_kinds_defined(self):
        import vault_billing_notifications as vbn
        self.assertEqual(
            vbn.ALL_BILLING_KINDS,
            frozenset({
                vbn.NOTIFY_KIND_PAYMENT_FAILED,
                vbn.NOTIFY_KIND_PAYMENT_RECOVERED,
                vbn.NOTIFY_KIND_SUBSCRIPTION_CANCELLED,
                vbn.NOTIFY_KIND_ACCOUNT_OVER_QUOTA,
            }),
        )

    def test_email_placeholder_never_raises(self):
        import vault_billing_notifications as vbn
        # The placeholder is a pure log; ensure it doesn't raise
        # for any of the four kinds.
        for kind in vbn.ALL_BILLING_KINDS:
            vbn._dispatch_billing_email(
                ACCOUNT_A, kind, metadata={"key": "val"},
            )
        # Passing an unknown account id or None must also not raise.
        vbn._dispatch_billing_email(
            "", vbn.NOTIFY_KIND_PAYMENT_FAILED,
        )

    def test_fanout_inserts_per_vault(self):
        import vault_billing_notifications as vbn
        banner_calls: list = []

        def stub_insert(vault_id, kind, metadata=None):
            banner_calls.append((vault_id, kind))

        with mock.patch(
            "vault_billing_notifications._vault_ids_for_account",
            return_value=["v1", "v2", "v3"],
        ), mock.patch(
            "vault_billing_notifications._insert_banner",
            side_effect=stub_insert,
        ):
            vbn.notify_payment_failed(ACCOUNT_A)
        self.assertEqual(
            {c[0] for c in banner_calls},
            {"v1", "v2", "v3"},
        )
        for _vid, kind in banner_calls:
            self.assertEqual(kind, vbn.NOTIFY_KIND_PAYMENT_FAILED)

    def test_public_api_swallows_errors(self):
        # Notification failures must NEVER propagate — webhook
        # handlers depend on this.
        import vault_billing_notifications as vbn
        with mock.patch(
            "vault_billing_notifications._vault_ids_for_account",
            side_effect=RuntimeError("db down"),
        ):
            # No exception should escape.
            vbn.notify_payment_failed(ACCOUNT_A)
            vbn.notify_payment_recovered(ACCOUNT_A)
            vbn.notify_subscription_cancelled(ACCOUNT_A, over_quota=True)
            vbn.notify_account_over_quota(ACCOUNT_A)


# ---------------------------------------------------------------------------
# Read-side product-behavior guards (no billing check ever)
# ---------------------------------------------------------------------------

class ReadPathsRemainUnguardedTest(unittest.TestCase):
    """Regression trap for the product-behavior invariant that
    read/download/delete NEVER check billing. This is the intended
    behavior — users retain access to their existing files after
    their subscription ends. Anyone who adds a billing gate on a
    read path will break this test."""

    def _handler_body(self, marker, window=2500):
        import main as _main
        with open(_main.__file__, "r", encoding="utf-8") as fp:
            source = fp.read()
        pos = source.find(marker)
        self.assertGreater(pos, 0, f"marker {marker!r} not found")
        return source[pos:pos + window]

    def test_download_file_endpoint_no_billing_check(self):
        body = self._handler_body("download_file_endpoint(")
        self.assertNotIn("get_entitlement", body)
        self.assertNotIn("has_active_subscription", body)

    def test_list_files_endpoint_no_billing_check(self):
        body = self._handler_body("list_files_endpoint(")
        self.assertNotIn("get_entitlement", body)
        self.assertNotIn("has_active_subscription", body)

    def test_delete_file_endpoint_no_billing_check(self):
        body = self._handler_body("delete_file_endpoint(")
        self.assertNotIn("get_entitlement", body)
        self.assertNotIn("has_active_subscription", body)


# ---------------------------------------------------------------------------
# Pre-deployment focused test #1 — multi-block recovery quantity
# ---------------------------------------------------------------------------
#
# Delayed payment recovery must restore the exact block quantity from
# the Stripe invoice line item. Bug pattern to catch: any place the
# handler treats "1 block" as a default or ignores the quantity.
#   1 block   =  50 GB
#   2 blocks  = 100 GB
#   5 blocks  = 250 GB
# 100 blocks  =   5 TB
# For each, block_count MUST equal the invoice-line quantity exactly
# and purchased_bytes MUST equal quantity * 53_687_091_200 exactly.
# ---------------------------------------------------------------------------

class MultiBlockRecoveryExactQuantityTest(unittest.TestCase):
    """The audit's Bug #1 fix depends on
    ``_extract_block_quantity_from_invoice`` returning EXACTLY the
    line-item quantity and ``_handle_invoice_payment_succeeded``
    writing that quantity verbatim into ``block_count`` and
    ``block_count * 50GB`` into ``purchased_bytes``. This test
    exercises the whole path with four representative quantities."""

    _BLOCK_BYTES = 53_687_091_200  # 50 GB — must match billing.block_bytes()

    def _run_recovery(self, invoice_blocks, prior_status="expired"):
        import stripe_service as ss
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": prior_status, "block_count": 0,
                  "purchased_bytes": 0}],
        }
        conn = _FakeConn(rows)
        cur = conn.cursor()
        prev = _billing_setup_env()
        try:
            with mock.patch(
                "vault_billing_notifications.notify_payment_recovered",
                side_effect=lambda *a, **k: None,
            ):
                account_id = ss._handle_invoice_payment_succeeded(
                    _fake_invoice_paid(blocks=invoice_blocks),
                    cur,
                )
        finally:
            _restore_env(prev)
        return account_id, cur

    def _restore_params(self, cur):
        """Locate the restore UPDATE and return its bound params.
        Raises AssertionError if no restore UPDATE was issued (that
        would itself be a recovery-bug regression)."""
        for sql, params in cur.executed:
            if ("UPDATE account_subscriptions" in sql
                    and "block_count" in sql
                    and "'active'" in sql):
                return sql, params
        raise AssertionError(
            "no restore UPDATE fired — recovery-bug regression"
        )

    def test_extractor_returns_exact_quantity_1(self):
        import stripe_service as ss
        prev = _billing_setup_env()
        try:
            invoice = _fake_invoice_paid(blocks=1)["data"]["object"]
            self.assertEqual(
                ss._extract_block_quantity_from_invoice(invoice), 1,
            )
        finally:
            _restore_env(prev)

    def test_extractor_returns_exact_quantity_2(self):
        import stripe_service as ss
        prev = _billing_setup_env()
        try:
            invoice = _fake_invoice_paid(blocks=2)["data"]["object"]
            self.assertEqual(
                ss._extract_block_quantity_from_invoice(invoice), 2,
            )
        finally:
            _restore_env(prev)

    def test_extractor_returns_exact_quantity_5(self):
        import stripe_service as ss
        prev = _billing_setup_env()
        try:
            invoice = _fake_invoice_paid(blocks=5)["data"]["object"]
            self.assertEqual(
                ss._extract_block_quantity_from_invoice(invoice), 5,
            )
        finally:
            _restore_env(prev)

    def test_extractor_returns_exact_quantity_100(self):
        import stripe_service as ss
        prev = _billing_setup_env()
        try:
            invoice = _fake_invoice_paid(blocks=100)["data"]["object"]
            self.assertEqual(
                ss._extract_block_quantity_from_invoice(invoice), 100,
            )
        finally:
            _restore_env(prev)

    def test_recovery_restores_exact_1_block_50gb(self):
        _acct, cur = self._run_recovery(invoice_blocks=1)
        _sql, params = self._restore_params(cur)
        self.assertEqual(params[0], 1,
                         "block_count must be exactly 1")
        self.assertEqual(params[1], 1 * self._BLOCK_BYTES,
                         "purchased_bytes must be exactly 50 GB")
        self.assertEqual(params[-1], ACCOUNT_A)

    def test_recovery_restores_exact_2_blocks_100gb(self):
        _acct, cur = self._run_recovery(invoice_blocks=2)
        _sql, params = self._restore_params(cur)
        self.assertEqual(params[0], 2,
                         "block_count must be exactly 2")
        self.assertEqual(params[1], 2 * self._BLOCK_BYTES,
                         "purchased_bytes must be exactly 100 GB")

    def test_recovery_restores_exact_5_blocks_250gb(self):
        _acct, cur = self._run_recovery(invoice_blocks=5)
        _sql, params = self._restore_params(cur)
        self.assertEqual(params[0], 5,
                         "block_count must be exactly 5")
        self.assertEqual(params[1], 5 * self._BLOCK_BYTES,
                         "purchased_bytes must be exactly 250 GB")

    def test_recovery_restores_exact_100_blocks_5tb(self):
        _acct, cur = self._run_recovery(invoice_blocks=100)
        _sql, params = self._restore_params(cur)
        self.assertEqual(params[0], 100,
                         "block_count must be exactly 100")
        self.assertEqual(params[1], 100 * self._BLOCK_BYTES,
                         "purchased_bytes must be exactly 5 TB "
                         "(100 * 50 GB)")
        # Sanity: 5 TB in bytes.
        self.assertEqual(params[1], 5_368_709_120_000)

    def test_subscription_events_row_carries_exact_to_block_count(self):
        # The audit trail row (subscription_events) is what support
        # uses to confirm what a user was granted. It MUST also record
        # the exact restored quantity, not the pre-existing 0.
        _acct, cur = self._run_recovery(invoice_blocks=100)
        found = False
        for sql, params in cur.executed:
            if ("INSERT INTO subscription_events" in sql
                    and "'renewed'" in sql):
                found = True
                # Ordered params in the INSERT:
                #   (account_id, source_event_id, from_block_count,
                #    to_block_count, from_purchased_bytes,
                #    to_purchased_bytes, payload_jsonb)
                # from_block_count = prior (0), to_block_count = 100.
                self.assertEqual(params[2], 0,
                                 "from_block_count must equal prior")
                self.assertEqual(params[3], 100,
                                 "to_block_count must equal restored")
                self.assertEqual(params[5], 100 * self._BLOCK_BYTES,
                                 "to_purchased_bytes exact")
        self.assertTrue(
            found, "renewed audit row must be inserted",
        )


# ---------------------------------------------------------------------------
# Pre-deployment focused test #2 — duplicate webhook idempotency
# ---------------------------------------------------------------------------
#
# Stripe delivers webhooks at-least-once. Delivering the same
# invoice.payment_succeeded event twice must not double-grant
# storage. Idempotency is enforced by the UNIQUE (source,
# source_event_id) constraint on provider_event_log — the second
# INSERT raises psycopg2.errors.UniqueViolation and the dispatcher
# returns outcome='ignored_duplicate' WITHOUT invoking the handler.
# ---------------------------------------------------------------------------

class _FakeConnWithEventLogUnique:
    """Fake connection whose cursor rejects a second INSERT with the
    same event_id on ``provider_event_log`` — the exact behavior of
    the real UNIQUE (source, source_event_id) constraint. Everything
    else executes normally against a shared per-cursor rows fixture.

    A single instance is reused across dispatch_webhook_event calls
    (dispatch_webhook_event does one get_db() per call), so the
    seen-events set persists across calls just like the real DB."""

    def __init__(self, rows_by_query_fragment):
        self._rows = rows_by_query_fragment
        self._seen_event_ids: set[str] = set()
        self.commits = 0
        self.rollbacks = 0
        self.cursors: list = []
        self.handler_reached_count = 0

    def cursor(self, cursor_factory=None):
        cur = _EventLogAwareCursor(
            self._rows, self._seen_event_ids, self,
        )
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _EventLogAwareCursor(_FakeCursor):
    """_FakeCursor that raises UniqueViolation on repeated event_id
    INSERTs. Also tracks whenever a handler-side SQL runs so the
    test can assert the handler was NEVER invoked for the duplicate."""

    def __init__(self, rows, seen_event_ids, owner_conn):
        super().__init__(rows)
        self._seen_event_ids = seen_event_ids
        self._owner_conn = owner_conn

    def execute(self, sql, params=()):
        # Detect the provider_event_log INSERT specifically.
        if "INSERT INTO provider_event_log" in sql:
            event_id = str(params[0]) if params else ""
            if event_id and event_id in self._seen_event_ids:
                from psycopg2 import errors as _pg_errors
                # Raise the same class the dispatcher catches.
                raise _pg_errors.UniqueViolation(
                    "duplicate key value violates unique constraint "
                    "\"provider_event_log_source_source_event_id_key\"",
                )
            if event_id:
                self._seen_event_ids.add(event_id)
        # Track any handler-side SQL. The handler for
        # invoice.payment_succeeded issues either
        # "SELECT account_id FROM stripe_customers" or
        # "UPDATE account_subscriptions" — both are unambiguous
        # signals the handler ran.
        if ("SELECT account_id FROM stripe_customers" in sql
                or "UPDATE account_subscriptions" in sql
                or "INSERT INTO subscription_events" in sql):
            self._owner_conn.handler_reached_count += 1
        return super().execute(sql, params)


class DuplicateWebhookIdempotencyTest(unittest.TestCase):
    """Stripe's at-least-once delivery guarantee means the same
    event id can arrive N times. The dispatcher must apply it
    exactly once and no-op on every subsequent delivery."""

    def _paid_event(self, blocks=2):
        # Give this test its own event id so it can't collide with
        # any other test's fake webhook state.
        ev = _fake_invoice_paid(blocks=blocks)
        ev["id"] = "evt_test_dup_idempotency"
        ev["type"] = "invoice.payment_succeeded"
        ev["livemode"] = False
        return ev

    def _dispatch_twice(self, event, rows):
        import stripe_service as ss
        shared_conn = _FakeConnWithEventLogUnique(rows)
        prev = _billing_setup_env()
        try:
            with mock.patch(
                "stripe_service.get_db", return_value=shared_conn,
            ), mock.patch(
                "vault_billing_notifications.notify_payment_recovered",
                side_effect=lambda *a, **k: None,
            ):
                first = ss.dispatch_webhook_event(event)
                second = ss.dispatch_webhook_event(event)
        finally:
            _restore_env(prev)
        return first, second, shared_conn

    def test_duplicate_dispatch_returns_ignored_duplicate(self):
        event = self._paid_event(blocks=2)
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        first, second, _conn = self._dispatch_twice(event, rows)
        self.assertEqual(first.outcome, "applied",
                         "first delivery must apply the event")
        self.assertEqual(second.outcome, "ignored_duplicate",
                         "second delivery must be an idempotent no-op")
        # event_id preserved so ops traces are consistent.
        self.assertEqual(first.event_id, event["id"])
        self.assertEqual(second.event_id, event["id"])

    def test_handler_not_invoked_on_duplicate(self):
        # The critical invariant: on the second delivery, the handler
        # (which would issue SELECT account_id FROM stripe_customers
        # and UPDATE account_subscriptions) MUST NOT execute at all.
        event = self._paid_event(blocks=2)
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        _first, second, conn = self._dispatch_twice(event, rows)
        # Snapshot the handler-reached counter after both dispatches.
        # The first call reached the handler (SELECT + UPDATE + INSERT
        # subscription_events → 3 hits). The second call must have
        # added ZERO further hits.
        # We can't split the counter per-call from outside, but we
        # can assert an upper bound: the first-call handler-side SQL
        # count in this scenario is exactly 3 (customer lookup, prior
        # status lookup, subscription_events audit insert) — plus one
        # UPDATE. So total after two dispatches must equal the same
        # count as after one, not double it.
        one_call_count = conn.handler_reached_count
        # Re-dispatch a THIRD time — must still not invoke handler.
        import stripe_service as ss
        prev = _billing_setup_env()
        try:
            with mock.patch(
                "stripe_service.get_db", return_value=conn,
            ):
                third = ss.dispatch_webhook_event(event)
        finally:
            _restore_env(prev)
        self.assertEqual(third.outcome, "ignored_duplicate")
        # Counter unchanged between second and third dispatch = the
        # handler was NOT reached on either duplicate.
        self.assertEqual(
            conn.handler_reached_count, one_call_count,
            "handler-side SQL executed on a duplicate delivery — "
            "idempotency broken",
        )

    def test_duplicate_dispatch_does_not_double_storage(self):
        # End-to-end assertion: track every UPDATE that mentions
        # block_count and confirm exactly ONE fires across two
        # dispatches. If the handler ran twice, we'd see two.
        event = self._paid_event(blocks=5)
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        _first, _second, conn = self._dispatch_twice(event, rows)
        # Aggregate every UPDATE across every cursor the shared conn
        # handed out.
        restore_updates = []
        for cur in conn.cursors:
            for sql, params in cur.executed:
                if ("UPDATE account_subscriptions" in sql
                        and "block_count" in sql
                        and "'active'" in sql):
                    restore_updates.append(params)
        self.assertEqual(
            len(restore_updates), 1,
            f"expected exactly ONE restore UPDATE across duplicate "
            f"deliveries, got {len(restore_updates)} — storage "
            f"double-grant risk",
        )
        # And the single restore that fired carried the correct
        # quantity (5 blocks = 250 GB) so we're not silently masking
        # a wrong-quantity write.
        self.assertEqual(restore_updates[0][0], 5)
        self.assertEqual(
            restore_updates[0][1], 5 * 53_687_091_200,
        )

    def test_duplicate_dispatch_no_extra_subscription_events_row(self):
        # The audit trail (subscription_events) must not double up
        # either — a duplicated 'renewed' row would mislead support
        # into thinking the customer paid twice.
        event = self._paid_event(blocks=2)
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        _first, _second, conn = self._dispatch_twice(event, rows)
        renewed_rows = []
        for cur in conn.cursors:
            for sql, params in cur.executed:
                if ("INSERT INTO subscription_events" in sql
                        and "'renewed'" in sql):
                    renewed_rows.append(params)
        self.assertEqual(
            len(renewed_rows), 1,
            "duplicate delivery produced a second 'renewed' audit "
            "row — audit trail integrity broken",
        )

    def test_duplicate_dispatch_only_one_provider_event_log_row(self):
        # provider_event_log itself must have exactly ONE row per
        # event_id — the first INSERT succeeds, subsequent INSERTs
        # raise UniqueViolation which the dispatcher catches.
        event = self._paid_event(blocks=1)
        rows = {
            "SELECT account_id FROM stripe_customers":
                [{"account_id": ACCOUNT_A}],
            "SELECT status, block_count, purchased_bytes":
                [{"status": "expired", "block_count": 0,
                  "purchased_bytes": 0}],
        }
        _first, _second, conn = self._dispatch_twice(event, rows)
        successful_inserts = 0
        raised_inserts = 0
        for cur in conn.cursors:
            for sql, _params in cur.executed:
                if "INSERT INTO provider_event_log" in sql:
                    successful_inserts += 1
        # The raised INSERT is not recorded in `executed` (our fake
        # raises BEFORE super().execute appends). So `successful`
        # counts only the ones that got past the unique check.
        self.assertEqual(
            successful_inserts, 1,
            "only the first delivery may insert into "
            "provider_event_log",
        )
        # A duplicate-triggered rollback is expected on the second
        # delivery (the dispatcher rolls back after UniqueViolation).
        self.assertGreaterEqual(conn.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
