

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient


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


class WalletEngineFeatureFlagTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env("VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED")
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_flag_defaults_to_true(self) -> None:
                                                                 
                                                                
        from vault_config import crypto_wallet_engine_enabled
        self.assertTrue(crypto_wallet_engine_enabled())

    def test_flag_honors_env_true(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from vault_config import crypto_wallet_engine_enabled
        self.assertTrue(crypto_wallet_engine_enabled())

    def test_flag_honors_env_false(self) -> None:
                                                             
                                                               
        for v in ("false", "0", "no", "off"):
            os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = v
            import vault_config
            vault_config.reset_for_tests()
            from vault_config import crypto_wallet_engine_enabled
            self.assertFalse(
                crypto_wallet_engine_enabled(),
                f"env value {v!r} must drive the flag off",
            )


class WalletEngineRouteRegistrationTests(unittest.TestCase):


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
                                                                   
                                                                     
        self._snap = _wipe_env("VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED")
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "false"
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

    def test_all_routes_registered(self) -> None:
                                                                    
                                                                    
        contracted = {
            "/crypto/wallet/assets":                 "GET",
            "/crypto/wallet/accounts":               "GET",
            "/crypto/wallet/{asset}/create":         "POST",
            "/crypto/wallet/{asset}":                "GET",
            "/crypto/wallet/{asset}/balance":        "GET",
            "/crypto/wallet/{asset}/transactions":   "GET",
            "/crypto/wallet/{asset}/receive":        "GET",
            "/crypto/wallet/{asset}/send/draft":     "POST",
            "/crypto/wallet/{asset}/send/broadcast": "POST",
        }
        routes = {r.path: r for r in self._app.routes}
        for path, method in contracted.items():
            self.assertIn(path, routes, f"missing route: {method} {path}")
            self.assertIn(method, routes[path].methods)

    def _client(self) -> TestClient:
        return TestClient(self._app)

    def test_flag_off_disabled_envelope_assets(self) -> None:
        c = self._client()
        if True:
            resp = c.get("/crypto/wallet/assets")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["wallet_engine"], "disabled")
                                                                    
                                                         
            assets = body["assets"]
            self.assertEqual(len(assets), 8)
            asset_ids = {a["asset"] for a in assets}
            self.assertIn("ETH", asset_ids)
            self.assertIn("XMR", asset_ids)

    def test_flag_off_disabled_envelope_accounts(self) -> None:
        c = self._client()
        if True:
            resp = c.get("/crypto/wallet/accounts")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["wallet_engine"], "engine_disabled")
            self.assertEqual(body["accounts"], [])

    def test_flag_off_disabled_envelope_balance(self) -> None:
        c = self._client()
        if True:
            for asset in ("ETH", "BTC", "XMR", "WAT"):
                resp = c.get(f"/crypto/wallet/{asset}/balance")
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["wallet_engine"], "engine_disabled")
                                                                 
                                                           
                self.assertNotIn("availableAmount", body)
                self.assertNotIn("balance", body)

    def test_flag_off_disabled_envelope_receive(self) -> None:
        c = self._client()
        if True:
            for asset in ("ETH", "BTC"):
                resp = c.get(f"/crypto/wallet/{asset}/receive")
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["wallet_engine"], "engine_disabled")
                                     
                self.assertNotIn("publicAddress", body)
                self.assertNotIn("address", body)

    def test_flag_off_disabled_envelope_transactions(self) -> None:
        c = self._client()
        if True:
            resp = c.get("/crypto/wallet/ETH/transactions")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["wallet_engine"], "engine_disabled")
                            
            self.assertEqual(body["transactions"], [])


class WalletEngineDisabledEnvelopeTests(unittest.TestCase):


    def test_default_envelope(self) -> None:
        from crypto_wallet_schemas import engine_disabled_envelope
        body = engine_disabled_envelope()
        self.assertEqual(body["wallet_engine"], "engine_disabled")
        # 2026-07-12: dropped the stale "Crypto Vault Lite remains
        # available" fragment; the message now points users at Crypto
        # Vault and its supported assets.
        self.assertIn("Crypto Wallet Engine is not enabled", body["message"])
        self.assertNotIn("Crypto Vault Lite", body["message"])

    def test_unsupported_asset_envelope(self) -> None:
        from crypto_wallet_schemas import (
            engine_disabled_envelope, ENGINE_STATUS_UNSUPPORTED,
        )
        body = engine_disabled_envelope(status=ENGINE_STATUS_UNSUPPORTED)
        self.assertEqual(body["wallet_engine"], "unsupported_asset")

    def test_not_ready_envelope(self) -> None:
        from crypto_wallet_schemas import (
            engine_disabled_envelope, ENGINE_STATUS_NOT_READY,
        )
        body = engine_disabled_envelope(status=ENGINE_STATUS_NOT_READY)
        self.assertEqual(body["wallet_engine"], "engine_not_ready")

    def test_unknown_status_falls_back_to_disabled(self) -> None:
        from crypto_wallet_schemas import engine_disabled_envelope
        body = engine_disabled_envelope(status="garbage")
        self.assertEqual(body["wallet_engine"], "engine_disabled")


