


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




class _FakeUrlopenResp:

    def __init__(self, body_obj):
        self._body = json.dumps(body_obj).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _capture_request(dest: list, body_obj):

    def _urlopen(request, timeout=None):
        dest.append(request)
        return _FakeUrlopenResp(body_obj)
    return _urlopen


class TronContractCallPayloadShapeTests(unittest.TestCase):




    def test_balance_of_payload_carries_the_right_selector(self):
        from tron_rpc import tron_get_trc20_balance_at_url
        captured = []
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_capture_request(captured, {
                "result": {"result": True},
                "constant_result": ["0" * 64],
            }),
        ):
            v = tron_get_trc20_balance_at_url(
                "http://mock", "key",
                contract_address_b58=_USDT_MAINNET_CONTRACT,
                holder_address_b58=_HOLDER,
            )
        self.assertEqual(v, 0)


        self.assertEqual(len(captured), 1)
        req = captured[0]


        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["function_selector"], "balanceOf(address)")

    def test_payload_owner_and_contract_are_hex_with_41_prefix_when_visible_is_false(self):

        from tron_rpc import tron_get_trc20_balance_at_url
        captured = []
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_capture_request(captured, {
                "result": {"result": True},
                "constant_result": ["0" * 64],
            }),
        ):
            tron_get_trc20_balance_at_url(
                "http://mock", "key",
                contract_address_b58=_USDT_MAINNET_CONTRACT,
                holder_address_b58=_HOLDER,
            )

        body = json.loads(captured[0].data.decode("utf-8"))



        self.assertFalse(body["visible"])
        self.assertEqual(len(body["owner_address"]), 42,
            "owner_address must be 42 hex chars (21 bytes) when visible=false")
        self.assertTrue(
            body["owner_address"].lower().startswith("41"),
            "TRON mainnet hex address must start with 41",
        )
        self.assertEqual(len(body["contract_address"]), 42,
            "contract_address must be 42 hex chars when visible=false")
        self.assertTrue(
            body["contract_address"].lower().startswith("41"),
            "TRON mainnet hex address must start with 41",
        )


        self.assertFalse(body["owner_address"].startswith("0x"))
        self.assertFalse(body["contract_address"].startswith("0x"))


    def test_parameter_is_64_hex_chars_padded_holder_address(self):

        from tron_rpc import (
            tron_get_trc20_balance_at_url,
            tron_address_to_evm_hex,
        )
        captured = []
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_capture_request(captured, {
                "result": {"result": True},
                "constant_result": ["0" * 64],
            }),
        ):
            tron_get_trc20_balance_at_url(
                "http://mock", "key",
                contract_address_b58=_USDT_MAINNET_CONTRACT,
                holder_address_b58=_HOLDER,
            )

        body = json.loads(captured[0].data.decode("utf-8"))
        param = body["parameter"]


        self.assertEqual(len(param), 64,
            "ABI-encoded address parameter must be 64 hex chars")


        holder_evm = tron_address_to_evm_hex(_HOLDER).lower()
        self.assertTrue(param.lower().endswith(holder_evm),
            "the 20-byte holder address must appear as the low 40 hex "
            "chars of the ABI-encoded parameter")


        self.assertTrue(param.startswith("0" * 24),
            "the parameter must be LEFT-padded with 24 zero chars (the "
            "high bytes of the 32-byte ABI slot)")


class TronContractCallResponseParsingTests(unittest.TestCase):




    def _run_with_response(self, body_obj):
        from tron_rpc import tron_get_trc20_balance_at_url
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=lambda req, timeout=None: _FakeUrlopenResp(body_obj),
        ):
            return tron_get_trc20_balance_at_url(
                "http://mock", "key",
                contract_address_b58=_USDT_MAINNET_CONTRACT,
                holder_address_b58=_HOLDER,
            )


    def test_zero_balance_response_returns_int_zero(self):
        v = self._run_with_response({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertEqual(v, 0)


    def test_positive_balance_response_parses_hex_to_base_units(self):

        hex_val = format(1_234_500_000, "x").rjust(64, "0")
        v = self._run_with_response({
            "result": {"result": True},
            "constant_result": [hex_val],
        })
        self.assertEqual(v, 1_234_500_000)


    def test_positive_balance_survives_optional_leading_0x(self):

        hex_val = "0x" + format(2_500_000, "x").rjust(64, "0")
        v = self._run_with_response({
            "result": {"result": True},
            "constant_result": [hex_val],
        })
        self.assertEqual(v, 2_500_000)


    def test_provider_error_message_maps_to_tron_contract_read_failed(self):

        from tron_rpc import TronRpcError, REASON_TRON_CONTRACT_READ_FAILED
        with self.assertRaises(TronRpcError) as ctx:
            self._run_with_response({
                "result": {
                    "result": False,
                    "code":    "CONTRACT_VALIDATE_ERROR",
                    "message": "malformed contract read",
                },
            })
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_CONTRACT_READ_FAILED)


    def test_missing_constant_result_maps_to_tron_contract_read_failed(self):

        from tron_rpc import TronRpcError, REASON_TRON_CONTRACT_READ_FAILED
        with self.assertRaises(TronRpcError) as ctx:
            self._run_with_response({"result": {"result": True}})
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_CONTRACT_READ_FAILED)


    def test_empty_constant_result_maps_to_tron_contract_read_failed(self):

        from tron_rpc import TronRpcError, REASON_TRON_CONTRACT_READ_FAILED
        with self.assertRaises(TronRpcError) as ctx:
            self._run_with_response({
                "result":          {"result": True},
                "constant_result": [],
            })
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_CONTRACT_READ_FAILED)


    def test_non_hex_constant_result_maps_to_tron_contract_read_failed(self):

        from tron_rpc import TronRpcError, REASON_TRON_CONTRACT_READ_FAILED
        with self.assertRaises(TronRpcError) as ctx:
            self._run_with_response({
                "result":          {"result": True},
                "constant_result": ["not_hex_zzz"],
            })
        self.assertEqual(ctx.exception.code,
                         REASON_TRON_CONTRACT_READ_FAILED)


