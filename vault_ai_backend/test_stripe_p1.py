

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import patch

import stripe as real_stripe

from stripe_service import (
    StripeCeilingExceededError,
    StripeUnconfiguredError,
    _extract_block_count,
    _extract_subscription_item_id,
    _iso_or_none,
    _STRIPE_STATUS_MAP,
    create_checkout_session,
    create_portal_session,
    dispatch_webhook_event,
)


class FakeCursor:
    def __init__(self, store: "FakeDBStore"):
        self.store = store
        self.last_sql: str = ""
        self.last_params: tuple = ()
                                                                           
                                                                       
        self._select_results = list(store.select_results)
                                                                   
                                                                       
        self.rowcount: int = 1

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.last_sql = sql
        self.last_params = tuple(params) if params else ()
        self.store.executed.append((sql, self.last_params))
                                                                  
                                                                     
        self.rowcount = 1
        if (
            self.store.next_update_rowcount is not None
            and "UPDATE account_subscriptions" in sql
            and "SET status" in sql
        ):
            self.rowcount = int(self.store.next_update_rowcount)
            self.store.next_update_rowcount = None
                                                                        
                                                             
        if self.store.next_unique_violation and \
                "INSERT INTO provider_event_log" in sql:
            self.store.next_unique_violation = False
            from psycopg2 import errors as pg_errors

            class _Mock(pg_errors.UniqueViolation):
                pass

            raise _Mock("simulated duplicate")

    def fetchone(self):
        if not self._select_results:
            return None
        return self._select_results.pop(0)

    def fetchall(self):
        out = list(self._select_results)
        self._select_results.clear()
        return out

    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


@dataclass
class FakeDBStore:
    select_results: list = None                                   
    executed: list = None                                         
    next_unique_violation: bool = False
    committed: int = 0
    rolled_back: int = 0
                                                                     
                                                                   
    next_update_rowcount: Optional[int] = None

    def __post_init__(self):
        if self.select_results is None:
            self.select_results = []
        if self.executed is None:
            self.executed = []


class FakeConn:
    def __init__(self, store: FakeDBStore):
        self.store = store

    def cursor(self, *args, **kwargs):
                                                                    
        return FakeCursor(self.store)

    def commit(self):
        self.store.committed += 1

    def rollback(self):
        self.store.rolled_back += 1

    def close(self): pass


def _install_fake_db(store: FakeDBStore):


    return patch("stripe_service.get_db",
                 return_value=FakeConn(store))


class ExtractionAndMappingTests(unittest.TestCase):
    def test_iso_or_none_handles_zero(self):
        self.assertIsNone(_iso_or_none(0))
        self.assertIsNone(_iso_or_none(None))

    def test_iso_or_none_handles_epoch_seconds(self):
                                           
        dt = _iso_or_none(1767225600)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.day, 1)

    def test_extract_block_count_happy_path(self):
        sub = {"items": {"data": [{"quantity": 3}]}}
        self.assertEqual(_extract_block_count(sub), 3)

    def test_extract_block_count_missing_returns_zero(self):
        self.assertEqual(_extract_block_count({}), 0)
        self.assertEqual(_extract_block_count({"items": None}), 0)
        self.assertEqual(_extract_block_count({"items": {"data": []}}), 0)
        self.assertEqual(_extract_block_count({"items": {"data": [{}]}}), 0)
        self.assertEqual(
            _extract_block_count({"items": {"data": [{"quantity": "x"}]}}),
            0,
        )

    def test_extract_block_count_works_on_stripe_object(self):
                                                                      
                                                             
        sub = real_stripe.Subscription.construct_from(
            {
                "id": "sub_real_stripe_obj",
                "items": {"data": [{"id": "si_x", "quantity": 7}]},
            },
            "sk_test",
        )
                                                                      
                                                                   
        self.assertFalse(isinstance(sub, dict))
        self.assertFalse(hasattr(sub, "get"))
                                                                       
        self.assertEqual(_extract_block_count(sub), 7)

    def test_extract_subscription_item_id_happy_path_dict(self):
                                                                     
                                                                      
        sub = {"items": {"data": [{"id": "si_dict", "quantity": 2}]}}
        self.assertEqual(_extract_subscription_item_id(sub), "si_dict")

    def test_extract_subscription_item_id_happy_path_stripe_object(self):
                                                                    
                                                                       
        sub = real_stripe.Subscription.construct_from(
            {
                "id": "sub_backfill_ok",
                "items": {"data": [
                    {"id": "si_UcoGCeOFXWDY7B", "quantity": 3},
                ]},
            },
            "sk_test",
        )
        self.assertEqual(
            _extract_subscription_item_id(sub),
            "si_UcoGCeOFXWDY7B",
        )

    def test_extract_subscription_item_id_missing_returns_none(self):
                                                                       
                                                                    
        self.assertIsNone(_extract_subscription_item_id({}))
        self.assertIsNone(_extract_subscription_item_id({"items": None}))
        self.assertIsNone(
            _extract_subscription_item_id({"items": {"data": []}}),
        )
        self.assertIsNone(
            _extract_subscription_item_id({"items": {"data": [{}]}}),
        )
                                                                   
                             
        sub_empty = real_stripe.Subscription.construct_from(
            {"id": "sub_empty", "items": {"data": []}},
            "sk_test",
        )
        self.assertIsNone(_extract_subscription_item_id(sub_empty))

    def test_stripe_status_mapping(self):
                                                               
        self.assertEqual(_STRIPE_STATUS_MAP["active"], "active")
        self.assertEqual(_STRIPE_STATUS_MAP["trialing"], "active")
        self.assertEqual(_STRIPE_STATUS_MAP["past_due"], "in_grace")
        self.assertEqual(_STRIPE_STATUS_MAP["canceled"], "expired")
        self.assertEqual(_STRIPE_STATUS_MAP["paused"], "paused")


class CheckoutSessionTests(unittest.TestCase):
    def setUp(self):
                                                                  
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_dummy",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_test_block",
            "STRIPE_WEBHOOK_SECRET":         "whsec_test_dummy",
        })
        self.env.start()

                                                      
        self.store = FakeDBStore(select_results=[None])
        self.db_patch = _install_fake_db(self.store)
        self.db_patch.start()

                                        
        class _Sess:
            def __init__(self, url, id):
                self.url, self.id = url, id

        self.sess_patch = patch(
            "stripe_service.stripe.checkout.Session.create",
            return_value=_Sess("https://stripe.example/checkout/abc",
                               "cs_test_abc"),
        )
        self.sess_mock = self.sess_patch.start()

    def tearDown(self):
        self.env.stop()
        self.db_patch.stop()
        self.sess_patch.stop()

    def test_successful_checkout_returns_url_and_session_id(self):
        result = create_checkout_session(
            account_id="acct-1",
            vault_id="vault-1",
            block_count=2,
        )
        self.assertEqual(result.checkout_url,
                         "https://stripe.example/checkout/abc")
        self.assertEqual(result.session_id, "cs_test_abc")
                                                        
        kwargs = self.sess_mock.call_args.kwargs
        self.assertEqual(kwargs["mode"], "subscription")
        self.assertEqual(kwargs["line_items"], [
            {"price": "price_test_block", "quantity": 2},
        ])
                                                                  
                       
        self.assertEqual(kwargs["metadata"]["account_id"], "acct-1")
        self.assertEqual(kwargs["metadata"]["vault_id"], "vault-1")
        self.assertEqual(kwargs["metadata"]["block_count"], "2")
        self.assertEqual(kwargs["client_reference_id"], "acct-1")

    def test_customer_creation_not_sent_in_subscription_mode(self):
                                                   
                                                                       
        create_checkout_session(
            account_id="acct-1", vault_id="vault-1",
            block_count=1,
        )
        kwargs = self.sess_mock.call_args.kwargs
        self.assertNotIn(
            "customer_creation", kwargs,
            "Stripe rejects customer_creation in subscription mode.",
        )
                                                                     
                                                                     
        self.assertNotIn("customer_email", kwargs)

    def test_stripe_error_is_wrapped_with_typed_exception(self):
                                                                     
                                                                      
        import stripe as _stripe
        self.sess_patch.stop()
                                                                   
                                                
        err = _stripe.InvalidRequestError(
            message="You cannot pass customer_creation in subscription mode.",
            param="customer_creation",
            code="parameter_unknown",
        )
        bad_patch = patch(
            "stripe_service.stripe.checkout.Session.create",
            side_effect=err,
        )
        bad_patch.start()
        try:
            from stripe_service import StripeCheckoutRejectedError
            with self.assertRaises(StripeCheckoutRejectedError) as cm:
                create_checkout_session(
                    account_id="acct-1", vault_id="vault-1",
                    block_count=1,
                )
            self.assertEqual(cm.exception.stripe_code, "parameter_unknown")
            self.assertEqual(cm.exception.param, "customer_creation")
            self.assertIn("customer_creation", cm.exception.stripe_message)
            self.assertEqual(cm.exception.stripe_type, "InvalidRequestError")
        finally:
            bad_patch.stop()
                                                                          
            self.sess_patch.start()

    def test_ceiling_refusal_does_not_call_stripe(self):
        with self.assertRaises(StripeCeilingExceededError) as cm:
            create_checkout_session(
                account_id="acct-1", vault_id="vault-1",
                block_count=101,                  
            )
        self.assertEqual(cm.exception.requested_blocks, 101)
        self.assertEqual(cm.exception.max_blocks, 100)
        self.sess_mock.assert_not_called()


