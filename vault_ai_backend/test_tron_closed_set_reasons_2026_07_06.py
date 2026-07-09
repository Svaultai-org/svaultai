


from __future__ import annotations

import io
import logging
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_BACKEND_ROOT = Path(__file__).parent


class TronPostJsonMapsHttpErrorsToClosedSetReasonsTests(unittest.TestCase):




    def _make_http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url='http://mock',
            code=code,
            msg=f'{code} status',
            hdrs=None,
            fp=io.BytesIO(b''),
        )


    def test_http_401_with_api_key_maps_to_tron_api_unauthorized(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_API_UNAUTHORIZED,
            _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=self._make_http_error(401),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='real_key',
                )
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_API_UNAUTHORIZED)

    def test_http_403_with_api_key_maps_to_tron_api_unauthorized(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_API_UNAUTHORIZED,
            _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=self._make_http_error(403),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='real_key',
                )
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_API_UNAUTHORIZED)

    def test_http_401_without_api_key_maps_to_tron_api_key_missing(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_API_KEY_MISSING, _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=self._make_http_error(401),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='',
                )
        self.assertEqual(ctx.exception.code, REASON_TRON_API_KEY_MISSING)

    def test_http_429_with_api_key_maps_to_tron_rate_limited(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_RATE_LIMITED, _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=self._make_http_error(429),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='real_key',
                )
        self.assertEqual(ctx.exception.code, REASON_TRON_RATE_LIMITED)

    def test_http_429_without_api_key_maps_to_tron_api_key_missing(self):

        from tron_rpc import (
            TronRpcError, REASON_TRON_API_KEY_MISSING, _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=self._make_http_error(429),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='',
                )
        self.assertEqual(ctx.exception.code, REASON_TRON_API_KEY_MISSING)

    def test_generic_url_error_maps_to_tron_provider_unreachable(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_PROVIDER_UNREACHABLE,
            _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=urllib.error.URLError('conn refused'),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='',
                )
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_PROVIDER_UNREACHABLE)

    def test_timeout_error_maps_to_tron_provider_unreachable(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_PROVIDER_UNREACHABLE,
            _post_tron_json,
        )
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=TimeoutError('slow'),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='',
                )
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_PROVIDER_UNREACHABLE)

    def test_empty_base_url_maps_to_tron_api_not_configured(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_API_NOT_CONFIGURED, _post_tron_json,
        )
        with self.assertRaises(TronRpcError) as ctx:
            _post_tron_json('', '/wallet/x', {}, api_key='')
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_API_NOT_CONFIGURED)


    def test_bad_json_body_maps_to_tron_provider_error(self):
        from tron_rpc import (
            TronRpcError, REASON_TRON_PROVIDER_ERROR, _post_tron_json,
        )

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'not-valid-json{{{'

        with mock.patch(
            'urllib.request.urlopen', return_value=_FakeResp(),
        ):
            with self.assertRaises(TronRpcError) as ctx:
                _post_tron_json(
                    'http://mock', '/wallet/x', {}, api_key='real',
                )
        self.assertEqual(ctx.exception.code, REASON_TRON_PROVIDER_ERROR)


class TronClosedSetConstantsExistTests(unittest.TestCase):


    def test_all_user_spec_reasons_are_defined_and_stable(self):
        from tron_rpc import (
            REASON_TRON_API_NOT_CONFIGURED,
            REASON_TRON_API_KEY_MISSING,
            REASON_TRON_API_UNAUTHORIZED,
            REASON_TRON_RATE_LIMITED,
            REASON_TRON_PROVIDER_UNREACHABLE,
            REASON_TRON_CONTRACT_NOT_CONFIGURED,
            REASON_TRON_CONTRACT_READ_FAILED,
            REASON_TRON_INVALID_ADDRESS,
            REASON_TRON_PROVIDER_ERROR,
        )
        expected = {
            REASON_TRON_API_NOT_CONFIGURED:      'tron_api_not_configured',
            REASON_TRON_API_KEY_MISSING:         'tron_api_key_missing',
            REASON_TRON_API_UNAUTHORIZED:        'tron_api_unauthorized',
            REASON_TRON_RATE_LIMITED:            'tron_rate_limited',
            REASON_TRON_PROVIDER_UNREACHABLE:    'tron_provider_unreachable',
            REASON_TRON_CONTRACT_NOT_CONFIGURED: 'tron_contract_not_configured',
            REASON_TRON_CONTRACT_READ_FAILED:    'tron_contract_read_failed',
            REASON_TRON_INVALID_ADDRESS:         'tron_invalid_address',
            REASON_TRON_PROVIDER_ERROR:          'tron_provider_error',
        }
        for actual, expect in expected.items():
            self.assertEqual(actual, expect)


class TronDevLogIsSafeNoSecretsTests(unittest.TestCase):




    def test_tron_dev_log_never_contains_key_url_address_txhash_body(self):

        src = (
            _BACKEND_ROOT / 'routes' / 'crypto_wallet_routes.py'
        ).read_text(encoding='utf-8')

        start = src.find('def _tron_dev_log(')
        self.assertGreater(start, 0,
            '_tron_dev_log helper must be defined')
        end = src.find('def _tron_balance(', start)
        self.assertGreater(end, start)
        block = src[start:end]



        banned = [
            'tron_api_key', 'TRON_API_KEY',
            'tron_api_base_url()', 'TRON_API_BASE_URL',
            'resolved_address', 'holder_address',
            'publicAddress', 'public_address',
            'wallet_address',
            'authorization', 'bearer',
            'private_key', 'encrypted_secret',
            'tx_hash', 'txid',
            'raw', 'response.body', 'response_body',
        ]
        low = block.lower()
        for b in banned:
            self.assertNotIn(b.lower(), low,
                f'_tron_dev_log block leaks {b!r}')



        self.assertIn('tron_balance_check', block)
        self.assertIn('configured=%s', block)
        self.assertIn('api_key_present=%s', block)
        self.assertIn('contract_configured=%s', block)
        self.assertIn('status=%s', block)
        self.assertIn('reason=%s', block)


    def test_tron_dev_log_only_emits_bool_flags_not_actual_values(self):

        src = (
            _BACKEND_ROOT / 'routes' / 'crypto_wallet_routes.py'
        ).read_text(encoding='utf-8')

        start = src.find('def _tron_dev_log(')
        end   = src.find('def _tron_balance(', start)
        block = src[start:end]



        self.assertIn('"true" if api_key_present else "false"', block,
            'api_key_present must be logged as a bool string, never as '
            'the actual key value.')
        self.assertIn('"true" if configured else "false"', block)
        self.assertIn('"true" if contract_configured else "false"', block)


if __name__ == '__main__':
    unittest.main()