class PlaintextKeyRejectionTests(unittest.TestCase):


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

    def tearDown(self) -> None:
        if self._prior_override is None:
            self._app.dependency_overrides.pop(self._dep_key, None)
        else:
            self._app.dependency_overrides[self._dep_key] = (
                self._prior_override
            )

    def _client(self) -> TestClient:
        return TestClient(self._app)

    def test_unit_detector_catches_every_alias(self) -> None:
                                                               
        from crypto_wallet_schemas import (
            PLAINTEXT_KEY_FIELD_NAMES, is_plaintext_key_field,
        )
        for field in PLAINTEXT_KEY_FIELD_NAMES:
            self.assertTrue(
                is_plaintext_key_field(field),
                f"{field!r} must be flagged",
            )

    def test_unit_detector_catches_case_variants(self) -> None:
        from crypto_wallet_schemas import is_plaintext_key_field
        for v in ("privateKey", "private_key", "Private-Key",
                  "PRIVATEKEY", "Priv_Key", "SeedPhrase",
                  "RECOVERY-PHRASE", "Mnemonic", "X_PRV"):
            self.assertTrue(
                is_plaintext_key_field(v),
                f"{v!r} must be flagged after normalization",
            )

    def test_unit_detector_does_not_flag_normal_fields(self) -> None:
        from crypto_wallet_schemas import is_plaintext_key_field
        for v in ("publicAddress", "walletLabel", "amount",
                  "network", "asset", "signedTransaction",
                  "encryptedWalletSecret"):
            self.assertFalse(
                is_plaintext_key_field(v),
                f"{v!r} must NOT be flagged",
            )

    def test_unit_finder_walks_nested_payloads(self) -> None:
        from crypto_wallet_schemas import find_plaintext_key_fields
        payload = {
            "asset": "ETH",
            "details": {
                "wallet": {"privateKey": "0xdead"},
            },
            "history": [
                {"label": "ok"},
                {"seed_phrase": "twelve words..."},
            ],
        }
        bad = find_plaintext_key_fields(payload)
        self.assertIn("privateKey", bad)
        self.assertIn("seed_phrase", bad)

    def test_create_route_rejects_plaintext_private_key(self) -> None:
                                                                    
                                                                   
        c = self._client()
        if True:
            resp = c.post(
                "/crypto/wallet/ETH/create",
                json={
                    "walletLabel": "x", "publicAddress": "0xabc",
                    "network": "Ethereum Sepolia",
                    "encryptedWalletSecret": "ct",
                    "privateKey": "0xdeadbeef",
                },
            )
                                                                 
                                                               
            self.assertEqual(resp.status_code, 422)

    def test_send_draft_route_rejects_plaintext_private_key(self) -> None:
        c = self._client()
        if True:
            resp = c.post(
                "/crypto/wallet/ETH/send/draft",
                json={
                    "fromAddress": "0xabc", "toAddress": "0xdef",
                    "amount": "0.1",
                    "seedPhrase": "twelve words ...",
                },
            )
            self.assertEqual(resp.status_code, 422)

    def test_broadcast_route_rejects_plaintext_private_key(self) -> None:
                                                                    
                                 
        c = self._client()
        if True:
            resp = c.post(
                "/crypto/wallet/ETH/send/broadcast",
                json={
                    "signedTransaction": "0xfeedface",
                    "mnemonic": "twelve words again",
                },
            )
            self.assertEqual(resp.status_code, 422)

    def test_broadcast_route_rejects_extra_fields_even_without_keys(self) -> None:
                                                                   
                                                         
        c = self._client()
        if True:
            resp = c.post(
                "/crypto/wallet/ETH/send/broadcast",
                json={
                    "signedTransaction": "0xfeedface",
                    "fromAddress": "0xabc",
                },
            )
            self.assertEqual(resp.status_code, 422)


