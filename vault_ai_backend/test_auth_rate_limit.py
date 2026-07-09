

from __future__ import annotations

import os
import types
import unittest
from unittest import mock

from fastapi import HTTPException

import rate_limit_auth
import rate_limit_backend


def _fake_request(*, client_host: str = "1.2.3.4", forwarded: str | None = None) -> object:

    headers = {}
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    client = types.SimpleNamespace(host=client_host)
    return types.SimpleNamespace(headers=headers, client=client)


def _reset_state() -> None:
    rate_limit_backend.reset_rate_limit_backend_for_tests()


class ClientIpExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()

    def tearDown(self) -> None:
        _reset_state()

    def test_falls_back_to_socket_host(self) -> None:
        req = _fake_request(client_host="10.0.0.1")
        self.assertEqual(rate_limit_auth._client_ip(req), "10.0.0.1")

    def test_x_forwarded_for_wins(self) -> None:
        req = _fake_request(client_host="10.0.0.1", forwarded="9.9.9.9, 8.8.8.8")
        self.assertEqual(rate_limit_auth._client_ip(req), "9.9.9.9")

    def test_x_real_ip_used_when_no_forwarded(self) -> None:
        req = _fake_request(client_host="10.0.0.1")
        req.headers["x-real-ip"] = "5.5.5.5"
        self.assertEqual(rate_limit_auth._client_ip(req), "5.5.5.5")


class SignupLimitTests(unittest.TestCase):


    def setUp(self) -> None:
        _reset_state()

    def tearDown(self) -> None:
        _reset_state()

    def test_allows_up_to_limit(self) -> None:
        req = _fake_request(client_host="11.0.0.1")
        with mock.patch.object(rate_limit_auth, "SIGNUP_LIMIT_PER_WINDOW", 3):
            rate_limit_auth.enforce_signup_rate_limit(req)
            rate_limit_auth.enforce_signup_rate_limit(req)
            rate_limit_auth.enforce_signup_rate_limit(req)
            with self.assertRaises(HTTPException) as ctx:
                rate_limit_auth.enforce_signup_rate_limit(req)
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertEqual(ctx.exception.detail["code"], "rate_limited")
            self.assertIn("Retry-After", ctx.exception.headers)

    def test_buckets_are_per_ip(self) -> None:
        req_a = _fake_request(client_host="12.0.0.1")
        req_b = _fake_request(client_host="12.0.0.2")
        with mock.patch.object(rate_limit_auth, "SIGNUP_LIMIT_PER_WINDOW", 1):
            rate_limit_auth.enforce_signup_rate_limit(req_a)
                                                             
            rate_limit_auth.enforce_signup_rate_limit(req_b)
                                      
            with self.assertRaises(HTTPException):
                rate_limit_auth.enforce_signup_rate_limit(req_a)


class LoginLimitTests(unittest.TestCase):


    def setUp(self) -> None:
        _reset_state()

    def tearDown(self) -> None:
        _reset_state()

    def test_allows_up_to_limit_then_blocks(self) -> None:
        req = _fake_request(client_host="13.0.0.1")
        with mock.patch.object(rate_limit_auth, "LOGIN_LIMIT_PER_WINDOW", 2):
            rate_limit_auth.enforce_login_rate_limit(req)
            rate_limit_auth.enforce_login_rate_limit(req)
            with self.assertRaises(HTTPException) as ctx:
                rate_limit_auth.enforce_login_rate_limit(req)
            self.assertEqual(ctx.exception.status_code, 429)

    def test_login_and_signup_buckets_are_separate(self) -> None:
                                                                    
                                                            
        req = _fake_request(client_host="14.0.0.1")
        with mock.patch.object(rate_limit_auth, "SIGNUP_LIMIT_PER_WINDOW", 1), \
             mock.patch.object(rate_limit_auth, "LOGIN_LIMIT_PER_WINDOW", 1):
            rate_limit_auth.enforce_signup_rate_limit(req)
            with self.assertRaises(HTTPException):
                rate_limit_auth.enforce_signup_rate_limit(req)
                                            
            rate_limit_auth.enforce_login_rate_limit(req)


class EnvIntClampTests(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_KEY", None)
            self.assertEqual(rate_limit_auth._env_int("TEST_KEY", 42), 42)

    def test_garbage_falls_back(self) -> None:
        with mock.patch.dict(os.environ, {"TEST_KEY": "not-a-number"}):
            self.assertEqual(rate_limit_auth._env_int("TEST_KEY", 42), 42)

    def test_clamped_to_bounds(self) -> None:
        with mock.patch.dict(os.environ, {"TEST_KEY": "0"}):
            self.assertEqual(rate_limit_auth._env_int("TEST_KEY", 5, lo=1, hi=10), 1)
        with mock.patch.dict(os.environ, {"TEST_KEY": "999"}):
            self.assertEqual(rate_limit_auth._env_int("TEST_KEY", 5, lo=1, hi=10), 10)


if __name__ == "__main__":
    unittest.main()