class PriceCurrencyProbeTests(unittest.TestCase):


    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_dummy",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_test_block",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _fake_price(self, *, currency: str, unit_amount: int,
                    interval: str = "month", active: bool = True):
        class _P:
            pass
        p = _P()
        p.currency = currency
        p.unit_amount = unit_amount
        p.recurring = {"interval": interval}
        p.active = active
        return p

    def test_usd_2500_month_matches_expected(self):
        from stripe_service import probe_stripe_price_currency
        with patch("stripe_service.stripe.Price.retrieve",
                   return_value=self._fake_price(
                       currency="usd", unit_amount=2500)):
            out = probe_stripe_price_currency()
        self.assertTrue(out["ok"])
        self.assertEqual(out["currency"], "usd")
        self.assertEqual(out["unit_amount_cents"], 2500)
        self.assertEqual(out["interval"], "month")
        self.assertTrue(out["matches_expected_usd_2500"])

    def test_gbp_price_fails_expectation(self):
                                                               
                                                                  
        from stripe_service import probe_stripe_price_currency
        with patch("stripe_service.stripe.Price.retrieve",
                   return_value=self._fake_price(
                       currency="gbp", unit_amount=2500)):
            out = probe_stripe_price_currency()
        self.assertTrue(out["ok"])
        self.assertEqual(out["currency"], "gbp")
        self.assertFalse(out["matches_expected_usd_2500"])

    def test_wrong_amount_fails_expectation(self):
        from stripe_service import probe_stripe_price_currency
        with patch("stripe_service.stripe.Price.retrieve",
                   return_value=self._fake_price(
                       currency="usd", unit_amount=2000)):
            out = probe_stripe_price_currency()
        self.assertFalse(out["matches_expected_usd_2500"])

    def test_wrong_interval_fails_expectation(self):
        from stripe_service import probe_stripe_price_currency
        with patch("stripe_service.stripe.Price.retrieve",
                   return_value=self._fake_price(
                       currency="usd", unit_amount=2500,
                       interval="year")):
            out = probe_stripe_price_currency()
        self.assertFalse(out["matches_expected_usd_2500"])

    def test_missing_api_key_returns_unconfigured(self):
        from stripe_service import probe_stripe_price_currency
        with patch.dict("os.environ",
                        {"STRIPE_API_KEY": ""}, clear=False):
            out = probe_stripe_price_currency()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "stripe_unconfigured_api_key")


class CheckoutSessionUnconfiguredTests(unittest.TestCase):
    def test_missing_api_key_raises_typed_error(self):
        with patch.dict("os.environ", {"STRIPE_API_KEY": ""}, clear=False):
            with self.assertRaises(StripeUnconfiguredError):
                create_checkout_session(
                    account_id="acct-1", vault_id="vault-1",
                    block_count=1,
                )

    def test_missing_price_id_raises_typed_error(self):
        with patch.dict("os.environ", {
            "STRIPE_API_KEY": "sk_test_dummy",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "",
        }, clear=False):
            store = FakeDBStore(select_results=[None])
            with _install_fake_db(store):
                with self.assertRaises(StripeUnconfiguredError):
                    create_checkout_session(
                        account_id="acct-1", vault_id="vault-1",
                        block_count=1,
                    )


class PortalSessionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY": "sk_test_dummy",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_returns_portal_url_when_customer_exists(self):
                                
        store = FakeDBStore(select_results=[("cus_test_xyz",)])

        class _Sess:
            url = "https://stripe.example/portal/xyz"

        with _install_fake_db(store), \
             patch("stripe_service.stripe.billing_portal.Session.create",
                   return_value=_Sess()) as portal_mock:
            result = create_portal_session(account_id="acct-1")
        self.assertEqual(result.portal_url, "https://stripe.example/portal/xyz")
        self.assertEqual(portal_mock.call_args.kwargs["customer"], "cus_test_xyz")

    def test_raises_lookup_error_when_no_customer(self):
                                     
        store = FakeDBStore(select_results=[None])
        with _install_fake_db(store):
            with self.assertRaises(LookupError):
                create_portal_session(account_id="acct-no-customer")


def _make_event(*, event_id: str, event_type: str, obj: dict, livemode: bool = False) -> dict:
    return {
        "id":        event_id,
        "type":      event_type,
        "livemode":  livemode,
        "data":      {"object": obj},
    }


