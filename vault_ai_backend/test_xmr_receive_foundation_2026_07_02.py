

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock


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


_XMR_ENV_KEYS = (
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SEND_ENABLED",
    "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
)


XMR_MAINNET_DONATION_ADDR = (
    "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb"
    "98uNbr2VBBEt7f2wfn3RVGQBEP3A"
)


class XmrConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_xmr_disabled_by_default(self):
        from vault_config import monero_enabled
        self.assertFalse(monero_enabled())

    def test_xmr_send_disabled_by_default(self):
        from vault_config import monero_send_enabled
        self.assertFalse(monero_send_enabled())

    def test_xmr_scanner_mode_default_none(self):
        from vault_config import monero_scanner_mode
        self.assertEqual(monero_scanner_mode(), "none")

    def test_xmr_enabled_when_env_true(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from vault_config import monero_enabled
        self.assertTrue(monero_enabled())

    def test_xmr_scanner_mode_rejects_disallowed_values(self):
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = (
            "backend_view_only_opt_in"
        )
        from vault_config import monero_scanner_mode
        self.assertEqual(monero_scanner_mode(), "none")

    def test_xmr_scanner_mode_accepts_none(self):
        os.environ["VAULTAI_CRYPTO_XMR_SCANNER_MODE"] = "none"
        from vault_config import monero_scanner_mode
        self.assertEqual(monero_scanner_mode(), "none")


class MoneroAddressValidationTests(unittest.TestCase):

    def test_valid_mainnet_primary_address(self):
        from monero_address import (
            is_valid_monero_address,
            is_valid_monero_primary_or_subaddress,
        )
        self.assertTrue(
            is_valid_monero_address(XMR_MAINNET_DONATION_ADDR),
        )
        self.assertTrue(
            is_valid_monero_primary_or_subaddress(
                XMR_MAINNET_DONATION_ADDR,
            ),
        )

    def test_none_and_empty_rejected(self):
        from monero_address import is_valid_monero_address
        self.assertFalse(is_valid_monero_address(None))
        self.assertFalse(is_valid_monero_address(""))

    def test_ethereum_shape_rejected(self):
        from monero_address import is_valid_monero_address
        self.assertFalse(
            is_valid_monero_address("0x" + "a" * 40),
        )

    def test_bad_checksum_rejected(self):
        from monero_address import is_valid_monero_address
        broken = list(XMR_MAINNET_DONATION_ADDR)
        broken[-1] = "9" if broken[-1] != "9" else "A"
        self.assertFalse(is_valid_monero_address("".join(broken)))

    def test_wrong_length_rejected(self):
        from monero_address import is_valid_monero_address
        self.assertFalse(
            is_valid_monero_address(XMR_MAINNET_DONATION_ADDR[:-1]),
        )
        self.assertFalse(
            is_valid_monero_address(XMR_MAINNET_DONATION_ADDR + "X"),
        )

    def test_solana_address_shape_rejected(self):
        from monero_address import is_valid_monero_address
        self.assertFalse(
            is_valid_monero_address(
                "So11111111111111111111111111111111111111112",
            ),
        )

    def test_keccak256_hash_of_empty_matches_known_vector(self):
        from monero_address import _monero_keccak256
        self.assertEqual(
            _monero_keccak256(b"").hex(),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )

    def test_keccak256_hash_of_abc_matches_known_vector(self):
        from monero_address import _monero_keccak256
        self.assertEqual(
            _monero_keccak256(b"abc").hex(),
            "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
        )


class XmrPlaintextKeyAliasRejectionTests(unittest.TestCase):

    def _assert_rejects(self, field: str):
        from crypto_wallet_schemas import (
            PlaintextKeyRejected, rejects_plaintext_secret,
        )
        with self.assertRaises(PlaintextKeyRejected):
            rejects_plaintext_secret({
                "publicAddress": XMR_MAINNET_DONATION_ADDR,
                field: "beef" * 16,
            })

    def test_reject_spendKey(self):
        self._assert_rejects("spendKey")

    def test_reject_privateSpendKey(self):
        self._assert_rejects("privateSpendKey")

    def test_reject_secretSpendKey(self):
        self._assert_rejects("secretSpendKey")

    def test_reject_viewKey(self):
        self._assert_rejects("viewKey")

    def test_reject_privateViewKey(self):
        self._assert_rejects("privateViewKey")

    def test_reject_secretViewKey(self):
        self._assert_rejects("secretViewKey")

    def test_reject_moneroSpendKey(self):
        self._assert_rejects("moneroSpendKey")

    def test_reject_moneroViewKey(self):
        self._assert_rejects("moneroViewKey")

    def test_reject_polyseed(self):
        self._assert_rejects("polyseed")

    def test_reject_moneroSeed(self):
        self._assert_rejects("moneroSeed")

    def test_reject_seed25(self):
        self._assert_rejects("seed25")

    def test_reject_walletPassword(self):
        self._assert_rejects("walletPassword")

    def test_reject_mnemonic(self):
        self._assert_rejects("mnemonic")

    def test_reject_recoveryPhrase(self):
        self._assert_rejects("recoveryPhrase")


class XmrFeaturesEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_default_xmr_disabled(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["xmrEnabled"])
        self.assertFalse(env["xmrReceiveEnabled"])
        self.assertFalse(env["xmrBalanceEnabled"])
        self.assertFalse(env["xmrSendEnabled"])
        self.assertFalse(env["xmrActivityConnected"])
        self.assertEqual(env["xmrScannerMode"], "none")

    def test_features_xmr_enabled_flags(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["xmrEnabled"])
        self.assertTrue(env["xmrReceiveEnabled"])
        self.assertFalse(env["xmrBalanceEnabled"])
        self.assertFalse(env["xmrSendEnabled"])
        self.assertFalse(env["xmrActivityConnected"])

    def test_features_xmr_disabled_hides_network(self):
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertNotIn("monero_mainnet", env["supportedNetworks"])
        self.assertNotIn(
            "monero_mainnet", env["supportedAssetsByNetwork"],
        )

    def test_features_xmr_enabled_adds_network(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertIn("monero_mainnet", env["supportedNetworks"])
        self.assertEqual(
            env["supportedAssetsByNetwork"]["monero_mainnet"], ["XMR"],
        )

    def test_features_never_exposes_secrets(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        blob = repr(env).lower()
        for banned in ("spendkey", "viewkey", "seed",
                       "mnemonic", "recovery"):
            self.assertNotIn(banned, blob,
                             f"features leaked '{banned}'")


class XmrHealthEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_health_includes_monero_section(self):
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        self.assertIn("monero", env)
        xmr = env["monero"]
        self.assertEqual(xmr["id"], "monero_mainnet")
        self.assertFalse(xmr["xmrEnabled"])
        self.assertFalse(xmr["xmrSendEnabled"])
        self.assertFalse(xmr["xmrScannerReady"])
        self.assertFalse(xmr["xmrActivityConnected"])

    def test_health_xmr_flags_when_enabled(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from crypto_wallet_health import build_health_envelope
        env = build_health_envelope()
        xmr = env["monero"]
        self.assertTrue(xmr["xmrEnabled"])
        self.assertTrue(xmr["xmrReceiveReady"])
        self.assertEqual(xmr["xmrScannerMode"], "none")
        self.assertFalse(xmr["xmrScannerReady"])
        self.assertFalse(xmr["xmrSendEnabled"])


class XmrRouteBranchSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")

    def test_monero_network_constant_present(self):
        self.assertIn("NETWORK_MONERO_MAINNET", self._src)
        self.assertIn('"monero_mainnet"', self._src)

    def test_receive_branch_present(self):
        self.assertIn("_xmr_receive", self._src)
        self.assertIn(
            "if nid == NETWORK_MONERO_MAINNET:", self._src,
        )

    def test_balance_branch_present(self):
        self.assertIn("_xmr_balance", self._src)

    def test_transactions_branch_present(self):
        self.assertIn("_xmr_transactions", self._src)

    def test_create_branch_present(self):
        self.assertIn("_create_xmr_wallet_account", self._src)

    def test_send_disabled_envelope_used_for_xmr(self):
        self.assertIn("_xmr_send_not_enabled_envelope", self._src)

    def test_no_backend_signing_or_scanning_for_xmr(self):
        low = self._src.lower()
        self.assertNotIn("xmr_sign_transaction", low)
        self.assertNotIn("xmr_broadcast", low)
        self.assertNotIn("monero_sign", low)
        self.assertNotIn("wallet2.sign", low)
        self.assertNotIn("xmr_scan_", low)
        self.assertNotIn("monero_scan_", low)


class XmrRouteBehaviorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_receive_disabled_when_flag_off(self):
        from routes.crypto_wallet_routes import _xmr_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _xmr_receive("XMR", principal)
        self.assertEqual(
            result["wallet_engine"], "xmr_privacy_wallet_later",
        )
        self.assertEqual(result["network"], "monero_mainnet")

    def test_receive_no_wallet_prompts_create(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = _xmr_receive("XMR", principal)
        self.assertEqual(
            result["wallet_engine"], "create_xmr_wallet_first",
        )

    def test_receive_ready_returns_address_warning_privacy_note(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={
                "walletLabel":   "My Monero",
                "publicAddress": XMR_MAINNET_DONATION_ADDR,
                "restoreHeight": 3220000,
            },
        ):
            result = _xmr_receive("XMR", principal)
        self.assertEqual(result["wallet_engine"], "receive_ready")
        self.assertEqual(
            result["publicAddress"], XMR_MAINNET_DONATION_ADDR,
        )
        self.assertEqual(result["restoreHeight"], 3220000)
        self.assertIn("XMR on Monero", result["warning"])
        self.assertIn("scanning", result["privacyNote"].lower())
        self.assertNotIn("Ethereum", result["warning"])
        self.assertNotIn("Solana",   result["warning"])
        self.assertNotIn("TRON",     result["warning"])
        self.assertNotIn("Sepolia",  result["warning"])

    def test_balance_returns_scanner_not_enabled(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _xmr_balance("XMR", principal)
        self.assertEqual(result["balanceStatus"], "unavailable")
        self.assertEqual(result["reason"], "xmr_scanner_not_enabled")
        self.assertIsNone(result["availableAmount"])
        self.assertIsNone(result["unit"])

    def test_balance_never_returns_fake_zero(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_balance
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _xmr_balance("XMR", principal)
        self.assertNotEqual(result.get("availableAmount"), "0")
        self.assertNotEqual(result.get("availableAmount"), 0)
        self.assertNotEqual(result.get("availableAmount"), "0.0")

    def test_transactions_returns_scanner_not_enabled(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_transactions
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _xmr_transactions("XMR", 20, principal)
        self.assertEqual(result["transactionsStatus"], "unavailable")
        self.assertEqual(result["reason"], "xmr_scanner_not_enabled")
        self.assertEqual(result["transactions"], [])

    def test_transactions_never_returns_fake_row(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _xmr_transactions
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _xmr_transactions("XMR", 20, principal)
        self.assertEqual(len(result["transactions"]), 0)

    def test_send_draft_returns_not_enabled(self):
        from routes.crypto_wallet_routes import (
            _xmr_send_not_enabled_envelope,
        )
        result = _xmr_send_not_enabled_envelope("XMR")
        self.assertEqual(
            result["wallet_engine"], "xmr_send_not_enabled",
        )
        self.assertIn("not enabled", result["message"].lower())


class XmrCreateRouteTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _payload(self, **overrides):
        from routes.crypto_wallet_routes import CreateWalletPayload
        base = dict(
            walletLabel="My Monero",
            publicAddress=XMR_MAINNET_DONATION_ADDR,
            network="monero_mainnet",
            encryptedWalletSecret="ciphertext-here-xxxxx",
            restoreHeight=3220000,
            scannerMode="none",
        )
        base.update(overrides)
        return CreateWalletPayload(**base)

    def test_create_disabled_when_flag_off(self):
        from routes.crypto_wallet_routes import (
            _create_xmr_wallet_account,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _create_xmr_wallet_account(
            "XMR", self._payload(), principal,
        )
        self.assertEqual(
            result["wallet_engine"], "xmr_privacy_wallet_later",
        )

    def test_create_rejects_invalid_monero_address(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _create_xmr_wallet_account,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = self._payload(publicAddress="0x" + "a" * 40)
        with self.assertRaises(HTTPException) as ctx:
            _create_xmr_wallet_account("XMR", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_create_rejects_negative_restore_height(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from pydantic import ValidationError
        from routes.crypto_wallet_routes import CreateWalletPayload
        with self.assertRaises(ValidationError):
            CreateWalletPayload(
                walletLabel="My Monero",
                publicAddress=XMR_MAINNET_DONATION_ADDR,
                network="monero_mainnet",
                encryptedWalletSecret="ciphertext-here-xxxxx",
                restoreHeight=-1,
                scannerMode="none",
            )

    def test_create_rejects_disallowed_scanner_mode(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _create_xmr_wallet_account,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = self._payload(scannerMode="backend_view_only_opt_in")
        with self.assertRaises(HTTPException) as ctx:
            _create_xmr_wallet_account("XMR", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_create_stores_ciphertext_only(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from routes.crypto_wallet_routes import (
            _create_xmr_wallet_account,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        captured: dict[str, dict] = {}

        def _fake_insert(vault_id, asset, network_id, record):
            captured["record"] = record

        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_insert_wallet_account_record_network",
            side_effect=_fake_insert,
        ):
            result = _create_xmr_wallet_account(
                "XMR", self._payload(), principal,
            )
        self.assertEqual(result["wallet_engine"], "created")
        rec = captured["record"]
        self.assertEqual(rec["asset"], "XMR")
        self.assertEqual(rec["network"], "monero_mainnet")
        self.assertEqual(rec["restoreHeight"], 3220000)
        self.assertEqual(rec["scannerMode"], "none")
        self.assertEqual(rec["keyOrigin"], "generated_client_side")
        self.assertEqual(rec["signingMode"], "client_side")
        self.assertEqual(
            rec["encryptedWalletSecret"], "ciphertext-here-xxxxx",
        )
        blob = repr(rec).lower()
        for banned in ("spendkey", "viewkey", "seed",
                       "mnemonic", "polyseed"):
            self.assertNotIn(banned, blob,
                             f"record leaked '{banned}'")

    def test_create_extra_fields_forbidden(self):
        from pydantic import ValidationError
        from routes.crypto_wallet_routes import CreateWalletPayload
        with self.assertRaises(ValidationError):
            CreateWalletPayload(
                walletLabel="My Monero",
                publicAddress=XMR_MAINNET_DONATION_ADDR,
                network="monero_mainnet",
                encryptedWalletSecret="ct" * 10,
                restoreHeight=100,
                scannerMode="none",
                privateSpendKey="beef" * 16,
            )


class XmrChatIntentTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_show_monero_wallet_when_disabled_is_monero_special(self):
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "show my Monero wallet",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "XMR")
        self.assertEqual(parsed["intent"], "monero_special")

    def test_receive_xmr_when_enabled_routes_to_monero(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "give me my XMR receive address",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "XMR")
        self.assertEqual(parsed["network"], "monero_mainnet")
        self.assertEqual(parsed["intent"], "receive_address")

    def test_send_xmr_when_enabled_and_send_off_is_unsupported(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "send 1 XMR to abc",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "XMR")
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_monero_alias_detected_as_network(self):
        from wallet_engine_chat import _detect_network
        self.assertEqual(_detect_network("show my monero wallet"),
                         "monero_mainnet")
        self.assertEqual(_detect_network("XMR balance please"),
                         "monero_mainnet")


class XmrBackendLoggingSafetyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_XMR_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_create_log_line_does_not_leak_address_or_secret(self):
        import logging
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        captured: list[str] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = _Cap()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("crypto_wallet_routes")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            with mock.patch(
                "routes.crypto_wallet_routes."
                "_load_wallet_account_record_network",
                return_value=None,
            ), mock.patch(
                "routes.crypto_wallet_routes."
                "_insert_wallet_account_record_network",
                return_value=None,
            ):
                from routes.crypto_wallet_routes import (
                    _create_xmr_wallet_account, CreateWalletPayload,
                )
                principal = {
                    "vault_id":
                    "00000000-0000-0000-0000-000000000000",
                }
                _create_xmr_wallet_account(
                    "XMR",
                    CreateWalletPayload(
                        walletLabel="My Monero",
                        publicAddress=XMR_MAINNET_DONATION_ADDR,
                        network="monero_mainnet",
                        encryptedWalletSecret="ct-secret-xxxxxxxxxxx",
                        restoreHeight=3220000,
                        scannerMode="none",
                    ),
                    principal,
                )
        finally:
            logger.removeHandler(handler)
        joined = "\n".join(captured)
        for banned in (
            XMR_MAINNET_DONATION_ADDR,
            "ct-secret-xxxxxxxxxxx",
            "3220000",
        ):
            self.assertNotIn(banned, joined,
                             f"log leaked {banned!r}")


class XmrSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._routes_src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")
        self._addr_src = (
            _BACKEND_ROOT / "monero_address.py"
        ).read_text(encoding="utf-8")

    def test_no_hardcoded_fake_xmr_address(self):
        for fake in (
            '"4' + "A" * 94 + '"',
            '"4' + "1" * 94 + '"',
            '"4' + "Z" * 94 + '"',
        ):
            self.assertNotIn(fake, self._routes_src)

    def test_monero_address_module_has_no_signing_or_seed_helpers(self):
        low = self._addr_src.lower()
        self.assertNotIn("privatekey", low)
        self.assertNotIn("spendkey", low)
        self.assertNotIn("viewkey", low)
        self.assertNotIn("mnemonic", low)
        self.assertNotIn("seed_phrase", low)
        self.assertNotIn("polyseed", low)


class NoFakeXmrCopyOrExchangeCopyTests(unittest.TestCase):

    def test_routes_have_no_buy_sell_swap_trade_xmr(self):
        src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8").lower()
        for word in ["buy xmr", "sell xmr", "swap xmr",
                     "trade xmr", "stake xmr", "bridge xmr"]:
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
