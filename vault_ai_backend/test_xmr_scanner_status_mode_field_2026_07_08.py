"""Backend endpoint now echoes the scanner mode + logs it — verifies
the field is present, closed-set, and safe.
"""

from __future__ import annotations

import io
import logging
import os
import unittest

from fastapi.testclient import TestClient


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

    def _client(self):
        return TestClient(self._app)


class ResponseEnvelopeCarriesMode(_BaseTest):


    def test_default_disabled_envelope_carries_mode_none(self):
        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["mode"], "none")


    def test_client_local_native_envelope_carries_mode_client_local(
        self,
    ):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()
        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "native"},
        ).json()
        self.assertEqual(body["mode"], "client_local")
        self.assertEqual(body["reason"], "local_scanner_available")


    def test_client_local_web_envelope_carries_mode_client_local(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()
        body = self._client().get(
            _XMR_SCANNER_STATUS_PATH, params={"platform": "web"},
        ).json()

        self.assertEqual(body["mode"], "client_local")
        self.assertEqual(body["reason"], "scanner_requires_desktop")


    def test_mode_is_closed_set(self):
        for env_val, expected in [
            (None,                    "none"),
            ("none",                  "none"),
            ("client_local",          "client_local"),
            ("server_view_only",      "server_view_only"),
            ("garbage_mode",          "none"),
        ]:
            os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
            if env_val is None:
                os.environ.pop("VAULTAI_CRYPTO_XMR_SCANNER_MODE", None)
            else:
                os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = env_val
            import vault_config; vault_config.reset_for_tests()
            body = self._client().get(
                _XMR_SCANNER_STATUS_PATH, params={"platform": "native"},
            ).json()
            self.assertEqual(
                body["mode"], expected,
                f"env {env_val!r} → mode {body['mode']!r}, "
                f"expected {expected!r}",
            )


class LogLineCarriesMode(_BaseTest):


    def _capture_log(self, platform_value):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
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
            self._client().get(
                _XMR_SCANNER_STATUS_PATH,
                params={"platform": platform_value},
            )
            handler.flush()
            return stream.getvalue()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_log_line_includes_mode_field(self):
        log = self._capture_log("web")
        low = log.lower()
        self.assertIn("mode=client_local", low)
        self.assertIn("client_platform=web", low)
        self.assertIn("reason=scanner_requires_desktop", low)


    def test_log_line_still_carries_no_secret_material(self):
        log = self._capture_log("native")
        low = log.lower()
        for banned in (
            "seed=", "mnemonic=",
            "spend_key=", "view_key=",
            "privateviewkey", "privatespendkey",
            "encryptedwalletsecret", "encrypted_secret",
            "authorization", "bearer",
            "txhash=", "tx_hash=",
        ):
            self.assertNotIn(banned, low,
                f"log line leaks {banned!r}")


if __name__ == "__main__":
    unittest.main()