class WebhookCreatedTests(unittest.TestCase):


    def test_created_event_applies_to_account(self):
                                                                  
                                                  
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},                   
        ])
        event = _make_event(
            event_id="evt_created_1",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_test_1",
                "status": "active",
                "current_period_start": 1767225600,              
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_test_xyz",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [
                                                                     
                                                                      
                    {"id": "si_test_1", "quantity": 3}
                ]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.account_id, "acct-1")

                                                                
        update_sql = next(
            sql for sql, _ in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
        self.assertIn("block_count", update_sql)
        self.assertIn("purchased_bytes", update_sql)
        update_params = next(
            params for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                                  
                                                                         
        self.assertEqual(update_params[0], "active")
        self.assertEqual(update_params[2], "si_test_1")                    
        self.assertEqual(update_params[3], 3)
        self.assertEqual(update_params[4], 3 * 53_687_091_200)
        self.assertEqual(update_params[7], False)
        self.assertEqual(update_params[8], "acct-1")


class WebhookUpdatedTests(unittest.TestCase):
    def test_updated_to_higher_quantity(self):
                                                   
        store = FakeDBStore(select_results=[
            {"block_count": 2, "purchased_bytes": 2 * 53_687_091_200},
        ])
        event = _make_event(
            event_id="evt_updated_1",
            event_type="customer.subscription.updated",
            obj={
                "id": "sub_test_1",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_test_xyz",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 5}]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")
        update_params = next(
            params for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                                   
        self.assertEqual(update_params[3], 5)
        self.assertEqual(update_params[4], 5 * 53_687_091_200)

    def test_cancel_at_period_end_flips_to_true(self):
        store = FakeDBStore(select_results=[
            {"block_count": 1, "purchased_bytes": 53_687_091_200},
        ])
        event = _make_event(
            event_id="evt_updated_2",
            event_type="customer.subscription.updated",
            obj={
                "id": "sub_test_1",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": True,
                "customer": "cus_test_xyz",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 1}]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")
        update_params = next(
            params for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                                   
                             
        self.assertEqual(update_params[7], True)


class WebhookDeletedTests(unittest.TestCase):
    def test_deleted_drops_entitlement_and_audits(self):
        store = FakeDBStore(select_results=[
            {"block_count": 2, "purchased_bytes": 2 * 53_687_091_200},
        ])
        event = _make_event(
            event_id="evt_deleted_1",
            event_type="customer.subscription.deleted",
            obj={
                "id": "sub_test_1",
                "status": "canceled",
                "customer": "cus_test_xyz",
                "metadata": {"account_id": "acct-1"},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")

        update_sql = next(
            sql for sql, _ in store.executed
            if "UPDATE account_subscriptions" in sql
               and "block_count            = 0" in sql
        )
        self.assertIn("over_quota_grace_ends_at", update_sql)
                                                    
        audit_params = next(
            params for sql, params in store.executed
            if "INSERT INTO subscription_events" in sql
               and 'canceled_by_provider' in sql
        )
                                                                         
        self.assertEqual(audit_params[0], "acct-1")
        self.assertEqual(audit_params[2], 2)


class WebhookIdempotencyTests(unittest.TestCase):
    def test_duplicate_event_short_circuits_to_ignored_duplicate(self):
        store = FakeDBStore(select_results=[])
        store.next_unique_violation = True
        event = _make_event(
            event_id="evt_dup_1",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_dup",
                "status": "active",
                "customer": "cus_dup",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 1}]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "ignored_duplicate")
                                                                  
                   
        for sql, _ in store.executed:
            self.assertFalse("UPDATE account_subscriptions" in sql,
                             msg="duplicate must not mutate entitlement")

    def test_missing_event_id_returns_error_without_db_write(self):
                                                                     
        store = FakeDBStore(select_results=[])
        event = {"id": "", "type": "customer.subscription.created",
                 "data": {"object": {}}}
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "error")
        self.assertEqual(result.error_text, "missing_event_id_or_type")
                           
        for sql, _ in store.executed:
            self.assertFalse("INSERT INTO provider_event_log" in sql)


class WebhookUnhandledTests(unittest.TestCase):
    def test_unknown_event_type_is_logged_and_no_oped(self):
        store = FakeDBStore(select_results=[])
        event = _make_event(
            event_id="evt_unknown_1",
            event_type="customer.discount.created",
            obj={},
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "ignored_unhandled")


class EntitlementRecalculationPin(unittest.TestCase):
    def test_create_then_update_lands_at_5_blocks_purchased(self):
                             
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},
        ])
        event_a = _make_event(
            event_id="evt_a",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_acct_1",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_acct_1",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 2}]},
            },
        )
        with _install_fake_db(store):
            r1 = dispatch_webhook_event(event_a)
        self.assertEqual(r1.outcome, "applied")
        a_params = next(
            params for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                                      
        self.assertEqual(a_params[3], 2)

                                                                      
        store_b = FakeDBStore(select_results=[
            {"block_count": 2, "purchased_bytes": 2 * 53_687_091_200},
        ])
        event_b = _make_event(
            event_id="evt_b",
            event_type="customer.subscription.updated",
            obj={
                "id": "sub_acct_1",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_acct_1",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 5}]},
            },
        )
        with _install_fake_db(store_b):
            r2 = dispatch_webhook_event(event_b)
        self.assertEqual(r2.outcome, "applied")
        b_params = next(
            params for sql, params in store_b.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                                        
                                                               
        self.assertEqual(b_params[3], 5)
                                                                  
                                                                    
        self.assertEqual(b_params[4], 5 * 53_687_091_200)


class SignatureVerificationTests(unittest.TestCase):
    def test_missing_secret_raises_unconfigured(self):
        from stripe_service import verify_webhook_signature
        with patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": ""}, clear=False):
            with self.assertRaises(StripeUnconfiguredError):
                verify_webhook_signature(
                    payload=b'{}', signature_header="t=1,v1=bad",
                )

    def test_bad_signature_raises_some_exception(self):
        from stripe_service import verify_webhook_signature
        with patch.dict("os.environ",
                        {"STRIPE_WEBHOOK_SECRET": "whsec_test"},
                        clear=False):
                                                                 
                                                         
            with self.assertRaises(Exception):
                verify_webhook_signature(
                    payload=b'{"id":"evt_x","type":"x"}',
                    signature_header="t=1,v1=clearly_not_valid",
                )


class RedirectUrlValidationTests(unittest.TestCase):


    def setUp(self):
                                                                      
                                                                   
        self._env = patch.dict("os.environ", {}, clear=False)
        self._env.start()
                                                              
        import os
        os.environ.pop("VAULTAI_ALLOWED_REDIRECT_ORIGINS", None)

    def tearDown(self):
        self._env.stop()

    def test_accepts_localhost_any_port_http_or_https(self):
        from stripe_service import is_safe_redirect_url
        for url in (
            "http://localhost:54321/storage?checkout=success",
            "http://localhost:8000/storage",
            "http://127.0.0.1:5173/storage?checkout=cancel",
            "https://localhost:443/storage",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_safe_redirect_url(url))

    def test_rejects_non_http_schemes(self):
        from stripe_service import is_safe_redirect_url
        for url in (
            "javascript://evil.example.com/storage",
            "file:///etc/passwd",
            "ftp://localhost:21/storage",
            "data:text/html,<script>",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_safe_redirect_url(url))

    def test_rejects_wrong_path(self):
                                                                 
                                             
        from stripe_service import is_safe_redirect_url
        for url in (
            "http://localhost:54321/",
            "http://localhost:54321/login",
            "http://localhost:54321/storage/extra",
            "http://localhost:54321/storage/../admin",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_safe_redirect_url(url))

    def test_rejects_credentials_in_url(self):
        from stripe_service import is_safe_redirect_url
        self.assertFalse(
            is_safe_redirect_url(
                "http://evil:pass@localhost:5173/storage"
            )
        )

    def test_rejects_non_localhost_when_no_allowlist(self):
                                                                     
                                                               
        from stripe_service import is_safe_redirect_url
        for url in (
            "https://evil.example.com/storage",
            "https://attacker.tld/storage?checkout=success",
            "http://10.0.0.1/storage",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_safe_redirect_url(url))

    def test_accepts_origin_when_on_allowlist(self):
                                                                  
        import os
        os.environ["VAULTAI_ALLOWED_REDIRECT_ORIGINS"] = (
            "https://app.vaultai.com,https://staging.vaultai.com"
        )
        try:
            from stripe_service import is_safe_redirect_url
            self.assertTrue(
                is_safe_redirect_url("https://app.vaultai.com/storage"),
            )
            self.assertTrue(
                is_safe_redirect_url(
                    "https://staging.vaultai.com/storage?checkout=success",
                ),
            )
                                               
            self.assertFalse(
                is_safe_redirect_url("https://other.vaultai.com/storage"),
            )
        finally:
            os.environ.pop("VAULTAI_ALLOWED_REDIRECT_ORIGINS", None)

    def test_handles_none_and_empty(self):
        from stripe_service import is_safe_redirect_url
        self.assertFalse(is_safe_redirect_url(None))
        self.assertFalse(is_safe_redirect_url(""))
        self.assertFalse(is_safe_redirect_url("   "))


class ResolveRedirectUrlTests(unittest.TestCase):


    def test_safe_provided_wins(self):
        from stripe_service import resolve_redirect_url
        out = resolve_redirect_url(
            provided="http://localhost:55001/storage?checkout=success",
            fallback="https://app.vaultai.example/storage?checkout=success",
            purpose="checkout_success",
        )
        self.assertEqual(out,
                         "http://localhost:55001/storage?checkout=success")

    def test_unsafe_provided_falls_back(self):
        from stripe_service import resolve_redirect_url
        out = resolve_redirect_url(
            provided="https://evil.example.com/storage?checkout=success",
            fallback="https://app.vaultai.example/storage?checkout=success",
            purpose="checkout_success",
        )
                                                                     
        self.assertEqual(
            out, "https://app.vaultai.example/storage?checkout=success",
        )

    def test_none_provided_uses_fallback(self):
        from stripe_service import resolve_redirect_url
        out = resolve_redirect_url(
            provided=None,
            fallback="http://localhost:8000/storage?checkout=success",
            purpose="checkout_success",
        )
        self.assertEqual(out, "http://localhost:8000/storage?checkout=success")


class CheckoutSessionUrlForwardingTests(unittest.TestCase):


    def setUp(self):
                                                                  
                                                               
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_dummy",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_test_block",
            "STRIPE_WEBHOOK_SECRET":         "whsec_test_dummy",
            "STRIPE_CHECKOUT_SUCCESS_URL":
                "http://localhost:8000/storage?checkout=success",
            "STRIPE_CHECKOUT_CANCEL_URL":
                "http://localhost:8000/storage?checkout=cancel",
        })
        self.env.start()
        self.store = FakeDBStore(select_results=[None])
        self.db_patch = _install_fake_db(self.store)
        self.db_patch.start()

        class _Sess:
            def __init__(self, url, id):
                self.url, self.id = url, id

        self.sess_patch = patch(
            "stripe_service.stripe.checkout.Session.create",
            return_value=_Sess("https://stripe.example/checkout/x",
                               "cs_x"),
        )
        self.sess_mock = self.sess_patch.start()

    def tearDown(self):
        self.env.stop()
        self.db_patch.stop()
        self.sess_patch.stop()

    def test_safe_forwarded_urls_reach_stripe(self):
                                                                     
                                                                     
        create_checkout_session(
            account_id="acct-1", vault_id="vault-1",
            block_count=1,
            success_url="http://localhost:54321/storage?checkout=success",
            cancel_url="http://localhost:54321/storage?checkout=cancel",
        )
        kwargs = self.sess_mock.call_args.kwargs
        self.assertEqual(
            kwargs["success_url"],
            "http://localhost:54321/storage?checkout=success",
        )
        self.assertEqual(
            kwargs["cancel_url"],
            "http://localhost:54321/storage?checkout=cancel",
        )

    def test_malicious_forwarded_urls_replaced_by_fallback(self):
                                                                    
                                                                   
        create_checkout_session(
            account_id="acct-1", vault_id="vault-1",
            block_count=1,
            success_url="https://evil.example.com/steal?checkout=success",
            cancel_url=None,
        )
        kwargs = self.sess_mock.call_args.kwargs
                                               
        self.assertNotIn("evil.example.com", kwargs["success_url"])
                                                              
        self.assertEqual(
            kwargs["success_url"],
            "http://localhost:8000/storage?checkout=success",
        )


