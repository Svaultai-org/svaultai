

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import crypto_schemas as cs
import vault_secure_item_save as vsi
import vault_saved_item_taxonomy as t
import vault_secure_item_draft as draft_store


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
_ETH_ADDR  = "0x" + "0" * 39 + "1"
_ETH_ADDR2 = "0x" + "0" * 39 + "2"
_RECOVERY_PHRASE = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
_RECOVERY_PHRASE2 = (
    "broken broken broken broken broken broken "
    "broken broken broken broken broken below"
)


def _build_existing_wallet_record() -> str:


    record = {
        "category": t.CATEGORY_CRYPTO_WALLET_ADDRESS,
        "title":    "MetaMask Ethereum wallet",
        "fields": {
            "wallet_address": _ETH_ADDR,
            "network":        "Ethereum",
            "wallet_label":   "MetaMask",
            "asset":          "ETH",
            "balance_status": "lookup_not_connected",
        },
        "notes":   None,
        "item_id": "deadbeef-wallet",
    }
    cs.annotate_crypto_record(
        record, category=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
    )
    return _fake_encrypt(json.dumps(record), _VAULT_KEY)


def _build_existing_backup_record() -> str:
    record = {
        "category": t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
        "title":    "Ledger BTC recovery",
        "fields": {
            "recovery_phrase": _RECOVERY_PHRASE,
            "network":         "Bitcoin",
            "wallet_label":    "Ledger",
            "asset":           "BTC",
            "secret_type":     "recovery_phrase",
        },
        "notes":   "cold storage",
        "item_id": "deadbeef-backup",
    }
    cs.annotate_crypto_record(
        record,
        category=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
        warning_confirmed=True,
    )
    return _fake_encrypt(json.dumps(record), _VAULT_KEY)


def _simulate_update_merge(
    existing_blob: str,
    item_type: str,
    new_service: str,
    incoming_fields: dict,
) -> dict:


    existing = json.loads(_fake_decrypt(existing_blob, _VAULT_KEY))
    _SCHEMA_B_MARKERS = {"category", "title", "fields", "item_id"}
    if any(k in existing for k in _SCHEMA_B_MARKERS):
        existing_fields = existing.get("fields") or {}
        if not isinstance(existing_fields, dict):
            existing_fields = {}
        existing_notes = existing.get("notes")
    else:
        existing_fields = existing
        existing_notes  = None
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


class TestWalletUpdatePreservesSchema(unittest.TestCase):
    def test_label_edit_preserves_schema(self) -> None:
        existing = _build_existing_wallet_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="MetaMask Hot Wallet",
            incoming_fields={"wallet_label": "MetaMask Hot Wallet"},
        )
        self.assertEqual(merged["schema"], "crypto_wallet_profile_v1")
                                                             
        self.assertEqual(merged["title"], "MetaMask Hot Wallet")
        self.assertEqual(
            merged["fields"]["wallet_address"], _ETH_ADDR,
        )
        self.assertEqual(
            merged["fields"]["wallet_label"],
            "MetaMask Hot Wallet",
        )

    def test_address_edit_preserves_schema(self) -> None:
        existing = _build_existing_wallet_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="MetaMask Ethereum wallet",
            incoming_fields={"wallet_address": _ETH_ADDR2},
        )
        self.assertEqual(merged["schema"], "crypto_wallet_profile_v1")
        self.assertEqual(
            merged["fields"]["wallet_address"], _ETH_ADDR2,
        )
                                                                 
                                               
        envelope_view = {
            "schema":        merged["schema"],
            "publicAddress": merged["fields"]["wallet_address"],
        }
        self.assertTrue(cs.is_receive_qr_eligible(envelope_view))

    def test_note_edit_preserves_schema(self) -> None:
        existing = _build_existing_wallet_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="MetaMask Ethereum wallet",
            incoming_fields={"note": "Cold storage variant"},
        )
        self.assertEqual(merged["schema"], "crypto_wallet_profile_v1")

    def test_legacy_unannotated_row_gets_schema_on_update(self) -> None:


        legacy_record = {
            "category": t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            "title":    "Legacy wallet",
            "fields": {
                "wallet_address": _ETH_ADDR,
                "network":        "Ethereum",
            },
            "notes":   None,
            "item_id": "legacy-id",
                            
        }
        legacy_blob = _fake_encrypt(
            json.dumps(legacy_record), _VAULT_KEY,
        )
        merged = _simulate_update_merge(
            legacy_blob,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="Legacy wallet (edited)",
            incoming_fields={"wallet_label": "Custom"},
        )
        self.assertEqual(merged["schema"], "crypto_wallet_profile_v1")


class TestSensitiveBackupUpdatePreservesSchema(unittest.TestCase):
    def test_label_metadata_edit_preserves_schema_and_warning(self) -> None:
        existing = _build_existing_backup_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            new_service="Ledger BTC cold backup",
            incoming_fields={"wallet_label": "Ledger Cold"},
        )
        self.assertEqual(
            merged["schema"], "crypto_sensitive_backup_v1",
        )
        self.assertEqual(merged["warningConfirmed"], True)
        self.assertEqual(
            merged["fields"]["recovery_phrase"], _RECOVERY_PHRASE,
        )
        self.assertEqual(
            merged["fields"]["wallet_label"], "Ledger Cold",
        )

    def test_secret_value_rotation_keeps_schema_and_warning(self) -> None:


        existing = _build_existing_backup_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
            new_service="Ledger BTC recovery",
            incoming_fields={"recovery_phrase": _RECOVERY_PHRASE2},
        )
        self.assertEqual(
            merged["schema"], "crypto_sensitive_backup_v1",
        )
        self.assertEqual(merged["warningConfirmed"], True)
        self.assertEqual(
            merged["fields"]["recovery_phrase"], _RECOVERY_PHRASE2,
        )


