

from __future__ import annotations

import base64
import json
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import crypto_schemas as cs
import vault_saved_item_taxonomy as t


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
        patch("routes.login_routes.decrypt_message",
              side_effect=_fake_decrypt),
    )


_VAULT_KEY = b"\x07" * 32
_VAULT_ID  = "v_test_reveal_route"
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
_ETH_ADDR = "0x" + "0" * 39 + "1"


def _build_blob(
    *,
    category: str,
    field_key: str,
    field_value: str,
    extras: dict | None = None,
    schema: str | None = None,
    warning_confirmed: bool | None = None,
) -> str:
    fields = {field_key: field_value, "wallet_label": "Ledger"}
    if extras:
        fields.update(extras)
    record = {
        "category": category,
        "title":    "Test row",
        "fields":   fields,
        "notes":    None,
        "item_id":  "deadbeef",
    }
    if schema is not None:
        record["schema"] = schema
    if warning_confirmed is not None:
        record["warningConfirmed"] = warning_confirmed
    return _fake_encrypt(json.dumps(record), _VAULT_KEY)


class _AuthedClient:
    def __init__(self, *, row: dict | None = None) -> None:
        import main
        from device_gate import verify_trusted_device
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
                                                                  
                                                            
        self._row = row
        self._db_patch = patch(
            "routes.login_routes.get_db",
            side_effect=self._fake_get_db,
        )
        self._db_patch.start()
        self._enc_p, self._dec_p, self._dec_route_p = _patch_crypto()
        self._enc_p.start()
        self._dec_p.start()
        self._dec_route_p.start()
        self.client = TestClient(self.app)

    def _fake_get_db(self):
        row = self._row
        class _Cur:
            def execute(self_inner, *_a, **_kw): pass
            def fetchone(self_inner): return row
            def fetchall(self_inner): return [row] if row else []
            def close(self_inner): pass
        class _Conn:
            def cursor(self_inner, **_kw): return _Cur()
            def commit(self_inner): pass
            def close(self_inner): pass
        return _Conn()

    def close(self) -> None:
        from device_gate import verify_trusted_device
        prev = self._dep_originals[verify_trusted_device]
        if prev is None:
            self.app.dependency_overrides.pop(
                verify_trusted_device, None)
        else:
            self.app.dependency_overrides[verify_trusted_device] = prev
        self._pin_patch.stop()
        self._db_patch.stop()
        self._enc_p.stop()
        self._dec_p.stop()
        self._dec_route_p.stop()

    def __enter__(self) -> "_AuthedClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class TestRouteMounted(unittest.TestCase):
    def test_reveal_route_registered(self) -> None:
        import main
        paths = {r.path for r in main.app.routes}
        self.assertIn(
            "/crypto/reveal-sensitive-backup", paths,
            msg=(
                "POST /crypto/reveal-sensitive-backup must be "
                "mounted at the root prefix."
            ),
        )


class TestUnauthDoesNotReturn404(unittest.TestCase):
    def test_unauth_call_is_4xx(self) -> None:
        import main
        client = TestClient(main.app)
        resp = client.post(
            "/crypto/reveal-sensitive-backup",
            json={"pin": "0000", "service": "x",
                  "item_type": "crypto_recovery_phrase"},
        )
        self.assertNotEqual(resp.status_code, 404)
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)


class TestRevealHappyPath(unittest.TestCase):
    def test_recovery_phrase_reveal_returns_minimal_envelope(self) -> None:
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            field_key="recovery_phrase",
            field_value=_RECOVERY_PHRASE,
            extras={"secret_type": "recovery_phrase"},
            schema=cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            warning_confirmed=True,
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "Ledger BTC recovery",
                    "item_type": t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
                                   
            self.assertEqual(
                set(body.keys()),
                {"status", "schema", "secretType", "secretValue"},
                msg=(
                    "reveal envelope MUST carry only "
                    "{status, schema, secretType, secretValue}. "
                    f"Got: {sorted(body.keys())}"
                ),
            )
            self.assertEqual(body["status"], "ok")
            self.assertEqual(
                body["schema"], "crypto_sensitive_backup_v1",
            )
            self.assertEqual(body["secretType"], "recovery_phrase")
            self.assertEqual(body["secretValue"], _RECOVERY_PHRASE)

    def test_seed_phrase_reveal_returns_seed_phrase(self) -> None:
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_SEED_PHRASE,
            field_key="seed_phrase",
            field_value=_SEED,
            extras={"secret_type": "seed_phrase"},
            schema=cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            warning_confirmed=True,
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "Trezor seed",
                    "item_type": t.CATEGORY_CRYPTO_SEED_PHRASE,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()["secretType"], "seed_phrase")
            self.assertEqual(resp.json()["secretValue"], _SEED)

    def test_private_key_reveal_returns_private_key(self) -> None:
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_PRIVATE_KEY,
            field_key="private_key",
            field_value=_PRIVATE_KEY,
            extras={"secret_type": "private_key"},
            schema=cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            warning_confirmed=True,
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "MetaMask key",
                    "item_type": t.CATEGORY_CRYPTO_PRIVATE_KEY,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()["secretType"], "private_key")
            self.assertEqual(resp.json()["secretValue"], _PRIVATE_KEY)