class PortalSessionUrlForwardingTests(unittest.TestCase):


    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_dummy",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_test_block",
            "STRIPE_WEBHOOK_SECRET":         "whsec_test_dummy",
        })
        self.env.start()
                                                                     
                                                         
        self.store = FakeDBStore(
            select_results=[("cus_test_x",)],
        )
        self.db_patch = _install_fake_db(self.store)
        self.db_patch.start()

        class _Sess:
            def __init__(self, url):
                self.url = url

        self.portal_patch = patch(
            "stripe_service.stripe.billing_portal.Session.create",
            return_value=_Sess("https://stripe.example/portal/x"),
        )
        self.portal_mock = self.portal_patch.start()

    def tearDown(self):
        self.env.stop()
        self.db_patch.stop()
        self.portal_patch.stop()

    def test_safe_forwarded_return_url_reaches_stripe(self):
        create_portal_session(
            account_id="acct-1",
            return_url="http://localhost:38000/storage",
        )
        kwargs = self.portal_mock.call_args.kwargs
        self.assertEqual(kwargs["return_url"],
                         "http://localhost:38000/storage")

    def test_malicious_forwarded_return_url_replaced_by_fallback(self):
        create_portal_session(
            account_id="acct-1",
            return_url="https://evil.example.com/storage",
        )
        kwargs = self.portal_mock.call_args.kwargs
        self.assertNotIn("evil.example.com", kwargs["return_url"])


class SubscriptionCreatedNoRowGuardTests(unittest.TestCase):


    def setUp(self):
                                                                  
                                                                      
        self.store = FakeDBStore(
            select_results=[None],
            next_update_rowcount=0,
        )

    def test_zero_rowcount_update_self_heals_to_applied(self):
        event = _make_event(
            event_id="evt_no_row",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_test_zr",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_test_zr",
                "metadata": {"account_id": "acct-missing"},
                "items": {"data": [{"quantity": 1}]},
            },
        )
        with _install_fake_db(self.store):
            result = dispatch_webhook_event(event)
                                                                     
                                                                      
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.event_id, "evt_no_row")
        self.assertEqual(result.account_id, "acct-missing")
                                                                       
                                                                       
        insert_sql = [
            sql for sql, _params in self.store.executed
            if "INSERT INTO account_subscriptions" in sql
               and "ON CONFLICT (account_id) DO UPDATE" in sql
        ]
        self.assertTrue(
            insert_sql,
            "Self-heal path must INSERT into account_subscriptions "
            "with ON CONFLICT (account_id) DO UPDATE so the webhook "
            "lands the entitlement even on a race.",
        )

    def test_nonzero_rowcount_still_returns_applied(self):
                                                                   
                                                                    
        store = FakeDBStore(
            select_results=[{"block_count": 0, "purchased_bytes": 0}],
        )
        event = _make_event(
            event_id="evt_happy_path",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_test_happy",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_test_h",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 1}]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.account_id, "acct-1")


from contextlib import contextmanager
import io
import sys


@contextmanager
def _capture_stdout():
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = saved


class WebhookDebugLogTests(unittest.TestCase):
    def _happy_event(self, event_id: str) -> dict:
        return _make_event(
            event_id=event_id,
            event_type="customer.subscription.created",
            obj={
                "id": "sub_test_log",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_test_log",
                "metadata": {"account_id": "acct-1"},
                "items": {"data": [{"quantity": 1}]},
            },
        )

    def test_dispatch_emits_webhook_dispatch_log(self):
                                                         
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},
        ])
        with _install_fake_db(store), _capture_stdout() as out:
            dispatch_webhook_event(self._happy_event("evt_log_1"))
        captured = out.getvalue()
        self.assertIn("[STRIPE] webhook dispatch", captured)
        self.assertIn("evt_log_1", captured)
        self.assertIn("customer.subscription.created", captured)

    def test_subscription_handler_emits_apply_attempt_and_applied(self):
                                                 
                                                                      
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},
        ])
        with _install_fake_db(store), _capture_stdout() as out:
            dispatch_webhook_event(self._happy_event("evt_log_apply"))
        captured = out.getvalue()

        self.assertIn("[STRIPE] subscription apply attempt", captured)
                                                             
                       
        self.assertIn("resolved_account_id='acct-1'", captured)
        self.assertIn("block_count=1", captured)

        self.assertIn("[STRIPE] subscription applied", captured)
                                                                  
                                                     
        self.assertIn("from_blocks=0", captured)
        self.assertIn("to_blocks=1", captured)

    def test_no_row_branch_self_heals_and_emits_applied(self):
                                                                    
                                                               
        store = FakeDBStore(
            select_results=[None],
            next_update_rowcount=0,
        )
        with _install_fake_db(store), _capture_stdout() as out:
            dispatch_webhook_event(self._happy_event("evt_log_norow"))
        captured = out.getvalue()
        self.assertIn("[STRIPE] subscription apply attempt", captured)
        self.assertIn(
            "[STRIPE] subscription applied", captured,
            msg=(
                "Self-heal branch must emit 'applied' so an operator "
                "can confirm the row was INSERTed and the entitlement "
                "actually landed."
            ),
        )


class StripeEventToPlainDictConversionTests(unittest.TestCase):


    def test_returns_plain_nested_dict_for_signed_payload(self):
                                                                      
                                                                 
        import json, hmac, time
        from hashlib import sha256
        from stripe_service import _stripe_event_to_plain_dict

        body_dict = {
            "id": "evt_unit_convert",
            "object": "event",
            "type": "customer.subscription.created",
            "livemode": False,
            "created": 1767225600,
            "data": {"object": {
                "id": "sub_unit", "object": "subscription",
                "customer": "cus_unit",
                "metadata": {"account_id": "acct-unit", "block_count": "1"},
                "status": "active",
                "items": {"data": [{"quantity": 1}]},
            }},
        }
        body = json.dumps(body_dict).encode("utf-8")
        secret = "whsec_test_unit"
        ts = int(time.time())
        sig = hmac.new(secret.encode(),
                       f"{ts}.{body.decode()}".encode(),
                       sha256).hexdigest()
        header = f"t={ts},v1={sig}"

        sdk_event = real_stripe.Webhook.construct_event(body, header, secret)
                                                                         
                                                                     
        self.assertNotIsInstance(sdk_event, dict)

        plain = _stripe_event_to_plain_dict(sdk_event, raw_payload=body)
        self.assertIsInstance(plain, dict)
        self.assertEqual(plain.get("id"), "evt_unit_convert")
        self.assertEqual(plain.get("type"), "customer.subscription.created")
                                                                       
                                                                  
        obj = plain["data"]["object"]
        self.assertIsInstance(obj, dict)
        self.assertIsInstance(obj["metadata"], dict)
        self.assertIsInstance(obj["items"], dict)
        self.assertIsInstance(obj["items"]["data"][0], dict)
        self.assertEqual(obj["metadata"]["account_id"], "acct-unit")
        self.assertEqual(obj["items"]["data"][0]["quantity"], 1)

    def test_does_not_depend_on_sdk_event_internals(self):
                                                                      
                                                                      
        from stripe_service import _stripe_event_to_plain_dict

        class StubFutureEvent:
            pass                                                    
                                                                 

        body = b'{"id":"evt_fallback","type":"x","data":{"object":{"k":1}}}'
        out = _stripe_event_to_plain_dict(StubFutureEvent(), raw_payload=body)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["id"], "evt_fallback")
        self.assertEqual(out["data"]["object"]["k"], 1)


class StripeEventDictCoercionRegressionPin(unittest.TestCase):


    def test_dict_of_real_stripe_event_raises_keyerror_zero(self):
        import json, hmac, time
        from hashlib import sha256

        body = json.dumps({
            "id": "evt_pin", "object": "event", "type": "x",
            "livemode": False, "created": 1767225600,
            "data": {"object": {}},
        }).encode("utf-8")
        secret = "whsec_pin"
        ts = int(time.time())
        sig = hmac.new(secret.encode(),
                       f"{ts}.{body.decode()}".encode(),
                       sha256).hexdigest()
        evt = real_stripe.Webhook.construct_event(
            body, f"t={ts},v1={sig}", secret,
        )
        with self.assertRaises(KeyError) as ctx:
            dict(evt)
                                                                    
                                                                      
        self.assertEqual(ctx.exception.args, (0,))


