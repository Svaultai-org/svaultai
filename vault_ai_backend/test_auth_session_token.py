

from __future__ import annotations

import os
import unittest
from unittest import mock

import auth_local


class TokenCodecTests(unittest.TestCase):


    def setUp(self) -> None:
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        auth_local.reset_secret_for_tests()

    def tearDown(self) -> None:
        os.environ.pop("VAULT_SESSION_SECRET", None)
        auth_local.reset_secret_for_tests()

    def test_format_then_parse_roundtrips(self) -> None:
        token_id_bytes = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff"
        token = auth_local._format_token(token_id_bytes)
        parsed = auth_local._parse_token(token)
        self.assertEqual(parsed, token_id_bytes)

    def test_parse_rejects_wrong_length(self) -> None:
                                                                           
        self.assertIsNone(auth_local._parse_token(""))
        self.assertIsNone(auth_local._parse_token("AAA"))
        self.assertIsNone(auth_local._parse_token("a" * 200))

    def test_parse_rejects_garbage(self) -> None:
        self.assertIsNone(auth_local._parse_token("!!! not base64 !!!"))
        self.assertIsNone(auth_local._parse_token(None))                          
        self.assertIsNone(auth_local._parse_token(12345))                          

    def test_parse_rejects_tampered_signature(self) -> None:
        token_id_bytes = b"\x01" * 16
        token = auth_local._format_token(token_id_bytes)
                                                                       
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertIsNone(auth_local._parse_token(tampered))

    def test_parse_rejects_different_secret(self) -> None:
        token_id_bytes = b"\x02" * 16
        token = auth_local._format_token(token_id_bytes)

                                                                      
        os.environ["VAULT_SESSION_SECRET"] = "y" * 48
        auth_local.reset_secret_for_tests()
        self.assertIsNone(auth_local._parse_token(token))


class SecretLoadingTests(unittest.TestCase):


    def setUp(self) -> None:
                                                                        
        for key in (
            "VAULT_SESSION_SECRET",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            os.environ.pop(key, None)
        auth_local.reset_secret_for_tests()

    def tearDown(self) -> None:
        for key in (
            "VAULT_SESSION_SECRET",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        ):
            os.environ.pop(key, None)
        auth_local.reset_secret_for_tests()

    def test_env_secret_wins(self) -> None:
        os.environ["VAULT_SESSION_SECRET"] = "z" * 48
        secret = auth_local._get_secret()
        self.assertEqual(secret, b"z" * 48)

    def test_short_secret_is_refused(self) -> None:
        os.environ["VAULT_SESSION_SECRET"] = "short"
        with self.assertRaises(RuntimeError):
            auth_local._get_secret()

    def test_dev_also_refuses_when_secret_unset(self) -> None:


        os.environ["VAULTAI_ENV"] = "dev"
        with self.assertRaises(RuntimeError) as ctx:
            auth_local._get_secret()
        self.assertIn("VAULT_SESSION_SECRET", str(ctx.exception))

    def test_dev_error_message_explains_no_fallback(self) -> None:


        os.environ["VAULTAI_ENV"] = "dev"
        try:
            auth_local._get_secret()
        except RuntimeError as exc:
            msg = str(exc)
            self.assertIn("no built-in fallback", msg.lower())
            self.assertIn(".env", msg)
            self.assertIn("VAULT_SESSION_SECRET", msg)
        else:
            self.fail("expected RuntimeError")

    def test_prod_refuses_without_secret(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        with self.assertRaises(RuntimeError):
            auth_local._get_secret()

    def test_returned_secret_is_never_legacy_fallback(self) -> None:


        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        secret = auth_local._get_secret()
        self.assertNotIn(b"do-not-ship", secret)
        self.assertNotIn(b"dev-only-fallback", secret)


class ProductionDetectionTests(unittest.TestCase):


    def setUp(self) -> None:
        for key in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
            os.environ.pop(key, None)

    def test_no_signal_is_not_production(self) -> None:
        self.assertFalse(auth_local._is_production())

    def test_each_hook_marks_production(self) -> None:
        for key in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
            for value in ("prod", "production", "live"):
                with self.subTest(key=key, value=value):
                    os.environ.clear()
                    os.environ[key] = value
                    self.assertTrue(auth_local._is_production())

    def test_unrelated_value_is_not_production(self) -> None:
        os.environ["VAULTAI_ENV"] = "staging"
        self.assertFalse(auth_local._is_production())


class SessionTtlClampTests(unittest.TestCase):


    def test_default_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULT_SESSION_TTL_HOURS", None)
            self.assertEqual(
                auth_local._read_ttl_hours(),
                auth_local.SESSION_TTL_HOURS_DEFAULT,
            )

    def test_garbage_falls_back(self) -> None:
        with mock.patch.dict(os.environ, {"VAULT_SESSION_TTL_HOURS": "abc"}):
            self.assertEqual(
                auth_local._read_ttl_hours(),
                auth_local.SESSION_TTL_HOURS_DEFAULT,
            )

    def test_too_small_is_clamped(self) -> None:
        with mock.patch.dict(os.environ, {"VAULT_SESSION_TTL_HOURS": "0"}):
            self.assertEqual(
                auth_local._read_ttl_hours(),
                auth_local.SESSION_TTL_HOURS_MIN,
            )

    def test_too_big_is_clamped(self) -> None:
        with mock.patch.dict(os.environ, {"VAULT_SESSION_TTL_HOURS": "100000"}):
            self.assertEqual(
                auth_local._read_ttl_hours(),
                auth_local.SESSION_TTL_HOURS_MAX,
            )


if __name__ == "__main__":
    unittest.main()
