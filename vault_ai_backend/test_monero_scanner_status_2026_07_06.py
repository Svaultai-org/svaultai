"""Monero scanner-status endpoint + adapter safety.

Part F backend tests. Covers:
 - default XMR scanner status is disabled/scanner_not_enabled
 - closed-set scannerStatus/reason enums, always canSend=false
 - env-driven adapter selection (none, client_local, server_view_only)
 - safety: no seed/mnemonic/spend key/view key/encrypted secret/wallet
   address/scanner URL/auth token/raw scanner body in response or log
 - no fake zero balance from disabled/not-configured adapters
"""

from __future__ import annotations

import io
import logging
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).parent


def _wipe_env(*names: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore_env(snap: dict[str, str | None]) -> None:
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


class _BaseXmrScannerRouteTest(unittest.TestCase):


    def setUp(self) -> None:
        from main import app
        from device_gate import verify_trusted_device
        self._app = app
        self._dep_key = verify_trusted_device
        self._prior_override = app.dependency_overrides.get(
            verify_trusted_device,
        )
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id": "test-vault-uuid", "account_id": "test-account",
        }
        self._snap = _wipe_env(*_MONERO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
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


class ScannerStatusDefaultDisabledTests(_BaseXmrScannerRouteTest):


    def test_default_response_is_disabled_scanner_not_enabled(self):
        c = self._client()
        resp = c.get(_XMR_SCANNER_STATUS_PATH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["asset"], "XMR")
        self.assertEqual(body["scannerStatus"], "disabled")
        self.assertEqual(body["reason"], "scanner_not_enabled")
        self.assertFalse(body["canShowBalance"])
        self.assertFalse(body["canShowActivity"])
        self.assertFalse(body["canSend"])


    def test_response_carries_schema_field(self):
        c = self._client()
        body = c.get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["schema"], "monero_scanner_status_v1")


    def test_endpoint_requires_verify_trusted_device(self):
        from device_gate import verify_trusted_device


        self._app.dependency_overrides.pop(self._dep_key, None)
        try:
            c = self._client()
            resp = c.get(_XMR_SCANNER_STATUS_PATH)
            self.assertNotEqual(
                resp.status_code, 200,
                "endpoint must require device trust — no anonymous "
                "access",
            )
        finally:
            self._app.dependency_overrides[self._dep_key] = lambda: {
                "vault_id": "test-vault-uuid",
                "account_id": "test-account",
            }


class ScannerStatusModeDrivenTests(_BaseXmrScannerRouteTest):


    def test_mode_none_still_reports_disabled_even_when_enabled(self):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "none"
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["scannerStatus"], "disabled")
        self.assertEqual(body["reason"], "scanner_not_enabled")


    def test_mode_client_local_reports_configured_local_available(
        self,
    ):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "client_local"
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()


        self.assertEqual(body["scannerStatus"], "configured")
        self.assertEqual(body["reason"], "local_scanner_available")


        self.assertFalse(body["canShowBalance"])
        self.assertFalse(body["canShowActivity"])
        self.assertFalse(body["canSend"])


    def test_mode_server_view_only_with_no_url_reports_not_configured(
        self,
    ):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "server_view_only"

        os.environ.pop("VAULTAI_CRYPTO_XMR_SCANNER_URL", None)
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
        self.assertEqual(body["scannerStatus"], "not_configured")
        self.assertEqual(body["reason"], "scanner_not_configured")


    def test_mode_server_view_only_with_url_reports_view_key_missing(
        self,
    ):

        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"]      = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "server_view_only"
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_URL"]  = (
            "http://placeholder-scanner-url.example/internal"
        )
        import vault_config; vault_config.reset_for_tests()

        body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()

        self.assertEqual(body["scannerStatus"], "configured")
        self.assertEqual(body["reason"], "view_key_not_available")


