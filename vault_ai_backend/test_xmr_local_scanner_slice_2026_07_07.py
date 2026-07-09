"""Local-client Monero scanner slice — backend side.

Verifies:
 - scanner_mode="client_local" maps to configured / local_scanner_available
 - the LocalScannerAvailableMoneroScannerAdapter never accepts or
   returns a private view key, spend key, seed, or mnemonic
 - canSend remains false in every code path
 - safe log line does not leak scanner URL / API key / auth token
 - backend does NOT ship a real Monero scanner library
"""

from __future__ import annotations

import inspect
import io
import logging
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).parent


def _wipe_env(*names):
    snap = {n: os.environ.get(n) for n in names}
    for n in names:
        os.environ.pop(n, None)
    return snap


def _restore_env(snap):
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_MONERO_ENV_KEYS = (
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
    "VAULTAI_CRYPTO_XMR_SCANNER_URL",
)


_XMR_SCANNER_STATUS_PATH = "/crypto/wallet/xmr/scanner/status"


class _BaseXmrRouteTest(unittest.TestCase):

    def setUp(self):
        from main import app
        from device_gate import verify_trusted_device
        self._app = app
        self._dep_key = verify_trusted_device
        self._prior_override = app.dependency_overrides.get(
            verify_trusted_device,
        )
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id": "test-vault-uuid",
            "account_id": "test-account",
        }
        self._snap = _wipe_env(*_MONERO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self):
        if self._prior_override is None:
            self._app.dependency_overrides.pop(self._dep_key, None)
        else:
            self._app.dependency_overrides[self._dep_key] = (
                self._prior_override
            )
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def _client(self) -> TestClient:
        return TestClient(self._app)


class ClientLocalScannerModeRoutingTests(_BaseXmrRouteTest):


    def test_client_local_mode_reports_configured_local_available(
        self,
    ):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["scannerStatus"], "configured")
        self.assertEqual(body["reason"], "local_scanner_available")


    def test_client_local_mode_still_reports_can_send_false(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertFalse(body["canSend"])
        self.assertFalse(body["canShowBalance"])
        self.assertFalse(body["canShowActivity"])


    def test_client_local_mode_does_not_require_scanner_url(self):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        os.environ.pop("VAULTAI_CRYPTO_XMR_SCANNER_URL", None)
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["scannerStatus"], "configured")


class LocalScannerAvailableAdapterTests(unittest.TestCase):


    def test_get_balance_returns_unavailable_because_backend_cannot_scan(
        self,
    ):

        from xmr_scanner import LocalScannerAvailableMoneroScannerAdapter
        b = LocalScannerAvailableMoneroScannerAdapter().get_balance(
            "4placeholder_address",
        )
        self.assertEqual(b["balanceStatus"], "unavailable")
        self.assertIsNone(b["availableAmount"],
            "backend MUST NOT return a numeric XMR balance — only "
            "the client can compute one")
        self.assertEqual(b["reason"], "local_scanner_available")


    def test_get_activity_returns_empty_because_backend_cannot_scan(
        self,
    ):
        from xmr_scanner import LocalScannerAvailableMoneroScannerAdapter
        a = LocalScannerAvailableMoneroScannerAdapter().get_activity(
            "4placeholder_address",
        )
        self.assertEqual(a["transactionsStatus"], "unavailable")
        self.assertEqual(a["transactions"], [])
        self.assertEqual(a["reason"], "local_scanner_available")


    def test_get_status_returns_can_send_false(self):
        from xmr_scanner import LocalScannerAvailableMoneroScannerAdapter
        s = LocalScannerAvailableMoneroScannerAdapter().get_status()
        self.assertFalse(s["canSend"])
        self.assertFalse(s["canShowBalance"])
        self.assertFalse(s["canShowActivity"])


    def test_get_balance_accepts_only_public_address_argument(self):

        from xmr_scanner import (
            LocalScannerAvailableMoneroScannerAdapter,
            MoneroScannerAdapter,
        )
        for cls in (
            LocalScannerAvailableMoneroScannerAdapter,
            MoneroScannerAdapter,
        ):
            sig = inspect.signature(cls.get_balance)
            params = list(sig.parameters)
            self.assertEqual(
                params, ["self", "public_address"],
                f"{cls.__name__}.get_balance must accept ONLY the "
                f"public address — not a view key, spend key, seed, "
                f"or mnemonic",
            )


class ClosedSetReasonTests(unittest.TestCase):


    def test_local_scanner_available_is_in_the_allowed_reason_set(
        self,
    ):
        from xmr_scanner import (
            REASON_LOCAL_SCANNER_AVAILABLE,
            _ALLOWED_SCANNER_REASON,
        )
        self.assertIn(
            REASON_LOCAL_SCANNER_AVAILABLE, _ALLOWED_SCANNER_REASON,
        )
        self.assertEqual(
            REASON_LOCAL_SCANNER_AVAILABLE, "local_scanner_available",
        )


    def test_status_envelope_builder_accepts_local_available_reason(
        self,
    ):
        from xmr_scanner import (
            _build_status_envelope,
            SCANNER_STATUS_CONFIGURED,
            REASON_LOCAL_SCANNER_AVAILABLE,
        )
        env = _build_status_envelope(
            SCANNER_STATUS_CONFIGURED,
            REASON_LOCAL_SCANNER_AVAILABLE,
        )
        self.assertEqual(env["scannerStatus"], "configured")
        self.assertEqual(env["reason"], "local_scanner_available")


class ClientLocalNoScannerLibraryImportsTests(unittest.TestCase):


    def test_backend_does_not_import_any_real_monero_scanner_library(
        self,
    ):

        src = (_BACKEND_ROOT / "xmr_scanner.py").read_text(
            encoding="utf-8",
        )
        for banned in (
            "import wallet2",
            "from wallet2",
            "import monero_serai",
            "from monero_serai",
            "import monero_lws",
            "from monero_lws",
            "import xmrpy",
        ):
            self.assertNotIn(banned, src)


class ClientLocalRouteSafetyTests(_BaseXmrRouteTest):


    _SECRET_URL = "https://placeholder-secret-scanner.internal/probe"


    def _capture_route_log(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"

        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_URL"] = self._SECRET_URL
        import vault_config; vault_config.reset_for_tests()

        logger = logging.getLogger("crypto_wallet_routes")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        original_level = logger.level
        original_disabled = logger.disabled
        logger.disabled = False
        logger.setLevel(logging.INFO)
        try:
            body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
            handler.flush()
            return stream.getvalue(), body
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_client_local_response_body_never_leaks_secrets(self):
        _, body = self._capture_route_log()
        blob = str(body).lower()

        for banned in (
            "placeholder-secret-scanner",
            self._SECRET_URL.lower(),
            "spend_key", "view_key",
            "mnemonic", "seed",
            "encryptedwalletsecret", "encrypted_secret",
            "authorization", "bearer",
            "txhash", "tx_hash", "txid",
        ):
            self.assertNotIn(banned, blob,
                f"response body leaks {banned!r}")


    def test_client_local_log_line_only_carries_closed_set_fields(self):
        log_out, _ = self._capture_route_log()

        low = log_out.lower()
        self.assertIn("xmr_scanner_status_check", low)
        self.assertIn("scanner_status=configured", low)
        self.assertIn("reason=local_scanner_available", low)
        self.assertIn("can_send=false", low)


        self.assertNotIn("placeholder-secret-scanner", low)
        self.assertNotIn(self._SECRET_URL.lower(), low)


if __name__ == "__main__":
    unittest.main()
