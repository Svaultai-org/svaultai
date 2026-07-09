

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
    )


_VAULT_KEY = b"\x07" * 32
_VAULT_ID  = "v_test_notes"

_GENERAL_TITLE = "Cold-wallet rotation reminder"
_GENERAL_BODY  = "Rotate Ledger BTC cold wallet on Q3 2026."
_TX_TITLE      = "ETH withdrawal to Trezor"
_TX_BODY       = "Pulled funds off exchange, transferred to Trezor."
_TX_HASH       = "0xabcd" + "ef" * 30
_TX_AMOUNT     = "0.5 ETH"
_TX_DATE       = "2026-06-29"


class _AuthedClient:
    def __init__(self) -> None:
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
        return json.loads(
            _fake_decrypt(
                self.captured[idx]["encrypted_data"], _VAULT_KEY),
        )


class TestNoteRouteMounted(unittest.TestCase):
    def test_save_note_route_registered(self) -> None:
        import main
        paths = {r.path for r in main.app.routes}
        self.assertIn(
            "/crypto/save-note", paths,
            msg=(
                "POST /crypto/save-note must be mounted at the "
                "root prefix."
            ),
        )


class TestUnauthDoesNotReturn404(unittest.TestCase):
    def test_unauth_call_is_4xx(self) -> None:
        import main
        client = TestClient(main.app)
        resp = client.post(
            "/crypto/save-note",
            json={
                "pin": "0000", "title": "t", "note": "n",
                "noteType": "general",
            },
        )
        self.assertNotEqual(resp.status_code, 404)
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)


class TestBuilderShapes(unittest.TestCase):
    def test_general_note_record_shape(self) -> None:
        rec = cs.build_crypto_note_record(
            title=_GENERAL_TITLE,
            note=_GENERAL_BODY,
            asset="BTC",
        )
        self.assertEqual(rec["schema"],   "crypto_note_v1")
        self.assertEqual(rec["noteType"], "general")
        self.assertEqual(rec["title"],    _GENERAL_TITLE)
        self.assertEqual(rec["note"],     _GENERAL_BODY)
        self.assertEqual(rec["asset"],    "BTC")
        self.assertEqual(rec["network"],  "Bitcoin")
                                        
        self.assertEqual(rec["walletLabel"], "")
        self.assertEqual(rec["txHash"],      "")
        self.assertEqual(rec["amountText"],  "")
        self.assertEqual(rec["dateText"],    "")

    def test_transaction_note_record_shape(self) -> None:
        rec = cs.build_crypto_note_record(
            title=_TX_TITLE,
            note=_TX_BODY,
            asset="ETH",
            note_type=cs.NOTE_TYPE_TRANSACTION_NOTE,
            wallet_label="Trezor",
            tx_hash=_TX_HASH,
            amount_text=_TX_AMOUNT,
            date_text=_TX_DATE,
        )
        self.assertEqual(rec["schema"],     "crypto_note_v1")
        self.assertEqual(rec["noteType"],   "transaction_note")
        self.assertEqual(rec["walletLabel"], "Trezor")
        self.assertEqual(rec["txHash"],     _TX_HASH)
        self.assertEqual(rec["amountText"], _TX_AMOUNT)
        self.assertEqual(rec["dateText"],   _TX_DATE)


class TestBuilderValidation(unittest.TestCase):
    def test_missing_title_rejected(self) -> None:
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(title="", note="x")

    def test_missing_note_rejected(self) -> None:
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(title="x", note="")

    def test_unknown_asset_rejected(self) -> None:
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(
                title="x", note="y", asset="WAT")

    def test_unknown_note_type_rejected(self) -> None:
        with self.assertRaises(cs.CryptoSchemaError):
            cs.build_crypto_note_record(
                title="x", note="y", note_type="other")