class ScannerAdapterUnitTests(unittest.TestCase):


    def test_disabled_adapter_returns_no_balance_and_no_activity(self):
        from xmr_scanner import DisabledMoneroScannerAdapter
        a = DisabledMoneroScannerAdapter()
        b = a.get_balance("4placeholder_addr")
        self.assertEqual(b["balanceStatus"], "unavailable")
        self.assertIsNone(b["availableAmount"],
            "MUST NOT fake 0 XMR when scanner disabled")
        self.assertIsNone(b["unit"])
        self.assertEqual(b["reason"], "scanner_not_enabled")

        ac = a.get_activity("4placeholder_addr")
        self.assertEqual(ac["transactionsStatus"], "unavailable")
        self.assertEqual(ac["transactions"], [],
            "empty list means no data — never faked")
        self.assertEqual(ac["reason"], "scanner_not_enabled")


    def test_not_configured_adapter_never_fakes_zero(self):
        from xmr_scanner import NotConfiguredMoneroScannerAdapter
        a = NotConfiguredMoneroScannerAdapter()
        b = a.get_balance("4placeholder")
        self.assertEqual(b["balanceStatus"], "unavailable")
        self.assertIsNone(b["availableAmount"])
        self.assertEqual(b["reason"], "scanner_not_configured")


    def test_ready_adapter_still_refuses_to_invent_balance(self):

        from xmr_scanner import ReadyMoneroScannerAdapter
        a = ReadyMoneroScannerAdapter()
        b = a.get_balance("4placeholder")
        self.assertEqual(b["balanceStatus"], "unavailable")
        self.assertIsNone(b["availableAmount"])
        self.assertEqual(b["reason"], "scanner_ready")


    def test_syncing_adapter_reports_syncing_not_ready(self):
        from xmr_scanner import SyncingMoneroScannerAdapter
        s = SyncingMoneroScannerAdapter().get_status()
        self.assertEqual(s["scannerStatus"], "syncing")
        self.assertEqual(s["reason"], "scanner_syncing")


    def test_unreachable_adapter_reports_error(self):
        from xmr_scanner import UnreachableMoneroScannerAdapter
        s = UnreachableMoneroScannerAdapter().get_status()
        self.assertEqual(s["scannerStatus"], "error")
        self.assertEqual(s["reason"], "scanner_unreachable")


    def test_view_key_missing_adapter_reports_view_key_not_available(
        self,
    ):
        from xmr_scanner import ViewKeyMissingMoneroScannerAdapter
        s = ViewKeyMissingMoneroScannerAdapter().get_status()
        self.assertEqual(s["scannerStatus"], "configured")
        self.assertEqual(s["reason"], "view_key_not_available")


    def test_every_adapter_returns_can_send_false_in_this_slice(self):
        from xmr_scanner import (
            DisabledMoneroScannerAdapter,
            NotConfiguredMoneroScannerAdapter,
            ViewKeyMissingMoneroScannerAdapter,
            SyncingMoneroScannerAdapter,
            UnreachableMoneroScannerAdapter,
            ReadyMoneroScannerAdapter,
        )
        for cls in (
            DisabledMoneroScannerAdapter,
            NotConfiguredMoneroScannerAdapter,
            ViewKeyMissingMoneroScannerAdapter,
            SyncingMoneroScannerAdapter,
            UnreachableMoneroScannerAdapter,
            ReadyMoneroScannerAdapter,
        ):
            self.assertFalse(
                cls().get_status()["canSend"],
                f"{cls.__name__} must set canSend=false in this slice "
                f"— backend never signs XMR",
            )


class ScannerAdapterInterfaceContractTests(unittest.TestCase):


    def test_abstract_get_balance_accepts_only_public_address(self):

        import inspect
        from xmr_scanner import MoneroScannerAdapter
        sig = inspect.signature(MoneroScannerAdapter.get_balance)
        params = list(sig.parameters)
        self.assertEqual(params, ["self", "public_address"],
            "get_balance must accept ONLY the public wallet address "
            "— never a seed, view key, spend key, or encrypted secret.")


    def test_abstract_get_activity_accepts_only_public_address_and_limit(
        self,
    ):
        import inspect
        from xmr_scanner import MoneroScannerAdapter
        sig = inspect.signature(MoneroScannerAdapter.get_activity)
        params = list(sig.parameters)
        self.assertEqual(params, ["self", "public_address", "limit"])


    def test_module_source_never_references_forbidden_secret_names(self):

        src = (_BACKEND_ROOT / "xmr_scanner.py").read_text(
            encoding="utf-8",
        ).lower()


        for forbidden in (
            "seed_hex", "mnemonic_words", "spend_key_hex",
            "private_view_key", "view_key_hex",
            "encrypted_wallet_secret",
            "wallet_secret",
            "raw_scanner_body",
            "tx_hash", "txid",
        ):
            self.assertNotIn(forbidden, src,
                f"xmr_scanner.py refers to {forbidden!r} — this "
                f"module must never accept or handle that value.")