class TronContractCallShapeLogSafetyTests(unittest.TestCase):




    def _capture_shape_log(self, response_body):
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
            from tron_rpc import tron_get_trc20_balance_at_url
            try:
                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=lambda r, timeout=None:
                        _FakeUrlopenResp(response_body),
                ):
                    tron_get_trc20_balance_at_url(
                        "http://mock", "sensitive_key_value_XYZ_do_not_leak",
                        contract_address_b58=_USDT_MAINNET_CONTRACT,
                        holder_address_b58=_HOLDER,
                    )
            except Exception:

                pass
            handler.flush()
            return stream.getvalue()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_shape_log_appears_on_success_with_ok_status(self):
        out = self._capture_shape_log({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertIn("tron_contract_call_shape", out)
        self.assertIn("provider_status=ok", out)


    def test_shape_log_appears_on_provider_error(self):

        out = self._capture_shape_log({
            "result": {
                "result": False, "code": "X", "message": "bad",
            },
        })
        self.assertIn("provider_status=provider_error_message", out)


    def test_shape_log_appears_on_missing_constant_result(self):

        out = self._capture_shape_log({"result": {"result": True}})
        self.assertIn("provider_status=constant_result_missing", out)


    def test_shape_log_never_leaks_api_key_addresses_url_response_body(self):

        out = self._capture_shape_log({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        }).lower()


        self.assertNotIn("sensitive_key_value_xyz_do_not_leak", out,
            "the API key value we passed must NEVER appear in the log")


        self.assertNotIn(_HOLDER.lower(), out,
            "wallet address must NEVER be in the shape log")
        self.assertNotIn(_USDT_MAINNET_CONTRACT.lower(), out,
            "contract address must NEVER be in the shape log")


        self.assertNotIn("http://mock", out,
            "provider URL must NEVER be in the shape log")


        for banned in ("bearer", "authorization", "encrypted_secret",
                       "private_key", "tx_hash", "txid",
                       '"result":', "constant_result:[",
                       "constant_result:0000",):
            self.assertNotIn(banned, out,
                f"shape log leaks {banned!r}")


    def test_shape_log_uses_only_bool_and_int_and_enum_fields(self):

        src = (_BACKEND_ROOT / "tron_rpc.py").read_text(encoding="utf-8")
        start = src.find("def _log_tron_contract_call_shape(")
        self.assertGreater(start, 0)
        end = src.find("def tron_get_trc20_balance_at_url(", start)
        self.assertGreater(end, start)
        block = src[start:end]


        self.assertIn('owner_hex_present=%s', block)
        self.assertIn('contract_hex_present=%s', block)
        self.assertIn('parameter_len=%d', block)
        self.assertIn('function_selector=balanceOf(address)', block)
        self.assertIn('visible=%s', block)
        self.assertIn('provider_status=%s', block)
        self.assertIn('result_present=%s', block)
        self.assertIn('constant_result_present=%s', block)


        self.assertIn('"true" if owner_hex_present else "false"', block,
            "owner_hex_present must be logged as a bool string, never as "
            "the actual hex address")
        self.assertIn('"true" if contract_hex_present else "false"', block)



        for banned in ("owner_hex,", "contract_hex,", "parameter,",
                       "api_key,", "base_url,",
                       "raw", "parsed,", "response",):
            self.assertNotIn(banned, block,
                f"shape log block references {banned!r} which could leak "
                f"a value")


if __name__ == "__main__":
    unittest.main()
