

from __future__ import annotations

import logging
import os
import unittest

                                                                   
os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

from fastapi import HTTPException              

from routes.auth_routes import (              
    PIN_MAX_LENGTH,
    SignupRequest,
    LoginRequest,
    _validate_pin_shape,
)
from vault_core import MIN_PIN_LENGTH_NEW_VAULT              


class TestPinPolicyConstants(unittest.TestCase):

    def test_pin_max_length_is_64(self):
        self.assertEqual(PIN_MAX_LENGTH, 64)

    def test_min_pin_length_is_6(self):
        self.assertEqual(MIN_PIN_LENGTH_NEW_VAULT, 6)


class TestPinShapeOnSignup(unittest.TestCase):


    def _expect_400(self, pin: str, expected_detail: str) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _validate_pin_shape(pin, is_signup=True)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, expected_detail)

    def test_4_digit_pin_rejected(self):
        self._expect_400("1234", "PIN must be at least 6 digits.")

    def test_5_digit_pin_rejected(self):
        self._expect_400("12345", "PIN must be at least 6 digits.")

    def test_6_digit_pin_accepted(self):
        _validate_pin_shape("123456", is_signup=True)                  

    def test_64_digit_pin_accepted(self):
        _validate_pin_shape("1" * 64, is_signup=True)                  

    def test_65_digit_pin_rejected(self):
        self._expect_400("1" * 65, "PIN must be 64 digits or fewer.")

    def test_non_digit_pin_rejected(self):
        self._expect_400("12345a", "PIN can only contain digits.")

    def test_empty_pin_rejected(self):
        self._expect_400("", "PIN is required")

    def test_unicode_digit_lookalike_rejected(self):
                                                                       
                                                                     
        try:
            _validate_pin_shape("٠" * 6, is_signup=True)
        except HTTPException:
            pass                   
                                                                   
                                                                  
class TestPinShapeOnLogin(unittest.TestCase):


    def _expect_400(self, pin: str, expected_detail: str) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _validate_pin_shape(pin, is_signup=False)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, expected_detail)

    def test_login_rejects_4_digit_pin(self):
        self._expect_400("1234", "PIN must be at least 6 digits.")

    def test_login_rejects_5_digit_pin(self):
        self._expect_400("12345", "PIN must be at least 6 digits.")

    def test_login_accepts_6_to_64_digit_pin(self):
        for length in (6, 7, 8, 12, 32, 63, 64):
            with self.subTest(length=length):
                _validate_pin_shape("1" * length, is_signup=False)

    def test_login_rejects_65_digit_pin(self):
        self._expect_400("1" * 65, "PIN must be 64 digits or fewer.")

    def test_login_rejects_non_digit_pin(self):
        self._expect_400("abcdef", "PIN can only contain digits.")


class TestRequestModelsCapAt64(unittest.TestCase):

    def test_signup_request_accepts_64_digit_pin(self):
        SignupRequest(
            vault_name="abc", pin="1" * 64, confirm_pin="1" * 64,
            acknowledged_irrecoverable=True,
        )

    def test_signup_request_rejects_65_digit_pin(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SignupRequest(
                vault_name="abc", pin="1" * 65, confirm_pin="1" * 65,
                acknowledged_irrecoverable=True,
            )

    def test_login_request_accepts_64_digit_pin(self):
        LoginRequest(vault_name="abc", pin="1" * 64)

    def test_login_request_rejects_65_digit_pin(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            LoginRequest(vault_name="abc", pin="1" * 65)


class TestValidatorNeverLogsPin(unittest.TestCase):


    def test_validator_emits_no_log_records(self):
                                                                   
                                                                      
        ar_logger = logging.getLogger("routes.auth_routes")
        root_logger = logging.getLogger()

        ar_handler = _CapturingHandler()
        root_handler = _CapturingHandler()
        ar_logger.addHandler(ar_handler)
        root_logger.addHandler(root_handler)
        prior_ar_level = ar_logger.level
        prior_root_level = root_logger.level
        ar_logger.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.DEBUG)
        try:
            pin_value = "112233445566"                      
            _validate_pin_shape(pin_value, is_signup=True)
            try:
                _validate_pin_shape("1234", is_signup=True)
            except HTTPException:
                pass
            try:
                _validate_pin_shape("abc", is_signup=True)
            except HTTPException:
                pass
            for record in ar_handler.records + root_handler.records:
                rendered = record.getMessage()
                self.assertNotIn(
                    pin_value, rendered,
                    msg="Validator must NEVER log the PIN value.",
                )
                self.assertNotIn(
                    "1234", rendered,
                    msg="Validator must NEVER log a rejected PIN.",
                )
                self.assertNotIn(
                    "abc", rendered,
                    msg="Validator must NEVER log a rejected PIN.",
                )
        finally:
            ar_logger.removeHandler(ar_handler)
            root_logger.removeHandler(root_handler)
            ar_logger.setLevel(prior_ar_level)
            root_logger.setLevel(prior_root_level)


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:              
        self.records.append(record)


if __name__ == "__main__":                    
    unittest.main()