class ScannerStatusResponseSafetyTests(_BaseXmrScannerRouteTest):


    _SECRET_URL     = "https://placeholder-secret-scanner.internal/probe"


    def _capture_log_for_call(self, mode_env: str | None = None,
                              scanner_url_env: str | None = None) -> str:
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        if mode_env is not None:
            os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = mode_env
        if scanner_url_env is not None:
            os.environ["VAULTAI_CRYPTO_XMR_SCANNER_URL"] = scanner_url_env
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


    def test_response_body_never_leaks_scanner_url(self):

        _, body = self._capture_log_for_call(
            mode_env="server_view_only",
            scanner_url_env=self._SECRET_URL,
        )
        as_text = str(body).lower()
        self.assertNotIn("placeholder-secret-scanner", as_text)
        self.assertNotIn(self._SECRET_URL.lower(), as_text)


    def test_response_body_never_contains_key_material_fields(self):

        _, body = self._capture_log_for_call(
            mode_env="server_view_only",
            scanner_url_env=self._SECRET_URL,
        )
        for banned in (
            "seed", "mnemonic",
            "spendKey", "viewKey",
            "spend_key", "view_key",
            "privateSpendKey", "privateViewKey",
            "publicAddress", "walletAddress",
            "encryptedWalletSecret", "encrypted_secret",
            "authToken", "auth_token",
            "scannerUrl", "scanner_url",
            "rawBody", "raw_body",
            "txHash", "tx_hash",
        ):
            self.assertNotIn(banned, body,
                f"response leaks {banned!r} — must not be in body")


    def test_log_line_only_carries_closed_set_enums_and_booleans(self):

        log_out, _ = self._capture_log_for_call(
            mode_env="server_view_only",
            scanner_url_env=self._SECRET_URL,
        )

        self.assertIn("xmr_scanner_status_check", log_out)


        low = log_out.lower()


        self.assertNotIn("placeholder-secret-scanner", low)
        self.assertNotIn(self._SECRET_URL.lower(), low)


        without_reason = low.replace(
            "reason=view_key_not_available", "reason=<reason>",
        )
        for banned in (
            "seed", "mnemonic",
            "spend_key=", "view_key=",
            "privateviewkey", "privatespendkey",
            "encryptedwalletsecret", "encrypted_secret",
            "authorization", "bearer",
            "txhash=", "tx_hash=", "txid=",
            "walletaddress=", "publicaddress=",
            "view_key_value", "spend_key_value",
        ):
            self.assertNotIn(banned, without_reason,
                f"log line leaks {banned!r}")


    def test_log_line_carries_only_expected_status_and_boolean_fields(
        self,
    ):

        log_out, _ = self._capture_log_for_call()

        self.assertIn("scanner_status=disabled", log_out)
        self.assertIn("reason=scanner_not_enabled", log_out)
        self.assertIn("can_show_balance=false", log_out)
        self.assertIn("can_show_activity=false", log_out)
        self.assertIn("can_send=false", log_out)


class ClosedSetSchemaTests(_BaseXmrScannerRouteTest):

    _ALLOWED_STATUSES = {
        "disabled", "not_configured", "configured",
        "syncing", "ready", "error",
    }
    _ALLOWED_REASONS = {
        "scanner_not_enabled", "scanner_not_configured",
        "view_key_not_available", "scanner_unreachable",
        "scanner_syncing", "scanner_ready", "scanner_error",
        "local_scanner_available",
    }


    def test_status_and_reason_are_from_the_closed_sets(self):

        cases = [
            (None,               None),
            ("none",             None),
            ("client_local",     None),
            ("server_view_only", None),
            ("server_view_only", "https://ok.example/scanner"),
        ]
        for mode, url in cases:
            for k in _MONERO_ENV_KEYS:
                os.environ.pop(k, None)
            if mode is not None:
                os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
                os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = mode
            if url is not None:
                os.environ["VAULTAI_CRYPTO_XMR_SCANNER_URL"] = url
            import vault_config; vault_config.reset_for_tests()

            body = self._client().get(_XMR_SCANNER_STATUS_PATH).json()
            self.assertIn(body["scannerStatus"], self._ALLOWED_STATUSES,
                f"mode={mode!r} url={url!r} → status "
                f"{body['scannerStatus']!r} outside closed set")
            self.assertIn(body["reason"], self._ALLOWED_REASONS,
                f"mode={mode!r} url={url!r} → reason "
                f"{body['reason']!r} outside closed set")


if __name__ == "__main__":
    unittest.main()