class TestRevealResponseHasNoExtraFields(unittest.TestCase):
    def test_no_public_address_no_metadata_in_response(self) -> None:
                                                               
                                      
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            field_key="recovery_phrase",
            field_value=_RECOVERY_PHRASE,
            extras={
                "secret_type":    "recovery_phrase",
                "wallet_address": _ETH_ADDR,
                "wallet_label":   "Ledger Pro",
                "network":        "Bitcoin",
                "asset":          "BTC",
                "balance_status": "lookup_not_connected",
            },
            schema=cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            warning_confirmed=True,
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "Ledger BTC recovery",
                    "item_type": t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertNotIn(_ETH_ADDR, resp.text)
            self.assertNotIn("wallet_address", resp.text)
            self.assertNotIn("publicAddress", resp.text)
            self.assertNotIn("walletLabel", resp.text)
            self.assertNotIn("asset", resp.text)
            self.assertNotIn("Ledger Pro", resp.text)


class TestCategoryGate(unittest.TestCase):
    def test_wallet_profile_item_type_refused(self) -> None:
        with _AuthedClient(row=None) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "ignored",
                    "item_type": t.CATEGORY_CRYPTO_WALLET_ADDRESS,
                },
            )
            self.assertEqual(resp.status_code, 403, resp.text)
            self.assertEqual(
                resp.json()["detail"]["reveal_error"],
                "not_sensitive_backup",
            )

    def test_crypto_note_item_type_refused(self) -> None:
        with _AuthedClient(row=None) as c:
            for item_type in (
                t.CATEGORY_CRYPTO_NOTE,
                t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
                t.CATEGORY_CRYPTO_EXCHANGE_NOTE,
                t.CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
            ):
                resp = c.client.post(
                    "/crypto/reveal-sensitive-backup",
                    json={
                        "pin":       "1234",
                        "service":   "ignored",
                        "item_type": item_type,
                    },
                )
                self.assertEqual(
                    resp.status_code, 403,
                    msg=f"item_type={item_type} should be refused",
                )

    def test_login_item_type_refused(self) -> None:
        with _AuthedClient(row=None) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "ignored",
                    "item_type": "login",
                },
            )
            self.assertEqual(resp.status_code, 403)

    def test_imei_item_type_refused(self) -> None:
        with _AuthedClient(row=None) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "ignored",
                    "item_type": "imei",
                },
            )
            self.assertEqual(resp.status_code, 403)


class TestWrongPinRejected(unittest.TestCase):
    def test_wrong_pin_propagates_4xx(self) -> None:
        import main
        from device_gate import verify_trusted_device
        from fastapi import HTTPException
        main.app.dependency_overrides[verify_trusted_device] = (
            lambda: {"vault_id": _VAULT_ID, "device_id": "dev-test"}
        )
        try:
            with patch(
                "routes.login_routes.verify_vault_pin",
                side_effect=HTTPException(
                    status_code=401, detail="invalid PIN"),
            ):
                client = TestClient(main.app)
                resp = client.post(
                    "/crypto/reveal-sensitive-backup",
                    json={
                        "pin":       "wrong",
                        "service":   "Ledger BTC recovery",
                        "item_type":
                            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                    },
                )
                self.assertEqual(resp.status_code, 401)
                                                              
                self.assertNotIn(_RECOVERY_PHRASE, resp.text)
        finally:
            main.app.dependency_overrides.pop(
                verify_trusted_device, None)


class TestNotFound(unittest.TestCase):
    def test_no_matching_row_returns_404(self) -> None:
        with _AuthedClient(row=None) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "nonexistent",
                    "item_type": t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                },
            )
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(
                resp.json()["detail"]["reveal_error"], "not_found",
            )


