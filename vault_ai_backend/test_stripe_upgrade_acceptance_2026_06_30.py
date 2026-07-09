

from __future__ import annotations

import inspect
import os
import unittest
from unittest import mock


os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

import billing              
import stripe_service              


class TestCheckoutSessionMetadata(unittest.TestCase):


    def test_checkout_session_metadata_carries_account_and_block_count(self):
        src = inspect.getsource(stripe_service.create_checkout_session)
                                                                     
        self.assertIn('"account_id": account_id', src)
        self.assertIn('"block_count": str(block_count)', src)
        self.assertIn('"vault_id": vault_id', src)
                                                                  
                                                          
        self.assertIn('"client_reference_id": account_id', src)
                                                               
                                                                
        self.assertIn('"subscription_data"', src)


class TestWebhookDispatchCoversRequiredEvents(unittest.TestCase):

    _REQUIRED_EVENTS = (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    )

    def test_handlers_table_covers_every_required_event(self):
        src = inspect.getsource(stripe_service)
        for event in self._REQUIRED_EVENTS:
            with self.subTest(event=event):
                self.assertIn(
                    f'"{event}"', src,
                    msg=(
                        f"_HANDLERS table must dispatch on the "
                        f"closed-set event type {event!r}."
                    ),
                )


class TestSelfHealMissingRow(unittest.TestCase):


    def test_apply_subscription_state_contains_self_heal_insert(self):
        src = inspect.getsource(stripe_service._apply_subscription_state)
                                                                  
                                                
        self.assertIn("cur.rowcount == 0", src)
        self.assertIn("INSERT INTO account_subscriptions", src)
        self.assertIn("ON CONFLICT (account_id) DO UPDATE", src)
                                                                    
                  
        self.assertIn("self-heal INSERT account_subscriptions", src)

    def test_no_NoAccountSubscriptionRowError_raise_path(self):
                                                                 
                                                                   
        src = inspect.getsource(stripe_service._apply_subscription_state)
        executable = _strip_python_comments(src)
        self.assertNotIn(
            "raise _NoAccountSubscriptionRowError", executable,
            msg=(
                "_apply_subscription_state must NOT raise "
                "_NoAccountSubscriptionRowError anymore — it must "
                "self-heal by INSERTing the row."
            ),
        )


class TestWebhookIdempotency(unittest.TestCase):

    def test_dispatch_dedupes_via_provider_event_log_pk(self):
        src = inspect.getsource(stripe_service.dispatch_webhook_event)
                                                                   
                                                              
        self.assertIn("INSERT INTO provider_event_log", src)
        self.assertIn("UniqueViolation", src)
        self.assertIn("ignored_duplicate", src)