class StripeSignatureErrorTypingTests(unittest.TestCase):


    def _set_secret(self, secret: str):
                                                                
                                                
        return patch.dict(
            "os.environ",
            {"STRIPE_WEBHOOK_SECRET": secret},
            clear=False,
        )

    def test_bad_signature_raises_typed_StripeSignatureError(self):
        from stripe_service import (
            StripeSignatureError, verify_webhook_signature,
        )
        with self._set_secret("whsec_correct"):
            with self.assertRaises(StripeSignatureError) as ctx:
                verify_webhook_signature(
                    payload=b'{"id":"evt_x","type":"x","data":{"object":{}}}',
                    signature_header="t=1,v1=clearly_wrong",
                )
                                                                           
                                                        
        self.assertIsInstance(
            ctx.exception.underlying,
            real_stripe.error.SignatureVerificationError,
        )

    def test_missing_secret_still_raises_unconfigured_not_signature(self):
                                                                    
        from stripe_service import verify_webhook_signature
        with self._set_secret(""):
            with self.assertRaises(StripeUnconfiguredError):
                verify_webhook_signature(
                    payload=b'{"id":"evt","type":"x"}',
                    signature_header="t=1,v1=x",
                )

    def test_good_signature_returns_plain_dict_not_stripeobject(self):
                                                                       
                                                                   
        import json, hmac, time
        from hashlib import sha256
        from stripe_service import verify_webhook_signature

        body_dict = {
            "id": "evt_end_to_end",
            "type": "customer.subscription.created",
            "object": "event",
            "livemode": False,
            "created": 1767225600,
            "data": {"object": {
                "id": "sub_e2e", "customer": "cus_e2e",
                "metadata": {"account_id": "acct-e2e"},
                "status": "active",
                "items": {"data": [{"quantity": 1}]},
            }},
        }
        body = json.dumps(body_dict).encode("utf-8")
        secret = "whsec_end_to_end"
        ts = int(time.time())
        sig = hmac.new(secret.encode(),
                       f"{ts}.{body.decode()}".encode(),
                       sha256).hexdigest()

        with self._set_secret(secret):
            result = verify_webhook_signature(
                payload=body, signature_header=f"t={ts},v1={sig}",
            )

                                                                        
        self.assertIsInstance(result, dict)
        self.assertEqual(result["type"], "customer.subscription.created")
        self.assertEqual(result["data"]["object"]["metadata"]["account_id"],
                         "acct-e2e")


class StripeEventDecodeErrorTypingTests(unittest.TestCase):


    def test_malformed_body_after_valid_signature_raises_decode_error(self):
                                                                        
                                                                       
        from stripe_service import (
            StripeEventDecodeError, verify_webhook_signature,
        )

                                                                     
        with patch.object(
            real_stripe.Webhook, "construct_event",
            return_value=object(),
        ), patch.dict("os.environ",
                      {"STRIPE_WEBHOOK_SECRET": "whsec_x"},
                      clear=False):
            with self.assertRaises(StripeEventDecodeError) as ctx:
                verify_webhook_signature(
                    payload=b"not valid json at all",
                    signature_header="t=1,v1=x",
                )

                                                                  
        self.assertIsInstance(ctx.exception.underlying, Exception)
        self.assertIn("JSONDecodeError", ctx.exception.reason)

    def test_key_error_during_conversion_preserves_args_for_route_logging(self):
                                                                       
                                                                       
        from stripe_service import (
            StripeEventDecodeError, verify_webhook_signature,
        )

        with patch.object(
            real_stripe.Webhook, "construct_event",
            return_value=object(),
        ), patch(
            "stripe_service._stripe_event_to_plain_dict",
            side_effect=KeyError("metadata"),
        ), patch.dict("os.environ",
                      {"STRIPE_WEBHOOK_SECRET": "whsec_x"},
                      clear=False):
            with self.assertRaises(StripeEventDecodeError) as ctx:
                verify_webhook_signature(
                    payload=b'{"id":"evt"}', signature_header="t=1,v1=x",
                )

        self.assertIsInstance(ctx.exception.underlying, KeyError)
        self.assertEqual(ctx.exception.underlying.args, ("metadata",))
        self.assertIn("KeyError", ctx.exception.reason)
        self.assertIn("metadata", ctx.exception.reason)


class StripeWebhookRouteDecodeFailLogTests(unittest.TestCase):


    def _build_app(self):
        from fastapi import FastAPI
        from routes.stripe_routes import router
                                                                          
                                                                 
        app = FastAPI()
        app.include_router(router)
        return app

    def test_decode_failure_returns_400_with_error_type_and_log_includes_key(self):
        from fastapi.testclient import TestClient
        from stripe_service import StripeEventDecodeError

        app = self._build_app()
        client = TestClient(app)

                                                                   
        underlying = KeyError("metadata")
        with patch("stripe_service.verify_webhook_signature",
                   side_effect=StripeEventDecodeError(
                       reason="KeyError: 'metadata'", underlying=underlying,
                   )), _capture_stdout() as out:
            resp = client.post(
                "/billing/stripe/webhook",
                content=b'{"id":"evt","type":"x"}',
                headers={"stripe-signature": "t=1,v1=x"},
            )

                                                                    
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["code"], "event_decode_failed")
        self.assertEqual(body["error_type"], "KeyError")

                                                                      
        captured = out.getvalue()
        self.assertIn("[STRIPE] webhook decode fail", captured)
        self.assertIn("error_type=KeyError", captured)
        self.assertIn("'metadata'", captured)

                                                                       
        self.assertNotIn("reason=signature_verification", captured)

    def _post_webhook_with_canned_entitlement(
        self, *, ent, dispatch_outcome="applied", account_id="acct-tier-test",
    ):


        from fastapi.testclient import TestClient
        from stripe_service import WebhookDispatchResult

        app = self._build_app()
        client = TestClient(app)

        canned_event = {
            "id": "evt_tier_pin",
            "type": "customer.subscription.created",
            "livemode": False,
            "data": {"object": {}},
        }
        canned_result = WebhookDispatchResult(
            outcome=dispatch_outcome,
            event_id="evt_tier_pin",
            event_type="customer.subscription.created",
            account_id=account_id,
        )
        with patch(
            "stripe_service.verify_webhook_signature",
            return_value=canned_event,
        ), patch(
            "stripe_service.dispatch_webhook_event",
            return_value=canned_result,
        ), patch(
            "billing.get_entitlement",
            return_value=ent,
        ), _capture_stdout() as out:
            resp = client.post(
                "/billing/stripe/webhook",
                content=b'{"id":"evt_tier_pin","type":"customer.subscription.created"}',
                headers={"stripe-signature": "t=1,v1=x"},
            )
        return resp, out.getvalue()

    def _make_entitlement(self, **overrides):
                                                                      
                                                                     
        from billing import StorageEntitlement
        defaults = {
            "account_id":              "acct-tier-test",
            "account_type":            "individual",
            "sales_channel":           "self_service",
            "included_bytes":          1_073_741_824,
            "purchased_bytes":         0,
            "storage_bytes_grant":     0,
            "effective_limit_bytes":   1_073_741_824,
            "used_bytes":              0,
            "percent_used":            0.0,
            "block_count":             0,
            "self_service_max_blocks": 100,
            "status":                  "active",
            "source":                  "stripe",
            "current_period_end":      None,
            "cancel_at_period_end":    False,
            "block_price_cents_usd":   2500,
            "block_bytes":             53_687_091_200,
                                                                   
                                                                  
            "has_active_subscription": False,
        }
        defaults.update(overrides)
        return StorageEntitlement(**defaults)

    def test_paid_one_block_emits_tier_paid_and_fifty_gigabyte_limit(self):
                                                                
                                                                     
        ent = self._make_entitlement(
            block_count=1,
            purchased_bytes=53_687_091_200,
            effective_limit_bytes=53_687_091_200,
        )
        resp, captured = self._post_webhook_with_canned_entitlement(ent=ent)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("[STRIPE] entitlement after webhook", captured)
        self.assertIn("tier='paid'", captured)
        self.assertIn("effective_limit_bytes=53687091200", captured)
                                                               
                                                               
        self.assertNotIn("effective_limit_bytes=54760833024", captured)

    def test_free_user_emits_tier_free_and_one_gigabyte_limit(self):
        ent = self._make_entitlement(
            block_count=0,
            purchased_bytes=0,
            effective_limit_bytes=1_073_741_824,
            status="none",
        )
        resp, captured = self._post_webhook_with_canned_entitlement(ent=ent)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tier='free'", captured)
        self.assertIn("effective_limit_bytes=1073741824", captured)

    def test_expired_paid_subscription_logs_tier_free(self):
                                                                    
                                                                  
        ent = self._make_entitlement(
            block_count=1,                                        
            purchased_bytes=0,                                      
            effective_limit_bytes=1_073_741_824,
            status="expired",
        )
        resp, captured = self._post_webhook_with_canned_entitlement(ent=ent)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tier='free'", captured)

    def test_real_signature_failure_logs_signature_verification_not_decode(self):
        from fastapi.testclient import TestClient
        from stripe_service import StripeSignatureError

        app = self._build_app()
        client = TestClient(app)

                                                               
        sdk_exc = real_stripe.error.SignatureVerificationError(
            "no sig found", "t=1,v1=x", "{}",
        )
        with patch("stripe_service.verify_webhook_signature",
                   side_effect=StripeSignatureError(
                       reason="no_match", underlying=sdk_exc,
                   )), _capture_stdout() as out:
            resp = client.post(
                "/billing/stripe/webhook",
                content=b'{"id":"evt","type":"x"}',
                headers={"stripe-signature": "t=1,v1=wrong"},
            )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "invalid_signature")

        captured = out.getvalue()
        self.assertIn("reason=signature_verification", captured)
        self.assertIn("error_type=SignatureVerificationError", captured)
                                                                       
        self.assertNotIn("[STRIPE] webhook decode fail", captured)


