"""Verifies the tron_contract_call_shape log is emitted on every
sub-path of tron_get_trc20_balance_at_url, not just the parsed-body
branches.
"""

from __future__ import annotations

import io
import json
import logging
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


_BACKEND_ROOT = Path(__file__).parent


_USDT_MAINNET_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
_HOLDER = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"


def _capture_shape_log(func):
    logger = logging.getLogger("tron_rpc")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    original_level = logger.level
    original_disabled = logger.disabled
    logger.disabled = False
    logger.setLevel(logging.INFO)
    try:
        try:
            func()
        except Exception:
            pass
        handler.flush()
        return stream.getvalue()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.disabled = original_disabled


def _make_http_error(status: int):
    return urllib.error.HTTPError(
        url="http://mock", code=status, msg="err",
        hdrs=None, fp=io.BytesIO(b""),
    )


class TronShapeLogFiresOnEveryProviderErrorTests(unittest.TestCase):


    def _run_with_urlopen_side_effect(
        self, api_key: str, side_effect,
    ) -> str:
        from tron_rpc import tron_get_trc20_balance_at_url

        def _call():
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=side_effect,
            ):
                tron_get_trc20_balance_at_url(
                    "http://mock", api_key,
                    contract_address_b58=_USDT_MAINNET_CONTRACT,
                    holder_address_b58=_HOLDER,
                )

        return _capture_shape_log(_call)


    def test_shape_log_fires_on_provider_unreachable(self):
        def raise_urlerror(req, timeout=None):
            raise urllib.error.URLError("no route")

        out = self._run_with_urlopen_side_effect("k", raise_urlerror)
        self.assertIn("tron_contract_call_shape", out)
        self.assertIn("provider_status=provider_unreachable", out)


    def test_shape_log_fires_on_provider_timeout(self):
        def raise_timeout(req, timeout=None):
            raise TimeoutError("timed out")

        out = self._run_with_urlopen_side_effect("k", raise_timeout)
        self.assertIn("provider_status=provider_unreachable", out)


    def test_shape_log_fires_on_api_unauthorized_when_key_present(self):
        def raise_401(req, timeout=None):
            raise _make_http_error(401)

        out = self._run_with_urlopen_side_effect("k", raise_401)
        self.assertIn("provider_status=api_unauthorized", out)


    def test_shape_log_fires_on_api_key_missing_when_key_absent(self):
        def raise_401(req, timeout=None):
            raise _make_http_error(401)

        out = self._run_with_urlopen_side_effect("", raise_401)
        self.assertIn("provider_status=api_key_missing", out)


    def test_shape_log_fires_on_rate_limited(self):
        def raise_429(req, timeout=None):
            raise _make_http_error(429)

        out = self._run_with_urlopen_side_effect("k", raise_429)
        self.assertIn("provider_status=rate_limited", out)


    def test_shape_log_fires_on_other_http_error(self):
        def raise_500(req, timeout=None):
            raise _make_http_error(500)

        out = self._run_with_urlopen_side_effect("k", raise_500)
        self.assertIn("provider_status=provider_error", out)


    def test_shape_log_fires_on_non_json_response(self):
        class _NonJson:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"not json at all"

        def _urlopen(req, timeout=None):
            return _NonJson()

        out = self._run_with_urlopen_side_effect("k", _urlopen)
        self.assertIn("provider_status=provider_error", out)


class TronShapeLogFiresOnInvalidInputTests(unittest.TestCase):


    def test_shape_log_fires_on_invalid_contract_address(self):
        from tron_rpc import tron_get_trc20_balance_at_url

        def _call():
            tron_get_trc20_balance_at_url(
                "http://mock", "k",
                contract_address_b58="not_a_tron_address",
                holder_address_b58=_HOLDER,
            )

        out = _capture_shape_log(_call)
        self.assertIn("tron_contract_call_shape", out)
        self.assertIn("provider_status=invalid_contract", out)
        self.assertIn("parameter_len=0", out)


    def test_shape_log_fires_on_invalid_holder_address(self):
        from tron_rpc import tron_get_trc20_balance_at_url

        def _call():
            tron_get_trc20_balance_at_url(
                "http://mock", "k",
                contract_address_b58=_USDT_MAINNET_CONTRACT,
                holder_address_b58="not_a_tron_address",
            )

        out = _capture_shape_log(_call)
        self.assertIn("provider_status=invalid_address", out)


class TronShapeLogClosedSetTests(unittest.TestCase):


    def test_provider_status_labels_are_all_closed_set(self):
        src = (_BACKEND_ROOT / "tron_rpc.py").read_text(encoding="utf-8")

        allowed = {
            "ok",
            "response_not_dict",
            "provider_error_message",
            "constant_result_missing",
            "constant_result_invalid_string",
            "constant_result_non_hex",
            "negative_value",
            "api_not_configured",
            "api_key_missing",
            "api_unauthorized",
            "rate_limited",
            "provider_unreachable",
            "provider_error",
            "invalid_contract",
            "invalid_address",
        }
        import re as _re
        labels = set(_re.findall(
            r'provider_status="([a-z_]+)"', src,
        ))
        unknown = labels - allowed
        self.assertFalse(
            unknown,
            f"tron_rpc.py uses provider_status labels outside the "
            f"closed set: {sorted(unknown)}",
        )


    def test_mapping_covers_every_pre_request_reason(self):
        from tron_rpc import (
            _PROVIDER_STATUS_FOR_REASON,
            REASON_TRON_API_NOT_CONFIGURED,
            REASON_TRON_API_KEY_MISSING,
            REASON_TRON_API_UNAUTHORIZED,
            REASON_TRON_RATE_LIMITED,
            REASON_TRON_PROVIDER_UNREACHABLE,
            REASON_TRON_PROVIDER_ERROR,
            REASON_TRON_CONTRACT_NOT_CONFIGURED,
            REASON_TRON_INVALID_ADDRESS,
        )
        for reason in (
            REASON_TRON_API_NOT_CONFIGURED,
            REASON_TRON_API_KEY_MISSING,
            REASON_TRON_API_UNAUTHORIZED,
            REASON_TRON_RATE_LIMITED,
            REASON_TRON_PROVIDER_UNREACHABLE,
            REASON_TRON_PROVIDER_ERROR,
            REASON_TRON_CONTRACT_NOT_CONFIGURED,
            REASON_TRON_INVALID_ADDRESS,
        ):
            self.assertIn(reason, _PROVIDER_STATUS_FOR_REASON)


if __name__ == "__main__":
    unittest.main()
