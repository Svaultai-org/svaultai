"""Web-platform gate for local Monero scanner — backend side.

Verifies:
 - GET /crypto/wallet/xmr/scanner/status honors ?platform=web|native|unknown
 - client_local + web  → configured / scanner_requires_desktop
 - client_local + native  → configured / local_scanner_available
 - unknown / garbage platform coerces to unknown → local_scanner_available
 - canSend stays false in every code path
 - the endpoint never accepts or logs a private view/spend key, seed,
   mnemonic, encrypted secret, or the raw platform value if it's junk
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


class _BaseTest(unittest.TestCase):

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

    def _enable_client_local(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()

    def _client(self) -> TestClient:
        return TestClient(self._app)


class PlatformRoutingTests(_BaseTest):


    def test_platform_web_reports_scanner_requires_desktop(self):
        self._enable_client_local()
        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "web"},
        ).json()
        self.assertEqual(body["scannerStatus"], "configured")
        self.assertEqual(body["reason"], "scanner_requires_desktop")
        self.assertFalse(body["canShowBalance"])
        self.assertFalse(body["canShowActivity"])
        self.assertFalse(body["canSend"])


    def test_platform_native_reports_local_scanner_available(self):
        self._enable_client_local()
        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "native"},
        ).json()
        self.assertEqual(body["scannerStatus"], "configured")
        self.assertEqual(body["reason"], "local_scanner_available")


    def test_platform_unknown_reports_local_scanner_available(self):
        self._enable_client_local()
        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "unknown"},
        ).json()

        self.assertEqual(body["reason"], "local_scanner_available")


    def test_no_platform_query_defaults_to_local_scanner_available(
        self,
    ):
        self._enable_client_local()
        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()

        self.assertEqual(body["reason"], "local_scanner_available")


    def test_garbage_platform_is_coerced_to_unknown(self):
        self._enable_client_local()

        for junk in ("android-6", "'; DROP TABLE users; --",
                     "web/../etc/passwd", " WEB "):
            body = self._client().get(
                _XMR_SCANNER_STATUS_PATH,
                params={"platform": junk},
            ).json()
            self.assertIn(body["reason"], (
                "local_scanner_available",
                "scanner_requires_desktop",
            ), f"junk platform {junk!r} produced illegal reason "
               f"{body['reason']!r}")

            self.assertEqual(body["canSend"], False)


    def test_platform_query_does_not_upgrade_disabled_mode(self):

        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "native"},
        ).json()
        self.assertEqual(body["scannerStatus"], "disabled")
        self.assertEqual(body["reason"], "scanner_not_enabled")


class RequiresDesktopAdapterUnitTests(unittest.TestCase):


    def test_get_balance_returns_unavailable_never_zero(self):
        from xmr_scanner import (
            RequiresDesktopMoneroScannerAdapter,
        )
        b = RequiresDesktopMoneroScannerAdapter().get_balance(
            "4placeholder_address",
        )
        self.assertEqual(b["balanceStatus"], "unavailable")
        self.assertIsNone(b["availableAmount"],
            "web build MUST NOT fabricate a zero XMR balance")
        self.assertEqual(b["reason"], "scanner_requires_desktop")


    def test_get_activity_returns_empty_never_synthesised(self):
        from xmr_scanner import (
            RequiresDesktopMoneroScannerAdapter,
        )
        a = RequiresDesktopMoneroScannerAdapter().get_activity(
            "4placeholder_address",
        )
        self.assertEqual(a["transactionsStatus"], "unavailable")
        self.assertEqual(a["transactions"], [])
        self.assertEqual(a["reason"], "scanner_requires_desktop")


    def test_can_send_is_false_in_status(self):
        from xmr_scanner import (
            RequiresDesktopMoneroScannerAdapter,
        )
        s = RequiresDesktopMoneroScannerAdapter().get_status()
        self.assertFalse(s["canSend"])
        self.assertFalse(s["canShowBalance"])
        self.assertFalse(s["canShowActivity"])


    def test_get_balance_accepts_only_public_address(self):

        import inspect
        from xmr_scanner import RequiresDesktopMoneroScannerAdapter
        sig = inspect.signature(
            RequiresDesktopMoneroScannerAdapter.get_balance,
        )
        params = list(sig.parameters)
        self.assertEqual(
            params, ["self", "public_address"],
            "web-gate adapter must not accept a view key or seed",
        )


class ClosedSetTests(unittest.TestCase):


    def test_scanner_requires_desktop_is_in_allowed_reason_set(self):
        from xmr_scanner import (
            REASON_SCANNER_REQUIRES_DESKTOP,
            _ALLOWED_SCANNER_REASON,
        )
        self.assertEqual(
            REASON_SCANNER_REQUIRES_DESKTOP,
            "scanner_requires_desktop",
        )
        self.assertIn(
            REASON_SCANNER_REQUIRES_DESKTOP, _ALLOWED_SCANNER_REASON,
        )


    def test_client_platform_closed_set(self):
        from xmr_scanner import (
            CLIENT_PLATFORM_WEB,
            CLIENT_PLATFORM_NATIVE,
            CLIENT_PLATFORM_UNKNOWN,
            _ALLOWED_CLIENT_PLATFORM,
            _normalize_client_platform,
        )
        self.assertEqual(CLIENT_PLATFORM_WEB, "web")
        self.assertEqual(CLIENT_PLATFORM_NATIVE, "native")
        self.assertEqual(CLIENT_PLATFORM_UNKNOWN, "unknown")
        self.assertEqual(_normalize_client_platform(None), "unknown")
        self.assertEqual(_normalize_client_platform(""), "unknown")
        self.assertEqual(_normalize_client_platform("web"), "web")
        self.assertEqual(_normalize_client_platform("WEB"), "web")
        self.assertEqual(_normalize_client_platform(" native "),
                         "native")
        self.assertEqual(_normalize_client_platform("garbage"),
                         "unknown")


class RequiresDesktopSafetyTests(_BaseTest):


    def _capture_log(self, platform_value):
        self._enable_client_local()

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
            body = self._client().get(
                _XMR_SCANNER_STATUS_PATH,
                params={"platform": platform_value},
            ).json()
            handler.flush()
            return stream.getvalue(), body
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_web_platform_log_line_carries_normalized_enum_only(self):
        log, _ = self._capture_log("web")
        low = log.lower()
        self.assertIn("client_platform=web", low)
        self.assertIn("reason=scanner_requires_desktop", low)


    def test_junk_platform_is_normalized_to_unknown_before_logging(
        self,
    ):

        junk = "'; DROP TABLE users; --"
        log, _ = self._capture_log(junk)
        low = log.lower()
        self.assertIn("client_platform=unknown", low)
        self.assertNotIn("drop table", low)
        self.assertNotIn("';", low)


    def test_response_body_never_contains_key_material_fields(self):
        _, body = self._capture_log("web")
        for banned in (
            "seed", "mnemonic",
            "spendKey", "viewKey",
            "spend_key", "view_key",
            "privateSpendKey", "privateViewKey",
            "publicAddress", "walletAddress",
            "encryptedWalletSecret", "encrypted_secret",
            "authToken", "auth_token",
        ):
            self.assertNotIn(banned, body,
                f"response leaks {banned!r}")


class ExistingClosedSetInvariantsPreserved(_BaseTest):


    def test_default_disabled_still_reports_scanner_not_enabled(self):
        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["scannerStatus"], "disabled")
        self.assertEqual(body["reason"], "scanner_not_enabled")


    def test_none_mode_ignores_platform_hint(self):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "none"
        import vault_config; vault_config.reset_for_tests()
        for platform in ("web", "native", "unknown"):
            body = self._client().get(
                _XMR_SCANNER_STATUS_PATH,
                params={"platform": platform},
            ).json()
            self.assertEqual(body["reason"], "scanner_not_enabled",
                f"platform {platform} accidentally activated a scanner")


if __name__ == "__main__":
    unittest.main()
