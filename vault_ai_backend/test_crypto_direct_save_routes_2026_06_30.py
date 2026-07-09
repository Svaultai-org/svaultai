

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient


def _fake_encrypt(plain: str, key: bytes) -> str:
    k = key[0] if key else 0
    return base64.b64encode(
        bytes(b ^ k for b in plain.encode("utf-8")),
    ).decode("ascii")


def _fake_decrypt(blob: str, key: bytes) -> str:
    k = key[0] if key else 0
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ k for b in raw).decode("utf-8")


def _patch_crypto():
    return (
        patch("vault_core.encrypt_message", side_effect=_fake_encrypt),
        patch("vault_core.decrypt_message", side_effect=_fake_decrypt),
    )


_VAULT_KEY = b"\x07" * 32
_VAULT_ID  = "v_test_crypto_routes"

_ETH_ADDR = "0x" + "0" * 39 + "1"
_BTC_ADDR = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_USDT_TRC20_ADDR = "TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY"
_RECOVERY_PHRASE = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
_SEED = (
    "witch collapse practice feed shame open despair "
    "creek road again ice least"
)
_PRIVATE_KEY = (
    "L1aW4aubDFB7yfras2S1mN3bqg9nwySY8nkoLmJebSLD5BWv3ENZ"
)


class TestRoutesMounted(unittest.TestCase):
    def setUp(self) -> None:
        import main
        self.app   = main.app
        self.paths = {r.path for r in self.app.routes}

    def test_save_wallet_profile_route_registered(self) -> None:
        self.assertIn(
            "/crypto/save-wallet-profile", self.paths,
            msg=(
                "POST /crypto/save-wallet-profile must be mounted "
                "at the root prefix — the Flutter Add Crypto "
                "Wallet dialog calls it directly."
            ),
        )

    def test_save_sensitive_backup_route_registered(self) -> None:
        self.assertIn(
            "/crypto/save-sensitive-backup", self.paths,
            msg=(
                "POST /crypto/save-sensitive-backup must be "
                "mounted at the root prefix."
            ),
        )


class TestUnauthDoesNotReturn404(unittest.TestCase):
    def setUp(self) -> None:
        import main
        self.client = TestClient(main.app)

    def _assert_not_404(self, path: str, payload: dict) -> None:
        resp = self.client.post(path, json=payload)
        self.assertNotEqual(
            resp.status_code, 404,
            msg=(
                f"{path} returned 404 — the handler is not mounted. "
                "Confirm routes/login_routes.py declares the route."
            ),
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)

    def test_save_wallet_profile_unauth_is_4xx(self) -> None:
        self._assert_not_404(
            "/crypto/save-wallet-profile",
            {"pin": "0000", "asset": "ETH",
             "walletLabel": "MetaMask",
             "publicAddress": _ETH_ADDR},
        )

    def test_save_sensitive_backup_unauth_is_4xx(self) -> None:
        self._assert_not_404(
            "/crypto/save-sensitive-backup",
            {"pin": "0000", "walletLabel": "Ledger",
             "secretType": "recovery_phrase",
             "secretValue": _RECOVERY_PHRASE,
             "warningConfirmed": True},
        )


class _AuthedClient:


    def __init__(self) -> None:
        import main
        from device_gate import verify_trusted_device
        from vault_core import verify_vault_pin
        self.app = main.app
        self.principal = {"vault_id": _VAULT_ID, "device_id": "dev-test"}
        self._dep_originals = {
            verify_trusted_device: main.app.dependency_overrides.get(
                verify_trusted_device,
            ),
        }
        main.app.dependency_overrides[verify_trusted_device] = (
            lambda: self.principal
        )
                                                              
                                             
        self._pin_patch = patch(
            "routes.login_routes.verify_vault_pin",
            return_value=_VAULT_KEY,
        )
        self._pin_patch.start()
                                                                  
        self.captured: list[dict] = []
        self._upsert_patch = patch(
            "vault_secure_item_save._default_upsert",
            side_effect=lambda payload: self.captured.append(payload),
        )
        self._upsert_patch.start()
                                  
        self._enc_p, self._dec_p = _patch_crypto()
        self._enc_p.start()
        self._dec_p.start()
        self.client = TestClient(self.app)

    def close(self) -> None:
        from device_gate import verify_trusted_device
        prev = self._dep_originals[verify_trusted_device]
        if prev is None:
            self.app.dependency_overrides.pop(
                verify_trusted_device, None)
        else:
            self.app.dependency_overrides[verify_trusted_device] = prev
        self._pin_patch.stop()
        self._upsert_patch.stop()
        self._enc_p.stop()
        self._dec_p.stop()

    def __enter__(self) -> "_AuthedClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def decrypted(self, idx: int = -1) -> dict:
        blob = self.captured[idx]["encrypted_data"]
        return json.loads(_fake_decrypt(blob, _VAULT_KEY))