class TestSensitiveBackupNeverQrEligible(unittest.TestCase):
    def test_qr_helper_rejects_sensitive_backup_after_any_edit(self) -> None:
        existing = _build_existing_backup_record()
                                                                 
                                                                    
        for edits in (
            {"wallet_label": "Ledger Pro"},
            {"note": "rotated 2026-Q3"},
                                                               
                                                           
            {"wallet_address": _ETH_ADDR},
        ):
            merged = _simulate_update_merge(
                existing,
                item_type=t.CATEGORY_CRYPTO_RECOVERY_PHRASE,
                new_service="Ledger BTC recovery",
                incoming_fields=edits,
            )
                                                                 
                                                    
            envelope_view = {
                "schema":        merged["schema"],
                "publicAddress": merged["fields"].get(
                    "wallet_address", ""),
            }
            self.assertFalse(
                cs.is_receive_qr_eligible(envelope_view),
                msg=(
                    "sensitive backup MUST never become QR-eligible "
                    f"after edits={edits!r}"
                ),
            )


class TestWalletProfileQrEligibility(unittest.TestCase):
    def test_empty_address_after_edit_disables_qr(self) -> None:
        existing = _build_existing_wallet_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="MetaMask wallet",
            incoming_fields={"wallet_address": ""},
        )
        envelope_view = {
            "schema":        merged["schema"],
            "publicAddress": merged["fields"]["wallet_address"],
        }
        self.assertFalse(cs.is_receive_qr_eligible(envelope_view))

    def test_address_present_after_edit_keeps_qr(self) -> None:
        existing = _build_existing_wallet_record()
        merged = _simulate_update_merge(
            existing,
            item_type=t.CATEGORY_CRYPTO_WALLET_ADDRESS,
            new_service="MetaMask wallet",
            incoming_fields={"wallet_address": _ETH_ADDR2},
        )
        envelope_view = {
            "schema":        merged["schema"],
            "publicAddress": merged["fields"]["wallet_address"],
        }
        self.assertTrue(cs.is_receive_qr_eligible(envelope_view))


_ROUTE_SRC = Path(
    "routes/login_routes.py",
).read_text(encoding="utf-8")


def _slice_handler(anchor: str) -> str:
    start = _ROUTE_SRC.index(anchor)
    nxt = _ROUTE_SRC.find("@router.", start + 1)
    end = nxt if nxt != -1 else len(_ROUTE_SRC)
    return _ROUTE_SRC[start:end]


class TestUpdateHandlerPreservesAnnotation(unittest.TestCase):
    def test_handler_preserves_schema_key(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
                                                        
        self.assertIn('"schema"', body)
        self.assertIn('"warningConfirmed"', body)

    def test_handler_calls_annotate_crypto_record(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
        self.assertIn("annotate_crypto_record(", body)


class TestUpdateHandlerLogGuard(unittest.TestCase):
    def test_update_handler_does_not_log_address_or_secret(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
        for line in body.splitlines():
            for needle in (
                "logger.info", "logger.debug",
                "logger.warning", "logger.error",
                "print(",
            ):
                if needle in line:
                    for forbidden in (
                        "publicAddress", "public_address",
                        "wallet_address", "secretValue",
                        "secret_value", "seed_phrase",
                        "private_key", "recovery_phrase",
                    ):
                        self.assertNotIn(forbidden, line,
                            msg=f"update handler log "
                                f"emits {forbidden}: {line!r}")


class TestDeleteHandlerLogGuard(unittest.TestCase):
    def test_delete_handler_does_not_log_address_or_secret(self) -> None:
        body = _slice_handler(
            '@router.post("/delete-secure-item")',
        )
        for line in body.splitlines():
            for needle in (
                "logger.info", "logger.debug",
                "logger.warning", "logger.error",
                "print(",
            ):
                if needle in line:
                    for forbidden in (
                        "publicAddress", "public_address",
                        "wallet_address", "secretValue",
                        "secret_value", "seed_phrase",
                        "private_key", "recovery_phrase",
                    ):
                        self.assertNotIn(forbidden, line,
                            msg=f"delete handler log "
                                f"emits {forbidden}: {line!r}")


class TestDeleteHandlerVaultGate(unittest.TestCase):
    def test_delete_handler_uses_trusted_device_dep(self) -> None:
        body = _slice_handler(
            '@router.post("/delete-secure-item")',
        )
        self.assertIn("verify_trusted_device", body)

    def test_delete_handler_calls_verify_vault_pin(self) -> None:
        body = _slice_handler(
            '@router.post("/delete-secure-item")',
        )
        self.assertIn("verify_vault_pin(", body)

    def test_delete_query_scopes_to_vault_id(self) -> None:
        body = _slice_handler(
            '@router.post("/delete-secure-item")',
        )
                                                              
                                                           
        self.assertIn("DELETE FROM vault_items", body)
        self.assertIn("WHERE vault_id", body)

    def test_delete_handler_bumps_storage_quota(self) -> None:
        body = _slice_handler(
            '@router.post("/delete-secure-item")',
        )
        self.assertIn("bump_vault_total_bytes", body)


class TestUpdateHandlerGuards(unittest.TestCase):
    def test_update_handler_uses_trusted_device_dep(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
        self.assertIn("verify_trusted_device", body)

    def test_update_handler_calls_verify_vault_pin(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
        self.assertIn("verify_vault_pin(", body)

    def test_update_handler_bumps_storage_quota(self) -> None:
        body = _slice_handler(
            '@router.post("/update-secure-item")',
        )
        self.assertIn("bump_vault_total_bytes", body)


if __name__ == "__main__":
    unittest.main()
