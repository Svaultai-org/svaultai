


from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


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


class FeaturesEnvelopeExposesScannerFlagsTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
        )
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_scanner_flags_present_when_xmr_off(self):
        from crypto_wallet_health import build_features_envelope
        body = build_features_envelope()
        self.assertIn("xmrClientScannerSupported", body)
        self.assertIn("xmrBackendScannerEnabled", body)
        self.assertFalse(body["xmrClientScannerSupported"])
        self.assertFalse(body["xmrBackendScannerEnabled"])

    def test_scanner_flags_stay_false_when_xmr_on(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_health import build_features_envelope
        body = build_features_envelope()
        self.assertFalse(body["xmrClientScannerSupported"])
        self.assertFalse(body["xmrBackendScannerEnabled"])
        self.assertEqual(body["xmrScannerMode"], "none")

    def test_features_envelope_reveals_no_key_material(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_health import build_features_envelope
        blob = json.dumps(build_features_envelope())
        for banned in (
            "privateSpendKey", "privateViewKey", "spendKey", "viewKey",
            "mnemonic", "seed25", "polyseed", "walletPassword",
        ):
            self.assertNotIn(banned, blob)


class DiagnosisEnvelopeExposesScannerFlagsTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
        )
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_diagnosis_xmr_row_has_client_scanner_flags(self):
        from crypto_wallet_diagnosis import (
            ROW_MONERO_MAINNET_XMR, build_diagnosis_envelope,
        )
        env = build_diagnosis_envelope()
        row = next(r for r in env["assets"] if r["rowId"] == ROW_MONERO_MAINNET_XMR)
        self.assertIn("xmrClientScannerSupported", row)
        self.assertIn("xmrBackendScannerEnabled", row)
        self.assertIn("xmrBalanceReason", row)
        self.assertFalse(row["xmrClientScannerSupported"])
        self.assertFalse(row["xmrBackendScannerEnabled"])

    def test_diagnosis_xmr_balance_reason_is_client_required_when_on(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import (
            ROW_MONERO_MAINNET_XMR, build_diagnosis_envelope,
        )
        env = build_diagnosis_envelope()
        row = next(r for r in env["assets"] if r["rowId"] == ROW_MONERO_MAINNET_XMR)
        self.assertEqual(row["xmrBalanceReason"], "xmr_scanner_client_required")

    def test_diagnosis_envelope_reveals_no_key_material(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        blob = json.dumps(build_diagnosis_envelope())
        for banned in (
            "privateSpendKey", "privateViewKey", "spendKey", "viewKey",
            "mnemonic", "seed25", "polyseed",
        ):
            self.assertNotIn(banned, blob)


class BackendMoneroScannerSourceGuardTests(unittest.TestCase):


    def _all_backend_source(self) -> list[Path]:
        py_files: list[Path] = []
        for p in _BACKEND_ROOT.rglob('*.py'):
            parts = set(p.parts)
            if any(seg.startswith('.') for seg in p.parts):
                continue
            if 'node_modules' in parts or '__pycache__' in parts:
                continue
            if p.name.startswith('test_'):
                continue
            py_files.append(p)
        return py_files

    def test_no_monero_scanner_library_imports(self):
        forbidden_imports = [
            'import monero_wallet',
            'import monero_scanner',
            'from monero_wallet',
            'from monero_scanner',
            'import wallet2',
            'from wallet2',
            'import monero_serai',
            'from monero_serai',
            'import xmrpy',
            'from xmrpy',
        ]
        for p in self._all_backend_source():
            try:
                src = p.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for imp in forbidden_imports:
                self.assertNotIn(
                    imp, src,
                    f'{p.name} must not import scanner libraries via {imp!r}',
                )

    def test_no_backend_monero_scanning_symbols(self):
        forbidden_symbols = [
            'def scan_monero_blocks',
            'def scan_monero_outputs',
            'def xmr_scan_transactions',
            'def build_view_only_scanner',
            'def derive_output_secret',
            'def monero_check_output',
        ]
        for p in self._all_backend_source():
            try:
                src = p.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for sym in forbidden_symbols:
                self.assertNotIn(
                    sym, src,
                    f'{p.name} must not contain scanner symbol {sym!r}',
                )


class BackendXmrBalanceActivityStillHonestTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(
            'VAULTAI_CRYPTO_XMR_ENABLED',
            'VAULTAI_CRYPTO_XMR_SCANNER_MODE',
        )
        os.environ['VAULTAI_CRYPTO_XMR_ENABLED'] = 'true'
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_backend_xmr_balance_still_returns_xmr_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_balance
        out = _xmr_balance('XMR', {'vault_id': 'v'})
        self.assertEqual(out['balanceStatus'], 'unavailable')
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')
        self.assertIsNone(out['availableAmount'])

    def test_backend_xmr_transactions_still_returns_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_transactions
        out = _xmr_transactions('XMR', 10, {'vault_id': 'v'})
        self.assertEqual(out['transactionsStatus'], 'unavailable')
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')
        self.assertEqual(out['transactions'], [])


class BackendCreateXmrPayloadStillRejectsScannerKeyMaterialTests(unittest.TestCase):


    def test_create_payload_rejects_view_and_spend_keys_via_scanner_alias(self):
        from pydantic import ValidationError
        from routes.crypto_wallet_routes import CreateWalletPayload
        for alias in (
            'privateSpendKey', 'privateViewKey', 'spendKey', 'viewKey',
            'moneroSpendKey', 'moneroViewKey', 'walletPassword',
            'secretSpendKey', 'secretViewKey',
        ):
            with self.assertRaises(
                ValidationError,
                msg=f'must reject scanner-slice plaintext alias {alias}',
            ):
                CreateWalletPayload(
                    walletLabel='Monero',
                    publicAddress=(
                        '41fJjQDhryD11111111111111111111111111111111112N1G'
                        'uTZeagfRbbKcALdcZev4QXGGuoLh2x36LhaxLSxCc2YDhi'
                    ),
                    network='monero_mainnet',
                    encryptedWalletSecret='ct',
                    restoreHeight=3220000,
                    scannerMode='none',
                    **{alias: 'FORBIDDEN'},
                )


if __name__ == '__main__':
    unittest.main()