class TestSaveWalletProfileHappyPath(unittest.TestCase):
    def test_metamask_eth_save_round_trips(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "ETH",
                    "walletLabel":   "MetaMask",
                    "publicAddress": _ETH_ADDR,
                    "note":          "Daily driver",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["status"],   "saved")
            self.assertEqual(body["schema"],   "crypto_wallet_profile_v1")
            self.assertEqual(body["category"], "crypto_wallet_address")
            self.assertTrue(body.get("item_id"))

                                     
            self.assertEqual(len(c.captured), 1)
            payload = c.captured[0]
            self.assertEqual(payload["vault_id"], _VAULT_ID)
            self.assertEqual(
                payload["item_type"], "crypto_wallet_address",
            )

                                                              
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["schema"], "crypto_wallet_profile_v1",
            )
            self.assertEqual(
                decrypted["fields"]["wallet_address"], _ETH_ADDR,
            )
            self.assertEqual(
                decrypted["fields"]["network"], "Ethereum",
            )
            self.assertEqual(
                decrypted["fields"]["wallet_label"], "MetaMask",
            )
            self.assertEqual(decrypted["fields"]["asset"], "ETH")
                                                  
            self.assertNotIn("warningConfirmed", decrypted)

    def test_trust_wallet_usdt_trc20_save_round_trips(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "USDT_TRC20",
                    "walletLabel":   "Trust Wallet",
                    "publicAddress": _USDT_TRC20_ADDR,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["fields"]["asset"], "USDT_TRC20",
            )
            self.assertEqual(
                decrypted["fields"]["network"], "Tron TRC20",
            )
            self.assertEqual(
                decrypted["fields"]["wallet_label"], "Trust Wallet",
            )

    def test_xmr_save_pins_privacy_balance_status(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "XMR",
                    "walletLabel":   "Monero GUI",
                    "publicAddress":
                        "4" + "1" * 94,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["fields"]["balance_status"],
                "unavailable_privacy",
            )


class TestSensitiveBackupWarningGate(unittest.TestCase):
    def test_missing_warning_returns_403(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":         "1234",
                    "walletLabel": "Ledger",
                    "secretType":  "recovery_phrase",
                    "secretValue": _RECOVERY_PHRASE,
                                                                   
                },
            )
            self.assertEqual(resp.status_code, 403, resp.text)
            self.assertEqual(
                resp.json()["detail"]["warning_required"], True,
            )
                                
            self.assertEqual(len(c.captured), 0)

    def test_false_warning_returns_403(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "walletLabel":      "Ledger",
                    "secretType":       "recovery_phrase",
                    "secretValue":      _RECOVERY_PHRASE,
                    "warningConfirmed": False,
                },
            )
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(len(c.captured), 0)


class TestSensitiveBackupHappyPath(unittest.TestCase):
    def test_recovery_phrase_save_round_trips(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "asset":            "BTC",
                    "walletLabel":      "Ledger",
                    "secretType":       "recovery_phrase",
                    "secretValue":      _RECOVERY_PHRASE,
                    "note":             "cold storage",
                    "warningConfirmed": True,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(
                body["schema"], "crypto_sensitive_backup_v1",
            )
            self.assertEqual(
                body["category"], "crypto_recovery_phrase",
            )
            self.assertEqual(len(c.captured), 1)
            payload = c.captured[0]
            self.assertEqual(
                payload["item_type"], "crypto_recovery_phrase",
            )
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["schema"], "crypto_sensitive_backup_v1",
            )
            self.assertEqual(decrypted["warningConfirmed"], True)
            self.assertEqual(
                decrypted["fields"]["recovery_phrase"],
                _RECOVERY_PHRASE,
            )
            self.assertEqual(
                decrypted["fields"]["wallet_label"], "Ledger",
            )

    def test_seed_phrase_save_lands_on_seed_category(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "walletLabel":      "Trezor",
                    "secretType":       "seed_phrase",
                    "secretValue":      _SEED,
                    "warningConfirmed": True,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(
                resp.json()["category"], "crypto_seed_phrase",
            )
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["fields"]["seed_phrase"], _SEED,
            )

    def test_private_key_save_lands_on_private_key_category(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "walletLabel":      "MetaMask",
                    "secretType":       "private_key",
                    "secretValue":      _PRIVATE_KEY,
                    "warningConfirmed": True,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(
                resp.json()["category"], "crypto_private_key",
            )


class TestWalletSaveValidation(unittest.TestCase):
    def test_unknown_asset_rejected_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "WAT",
                    "walletLabel":   "MetaMask",
                    "publicAddress": _ETH_ADDR,
                },
            )
            self.assertEqual(resp.status_code, 400, resp.text)
            self.assertIn("schema_error", resp.json()["detail"])
            self.assertEqual(len(c.captured), 0)

    def test_empty_wallet_label_rejected_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "ETH",
                    "walletLabel":   "",
                    "publicAddress": _ETH_ADDR,
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(len(c.captured), 0)

    def test_empty_public_address_rejected_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "ETH",
                    "walletLabel":   "MetaMask",
                    "publicAddress": "",
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(len(c.captured), 0)

    def test_rejected_payload_does_not_echo_address(self) -> None:


        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "WAT",                 
                    "walletLabel":   "MetaMask",
                    "publicAddress": _ETH_ADDR,
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertNotIn(_ETH_ADDR, resp.text)