class NoFakeStateSourceScanTests(unittest.TestCase):


    def test_routes_module_has_no_hex_address(self) -> None:
        import io
        from pathlib import Path
        path = Path(__file__).resolve().parent / "routes" / "crypto_wallet_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
                                                                
                                                     
        import re
        addrs = re.findall(r"0x[0-9a-fA-F]{16,}", src)
        self.assertEqual(
            addrs, [],
            f"crypto_wallet_routes.py must not contain "
            f"address-shaped hex strings: {addrs}",
        )

    def test_routes_module_has_no_numeric_balance_literal(self) -> None:
                                                                
                                                                 
        import io, re
        from pathlib import Path
        path = Path(__file__).resolve().parent / "routes" / "crypto_wallet_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
        for unit in ("ETH", "BTC", "SOL", "BNB", "USDT", "USDC", "XMR"):
            matches = re.findall(rf'"\d+\.?\d*\s*{unit}"', src)
            self.assertEqual(
                matches, [],
                f"crypto_wallet_routes.py must not contain "
                f"numeric balance literal for {unit}: {matches}",
            )


class WalletEngineSchemaBuilderTests(unittest.TestCase):


    def test_account_builder_refuses_backend_signing_mode(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_account_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_account_record(
                asset="ETH",
                network="Ethereum Sepolia",
                wallet_label="x",
                public_address="0xabc",
                encrypted_wallet_secret="ct",
                signing_mode="server_side",             
            )

    def test_account_builder_refuses_unknown_key_origin(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_account_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_account_record(
                asset="ETH",
                network="Ethereum Sepolia",
                wallet_label="x",
                public_address="0xabc",
                encrypted_wallet_secret="ct",
                key_origin="generated_server_side",             
            )

    def test_account_builder_happy_path(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_account_record,
            SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
            KEY_ORIGIN_GENERATED_CLIENT_SIDE,
            SIGNING_MODE_CLIENT_SIDE,
            BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
        )
        rec = build_wallet_account_record(
            asset="ETH",
            network="Ethereum Sepolia",
            wallet_label="VaultAI ETH wallet",
            public_address="0xabc",
            encrypted_wallet_secret="ct",
        )
        self.assertEqual(rec["schema"], SCHEMA_CRYPTO_WALLET_ACCOUNT_V1)
        self.assertEqual(rec["keyOrigin"], KEY_ORIGIN_GENERATED_CLIENT_SIDE)
        self.assertEqual(rec["signingMode"], SIGNING_MODE_CLIENT_SIDE)
        self.assertEqual(
            rec["backupStatus"], BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
        )

    def test_balance_builder_refuses_amount_without_available(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_balance_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_balance_record(
                asset="ETH", network="x", public_address="0xabc",
                balance_status="unavailable",
                available_amount="0.1",                                  
                unit="ETH",
            )

    def test_balance_builder_refuses_unknown_status(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_balance_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_balance_record(
                asset="ETH", network="x", public_address="0xabc",
                balance_status="estimated",             
            )

    def test_transaction_builder_refuses_unknown_direction(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_transaction_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_transaction_record(
                asset="ETH", network="x", public_address="0xabc",
                tx_hash="0xfeed", direction="lateral",             
                amount="0.1", unit="ETH", status="confirmed",
            )

    def test_transaction_builder_refuses_negative_confirmations(self) -> None:
        from crypto_wallet_schemas import (
            build_wallet_transaction_record, WalletEngineSchemaError,
        )
        with self.assertRaises(WalletEngineSchemaError):
            build_wallet_transaction_record(
                asset="ETH", network="x", public_address="0xabc",
                tx_hash="0xfeed", direction="outgoing",
                amount="0.1", unit="ETH", status="pending",
                confirmations=-1,
            )


class WalletEngineChatParserTests(unittest.TestCase):

    def test_show_balance_intent(self) -> None:
        from wallet_engine_chat import (
            detect_wallet_engine_intent,
            INTENT_WALLET_ENGINE_SHOW_BALANCE,
        )
        out = detect_wallet_engine_intent("show my ETH balance")
        self.assertEqual(out["intent"], INTENT_WALLET_ENGINE_SHOW_BALANCE)
        self.assertEqual(out["asset"], "ETH")

    def test_show_receive_intent(self) -> None:
        from wallet_engine_chat import (
            detect_wallet_engine_intent,
            INTENT_WALLET_ENGINE_SHOW_RECEIVE,
            INTENT_WALLET_ENGINE_SHOW_QR,
        )
        out = detect_wallet_engine_intent("give me my ETH receive address")
        self.assertEqual(out["intent"], INTENT_WALLET_ENGINE_SHOW_RECEIVE)
        self.assertEqual(out["asset"], "ETH")
        out_qr = detect_wallet_engine_intent("show my ETH QR code")
        self.assertEqual(out_qr["intent"], INTENT_WALLET_ENGINE_SHOW_QR)

    def test_show_wallet_intent(self) -> None:
        from wallet_engine_chat import (
            detect_wallet_engine_intent,
            INTENT_WALLET_ENGINE_SHOW_WALLET,
        )
        out = detect_wallet_engine_intent("show my crypto wallet")
        self.assertEqual(out["intent"], INTENT_WALLET_ENGINE_SHOW_WALLET)

    def test_send_intent(self) -> None:
        from wallet_engine_chat import (
            detect_wallet_engine_intent,
            INTENT_WALLET_ENGINE_SEND_DRAFT,
        )
        out = detect_wallet_engine_intent(
            "send 0.01 ETH to 0xabcdef1234567890",
        )
        self.assertEqual(out["intent"], INTENT_WALLET_ENGINE_SEND_DRAFT)
        self.assertEqual(out["asset"], "ETH")

    def test_create_wallet_intent(self) -> None:
        from wallet_engine_chat import (
            detect_wallet_engine_intent,
            INTENT_WALLET_ENGINE_CREATE_WALLET,
        )
        out = detect_wallet_engine_intent("create an ETH wallet")
        self.assertEqual(out["intent"], INTENT_WALLET_ENGINE_CREATE_WALLET)

    def test_unrelated_message_returns_none(self) -> None:
        from wallet_engine_chat import detect_wallet_engine_intent
        self.assertIsNone(detect_wallet_engine_intent("what's the weather?"))
        self.assertIsNone(detect_wallet_engine_intent(""))
        self.assertIsNone(detect_wallet_engine_intent(None))

    def test_parser_does_not_echo_message(self) -> None:
                                                            
                                                             
        from wallet_engine_chat import detect_wallet_engine_intent
        msg = "send 0.01 ETH to 0xverysecretdestination please"
        out = detect_wallet_engine_intent(msg)
        flat = str(out).lower()
        self.assertNotIn("0xverysecretdestination", flat)
        self.assertNotIn("0.01", flat)
        self.assertNotIn("please", flat)


class WalletEngineChatComposerTests(unittest.TestCase):

    def test_send_response_pinned_copy(self) -> None:
                                                               
                                                                
        from wallet_engine_chat import (
            INTENT_WALLET_ENGINE_SEND_DRAFT,
            CHAT_MESSAGE_SEND_NOT_READY,
            compose_chat_response,
        )
        out = compose_chat_response(
            intent=INTENT_WALLET_ENGINE_SEND_DRAFT,
            asset="ETH", engine_enabled=True,
        )
        self.assertEqual(out["message"], CHAT_MESSAGE_SEND_NOT_READY)
        self.assertEqual(out["status"], "engine_not_ready")
        self.assertIn("VaultAI never sends from one message", out["message"])
        self.assertIn("require your PIN", out["message"])

    def test_send_response_when_flag_off(self) -> None:
        from wallet_engine_chat import (
            INTENT_WALLET_ENGINE_SEND_DRAFT,
            CHAT_MESSAGE_ENGINE_DISABLED,
            compose_chat_response,
        )
        out = compose_chat_response(
            intent=INTENT_WALLET_ENGINE_SEND_DRAFT,
            asset="ETH", engine_enabled=False,
        )
        self.assertEqual(out["status"], "engine_disabled")
        self.assertEqual(out["message"], CHAT_MESSAGE_ENGINE_DISABLED)

    def test_monero_response_uses_special_copy(self) -> None:
        from wallet_engine_chat import (
            INTENT_WALLET_ENGINE_SHOW_BALANCE,
            CHAT_MESSAGE_MONERO_SPECIAL,
            compose_chat_response,
        )
        out = compose_chat_response(
            intent=INTENT_WALLET_ENGINE_SHOW_BALANCE,
            asset="XMR", engine_enabled=True,
        )
        self.assertEqual(out["status"], "unsupported_asset")
        self.assertEqual(out["message"], CHAT_MESSAGE_MONERO_SPECIAL)

    def test_response_never_includes_user_secret_substrings(self) -> None:
                                                                    
                                                                    
        from wallet_engine_chat import (
            INTENT_WALLET_ENGINE_SEND_DRAFT, compose_chat_response,
        )
        out = compose_chat_response(
            intent=INTENT_WALLET_ENGINE_SEND_DRAFT,
            asset="ETH", engine_enabled=True,
        )
                                       
        self.assertEqual(
            set(out.keys()),
            {"ok", "status", "intent", "asset", "message", "engineMessage"},
        )


if __name__ == "__main__":
    unittest.main()