class TestSchemaMismatchInBlob(unittest.TestCase):
    def test_blob_with_wrong_schema_is_refused(self) -> None:
                                                                 
                                                                
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            field_key="recovery_phrase",
            field_value=_RECOVERY_PHRASE,
            schema=cs.SCHEMA_CRYPTO_WALLET_PROFILE_V1,               
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            resp = c.client.post(
                "/crypto/reveal-sensitive-backup",
                json={
                    "pin":       "1234",
                    "service":   "Ledger BTC recovery",
                    "item_type": t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                },
            )
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(
                resp.json()["detail"]["reveal_error"],
                "schema_mismatch",
            )
                                                                 
            self.assertNotIn(_RECOVERY_PHRASE, resp.text)


class TestRevealLogRedaction(unittest.TestCase):
    def test_success_log_does_not_contain_secret_or_address(self) -> None:
        blob = _build_blob(
            category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            field_key="recovery_phrase",
            field_value=_RECOVERY_PHRASE,
            extras={
                "secret_type": "recovery_phrase",
                "wallet_address": _ETH_ADDR,
            },
            schema=cs.SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
        )
        with _AuthedClient(row={"id": 1, "encrypted_data": blob}) as c:
            with self.assertLogs(
                "crypto_reveal_route", level="DEBUG",
            ) as cap:
                resp = c.client.post(
                    "/crypto/reveal-sensitive-backup",
                    json={
                        "pin":       "1234",
                        "service":   "Ledger BTC recovery",
                        "item_type":
                            t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                    },
                )
                self.assertEqual(resp.status_code, 200, resp.text)
            for line in cap.output:
                for forbidden in (
                    _RECOVERY_PHRASE, _ETH_ADDR,
                    "Ledger BTC recovery",
                ):
                    self.assertNotIn(
                        forbidden, line,
                        msg=(
                            f"reveal log MUST NOT contain "
                            f"{forbidden!r}; line={line!r}"
                        ),
                    )

    def test_refusal_log_does_not_contain_payload(self) -> None:
        with _AuthedClient(row=None) as c:
            with self.assertLogs(
                "crypto_reveal_route", level="DEBUG",
            ) as cap:
                c.client.post(
                    "/crypto/reveal-sensitive-backup",
                    json={
                        "pin":       "1234",
                        "service":   "Sensitive Title 12345",
                        "item_type": t.CATEGORY_CRYPTO_WALLET_ADDRESS,
                    },
                )
            for line in cap.output:
                self.assertNotIn(
                    "Sensitive Title 12345", line,
                    msg=(
                        "refusal log MUST NOT echo the service title "
                        f"from the request body; line={line!r}"
                    ),
                )


_ROUTE_SRC = Path(
    "routes/login_routes.py",
).read_text(encoding="utf-8")


def _slice_handler(anchor: str) -> str:
    start = _ROUTE_SRC.index(anchor)
    nxt = _ROUTE_SRC.find("@router.", start + 1)
    end = nxt if nxt != -1 else len(_ROUTE_SRC)
    return _ROUTE_SRC[start:end]


class TestRouteSourceGuards(unittest.TestCase):
    def test_reveal_handler_uses_trusted_device_dep(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        self.assertIn("verify_trusted_device", body)

    def test_reveal_handler_calls_verify_vault_pin(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        self.assertIn("verify_vault_pin(", body)

    def test_reveal_handler_calls_schema_gate(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        self.assertIn(
            "requires_warning_confirmation_for_category", body,
        )
        self.assertIn("is_sensitive_backup_schema", body)

    def test_reveal_handler_scopes_to_vault_id(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        self.assertIn("WHERE vault_id", body)

    def test_reveal_handler_does_not_log_sensitive_fields(self) -> None:
        body = _slice_handler(
            '@router.post("/crypto/reveal-sensitive-backup")',
        )
        for line in body.splitlines():
            for needle in (
                "logger.info", "logger.debug",
                "logger.warning", "logger.error",
                "_logger.info", "_logger.debug",
                "_logger.warning", "_logger.error",
                "print(",
            ):
                if needle in line:
                    for forbidden in (
                        "secretValue", "secret_value",
                        "wallet_address", "publicAddress",
                        "public_address",
                        "seed_phrase", "private_key",
                        "recovery_phrase",
                                                        
                        "payload.service",
                        "payload.pin",
                    ):
                        self.assertNotIn(
                            forbidden, line,
                            msg=(
                                f"reveal handler log emits "
                                f"{forbidden}: {line!r}"
                            ),
                        )


if __name__ == "__main__":
    unittest.main()
