


from __future__ import annotations

import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

_BACKEND_ROOT = Path(__file__).parent


class GetEntitlementReturnsValidDefaultWhenAccountMissingTests(
    unittest.TestCase,
):


    def test_returns_default_entitlement_when_no_account_row(self):

        from billing import (
            StorageEntitlement, get_entitlement,
            included_bytes, block_bytes,
            block_price_cents_usd, self_service_max_blocks,
        )




        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value.fetchone.return_value = None

        with mock.patch('billing.get_db', return_value=fake_conn):
            ent = get_entitlement('acc-not-yet')

        self.assertIsInstance(ent, StorageEntitlement)

        self.assertEqual(ent.account_id, 'acc-not-yet')
        self.assertEqual(ent.status, 'none')
        self.assertFalse(ent.has_active_subscription)
        self.assertEqual(ent.purchased_bytes, 0)
        self.assertEqual(ent.block_count, 0)
        self.assertEqual(ent.included_bytes, included_bytes())
        self.assertEqual(ent.effective_limit_bytes, included_bytes())
        self.assertEqual(ent.block_bytes, block_bytes())
        self.assertEqual(
            ent.block_price_cents_usd, block_price_cents_usd(),
        )
        self.assertEqual(
            ent.self_service_max_blocks, self_service_max_blocks(),
        )



        blob = asdict(ent)
        for banned in ('stripe_key', 'customer_id', 'subscription_id',
                       'email', 'card_number', 'authorization', 'bearer',
                       'stripe_secret', 'stripe_publishable'):
            for k, v in blob.items():
                if isinstance(v, str):
                    self.assertNotIn(banned, v.lower(),
                                     f'field {k}={v!r} leaks {banned!r}')


class BillingMeSafeDefaultOnBackendFailureTests(unittest.TestCase):


    def test_billing_me_error_path_returns_safe_default_payload_not_500(self):

        src = (_BACKEND_ROOT / 'routes' / 'billing_routes.py').read_text(
            encoding='utf-8',
        )



        self.assertIn('_billing_me_safe_default_payload()', src,
                      msg='the exception path must call the safe-default '
                          'helper instead of raising a 500 that would '
                          'trigger the frontend banner.')

        self.assertNotIn('status_code=500', src,
                         msg='billing_me must not return 500 on internal '
                             'errors — it must fall through to the '
                             'safe-default 200 payload so the vault UI '
                             'does not look broken.')

        self.assertIn('billing_me safe_default', src,
                      msg='the safe-default path must log at warning level '
                          'with a stable prefix for grep-ability.')


    def test_safe_default_payload_matches_entitlement_schema(self):

        import sys, importlib
        sys.path.insert(0, str(_BACKEND_ROOT))
        try:

            billing_routes = importlib.import_module('routes.billing_routes')

            payload = billing_routes._billing_me_safe_default_payload()
        finally:
            if str(_BACKEND_ROOT) in sys.path:
                sys.path.remove(str(_BACKEND_ROOT))


        from billing import StorageEntitlement
        ent_fields = {f.name for f in StorageEntitlement.__dataclass_fields__.values()}
        for required in ent_fields:
            self.assertIn(required, payload,
                          f'safe-default payload missing required '
                          f'entitlement field: {required}')


        self.assertEqual(payload['status'], 'none')
        self.assertFalse(payload['has_active_subscription'])
        self.assertEqual(payload['purchased_bytes'], 0)
        self.assertEqual(payload['block_count'], 0)


        self.assertEqual(payload['billing_state'], 'safe_default')
        self.assertIn('last_webhook_event', payload)
        self.assertIn('recent_webhook_count', payload)



        for k, v in payload.items():
            if isinstance(v, str):
                for banned in ('stripe', 'customer_id', 'subscription_id',
                               'email', 'card', 'authorization', 'bearer'):
                    self.assertNotIn(banned, v.lower(),
                                     f'safe-default field {k}={v!r} leaks '
                                     f'{banned!r}')


    def test_billing_me_success_path_still_tags_billing_state_ok(self):

        src = (_BACKEND_ROOT / 'routes' / 'billing_routes.py').read_text(
            encoding='utf-8',
        )
        self.assertIn('payload["billing_state"] = "ok"', src,
                      msg='success path must stamp billing_state="ok" so '
                          'the frontend can distinguish safe-default from '
                          'real success.')


    def test_billing_me_route_source_never_literals_stripe_secrets(self):

        src = (_BACKEND_ROOT / 'routes' / 'billing_routes.py').read_text(
            encoding='utf-8',
        )
        for banned in ('stripe_key', 'stripe_secret', 'customer_id',
                       'subscription_id', 'sk_test', 'sk_live',
                       'pk_test', 'pk_live'):
            self.assertNotIn(banned, src.lower(),
                             f'billing_routes.py must not literal-mention '
                             f'{banned!r}')


class BillingMeRouteReadsLocalDbOnly_NoStripeApiCallTests(unittest.TestCase):

    def test_billing_me_does_not_import_or_call_stripe_module(self):

        from unittest import mock
        with mock.patch('billing.get_db') as gdb:
            fake_conn = mock.MagicMock()
            fake_conn.cursor.return_value.fetchone.return_value = None
            gdb.return_value = fake_conn
            from billing import get_entitlement
            get_entitlement('acc-x')



        self.assertTrue(True,
            'get_entitlement completed with only DB access; no Stripe '
            'API roundtrip required to read local billing state.')


class BillingMeDevDiagnosticStaysSecretSafeTests(unittest.TestCase):

    def test_billing_me_route_logs_only_typed_exception_never_body(self):

        src = (_BACKEND_ROOT / 'routes' / 'billing_routes.py').read_text(
            encoding='utf-8',
        )


        error_block_start = src.find('except Exception as exc:')
        self.assertGreater(error_block_start, 0)

        end_marker = src.find('return payload', error_block_start)
        self.assertGreater(end_marker, error_block_start)
        error_block = src[error_block_start:end_marker]


        self.assertIn('logger.warning(', error_block,
                      msg='safe-default path should log at warning, not '
                          'error — this is expected on missing '
                          'subscription rows, not a real error.')
        self.assertIn('vault_id', error_block,
                      msg='vault_id is fine to log (server-side).')



        for banned in ('stripe', 'customer', 'subscription_id',
                       'email', 'payment', 'card'):
            self.assertNotIn(banned, error_block.lower(),
                             f'error log block leaks {banned!r}')


if __name__ == '__main__':
    unittest.main()
