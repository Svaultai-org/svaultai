"""Synthetic release-bound export of older saved-item ciphertext."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest
from fastapi import HTTPException, Response

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
        if "octet_length(encrypted_data)" in sql:
            assert params == (
                items._MAX_SOURCE_BYTES, OWNER["vault_id"], items._MAX_ITEMS + 1,
            )
            self.value = deepcopy(self.db.source)
            return
        super().execute(sql, params)


def _install_legacy_cursor(db, monkeypatch):
    monkeypatch.setattr(db, "cursor", lambda **_kwargs: LegacyCursor(db))


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