class TestSaveGeneralNoteHappyPath(unittest.TestCase):
    def test_general_note_save_round_trips(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin":      "1234",
                    "title":    _GENERAL_TITLE,
                    "note":     _GENERAL_BODY,
                    "noteType": "general",
                    "asset":    "BTC",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["status"],   "saved")
            self.assertEqual(body["schema"],   "crypto_note_v1")
            self.assertEqual(body["category"], "crypto_note")
            self.assertEqual(body["noteType"], "general")
            self.assertTrue(body.get("item_id"))

            self.assertEqual(len(c.captured), 1)
            self.assertEqual(
                c.captured[0]["item_type"], "crypto_note",
            )
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["schema"], "crypto_note_v1",
            )
            self.assertEqual(decrypted["category"], "crypto_note")
                                                               
            self.assertEqual(
                decrypted["fields"]["crypto_note"], _GENERAL_BODY,
            )
            self.assertEqual(
                decrypted["fields"]["note_type"], "general",
            )
            self.assertEqual(decrypted["fields"]["asset"], "BTC")


class TestSaveTransactionNoteHappyPath(unittest.TestCase):
    def test_tx_note_save_round_trips_with_all_optional_fields(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin":         "1234",
                    "title":       _TX_TITLE,
                    "note":        _TX_BODY,
                    "noteType":    "transaction_note",
                    "asset":       "ETH",
                    "walletLabel": "Trezor",
                    "txHash":      _TX_HASH,
                    "amountText":  _TX_AMOUNT,
                    "dateText":    _TX_DATE,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(
                body["category"], "crypto_transaction_note",
            )
            self.assertEqual(body["noteType"], "transaction_note")
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["schema"], "crypto_note_v1",
            )
                                                             
            self.assertEqual(
                decrypted["fields"]["transaction_note"], _TX_BODY,
            )
                                                   
            self.assertEqual(
                decrypted["fields"]["note_type"],
                "transaction_note",
            )
            self.assertEqual(
                decrypted["fields"]["wallet_label"], "Trezor",
            )
            self.assertEqual(
                decrypted["fields"]["tx_hash"], _TX_HASH,
            )
            self.assertEqual(
                decrypted["fields"]["amount_text"], _TX_AMOUNT,
            )
            self.assertEqual(
                decrypted["fields"]["date_text"], _TX_DATE,
            )

    def test_tx_note_with_only_required_fields(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin":      "1234",
                    "title":    "Manual tx note",
                    "note":     "Reminder body",
                    "noteType": "transaction_note",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            decrypted = c.decrypted()
            self.assertEqual(
                decrypted["fields"]["note_type"],
                "transaction_note",
            )
            self.assertEqual(
                decrypted["fields"]["tx_hash"], "",
            )


class TestValidationRefusals(unittest.TestCase):
    def test_missing_title_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin": "1234", "title": "", "note": "n",
                    "noteType": "general",
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(len(c.captured), 0)

    def test_missing_note_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin": "1234", "title": "t", "note": "",
                    "noteType": "general",
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(len(c.captured), 0)

    def test_unknown_note_type_400(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin": "1234", "title": "t", "note": "n",
                    "noteType": "blockchain_verified",
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(len(c.captured), 0)


class TestFreeTextFieldsArePlainText(unittest.TestCase):
    def test_arbitrary_tx_hash_string_accepted_verbatim(self) -> None:


        for hostile in (
            "not-a-real-hash",
            "0x0",             
            "rubbish text",
            "ＦＵＬＬＷＩＤＴＨ",           
        ):
            with _AuthedClient() as c:
                resp = c.client.post(
                    "/crypto/save-note",
                    json={
                        "pin":      "1234",
                        "title":    "Manual tx note",
                        "note":     "body",
                        "noteType": "transaction_note",
                        "txHash":   hostile,
                    },
                )
                self.assertEqual(resp.status_code, 200, hostile)
                self.assertEqual(
                    c.decrypted()["fields"]["tx_hash"], hostile,
                )

    def test_arbitrary_amount_text_accepted_verbatim(self) -> None:
        with _AuthedClient() as c:
            resp = c.client.post(
                "/crypto/save-note",
                json={
                    "pin":        "1234",
                    "title":      "Manual tx note",
                    "note":       "body",
                    "noteType":   "transaction_note",
                    "amountText": "about half an ETH",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                c.decrypted()["fields"]["amount_text"],
                "about half an ETH",
            )


class TestNotesAreNotQrEligible(unittest.TestCase):
    def test_crypto_note_record_is_not_qr_eligible(self) -> None:
        rec = cs.build_crypto_note_record(
            asset="BTC",
            title="reminder",
            note="rotate Q3",
        )
        self.assertFalse(cs.is_receive_qr_eligible(rec))

    def test_transaction_note_record_is_not_qr_eligible(self) -> None:
        rec = cs.build_crypto_note_record(
            title="Manual tx note",
            note="body",
            note_type=cs.NOTE_TYPE_TRANSACTION_NOTE,
            tx_hash=_TX_HASH,
        )
        self.assertFalse(cs.is_receive_qr_eligible(rec))

    def test_hostile_tx_note_with_wallet_address_field_is_not_qr_eligible(
        self,
    ) -> None:


        hostile = {
            "schema":        cs.SCHEMA_CRYPTO_NOTE_V1,
            "publicAddress": "0x0000000000000000000000000000000000000001",
        }
        self.assertFalse(cs.is_receive_qr_eligible(hostile))


def _build_existing_general_note() -> str:
    record = {
        "category": t.CATEGORY_CRYPTO_NOTE,
        "title":    _GENERAL_TITLE,
        "fields": {
            "crypto_note": _GENERAL_BODY,
            "note_type":   "general",
            "asset":       "BTC",
            "network":     "Bitcoin",
        },
        "notes":   None,
        "item_id": "deadbeef-note",
    }
    cs.annotate_crypto_record(
        record, category=t.CATEGORY_CRYPTO_NOTE,
    )
    return _fake_encrypt(json.dumps(record), _VAULT_KEY)


def _build_existing_tx_note() -> str:
    record = {
        "category": t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
        "title":    _TX_TITLE,
        "fields": {
            "transaction_note": _TX_BODY,
            "note_type":        "transaction_note",
            "asset":            "ETH",
            "network":          "Ethereum",
            "wallet_label":     "Trezor",
            "tx_hash":          _TX_HASH,
            "amount_text":      _TX_AMOUNT,
            "date_text":        _TX_DATE,
        },
        "notes":   None,
        "item_id": "deadbeef-tx-note",
    }
    cs.annotate_crypto_record(
        record, category=t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
    )
    return _fake_encrypt(json.dumps(record), _VAULT_KEY)


def _simulate_update_merge(
    existing_blob: str,
    item_type: str,
    new_service: str,
    incoming_fields: dict,
) -> dict:
    existing = json.loads(_fake_decrypt(existing_blob, _VAULT_KEY))
    existing_fields = existing.get("fields") or {}
    if not isinstance(existing_fields, dict):
        existing_fields = {}
    existing_notes = existing.get("notes")
    merged_fields = {**existing_fields, **incoming_fields}
    merged_record = {
        "category": (
            existing.get("category")
            if isinstance(existing.get("category"), str)
            else None
        ) or item_type,
        "title":    new_service,
        "fields":   merged_fields,
        "notes":    existing_notes,
        "item_id":  existing.get("item_id") or "row-id",
    }
    for k in ("schema", "warningConfirmed"):
        if k in existing:
            merged_record[k] = existing[k]
    cat = merged_record.get("category")
    warning_confirmed = (
        True
        if cs.requires_warning_confirmation_for_category(cat)
        else None
    )
    cs.annotate_crypto_record(
        merged_record, category=cat,
        warning_confirmed=warning_confirmed,
    )
    blob = _fake_encrypt(json.dumps(merged_record), _VAULT_KEY)
    return json.loads(_fake_decrypt(blob, _VAULT_KEY))


class TestNoteUpdatePreservesSchema(unittest.TestCase):
    def test_general_note_label_edit_preserves_schema_and_type(self) -> None:
        merged = _simulate_update_merge(
            _build_existing_general_note(),
            item_type=t.CATEGORY_CRYPTO_NOTE,
            new_service="Updated reminder",
            incoming_fields={"crypto_note": "Rotated body"},
        )
        self.assertEqual(merged["schema"],   "crypto_note_v1")
        self.assertEqual(
            merged["fields"]["note_type"], "general",
        )
        self.assertEqual(merged["title"], "Updated reminder")
        self.assertEqual(
            merged["fields"]["crypto_note"], "Rotated body",
        )

    def test_tx_note_edit_preserves_schema_and_type(self) -> None:
        merged = _simulate_update_merge(
            _build_existing_tx_note(),
            item_type=t.CATEGORY_CRYPTO_TRANSACTION_NOTE,
            new_service="Updated tx note",
            incoming_fields={"amount_text": "0.7 ETH"},
        )
        self.assertEqual(merged["schema"],   "crypto_note_v1")
        self.assertEqual(
            merged["fields"]["note_type"], "transaction_note",
        )
        self.assertEqual(
            merged["fields"]["amount_text"], "0.7 ETH",
        )
                                
        self.assertEqual(
            merged["fields"]["tx_hash"], _TX_HASH,
        )
        self.assertEqual(
            merged["fields"]["date_text"], _TX_DATE,
        )


class TestNotesAreNotBalanceInputs(unittest.TestCase):
    def test_balance_summary_ignores_crypto_note_records(self) -> None:
        from crypto_balance_query import build_balance_summary
        notes = [
            cs.build_crypto_note_record(
                asset="BTC", title="r", note="body",
            ),
            cs.build_crypto_note_record(
                title="tx", note="body",
                note_type=cs.NOTE_TYPE_TRANSACTION_NOTE,
                amount_text="500 BTC",                   
            ),
        ]
        summary = build_balance_summary(notes)
                                                                 
                                                                  
        for asset_row in summary["assets"]:
            self.assertEqual(asset_row["savedWallets"], 0)


class TestNoteLogRedaction(unittest.TestCase):
    def test_secure_item_save_log_does_not_emit_body_or_title(
        self,
    ) -> None:


        with _AuthedClient() as c:
            with self.assertLogs(
                "vault_secure_item_save", level="DEBUG",
            ) as cap:
                c.client.post(
                    "/crypto/save-note",
                    json={
                        "pin":         "1234",
                        "title":       _TX_TITLE,
                        "note":        _TX_BODY,
                        "noteType":    "transaction_note",
                        "walletLabel": "Trezor",
                        "txHash":      _TX_HASH,
                    },
                )
            for line in cap.output:
                for forbidden in (
                    _TX_BODY, _TX_TITLE, _TX_HASH, "Trezor",
                ):
                    self.assertNotIn(
                        forbidden, line,
                        msg=f"save-note log line emits "
                            f"{forbidden!r}: {line!r}",
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
    def test_route_uses_trusted_device_dep(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        self.assertIn("verify_trusted_device", body)

    def test_route_uses_verify_vault_pin(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        self.assertIn("verify_vault_pin(", body)

    def test_route_delegates_to_encrypt_and_write(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        self.assertIn("_encrypt_and_write(", body)
                                                          
                                             
        self.assertNotIn("encrypt_message(", body)

    def test_route_does_not_override_db_executor(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        self.assertIn("db_executor=None", body)

    def test_route_calls_builder_for_validation(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        self.assertIn("build_crypto_note_record(", body)

    def test_route_does_not_log_sensitive_fields(self) -> None:
        body = _slice_handler('@router.post("/crypto/save-note")')
        for line in body.splitlines():
            for needle in (
                "logger.info", "logger.debug",
                "logger.warning", "logger.error",
                "print(",
            ):
                if needle in line:
                    for forbidden in (
                        "payload.note", "payload.title",
                        "payload.txHash", "payload.walletLabel",
                        "record[\"note\"]",
                        "record[\"title\"]",
                        "record[\"txHash\"]",
                        "record[\"walletLabel\"]",
                    ):
                        self.assertNotIn(
                            forbidden, line,
                            msg=f"save-note handler log emits "
                                f"{forbidden}: {line!r}",
                        )


if __name__ == "__main__":
    unittest.main()