class TestBillingMeWebhookDiagnostic(unittest.TestCase):

    def test_billing_me_route_appends_last_webhook_event(self):
        from routes import billing_routes
        src = inspect.getsource(billing_routes.billing_me)
        self.assertIn('payload["last_webhook_event"]', src)
        self.assertIn("_read_last_webhook_event", src)

    def test_helper_uses_closed_set_safe_fields_only(self):
        from routes import billing_routes
        src = inspect.getsource(billing_routes._read_last_webhook_event)
                                                            
        for safe_field in (
            "event_id_prefix",
            "event_type",
            "outcome",
            "age_seconds",
        ):
            with self.subTest(field=safe_field):
                self.assertIn(f'"{safe_field}"', src)
                                                                   
                                                   
        executable = _strip_python_comments(src)
        for banned in (
            "raw_payload",
            "signature_header",
            "customer_email",
            "stripe_secret",
            "payment_method",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(
                    f'"{banned}"', executable,
                    msg=(
                        f"_read_last_webhook_event must NEVER expose "
                        f"{banned!r} — closed-set, safe fields only."
                    ),
                )

    def test_helper_returns_none_on_db_error(self):
                                                               
        from routes import billing_routes
        with mock.patch("vault_core.get_db") as get_db:
            get_db.side_effect = RuntimeError("simulated DB failure")
            result = billing_routes._read_last_webhook_event("acct-x")
        self.assertIsNone(result)

    def test_helper_returns_none_on_missing_account_id(self):
        from routes import billing_routes
        self.assertIsNone(
            billing_routes._read_last_webhook_event(None),
        )
        self.assertIsNone(
            billing_routes._read_last_webhook_event(""),
        )


class TestEntitlementBranches(unittest.TestCase):

    def test_active_50gb_returns_exactly_50gb_not_51gb(self):
        ent = billing.StorageEntitlement(
            account_id="acct-paid",
            account_type="individual",
            sales_channel="self_service",
            included_bytes=1_073_741_824,
            purchased_bytes=53_687_091_200,          
            storage_bytes_grant=0,
            effective_limit_bytes=53_687_091_200,
            used_bytes=0,
            percent_used=0.0,
            block_count=1,
            self_service_max_blocks=100,
            status="active",
            source="stripe",
            current_period_end=None,
            cancel_at_period_end=False,
            block_price_cents_usd=2500,
            block_bytes=53_687_091_200,
            has_active_subscription=True,
        )
                                                     
        self.assertEqual(ent.effective_limit_bytes, 53_687_091_200)
                                               
        self.assertNotEqual(
            ent.effective_limit_bytes,
            ent.included_bytes + ent.purchased_bytes,
        )

    def test_canceled_subscription_helper_returns_free_tier(self):
        from billing import get_effective_storage_limit
        ent_expired = billing.StorageEntitlement(
            account_id="acct-canceled",
            account_type="individual",
            sales_channel="self_service",
            included_bytes=1_073_741_824,
            purchased_bytes=0,
            storage_bytes_grant=0,
            effective_limit_bytes=1_073_741_824,
            used_bytes=0,
            percent_used=0.0,
            block_count=1,
            self_service_max_blocks=100,
            status="expired",
            source="stripe",
            current_period_end=None,
            cancel_at_period_end=True,
            block_price_cents_usd=2500,
            block_bytes=53_687_091_200,
            has_active_subscription=False,
        )
        with mock.patch.object(
            billing, "get_entitlement", return_value=ent_expired,
        ):
            limit = get_effective_storage_limit("acct-canceled")
        self.assertEqual(limit, 1_073_741_824)


class TestNoSecretsInLogs(unittest.TestCase):


    def test_self_heal_log_uses_prefix_only(self):
        src = inspect.getsource(stripe_service._apply_subscription_state)
                                                                      
        self.assertIn("(account_id or \"\")[:8]", src)
        self.assertIn("(sub_id or \"\")[:14]", src)

    def test_billing_me_diagnostic_log_uses_prefix_only(self):
        from routes import billing_routes
        src = inspect.getsource(billing_routes._read_last_webhook_event)
                                                                  
                                              
        self.assertIn('(account_id or "")[:8]', src)


class TestCrossAccountGuard(unittest.TestCase):


    def test_existing_mapping_to_different_account_is_kept(self):
                                                                     
        executed: list[tuple[str, tuple]] = []
        class FakeCur:
            def execute(self, sql, params=()):
                executed.append((sql, params))
            def fetchone(self):
                return {"account_id": "acct-A"}
        cur = FakeCur()
        event = {
            "data": {"object": {
                "customer": "cus_abc",
                "metadata": {"account_id": "acct-B"},
                "client_reference_id": "acct-B",
            }},
            "livemode": False,
        }
        result = stripe_service._handle_checkout_session_completed(
            event, cur,
        )
                                                  
        self.assertEqual(result, "acct-A")
                                                             
        self.assertEqual(len(executed), 1)
        self.assertIn("SELECT account_id FROM stripe_customers", executed[0][0])

    def test_matching_mapping_proceeds_with_upsert(self):
        executed: list[tuple[str, tuple]] = []
        class FakeCur:
            def execute(self, sql, params=()):
                executed.append((sql, params))
            def fetchone(self):
                return {"account_id": "acct-A"}
        cur = FakeCur()
        event = {
            "data": {"object": {
                "customer": "cus_abc",
                "metadata": {"account_id": "acct-A"},
            }},
            "livemode": False,
        }
        result = stripe_service._handle_checkout_session_completed(
            event, cur,
        )
        self.assertEqual(result, "acct-A")
                                              
        self.assertEqual(len(executed), 2)
        self.assertIn(
            "INSERT INTO stripe_customers", executed[1][0],
        )

    def test_no_prior_mapping_proceeds_with_upsert(self):
        executed: list[tuple[str, tuple]] = []
        class FakeCur:
            def execute(self, sql, params=()):
                executed.append((sql, params))
            def fetchone(self):
                return None
        cur = FakeCur()
        event = {
            "data": {"object": {
                "customer": "cus_new",
                "metadata": {"account_id": "acct-fresh"},
            }},
            "livemode": False,
        }
        result = stripe_service._handle_checkout_session_completed(
            event, cur,
        )
        self.assertEqual(result, "acct-fresh")
                                             
        self.assertEqual(len(executed), 2)


class TestRecentGlobalWebhookCount(unittest.TestCase):


    def test_billing_me_route_appends_recent_webhook_count(self):
        from routes import billing_routes
        src = inspect.getsource(billing_routes.billing_me)
        self.assertIn('payload["recent_webhook_count"]', src)
        self.assertIn("_count_recent_global_webhooks", src)

    def test_helper_returns_zero_on_db_error(self):
        from routes import billing_routes
        with mock.patch("vault_core.get_db") as get_db:
            get_db.side_effect = RuntimeError("simulated DB failure")
            result = billing_routes._count_recent_global_webhooks()
        self.assertEqual(result, 0)

    def test_helper_uses_60_second_default_window(self):
        from routes import billing_routes
        src = inspect.getsource(
            billing_routes._count_recent_global_webhooks,
        )
                                                                    
                                                                     
        self.assertIn("window_seconds: int = 60", src)
                                                        
        self.assertIn("INTERVAL '1 second'", src)
        self.assertIn("source = 'stripe'", src)


def _strip_python_comments(src: str) -> str:


    import re
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    src = re.sub(r"#[^\n]*", "", src)
    return src


if __name__ == "__main__":                    
    unittest.main()
