"""Synthetic release-bound export of older saved-item ciphertext."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from routes import linked_inheritance_v2_item_import_routes as items
from test_linked_inheritance_v2_item_import_2026_11_09 import (
    BENEFICIARY, OWNER, ItemCursor, ready,
)


def _old_item(item_id: int = 7, payload: bytes = b"secret") -> dict:
    ciphertext = base64.b64encode(
        b"n" * 12 + payload + b"t" * 16,
    ).decode("ascii")
    return {
        "id": item_id,
        "item_type": "note",
        "service": "Private note",
        "encrypted_data": ciphertext,
        "ciphertext_bytes": len(ciphertext),
    }


def _export(db) -> tuple[dict, Response]:
    response = Response()
    body = items.export_linked_v2_legacy_items(
        41, response, BENEFICIARY,
    )
    return body, response


class LegacyCursor(ItemCursor):
    def execute(self, sql, params):
        if "FROM vaults WHERE vault_id=%s FOR UPDATE" in sql:
            assert params == (OWNER["vault_id"],)
            self.value = {"vault_id": OWNER["vault_id"]}
            return
        if "octet_length(encrypted_data)" in sql:
            assert params == (
                items._MAX_SOURCE_BYTES, OWNER["vault_id"], items._MAX_ITEMS + 1,
            )
            self.value = deepcopy(self.db.source)
            return
        super().execute(sql, params)


def _install_legacy_cursor(db, monkeypatch):
    original = db.cursor

    def cursor(**kwargs):
        original(**kwargs)  # Keep the fixture's transaction snapshot.
        return LegacyCursor(db)

    monkeypatch.setattr(db, "cursor", cursor)


def _copy_payload(exported: dict) -> items.CopyLinkedV2LegacyItem:
    return items.CopyLinkedV2LegacyItem(
        beneficiary_link_id=41,
        source_item_id=7,
        stage_revision=1,
        offer_commitment=exported["offer_commitment"],
        source_inventory_sha256=exported["source_inventory_sha256"],
        source_row_sha256=exported["items"][0]["source_row_sha256"],
        item_type_ciphertext=items._b64(b"\x01" + b"t" * 39),
        service_ciphertext=items._b64(b"\x01" + b"s" * 39),
        payload_ciphertext=items._b64(b"\x01" + b"p" * 79),
        title_lookup_hash=items._b64(b"h" * 32),
        content_scope="legacy_saved_items_only",
    )


def test_older_item_export_is_default_off_and_release_bound(ready, monkeypatch):
    db = ready
    db.source = [_old_item()]
    _install_legacy_cursor(db, monkeypatch)
    with pytest.raises(HTTPException) as disabled:
        _export(db)
    assert disabled.value.status_code == 404

    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    with pytest.raises(HTTPException) as wrong_vault:
        items.export_linked_v2_legacy_items(41, Response(), OWNER)
    assert wrong_vault.value.status_code == 404

    db.link["status"] = "revoked"
    with pytest.raises(HTTPException) as revoked:
        _export(db)
    assert revoked.value.status_code == 404
    db.link["status"] = "linked"

    db.stage["beneficiary_readback_revision"] = None
    with pytest.raises(HTTPException) as no_receipt:
        _export(db)
    assert no_receipt.value.status_code == 409
    db.stage["beneficiary_readback_revision"] = 1

    db.credential["state"] = "pending"
    with pytest.raises(HTTPException) as not_released:
        _export(db)
    assert not_released.value.status_code == 409


def test_older_item_export_returns_only_bounded_ciphertext_after_release(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old_item()]
    _install_legacy_cursor(db, monkeypatch)
    original = deepcopy(db.source)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    body, response = _export(db)
    assert response.headers["Cache-Control"] == "no-store"
    assert body["content_scope"] == "legacy_saved_items_only"
    assert body["owner_content_complete"] is False
    assert body["item_count"] == 1
    assert body["ciphertext_bytes"] == len(original[0]["encrypted_data"])
    assert body["items"][0]["encrypted_data"] == original[0]["encrypted_data"]
    assert len(body["items"][0]["source_row_sha256"]) == 43
    assert "pin" not in str(body).lower()
    assert db.source == original
    assert db.destination == {}

    db.source[0] = _old_item(payload=b"changed")
    changed, _ = _export(db)
    assert changed["source_inventory_sha256"] != body["source_inventory_sha256"]


def test_older_item_export_rejects_malformed_and_oversized_rows(
    ready, monkeypatch,
):
    db = ready
    _install_legacy_cursor(db, monkeypatch)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    db.source = [{**_old_item(), "encrypted_data": "raw plaintext"}]
    with pytest.raises(HTTPException) as malformed:
        _export(db)
    assert malformed.value.status_code == 409

    db.source = [{**_old_item(), "ciphertext_bytes": items._MAX_SOURCE_BYTES + 1,
                  "encrypted_data": None}]
    with pytest.raises(HTTPException) as oversized:
        _export(db)
    assert oversized.value.status_code == 409

    row = _old_item()
    db.source = [{**row, "id": index} for index in range(1, 102)]
    with pytest.raises(HTTPException) as too_many:
        _export(db)
    assert too_many.value.status_code == 409


def test_legacy_copy_is_default_off_and_rejects_plaintext_fields(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old_item()]
    _install_legacy_cursor(db, monkeypatch)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    exported, _ = _export(db)
    payload = _copy_payload(exported)
    with pytest.raises(HTTPException) as disabled:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert disabled.value.status_code == 404
    with pytest.raises(ValidationError):
        items.CopyLinkedV2LegacyItem(**{
            **payload.model_dump(), "pin": "123456",
        })
    with pytest.raises(ValidationError):
        items.CopyLinkedV2LegacyItem(**{
            **payload.model_dump(), "service": "plaintext label",
        })


def test_legacy_copy_is_bounded_retry_safe_and_readback_is_exact(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old_item()]
    original = deepcopy(db.source)
    _install_legacy_cursor(db, monkeypatch)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    monkeypatch.setenv(items.LEGACY_COPY_FLAG_NAME, "true")
    exported, _ = _export(db)
    payload = _copy_payload(exported)
    first = items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert first["created"] is True
    assert len(db.destination) == len(db.copies) == 1
    assert db.source == original
    again = items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert again["created"] is False
    assert again["beneficiary_item_id"] == first["beneficiary_item_id"]
    response = Response()
    readback = items.readback_linked_v2_legacy_item_copies(
        41, response, exported["source_inventory_sha256"], BENEFICIARY,
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert readback["all_items_copied"] is True
    assert readback["content_scope"] == "legacy_saved_items_only"
    assert readback["copies"][0]["payload_ciphertext"] == (
        payload.payload_ciphertext
    )
    assert "encrypted_data" not in str(readback)

    db.destination[first["beneficiary_item_id"]]["payload_ciphertext"] = (
        b"\x01" + b"x" * 79
    )
    with pytest.raises(HTTPException) as altered:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert altered.value.status_code == 409
    with pytest.raises(HTTPException) as readback_altered:
        items.readback_linked_v2_legacy_item_copies(
            41, Response(), exported["source_inventory_sha256"], BENEFICIARY,
        )
    assert readback_altered.value.status_code == 409


def test_legacy_copy_stops_on_revocation_stale_source_or_oversized_write(
    ready, monkeypatch,
):
    db = ready
    db.source = [_old_item()]
    _install_legacy_cursor(db, monkeypatch)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    monkeypatch.setenv(items.LEGACY_COPY_FLAG_NAME, "true")
    exported, _ = _export(db)
    payload = _copy_payload(exported)
    db.link["status"] = "revoked"
    with pytest.raises(HTTPException) as revoked:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert revoked.value.status_code == 404
    db.link["status"] = "linked"
    db.stage["beneficiary_readback_revision"] = None
    with pytest.raises(HTTPException) as receipt:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert receipt.value.status_code == 409
    db.stage["beneficiary_readback_revision"] = 1
    db.source = [_old_item(payload=b"changed")]
    with pytest.raises(HTTPException) as changed:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert changed.value.status_code == 409
    db.source = [_old_item()]
    too_large = items.CopyLinkedV2LegacyItem(**{
        **payload.model_dump(),
        "payload_ciphertext": items._b64(b"\x01" + b"x" * 5000),
    })
    with pytest.raises(HTTPException) as oversized:
        items.copy_linked_v2_legacy_item(too_large, BENEFICIARY)
    assert oversized.value.status_code == 409
    assert db.destination == {}


def test_legacy_paths_reject_mixed_owner_saved_item_modes(ready, monkeypatch):
    db = ready
    db.source = [_old_item(), {"id": 8, "has_private": True}]
    _install_legacy_cursor(db, monkeypatch)
    monkeypatch.setenv(items.LEGACY_EXPORT_FLAG_NAME, "true")
    monkeypatch.setenv(items.LEGACY_COPY_FLAG_NAME, "true")
    with pytest.raises(HTTPException) as mixed_export:
        _export(db)
    assert mixed_export.value.detail == "mixed_saved_item_modes_unsupported"

    db.source = [_old_item()]
    exported, _ = _export(db)
    payload = _copy_payload(exported)
    db.source.append({"id": 8, "has_private": True})
    with pytest.raises(HTTPException) as mixed_copy:
        items.copy_linked_v2_legacy_item(payload, BENEFICIARY)
    assert mixed_copy.value.detail == "mixed_saved_item_modes_unsupported"
    with pytest.raises(HTTPException) as mixed_readback:
        items.readback_linked_v2_legacy_item_copies(
            41, Response(), exported["source_inventory_sha256"], BENEFICIARY,
        )
    assert mixed_readback.value.detail == "mixed_saved_item_modes_unsupported"
    assert db.destination == {}