class SubscriptionItemIdCaptureTests(unittest.TestCase):
    def test_extract_subscription_item_id_happy_path(self):
        from stripe_service import _extract_subscription_item_id
        sub = {"items": {"data": [{"id": "si_abc", "quantity": 1}]}}
        self.assertEqual(_extract_subscription_item_id(sub), "si_abc")

    def test_extract_returns_none_for_every_malformed_shape(self):
                                                                     
                                                                
        from stripe_service import _extract_subscription_item_id
        for bad in (
            {},
            {"items": None},
            {"items": {"data": []}},
            {"items": {"data": [{}]}},                                  
            {"items": {"data": [{"id": ""}]}},                        
            {"items": {"data": [{"id": None}]}},                     
            {"items": {"data": [{"id": 12345}]}},                       
        ):
            with self.subTest(payload=bad):
                self.assertIsNone(_extract_subscription_item_id(bad))

    def test_apply_subscription_state_persists_sub_item_id_in_update(self):
                                                                    
                                                                     
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},
        ])
        event = _make_event(
            event_id="evt_capture_sub_item",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_capture",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_capture",
                "metadata": {"account_id": "acct-capture"},
                "items": {"data": [
                    {"id": "si_capture_abc123", "quantity": 2},
                ]},
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")

                                                                     
        update_sql, update_params = next(
            (sql, params) for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
        self.assertIn("stripe_subscription_item_id", update_sql)
        self.assertEqual(update_params[2], "si_capture_abc123")
                                                                    
                                                               
        self.assertEqual(update_params[3], 2)
        self.assertEqual(update_params[4], 2 * 53_687_091_200)

    def test_missing_sub_item_id_still_writes_null_not_crash(self):
                                                                    
                                                                      
        store = FakeDBStore(select_results=[
            {"block_count": 0, "purchased_bytes": 0},
        ])
        event = _make_event(
            event_id="evt_missing_item_id",
            event_type="customer.subscription.created",
            obj={
                "id": "sub_no_item_id",
                "status": "active",
                "current_period_start": 1767225600,
                "current_period_end":   1769817600,
                "cancel_at_period_end": False,
                "customer": "cus_no_item_id",
                "metadata": {"account_id": "acct-no-item"},
                "items": {"data": [{"quantity": 1}]},         
            },
        )
        with _install_fake_db(store):
            result = dispatch_webhook_event(event)
        self.assertEqual(result.outcome, "applied")
        _, update_params = next(
            (sql, params) for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql and "SET status" in sql
        )
                                                            
        self.assertIsNone(update_params[2])


class ActiveSubscriptionLookupTests(unittest.TestCase):


    def _store_for_row(self, row):
        return FakeDBStore(select_results=[row])

    def test_returns_active_sub_for_stripe_active_row(self):
        from stripe_service import get_active_storage_subscription
        row = {
            "account_id": "acct-a",
            "source_subscription_id": "sub_xxx",
            "stripe_subscription_item_id": "si_xxx",
            "block_count": 2,
            "status": "active",
            "source": "stripe",
        }
        with _install_fake_db(self._store_for_row(row)):
            got = get_active_storage_subscription("acct-a")
        self.assertIsNotNone(got)
        self.assertEqual(got.stripe_subscription_id, "sub_xxx")
        self.assertEqual(got.stripe_subscription_item_id, "si_xxx")
        self.assertEqual(got.block_count, 2)
        self.assertEqual(got.status, "active")

    def test_returns_none_when_row_missing(self):
        from stripe_service import get_active_storage_subscription
        with _install_fake_db(self._store_for_row(None)):
            self.assertIsNone(get_active_storage_subscription("acct-x"))

    def test_returns_none_for_non_stripe_source(self):
                                                              
        from stripe_service import get_active_storage_subscription
        row = {
            "account_id": "acct-b",
            "source_subscription_id": "apple_sub_1",
            "stripe_subscription_item_id": None,
            "block_count": 1,
            "status": "active",
            "source": "apple",
        }
        with _install_fake_db(self._store_for_row(row)):
            self.assertIsNone(get_active_storage_subscription("acct-b"))

    def test_returns_none_for_terminal_status(self):
                                                                
                                                                 
        from stripe_service import get_active_storage_subscription
        for terminal in ("expired", "refunded", "over_quota_grace",
                         "over_quota_locked", "paused", "none"):
            with self.subTest(status=terminal):
                row = {
                    "account_id": "acct-c",
                    "source_subscription_id": "sub_yyy",
                    "stripe_subscription_item_id": "si_yyy",
                    "block_count": 1,
                    "status": terminal,
                    "source": "stripe",
                }
                with _install_fake_db(self._store_for_row(row)):
                    self.assertIsNone(
                        get_active_storage_subscription("acct-c"),
                    )

    def test_in_grace_and_canceled_pending_count_as_active(self):
                                                                   
                                                                      
        from stripe_service import get_active_storage_subscription
        for live in ("in_grace", "canceled_pending"):
            with self.subTest(status=live):
                row = {
                    "account_id": "acct-d",
                    "source_subscription_id": "sub_zzz",
                    "stripe_subscription_item_id": "si_zzz",
                    "block_count": 1,
                    "status": live,
                    "source": "stripe",
                }
                with _install_fake_db(self._store_for_row(row)):
                    got = get_active_storage_subscription("acct-d")
                self.assertIsNotNone(got)
                self.assertEqual(got.status, live)

    def test_missing_subscription_id_treated_as_no_sub(self):
                                                                   
                                                                       
        from stripe_service import get_active_storage_subscription
        row = {
            "account_id": "acct-e",
            "source_subscription_id": None,
            "stripe_subscription_item_id": None,
            "block_count": 1,
            "status": "active",
            "source": "stripe",
        }
        with _install_fake_db(self._store_for_row(row)):
            self.assertIsNone(get_active_storage_subscription("acct-e"))


class ModifyExistingQuantityTests(unittest.TestCase):


    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_modify",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_modify",
            "STRIPE_WEBHOOK_SECRET":         "whsec_modify",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _active(self, *, blocks: int, item_id="si_modify_test"):
        from stripe_service import ActiveStorageSubscription
        return ActiveStorageSubscription(
            account_id="acct-modify",
            stripe_subscription_id="sub_modify",
            stripe_subscription_item_id=item_id,
            block_count=blocks,
            status="active",
        )

    def test_modify_calls_stripe_with_always_invoice_proration(self):
                                                                     
                                                                  
        from stripe_service import modify_existing_subscription_quantity

        captured: dict = {}

        class _FakeItem:
            quantity = 4
            id = "si_modify_test"

        def _capture(item_id, **kwargs):
            captured["item_id"] = item_id
            captured.update(kwargs)
            return _FakeItem()

        with patch.object(
            real_stripe.SubscriptionItem, "modify",
            side_effect=_capture,
        ):
            result = modify_existing_subscription_quantity(
                active=self._active(blocks=1),
                new_block_count=4,
            )

        self.assertEqual(captured["item_id"], "si_modify_test")
        self.assertEqual(captured["quantity"], 4)
                                                                  
                                                                    
        self.assertEqual(captured["proration_behavior"], "always_invoice")
        self.assertEqual(result.previous_block_count, 1)
        self.assertEqual(result.new_block_count, 4)

    def test_same_quantity_raises_no_change(self):
        from stripe_service import (
            StripeSubscriptionAlreadyAtQuantityError,
            modify_existing_subscription_quantity,
        )
        with self.assertRaises(StripeSubscriptionAlreadyAtQuantityError):
            modify_existing_subscription_quantity(
                active=self._active(blocks=2),
                new_block_count=2,
            )

    def test_lower_quantity_raises_downgrade_unsupported(self):
                                                                 
                                                       
        from stripe_service import (
            StripeSubscriptionDowngradeUnsupportedError,
            modify_existing_subscription_quantity,
        )
        with self.assertRaises(StripeSubscriptionDowngradeUnsupportedError):
            modify_existing_subscription_quantity(
                active=self._active(blocks=3),
                new_block_count=1,
            )

    def test_over_ceiling_raises_ceiling_exceeded(self):
        from stripe_service import (
            StripeCeilingExceededError,
            modify_existing_subscription_quantity,
        )
        with self.assertRaises(StripeCeilingExceededError):
            modify_existing_subscription_quantity(
                active=self._active(blocks=1),
                new_block_count=999_999,
            )

    def test_missing_item_id_falls_back_to_checkout(self):
                                                                  
                                                                   
        from stripe_service import (
            StripeCheckoutRejectedError,
            modify_existing_subscription_quantity,
        )
        with self.assertRaises(StripeCheckoutRejectedError) as ctx:
            modify_existing_subscription_quantity(
                active=self._active(blocks=1, item_id=None),
                new_block_count=2,
            )
        self.assertEqual(ctx.exception.stripe_code,
                         "missing_subscription_item_id")


class BackfillSubscriptionItemIdTests(unittest.TestCase):


    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY":                "sk_test_backfill",
            "STRIPE_STORAGE_BLOCK_PRICE_ID": "price_backfill",
            "STRIPE_WEBHOOK_SECRET":         "whsec_backfill",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _active(self, *, item_id=None):
        from stripe_service import ActiveStorageSubscription
        return ActiveStorageSubscription(
            account_id="acct-backfill",
            stripe_subscription_id="sub_backfill",
            stripe_subscription_item_id=item_id,
            block_count=3,
            status="active",
        )

    def test_already_set_short_circuits_without_db_or_stripe_call(self):
                                                                       
                                                                   
        from stripe_service import backfill_subscription_item_id_from_stripe
        store = FakeDBStore()
        with _install_fake_db(store), patch(
            "stripe_service.stripe.Subscription.retrieve",
        ) as retrieve_mock:
            result = backfill_subscription_item_id_from_stripe(
                self._active(item_id="si_already_set"),
            )
        self.assertEqual(result.stripe_subscription_item_id, "si_already_set")
        retrieve_mock.assert_not_called()
        self.assertEqual(store.executed, [])

    def test_happy_path_persists_item_id_and_returns_refreshed_active(self):
                                                                   
                                                                       
        from stripe_service import backfill_subscription_item_id_from_stripe
        store = FakeDBStore()

        class _StripeSub(dict):
            pass

        fake_sub = _StripeSub({
            "id": "sub_backfill",
            "items": {"data": [
                {"id": "si_from_stripe", "quantity": 3},
            ]},
        })
        with _install_fake_db(store), patch(
            "stripe_service.stripe.Subscription.retrieve",
            return_value=fake_sub,
        ) as retrieve_mock:
            result = backfill_subscription_item_id_from_stripe(
                self._active(item_id=None),
            )

        retrieve_mock.assert_called_once_with("sub_backfill")
        self.assertEqual(result.stripe_subscription_item_id, "si_from_stripe")
                                                                     
        self.assertEqual(result.account_id, "acct-backfill")
        self.assertEqual(result.stripe_subscription_id, "sub_backfill")
        self.assertEqual(result.block_count, 3)
        self.assertEqual(result.status, "active")
                                                                   
                                                        
        updates = [
            (sql, params) for sql, params in store.executed
            if "UPDATE account_subscriptions" in sql
            and "stripe_subscription_item_id" in sql
        ]
        self.assertEqual(len(updates), 1)
        _sql, params = updates[0]
        self.assertEqual(params,
                         ("si_from_stripe", "acct-backfill", "sub_backfill"))
                                                                   
                                                                     
        self.assertIn("stripe_subscription_item_id IS NULL", _sql)
        self.assertEqual(store.committed, 1)

    def test_stripe_retrieve_error_returns_active_unchanged(self):
                                                                   
                                                                      
        from stripe_service import backfill_subscription_item_id_from_stripe
        store = FakeDBStore()
        with _install_fake_db(store), patch(
            "stripe_service.stripe.Subscription.retrieve",
            side_effect=real_stripe.error.APIConnectionError("network down"),
        ):
            result = backfill_subscription_item_id_from_stripe(
                self._active(item_id=None),
            )
        self.assertIsNone(result.stripe_subscription_item_id)
        self.assertEqual(store.executed, [])
        self.assertEqual(store.committed, 0)

    def test_malformed_payload_no_items_returns_active_unchanged(self):
                                                                       
                                                                     
        from stripe_service import backfill_subscription_item_id_from_stripe
        store = FakeDBStore()
        with _install_fake_db(store), patch(
            "stripe_service.stripe.Subscription.retrieve",
            return_value={"id": "sub_backfill", "items": {"data": []}},
        ):
            result = backfill_subscription_item_id_from_stripe(
                self._active(item_id=None),
            )
        self.assertIsNone(result.stripe_subscription_item_id)
        self.assertEqual(store.executed, [])


class CheckoutSessionDispatchRouteTests(unittest.TestCase):


    def _build_app(self):
        from fastapi import FastAPI
        from routes.stripe_routes import router
        from device_gate import verify_trusted_device
        app = FastAPI()
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id":   "vault-dispatch",
            "vault_name": "test-vault",
            "token_id":   "token-dispatch",
            "device_id":  None,
        }
        app.include_router(router)
        return app

    def _patch_ensure_account(self):
        return patch(
            "billing.ensure_account_for_vault",
            return_value="acct-dispatch",
        )

    def test_branch_a_opens_checkout_when_no_active_sub(self):
                                                                
                                                                 
        from fastapi.testclient import TestClient
        from stripe_service import CheckoutSession

        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=None,
        ), patch(
            "stripe_service.create_checkout_session",
            return_value=CheckoutSession(
                checkout_url="https://checkout.stripe.com/c/pay/test",
                session_id="cs_test_1",
            ),
        ) as create_mock:
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 1},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["action"], "open_checkout")
        self.assertTrue(body["checkout_url"].startswith("https://"))
        self.assertEqual(body["session_id"], "cs_test_1")
        create_mock.assert_called_once()

    def test_checkout_rejection_keeps_stripe_diagnostics_server_side(self):
        from fastapi.testclient import TestClient
        from stripe_service import StripeCheckoutRejectedError

        client = TestClient(self._build_app())
        raw_message = "Your account cannot currently make live charges."
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=None,
        ), patch(
            "stripe_service.create_checkout_session",
            side_effect=StripeCheckoutRejectedError(
                stripe_type="InvalidRequestError",
                stripe_code=None,
                stripe_message=raw_message,
                param=None,
            ),
        ):
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 1},
            )

        self.assertEqual(resp.status_code, 503)
        detail = resp.json()["detail"]
        self.assertEqual(
            detail,
            {
                "code": "checkout_temporarily_unavailable",
                "message": "We couldn't start checkout. Please try again.",
            },
        )
        serialized = resp.text
        self.assertNotIn(raw_message, serialized)
        self.assertNotIn("stripe_message", serialized)
        self.assertNotIn("InvalidRequestError", serialized)
        self.assertNotIn("See the stripe_message field", serialized)

    def test_unexpected_checkout_failure_does_not_expose_exception_type(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=None,
        ), patch(
            "stripe_service.create_checkout_session",
            side_effect=RuntimeError("operator-only diagnostic"),
        ):
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 1},
            )

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(
            resp.json()["detail"]["message"],
            "We couldn't start checkout. Please try again.",
        )
        self.assertNotIn("RuntimeError", resp.text)
        self.assertNotIn("operator-only diagnostic", resp.text)

    def test_branch_b_modifies_existing_when_active_sub_present(self):
                                                               
                                                     
        from fastapi.testclient import TestClient
        from stripe_service import (
            ActiveStorageSubscription, SubscriptionQuantityUpdate,
        )

        active = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_dispatch",
            stripe_subscription_item_id="si_dispatch",
            block_count=1,
            status="active",
        )
        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=active,
        ), patch(
            "stripe_service.modify_existing_subscription_quantity",
            return_value=SubscriptionQuantityUpdate(
                stripe_subscription_id="sub_dispatch",
                stripe_subscription_item_id="si_dispatch",
                previous_block_count=1,
                new_block_count=4,
            ),
        ) as modify_mock, patch(
            "stripe_service.create_checkout_session",
        ) as checkout_mock:
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 4},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["action"], "updated_existing")
        self.assertEqual(body["previous_blocks"], 1)
        self.assertEqual(body["new_blocks"], 4)
        self.assertEqual(body["stripe_subscription_id"], "sub_dispatch")
        self.assertEqual(body["stripe_subscription_item_id"], "si_dispatch")
                                                                     
                                                                     
        modify_mock.assert_called_once()
        checkout_mock.assert_not_called()

    def test_branch_b_same_quantity_returns_400_no_change(self):
        from fastapi.testclient import TestClient
        from stripe_service import (
            ActiveStorageSubscription,
            StripeSubscriptionAlreadyAtQuantityError,
        )
        active = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_dispatch",
            stripe_subscription_item_id="si_dispatch",
            block_count=2,
            status="active",
        )
        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=active,
        ), patch(
            "stripe_service.modify_existing_subscription_quantity",
            side_effect=StripeSubscriptionAlreadyAtQuantityError(
                current_blocks=2, requested_blocks=2,
            ),
        ):
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 2},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"]["code"], "no_change")

    def test_branch_b_downgrade_returns_400_downgrade_not_supported(self):
        from fastapi.testclient import TestClient
        from stripe_service import (
            ActiveStorageSubscription,
            StripeSubscriptionDowngradeUnsupportedError,
        )
        active = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_dispatch",
            stripe_subscription_item_id="si_dispatch",
            block_count=4,
            status="active",
        )
        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=active,
        ), patch(
            "stripe_service.modify_existing_subscription_quantity",
            side_effect=StripeSubscriptionDowngradeUnsupportedError(
                current_blocks=4, requested_blocks=2,
            ),
        ):
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 2},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"]["code"], "downgrade_not_supported",
        )

    def test_active_sub_without_item_id_backfills_then_modifies(self):
                                                      
                                                                     
        from fastapi.testclient import TestClient
        from stripe_service import (
            ActiveStorageSubscription, SubscriptionQuantityUpdate,
        )

        active_no_item = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_backfill",
            stripe_subscription_item_id=None,                       
            block_count=3,
            status="active",
        )
        active_filled = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_backfill",
            stripe_subscription_item_id="si_recovered",
            block_count=3,
            status="active",
        )
        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=active_no_item,
        ), patch(
            "stripe_service.backfill_subscription_item_id_from_stripe",
            return_value=active_filled,
        ) as backfill_mock, patch(
            "stripe_service.modify_existing_subscription_quantity",
            return_value=SubscriptionQuantityUpdate(
                stripe_subscription_id="sub_backfill",
                stripe_subscription_item_id="si_recovered",
                previous_block_count=3,
                new_block_count=4,
            ),
        ) as modify_mock, patch(
            "stripe_service.create_checkout_session",
        ) as checkout_mock:
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 4},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["action"], "updated_existing")
        self.assertEqual(body["previous_blocks"], 3)
        self.assertEqual(body["new_blocks"], 4)
        self.assertEqual(body["stripe_subscription_item_id"], "si_recovered")
        backfill_mock.assert_called_once_with(active_no_item)
        modify_mock.assert_called_once()
                                                                
                             
        checkout_mock.assert_not_called()

    def test_active_sub_without_item_id_falls_back_to_checkout_when_backfill_fails(self):
                                                                     
                                                                       
        from fastapi.testclient import TestClient
        from stripe_service import (
            ActiveStorageSubscription, CheckoutSession,
        )
        active = ActiveStorageSubscription(
            account_id="acct-dispatch",
            stripe_subscription_id="sub_backfill",
            stripe_subscription_item_id=None,
            block_count=1,
            status="active",
        )
        client = TestClient(self._build_app())
        with self._patch_ensure_account(), patch(
            "stripe_service.get_active_storage_subscription",
            return_value=active,
        ), patch(
            "stripe_service.backfill_subscription_item_id_from_stripe",
            return_value=active,                                         
        ), patch(
            "stripe_service.create_checkout_session",
            return_value=CheckoutSession(
                checkout_url="https://checkout.stripe.com/c/pay/backfill",
                session_id="cs_backfill",
            ),
        ) as checkout_mock, patch(
            "stripe_service.modify_existing_subscription_quantity",
        ) as modify_mock:
            resp = client.post(
                "/billing/checkout-session",
                json={"block_count": 2},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "open_checkout")
        checkout_mock.assert_called_once()
        modify_mock.assert_not_called()