class TestResponseSchemaStrings(unittest.TestCase):
    def test_wallet_profile_response_schema_string(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "ETH",
                    "walletLabel":   "MetaMask",
                    "publicAddress": _ETH_ADDR,
                },
            )
            self.assertEqual(
                resp.json()["schema"], "crypto_wallet_profile_v1",
            )

    def test_sensitive_backup_response_schema_string(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "walletLabel":      "Ledger",
                    "secretType":       "recovery_phrase",
                    "secretValue":      _RECOVERY_PHRASE,
                    "warningConfirmed": True,
                },
            )
            self.assertEqual(
                resp.json()["schema"], "crypto_sensitive_backup_v1",
            )


class TestRecordsRemainDistinguishable(unittest.TestCase):
    def test_two_kinds_are_different_categories_and_schemas(self) -> None:
        with _AuthedClient() as c:
            c.client.post(
                "/crypto/save-wallet-profile",
                json={
                    "pin":           "1234",
                    "asset":         "ETH",
                    "walletLabel":   "MetaMask",
                    "publicAddress": _ETH_ADDR,
                },
            )
            c.client.post(
                "/crypto/save-sensitive-backup",
                json={
                    "pin":              "1234",
                    "asset":            "ETH",
                    "walletLabel":      "MetaMask",
                    "secretType":       "private_key",
                    "secretValue":      _PRIVATE_KEY,
                    "warningConfirmed": True,
                },
            )
            self.assertEqual(len(c.captured), 2)
            wallet = c.decrypted(0)
            backup = c.decrypted(1)
            self.assertNotEqual(wallet["schema"], backup["schema"])
            self.assertNotEqual(
                c.captured[0]["item_type"],
                c.captured[1]["item_type"],
            )
                                                                
            self.assertIn("wallet_address", wallet["fields"])
            self.assertNotIn("private_key", wallet["fields"])
            self.assertIn("private_key",  backup["fields"])
            self.assertNotIn("wallet_address", backup["fields"])


_ROUTE_SRC = Path(
    "routes/login_routes.py",
).read_text(encoding="utf-8")


def _slice_handler(anchor: str) -> str:
    start = _ROUTE_SRC.index(anchor)
    nxt = _ROUTE_SRC.find("@router.", start + 1)
    end = nxt if nxt != -1 else len(_ROUTE_SRC)
    return _ROUTE_SRC[start:end]


class TestRouteSourceGuards(unittest.TestCase):
    def test_wallet_route_delegates_to_encrypt_and_write(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/save-wallet-profile")',
        )
        self.assertIn("_encrypt_and_write(", body)
                                                                
                             
        self.assertNotIn("encrypt_message(", body)

    def test_backup_route_delegates_to_encrypt_and_write(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/save-sensitive-backup")',
        )
        self.assertIn("_encrypt_and_write(", body)
        self.assertNotIn("encrypt_message(", body)

    def test_wallet_route_does_not_override_db_executor(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/save-wallet-profile")',
        )
                                                       
                                                                    
        self.assertIn("db_executor=None", body)

    def test_backup_route_does_not_override_db_executor(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/save-sensitive-backup")',
        )
        self.assertIn("db_executor=None", body)


class TestRouteLoggingGuard(unittest.TestCase):
    def _scan_route_block(self, anchor: str) -> str:
        return _slice_handler(anchor)

    def test_wallet_route_does_not_log_address(self) -> None:
        body = self._scan_route_block(
            '@router.post("/crypto/save-wallet-profile")',
        )
        for needle in (
            "logger.info", "logger.debug", "logger.warning",
            "logger.error", "print(",
        ):
            for line in body.splitlines():
                if needle in line:
                    self.assertNotIn("publicAddress", line)
                    self.assertNotIn("public_address", line)
                    self.assertNotIn("wallet_address", line)

    def test_backup_route_does_not_log_secret(self) -> None:
        body = self._scan_route_block(
            '@router.post("/crypto/save-sensitive-backup")',
        )
        for needle in (
            "logger.info", "logger.debug", "logger.warning",
            "logger.error", "print(",
        ):
            for line in body.splitlines():
                if needle in line:
                    self.assertNotIn("secretValue",     line)
                    self.assertNotIn("secret_value",    line)
                    self.assertNotIn("seed_phrase",     line)
                    self.assertNotIn("private_key",     line)
                    self.assertNotIn("recovery_phrase", line)


if __name__ == "__main__":
    unittest.main()
