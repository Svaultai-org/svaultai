


from __future__ import annotations

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


DART_GENERATED_ALL_ZEROS_ADDR = (
    '41fJjQDhryD11111111111111111111111111111111112N1GuTZeagfRbbKcALdc'
    'Zev4QXGGuoLh2x36LhaxLSxCc2YDhi'
)
DART_GENERATED_ALL_ONES_ADDR = (
    '49voQEbjouUQSDikRWKUt1PGbS47TBde4hiGyftN46CvTDd8LXCaimjHRGtofCJw'
    'Y5Ed5QhYwc12P15AH5w7SxUAMCz1nr1'
)
DART_GENERATED_ALL_AB_ADDR = (
    '46qNWGaUNT2jFiNwExbebhYmwgdHehTLiBVSXmaKvv9N88Kw8CeXTcTSFZjETMFk'
    'DNjmSTdv9B2JLGtQDBpdE847PF4VQLy'
)


class DartMoneroAddressesPassBackendValidationTests(unittest.TestCase):


    def test_all_zeros_seed_address_passes_backend(self):
        from monero_address import (
            is_valid_monero_address, is_valid_monero_primary_or_subaddress,
        )
        self.assertTrue(
            is_valid_monero_address(DART_GENERATED_ALL_ZEROS_ADDR),
        )
        self.assertTrue(
            is_valid_monero_primary_or_subaddress(
                DART_GENERATED_ALL_ZEROS_ADDR,
            ),
        )
        self.assertEqual(len(DART_GENERATED_ALL_ZEROS_ADDR), 95)
        self.assertEqual(DART_GENERATED_ALL_ZEROS_ADDR[0], '4')

    def test_all_ones_seed_address_passes_backend(self):
        from monero_address import is_valid_monero_address
        self.assertTrue(
            is_valid_monero_address(DART_GENERATED_ALL_ONES_ADDR),
        )

    def test_all_ab_seed_address_passes_backend(self):
        from monero_address import is_valid_monero_address
        self.assertTrue(
            is_valid_monero_address(DART_GENERATED_ALL_AB_ADDR),
        )


class BackendCreateRouteAcceptsGeneratedAddressTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
        )
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_create_payload_shape_is_ciphertext_only(self):
        from routes.crypto_wallet_routes import CreateWalletPayload
        payload = CreateWalletPayload(
            walletLabel='Monero',
            publicAddress=DART_GENERATED_ALL_ZEROS_ADDR,
            network='monero_mainnet',
            encryptedWalletSecret='vault-cipher-blob:xxxx',
            restoreHeight=3220000,
            scannerMode='none',
        )
        dumped = payload.model_dump()
        self.assertNotIn('mnemonic', dumped)
        self.assertNotIn('spendKey', dumped)
        self.assertNotIn('viewKey', dumped)
        self.assertNotIn('privateSpendKey', dumped)
        self.assertNotIn('privateViewKey', dumped)
        self.assertNotIn('walletPassword', dumped)
        self.assertNotIn('seed', dumped)
        self.assertEqual(dumped['scannerMode'], 'none')
        self.assertEqual(dumped['restoreHeight'], 3220000)
        self.assertEqual(dumped['encryptedWalletSecret'],
                         'vault-cipher-blob:xxxx')

    def test_create_payload_rejects_plaintext_alias_fields(self):
        from pydantic import ValidationError
        from routes.crypto_wallet_routes import CreateWalletPayload
        for alias in (
            'mnemonic', 'privateSpendKey', 'privateViewKey', 'spendKey',
            'viewKey', 'walletPassword', 'seed25', 'polyseed',
            'moneroSpendKey', 'moneroViewKey', 'moneroSeed',
            'recoveryPhrase',
        ):
            with self.assertRaises(
                ValidationError,
                msg=f'must reject plaintext alias {alias}',
            ):
                CreateWalletPayload(
                    walletLabel='Monero',
                    publicAddress=DART_GENERATED_ALL_ZEROS_ADDR,
                    network='monero_mainnet',
                    encryptedWalletSecret='ct',
                    restoreHeight=3220000,
                    scannerMode='none',
                    **{alias: 'FORBIDDEN'},
                )


class BackendMoneroSourceGuardsTests(unittest.TestCase):


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

    def test_no_backend_monero_key_generation_symbol(self):
        forbidden_symbols = [
            'def generate_monero_wallet',
            'def make_monero_wallet',
            'def create_monero_keypair',
            'def generate_xmr_keypair',
            'def scalarmult_base',
            'def ge_scalarmult_base',
            'def derive_monero_spend_key',
            'def derive_monero_view_key',
        ]
        for p in self._all_backend_source():
            try:
                src = p.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for sym in forbidden_symbols:
                self.assertNotIn(
                    sym, src,
                    f'{p.name} must not contain {sym!r} — '
                    'wallet generation is client-side only',
                )

    def test_no_backend_monero_signing_symbol(self):
        forbidden_symbols = [
            'def sign_monero_transaction',
            'def sign_xmr_transaction',
            'def monero_sign_tx',
            'def build_monero_ring_signature',
        ]
        for p in self._all_backend_source():
            try:
                src = p.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for sym in forbidden_symbols:
                self.assertNotIn(
                    sym, src,
                    f'{p.name} must not contain {sym!r} — '
                    'signing is client-side only',
                )

    def test_no_backend_monero_scanner_symbol(self):
        forbidden_symbols = [
            'def monero_scan_chain',
            'def xmr_scan_transactions',
            'def scan_monero_outputs',
            'def build_monero_view_only_scanner',
        ]
        for p in self._all_backend_source():
            try:
                src = p.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for sym in forbidden_symbols:
                self.assertNotIn(
                    sym, src,
                    f'{p.name} must not contain {sym!r} — '
                    'scanning is deferred to a future slice',
                )


class XmrBalanceActivitySendStillHonestTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(
            'VAULTAI_CRYPTO_XMR_ENABLED', 'VAULTAI_CRYPTO_XMR_SCANNER_MODE',
            'VAULTAI_CRYPTO_XMR_SEND_ENABLED',
        )
        os.environ['VAULTAI_CRYPTO_XMR_ENABLED'] = 'true'
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_xmr_balance_still_returns_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_balance
        out = _xmr_balance('XMR', {'vault_id': 'v'})
        self.assertEqual(out['balanceStatus'], 'unavailable')
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')
        self.assertIsNone(out['availableAmount'])

    def test_xmr_transactions_still_returns_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_transactions
        out = _xmr_transactions('XMR', 10, {'vault_id': 'v'})
        self.assertEqual(out['transactionsStatus'], 'unavailable')
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')
        self.assertEqual(out['transactions'], [])

    def test_xmr_send_disabled_envelope_still_shipped(self):
        from routes.crypto_wallet_routes import _xmr_send_not_enabled_envelope
        env = _xmr_send_not_enabled_envelope('XMR')
        self.assertIn('wallet_engine', env)
        self.assertEqual(env['wallet_engine'], 'xmr_send_not_enabled')


if __name__ == '__main__':
    unittest.main()