class HasActiveSubscriptionEntitlementTests(unittest.TestCase):


    def setUp(self) -> None:
                                                                   
                                                                  
        import billing
        billing._PRICING_CACHE.update({
            "included_bytes":          1_073_741_824,
            "block_bytes":             53_687_091_200,
            "block_price_cents_usd":   2500,
            "self_service_max_blocks": 100,
        })

    def tearDown(self) -> None:
        import billing
        billing.reset_pricing_cache()

    def _patched_get_db(self, row):
        from unittest.mock import MagicMock
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value = cursor
        grant_cursor = MagicMock()
        grant_cursor.fetchone.return_value = (False,)
        grant_conn = MagicMock()
        grant_conn.cursor.return_value = grant_cursor
        return patch(
            "billing.get_db",
            side_effect=[conn, grant_conn, grant_conn, grant_conn],
        )

    def _row(self, *, status="active", source="stripe", block_count=1):
        return {
            "account_id":              "acct-x",
            "account_type":            "individual",
            "sales_channel":           "self_service",
            "status":                  status,
            "source":                  source,
            "block_count":             block_count,
            "purchased_bytes":         block_count * 53_687_091_200,
            "storage_bytes_grant":     0,
            "storage_bytes_grant_expires_at": None,
            "current_period_end":      None,
            "cancel_at_period_end":    False,
            "used_bytes":              0,
        }

    def test_active_stripe_sub_flags_true(self):
        from billing import get_entitlement
        with self._patched_get_db(self._row(status="active")):
            ent = get_entitlement("acct-x")
        self.assertTrue(ent.has_active_subscription)

    def test_free_tier_flags_false(self):
        from billing import get_entitlement
        with self._patched_get_db(
            self._row(status="none", source="none", block_count=0),
        ):
            ent = get_entitlement("acct-x")
        self.assertFalse(ent.has_active_subscription)

    def test_expired_stripe_sub_flags_false(self):
                                                                
                                                               
        from billing import get_entitlement
        with self._patched_get_db(self._row(status="expired")):
            ent = get_entitlement("acct-x")
        self.assertFalse(ent.has_active_subscription)

    def test_in_grace_and_canceled_pending_flag_true(self):
                                                                    
                                                            
        from billing import get_entitlement
        for live in ("in_grace", "canceled_pending"):
            with self.subTest(status=live):
                with self._patched_get_db(self._row(status=live)):
                    ent = get_entitlement("acct-x")
                self.assertTrue(ent.has_active_subscription)

    def test_apple_sub_flags_false_even_when_active(self):
                                                                  
                                                                 
        from billing import get_entitlement
        with self._patched_get_db(
            self._row(status="active", source="apple"),
        ):
            ent = get_entitlement("acct-x")
        self.assertFalse(ent.has_active_subscription)


