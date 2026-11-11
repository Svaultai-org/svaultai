"""Synthetic mixed legacy/private inheritance inventory and copy checks."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from routes import linked_inheritance_v2_mixed_item_routes as mixed
from test_linked_inheritance_v2_item_import_2026_11_09 import (
    BENEFICIARY, OWNER, ItemCursor, ready,
)


def _old(item_id: int = 7, value: bytes = b"old secret") -> dict:
    ciphertext = base64.b64encode(
        b"n" * 12 + value + b"t" * 16,
    ).decode("ascii")
    return {
        "id": item_id, "has_legacy": True,
        "item_type": "note", "service": "Legacy note",
        "encrypted_data": ciphertext,
        "legacy_bytes": len(ciphertext),
    }


def _private(item_id: int = 8, value: int = 3) -> dict:
    return {
        "id": item_id, "has_legacy": False,
        "item_type_ciphertext": b"\x01" + b"a" * 39,
        "service_ciphertext": b"\x01" + b"b" * 39,
        "payload_ciphertext": b"\x01" + bytes([value]) * 39,
    }


class MixedCursor(ItemCursor):
    def execute(self, sql, params):
        if "FROM vaults WHERE vault_id=%s FOR UPDATE" in sql:
            assert params == (OWNER["vault_id"],)
            self.value = {"vault_id": OWNER["vault_id"]}
            return
        if "AS legacy_bytes" in sql and "FROM vault_items" in sql:
            assert params == (
                mixed._MAX_SOURCE_BYTES,
                mixed._MAX_FIELD_BYTES,
                mixed._MAX_FIELD_BYTES,
                mixed._MAX_FIELD_BYTES,
                OWNER["vault_id"],
                mixed._MAX_ITEMS + 1,
            )
            self.value = deepcopy(self.db.source)
            return
        super().execute(sql, params)


def _install(db, monkeypatch):
    original = db.cursor

    def cursor(**kwargs):
        original(**kwargs)
        return MixedCursor(db)

    monkeypatch.setattr(db, "cursor", cursor)
    monkeypatch.setattr(mixed, "get_db", lambda: db)
    monkeypatch.setattr(mixed, "enforce_export_rate_limit", lambda **_: None)
    monkeypatch.setenv(mixed.FLAG_NAME, "true")


def _payload(exported: dict, index: int) -> mixed.CopyLinkedV2MixedItem:
    source = exported["items"][index]
    return mixed.CopyLinkedV2MixedItem(
        beneficiary_link_id=41,
        source_item_id=source["item_id"],
        stage_revision=1,
        offer_commitment=exported["offer_commitment"],
        source_inventory_sha256=exported["source_inventory_sha256"],
        source_row_sha256=source["source_row_sha256"],
        item_type_ciphertext=mixed._b64(b"\x01" + b"c" * 39),
        service_ciphertext=mixed._b64(b"\x01" + b"d" * 39),
        payload_ciphertext=mixed._b64(b"\x01" + b"e" * 79),
        title_lookup_hash=mixed._b64(bytes([index + 1]) * 32),
        content_scope="mixed_saved_items_only",
    )


def test_mixed_routes_default_off_and_exact_two_mode_inventory(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old(), _private()]
    _install(db, monkeypatch)
    monkeypatch.delenv(mixed.FLAG_NAME)
    with pytest.raises(HTTPException) as off:
        mixed.export_mixed_items(41, Response(), BENEFICIARY)
    assert off.value.status_code == 404
    monkeypatch.setenv(mixed.FLAG_NAME, "true")
    with pytest.raises(HTTPException) as wrong_vault:
        mixed.export_mixed_items(41, Response(), OWNER)
    assert wrong_vault.value.status_code == 404
    response = Response()
    exported = mixed.export_mixed_items(41, response, BENEFICIARY)
    assert response.headers["Cache-Control"] == "no-store"
    assert exported["item_count"] == 2
    assert [row["source_kind"] for row in exported["items"]] == [
        "legacy", "private",
    ]
    assert exported["items"][0]["encrypted_data"] == db.source[0]["encrypted_data"]
    assert "encrypted_data" not in exported["items"][1]
    assert "pin" not in str(exported).lower()
    assert exported["owner_content_complete"] is False
    with pytest.raises(ValidationError):
        mixed.CopyLinkedV2MixedItem(**{
            **_payload(exported, 0).model_dump(), "pin": "123456",
        })


def test_both_modes_copy_and_verify_without_dropping_either(ready, monkeypatch):
    db = ready
    db.source = [_old(), _private()]
    original = deepcopy(db.source)
    _install(db, monkeypatch)
    exported = mixed.export_mixed_items(41, Response(), BENEFICIARY)
    response = Response()
    empty = mixed.readback_mixed_item_copies(
        41, response, exported["source_inventory_sha256"], BENEFICIARY,
    )
    assert empty["copies"] == []
    assert empty["all_items_copied"] is False
    first = mixed.copy_mixed_item(_payload(exported, 0), BENEFICIARY)
    assert first["created"] is True
    second = mixed.copy_mixed_item(_payload(exported, 1), BENEFICIARY)
    assert second["created"] is True
    assert len(db.destination) == len(db.copies) == 2
    assert db.source == original
    retry = mixed.copy_mixed_item(_payload(exported, 0), BENEFICIARY)
    assert retry["created"] is False
    readback = mixed.readback_mixed_item_copies(
        41, Response(), exported["source_inventory_sha256"], BENEFICIARY,
    )
    assert readback["all_items_copied"] is True
    assert {row["source_item_id"] for row in readback["copies"]} == {7, 8}
    assert "encrypted_data" not in str(readback)


def test_mixed_copy_stops_on_source_change_receipt_loss_and_prior_scope(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old(), _private()]
    _install(db, monkeypatch)
    exported = mixed.export_mixed_items(41, Response(), BENEFICIARY)
    db.source[1] = _private(value=9)
    with pytest.raises(HTTPException) as changed:
        mixed.copy_mixed_item(_payload(exported, 0), BENEFICIARY)
    assert changed.value.status_code == 409
    db.source[1] = _private()
    db.stage["beneficiary_readback_revision"] = None
    with pytest.raises(HTTPException) as no_receipt:
        mixed.copy_mixed_item(_payload(exported, 0), BENEFICIARY)
    assert no_receipt.value.status_code == 409
    db.stage["beneficiary_readback_revision"] = 1
    first = mixed.copy_mixed_item(_payload(exported, 0), BENEFICIARY)
    assert first["created"] is True
    db.source[0] = _private(item_id=7)
    with pytest.raises(HTTPException) as changed_mode:
        mixed.readback_mixed_item_copies(
            41, Response(), exported["source_inventory_sha256"], BENEFICIARY,
        )
    assert changed_mode.value.status_code == 409

