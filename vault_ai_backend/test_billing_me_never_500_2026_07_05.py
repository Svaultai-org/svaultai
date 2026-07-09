


from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

_BACKEND_ROOT = Path(__file__).parent


def _import_billing_routes():

    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))
    return importlib.import_module('routes.billing_routes')


class BillingMeNever500ForAnyBackendFailureTests(unittest.TestCase):




    def _run_billing_me(self, ensure_side_effect=None,
                        get_ent_side_effect=None):

        billing_routes = _import_billing_routes()
        principal = {'vault_id': 'vault-xyz-test'}


        with mock.patch(
            'billing.ensure_account_for_vault',
            side_effect=ensure_side_effect or (lambda vid: 'acc-xyz'),
        ), mock.patch(
            'billing.get_entitlement',
            side_effect=get_ent_side_effect or (lambda aid: None),
        ), mock.patch.object(
            billing_routes, '_read_last_webhook_event',
            return_value=None,
        ), mock.patch.object(
            billing_routes, '_count_recent_global_webhooks',
            return_value=0,
        ):

            import asyncio
            coro = billing_routes.billing_me(principal=principal)
            return asyncio.new_event_loop().run_until_complete(coro)


    def test_billing_me_returns_safe_default_when_ensure_account_raises(self):

        def _boom(vault_id):
            raise RuntimeError('accounts table missing')

        payload = self._run_billing_me(ensure_side_effect=_boom)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload['billing_state'], 'safe_default')
        self.assertEqual(payload['status'], 'none')
        self.assertFalse(payload['has_active_subscription'])


    def test_billing_me_returns_safe_default_when_get_entitlement_raises(self):

        def _boom(account_id):
            raise RuntimeError('account_subscriptions query failed')

        payload = self._run_billing_me(get_ent_side_effect=_boom)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload['billing_state'], 'safe_default')



    def test_safe_default_payload_has_every_frontend_field(self):

        billing_routes = _import_billing_routes()
        payload = billing_routes._billing_me_safe_default_payload()




        required = {
            'effective_limit_bytes',
            'block_count',
            'purchased_bytes',
            'included_bytes',
            'has_active_subscription',
            'status',
            'block_bytes',
            'block_price_cents_usd',
            'self_service_max_blocks',
            'used_bytes',
            'percent_used',
            'source',
            'account_type',
            'sales_channel',
            'cancel_at_period_end',
            'storage_bytes_grant',
            'current_period_end',
            'account_id',
        }
        for k in required:
            self.assertIn(k, payload,
                          f'safe-default missing required frontend field: {k}')




        self.assertIsInstance(payload['effective_limit_bytes'], int)
        self.assertIsInstance(payload['block_count'], int)
        self.assertIsInstance(payload['purchased_bytes'], int)
        self.assertIsInstance(payload['included_bytes'], int)
        self.assertIsInstance(payload['has_active_subscription'], bool)
        self.assertIsInstance(payload['cancel_at_period_end'], bool)



    def test_billing_me_source_does_not_import_stripe(self):

        src = (_BACKEND_ROOT / 'routes' / 'billing_routes.py').read_text(
            encoding='utf-8',
        )



        error_block_start = src.find('async def billing_me')
        contact_sales_start = src.find('async def contact_sales',
                                       error_block_start)
        self.assertGreater(contact_sales_start, error_block_start)
        billing_me_block = src[error_block_start:contact_sales_start]

        self.assertNotIn('import stripe', billing_me_block.lower())
        self.assertNotIn('stripe.', billing_me_block.lower())



class BillingMeSafeDefaultReflectsLiveConfigTests(unittest.TestCase):


    def test_included_bytes_defaults_to_live_config(self):

        from billing import included_bytes
        billing_routes = _import_billing_routes()
        payload = billing_routes._billing_me_safe_default_payload()

        self.assertEqual(payload['included_bytes'], included_bytes())
        self.assertEqual(payload['effective_limit_bytes'], included_bytes())


    def test_block_bytes_defaults_to_live_config(self):

        from billing import block_bytes, block_price_cents_usd, \
            self_service_max_blocks
        billing_routes = _import_billing_routes()
        payload = billing_routes._billing_me_safe_default_payload()

        self.assertEqual(payload['block_bytes'], block_bytes())
        self.assertEqual(payload['block_price_cents_usd'],
                         block_price_cents_usd())
        self.assertEqual(payload['self_service_max_blocks'],
                         self_service_max_blocks())



class BillingMeSafeDefaultSecretSafetyTests(unittest.TestCase):


    def test_safe_default_payload_no_secrets_in_any_field(self):

        billing_routes = _import_billing_routes()
        payload = billing_routes._billing_me_safe_default_payload()

        banned = ('stripe_key', 'stripe_secret', 'sk_test', 'sk_live',
                  'pk_test', 'pk_live', 'customer_id', 'subscription_id',
                  'card_number', 'authorization: bearer',
                  'bearer eyj')

        for k, v in payload.items():
            if isinstance(v, str):
                low = v.lower()
                for b in banned:
                    self.assertNotIn(b, low,
                        f'safe-default field {k}={v!r} leaks {b!r}')


if __name__ == '__main__':
    unittest.main()