class CleanupDuplicateSubsTests(unittest.TestCase):


    def setUp(self):
        self.env = patch.dict("os.environ", {
            "STRIPE_API_KEY": "sk_test_cleanup",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _sub(self, sub_id: str, status: str = "active"):
                                                                   
                                                   
        class _S:
            pass
        s = _S()
        s.id = sub_id
        s.status = status
        return s

    def test_cancels_every_active_sub_except_the_kept_one(self):
        from stripe_service import cancel_duplicate_storage_subscriptions

        kept = "sub_keep"
        listing = [
            self._sub("sub_dup_a", "active"),
            self._sub("sub_dup_b", "active"),
            self._sub(kept,        "active"),                   
        ]

        class _Page:
            def auto_paging_iter(self_inner):
                return iter(listing)

        canceled_ids: list[str] = []

        class _Canceled:
            pass

        def _cancel(sub_id, **kwargs):
            canceled_ids.append(sub_id)
                                                                   
                                                                   
            assert kwargs.get("prorate") is True, (
                "Cancel must pass prorate=True so the user is credited "
                "for unused time on the duplicate subscriptions."
            )
            assert kwargs.get("invoice_now") is False
            c = _Canceled()
            c.id = sub_id
            return c

        with patch.object(
            real_stripe.Subscription, "list", return_value=_Page(),
        ), patch.object(
            real_stripe.Subscription, "cancel", side_effect=_cancel,
        ):
            summary = cancel_duplicate_storage_subscriptions(
                account_id="acct-cleanup",
                customer_id="cus_cleanup",
                keep_subscription_id=kept,
            )

                                                              
        self.assertEqual(sorted(canceled_ids), ["sub_dup_a", "sub_dup_b"])
        self.assertEqual(summary["canceled_count"], 2)
        self.assertEqual(summary["kept_subscription_id"], kept)
        self.assertNotIn(kept, summary["canceled_subscription_ids"])

    def test_skips_already_canceled_status(self):
                                                                
                                             
        from stripe_service import cancel_duplicate_storage_subscriptions

        kept = "sub_keep_2"
        listing = [
            self._sub("sub_already_canceled", "canceled"),
            self._sub(kept, "active"),
        ]

        class _Page:
            def auto_paging_iter(self_inner):
                return iter(listing)

        def _cancel(sub_id, **kwargs):                    
            raise AssertionError(
                "cancel must not be called for an already-canceled sub",
            )

        with patch.object(
            real_stripe.Subscription, "list", return_value=_Page(),
        ), patch.object(
            real_stripe.Subscription, "cancel", side_effect=_cancel,
        ):
            summary = cancel_duplicate_storage_subscriptions(
                account_id="acct-cleanup-2",
                customer_id="cus_cleanup-2",
                keep_subscription_id=kept,
            )
        self.assertEqual(summary["canceled_count"], 0)


if __name__ == "__main__":
    unittest.main()
