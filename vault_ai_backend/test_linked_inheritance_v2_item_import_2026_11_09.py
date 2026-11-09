"""Synthetic checks for receipt-gated, bounded linked saved-item copies."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import linked_inheritance_v2_upgrade_routes as upgrade
from routes import linked_inheritance_v2_item_import_routes as items
from test_linked_inheritance_v2_upgrade_2026_11_09 import (
    FakeDb, FakeCursor, OWNER, BENEFICIARY, BENEFICIARY_ID,
)


def _ct(value: int, length: int = 40) -> bytes:
    return b"\x01" + bytes([value]) * (length - 1)


class ItemDb(FakeDb):
    def __init__(self):
        super().__init__()
        now = datetime.now(timezone.utc)
        self.link["pairing_state"] = "released"
        self.credential["state"] = "released"
        self.credential["released_at"] = now
        self.source = [{
            "id": 7,
            "has_legacy": False,
            "item_type_ciphertext": _ct(1),
            "service_ciphertext": _ct(2),
            "payload_ciphertext": _ct(3),
        }]
        self.destination = {}
        self.copies = []
        self.next_item_id = 100
        self.unindexed_destination = False
        self.stage = {
            "owner_vault_id": OWNER["vault_id"],
            "beneficiary_vault_id": BENEFICIARY_ID,
            "old_source_snapshot": upgrade._source_snapshot(
                self.link, self.credential,
            ),
            "beneficiary_pk_sha256": hashlib.sha256(self.pk).digest(),
            "encrypted_payload": b"n" * 48,
            "payload_nonce": b"a" * 12,
            "wrapped_key": b"b" * 48,
            "wrapping_ephemeral_pk": b"c" * 32,
            "wrapping_nonce": b"d" * 12,
            "stage_revision": 1,
            "state": "staged",
            "beneficiary_keycheck_revision": 1,
            "beneficiary_keycheck_at": now,
            "owner_readback_public_key": b"p" * 32,
            "owner_readback_revision": 1,
            "owner_readback_at": now,
            "beneficiary_readback_revision": 1,
            "beneficiary_readback_at": now,
        }
        self.stage["owner_readback_commitment"] = upgrade._offer_commitment(
            41, self.stage,
        )

    def cursor(self, **_kwargs):
        return ItemCursor(self)


class ItemCursor(FakeCursor):
    def execute(self, sql, params):
        normalized = " ".join(sql.split()).upper()
        if ("FROM VAULT_ITEMS WHERE VAULT_ID=%S" in normalized and
                "ORDER BY ID ASC" in normalized):
            assert params == (OWNER["vault_id"], items._MAX_ITEMS + 1)
            self.value = deepcopy(self.db.source)
            return
        if ("SELECT 1 FROM VAULT_ITEMS" in normalized and
                "TITLE_LOOKUP_HASH IS NULL" in normalized):
            assert params == (BENEFICIARY_ID,)
            self.value = {"has_unindexed": 1} if self.db.unindexed_destination else None
            return
        if ("FROM LINKED_INHERITANCE_V2_ITEM_COPIES" in normalized and
                "JOIN VAULT_ITEMS" not in normalized):
            assert params == (41,)
            self.value = deepcopy(self.db.copies)
            return
        if ("FROM LINKED_INHERITANCE_V2_ITEM_COPIES C" in normalized and
                "JOIN VAULT_ITEMS V" in normalized):
            assert params == (41,)
            self.value = [{
                **copy,
                "destination_vault_id":
                    self.db.destination[copy["beneficiary_item_id"]]["vault_id"],
                **{field: self.db.destination[
                    copy["beneficiary_item_id"]][field]
                   for field in (*items._ITEM_FIELDS, "title_lookup_hash")},
            } for copy in self.db.copies]
            return
        if normalized.startswith("INSERT INTO VAULT_ITEMS"):
            vault_id, type_ct, service_ct, payload_ct, title_hash = params
            item_id = self.db.next_item_id
            self.db.next_item_id += 1
            self.db.destination[item_id] = {
                "vault_id": vault_id,
                "item_type_ciphertext": type_ct,
                "service_ciphertext": service_ct,
                "payload_ciphertext": payload_ct,
                "title_lookup_hash": title_hash,
            }
            self.value = {"id": item_id}
            return
        if normalized.startswith("INSERT INTO LINKED_INHERITANCE_V2_ITEM_COPIES"):
            (link_id, source_id, beneficiary_id, beneficiary_item_id,
             revision, inventory, row_hash) = params
            assert link_id == 41
            self.db.copies.append({
                "source_item_id": source_id,
                "beneficiary_item_id": beneficiary_item_id,
                "beneficiary_vault_id": beneficiary_id,
                "stage_revision": revision,
                "source_inventory_sha256": inventory,
                "source_row_sha256": row_hash,
            })
            self.value = None
            return
        super().execute(sql, params)

    def fetchall(self):
        return self.value


@pytest.fixture
def ready(monkeypatch):
    for name in (
        upgrade.FLAG_NAME, upgrade.KEYCHECK_FLAG_NAME,
        upgrade.RELEASE_READBACK_FLAG_NAME, upgrade.READBACK_PROOF_FLAG_NAME,
        "VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED",
        items.FLAG_NAME,
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setattr(upgrade, "zk_beneficiary_v2_enabled", lambda: True)
    db = ItemDb()
    monkeypatch.setattr(items, "get_db", lambda: db)
    monkeypatch.setattr(items, "enforce_export_rate_limit", mock.Mock())
    monkeypatch.setattr(items, "require_content_write", mock.Mock())
    return db


def _copy_payload(db: ItemDb, exported: dict) -> items.CopyLinkedV2Item:
    return items.CopyLinkedV2Item(
        beneficiary_link_id=41,
        source_item_id=7,
        stage_revision=1,
        offer_commitment=db.stage["owner_readback_commitment"],
        source_inventory_sha256=exported["source_inventory_sha256"],
        source_row_sha256=exported["items"][0]["source_row_sha256"],
        item_type_ciphertext=items._b64(_ct(4, 42)),
        service_ciphertext=items._b64(_ct(5, 42)),
        payload_ciphertext=items._b64(_ct(6, 80)),
        title_lookup_hash=items._b64(b"h" * 32),
        content_scope="saved_items_only",
    )


def test_linked_item_routes_are_default_off_and_reject_plaintext(
        ready, monkeypatch):
    db = ready
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    payload = _copy_payload(db, exported)
    with pytest.raises(HTTPException) as owner:
        items.export_linked_v2_items(41, OWNER)
    assert owner.value.status_code == 404
    monkeypatch.delenv(items.FLAG_NAME)
    with pytest.raises(HTTPException) as off:
        items.export_linked_v2_items(41, BENEFICIARY)
    assert off.value.status_code == 404
    with pytest.raises(ValidationError):
        items.CopyLinkedV2Item(**{
            **payload.model_dump(), "pin": "123456",
        })
    with pytest.raises(ValidationError):
        items.CopyLinkedV2Item(**{
            **payload.model_dump(), "service": "private title",
        })


def test_exact_inventory_copy_retry_and_destination_readback(ready):
    db = ready
    source_before = deepcopy(db.source)
    old_link = deepcopy(db.link)
    old_credential = deepcopy(db.credential)
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    assert exported["content_scope"] == "saved_items_only"
    assert exported["owner_content_complete"] is False
    assert exported["item_count"] == 1
    assert exported["ciphertext_bytes"] == 120
    assert len(exported["source_inventory_sha256"]) == 43
    empty = items.readback_linked_v2_item_copies(
        41, exported["source_inventory_sha256"], BENEFICIARY,
    )
    assert empty["all_items_copied"] is False
    assert empty["copies"] == []
    payload = _copy_payload(db, exported)
    first = items.copy_linked_v2_item(payload, BENEFICIARY)
    assert first["created"] is True
    again = items.copy_linked_v2_item(payload, BENEFICIARY)
    assert again["created"] is False
    assert again["beneficiary_item_id"] == first["beneficiary_item_id"]
    assert len(db.destination) == len(db.copies) == 1
    readback = items.readback_linked_v2_item_copies(
        41, exported["source_inventory_sha256"], BENEFICIARY,
    )
    assert readback["all_items_copied"] is True
    assert readback["copies"][0]["item_type_ciphertext"] == (
        payload.item_type_ciphertext
    )
    assert readback["copies"][0]["title_lookup_hash"] == (
        payload.title_lookup_hash
    )
    assert db.source == source_before
    assert db.link == old_link
    assert db.credential == old_credential


def test_revoked_stale_and_missing_receipt_reject_before_copy(ready):
    db = ready
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    payload = _copy_payload(db, exported)
    db.link["status"] = "revoked"
    with pytest.raises(HTTPException) as revoked:
        items.copy_linked_v2_item(payload, BENEFICIARY)
    assert revoked.value.status_code == 404
    db.link["status"] = "linked"
    db.stage["beneficiary_readback_revision"] = None
    with pytest.raises(HTTPException) as no_receipt:
        items.copy_linked_v2_item(payload, BENEFICIARY)
    assert no_receipt.value.status_code == 409
    db.stage["beneficiary_readback_revision"] = 1
    db.source[0]["payload_ciphertext"] = _ct(9)
    with pytest.raises(HTTPException) as stale:
        items.copy_linked_v2_item(payload, BENEFICIARY)
    assert stale.value.status_code == 409
    assert db.destination == {}


def test_copy_readback_stops_after_source_change_or_revoke(ready):
    db = ready
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    items.copy_linked_v2_item(_copy_payload(db, exported), BENEFICIARY)
    db.source[0]["payload_ciphertext"] = _ct(8)
    with pytest.raises(HTTPException) as stale:
        items.readback_linked_v2_item_copies(
            41, exported["source_inventory_sha256"], BENEFICIARY,
        )
    assert stale.value.status_code == 409
    db.source[0]["payload_ciphertext"] = _ct(3)
    db.link["status"] = "revoked"
    with pytest.raises(HTTPException) as revoked:
        items.readback_linked_v2_item_copies(
            41, exported["source_inventory_sha256"], BENEFICIARY,
        )
    assert revoked.value.status_code == 404
    assert len(db.destination) == 1  # Existing copy is preserved.


def test_legacy_or_oversized_owner_source_fails_closed(ready):
    db = ready
    db.source[0]["has_legacy"] = True
    with pytest.raises(HTTPException) as legacy:
        items.export_linked_v2_items(41, BENEFICIARY)
    assert legacy.value.status_code == 409
    db.source[0]["has_legacy"] = False
    db.source = [
        {**db.source[0], "id": number}
        for number in range(1, items._MAX_ITEMS + 2)
    ]
    with pytest.raises(HTTPException) as many:
        items.export_linked_v2_items(41, BENEFICIARY)
    assert many.value.status_code == 409


def test_unindexed_destination_or_oversized_copy_rejects_before_insert(ready):
    db = ready
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    payload = _copy_payload(db, exported)
    db.unindexed_destination = True
    with pytest.raises(HTTPException) as unindexed:
        items.copy_linked_v2_item(payload, BENEFICIARY)
    assert unindexed.value.status_code == 409
    db.unindexed_destination = False
    too_large = payload.model_copy(update={
        "payload_ciphertext": items._b64(_ct(6, 5000)),
    })
    with pytest.raises(HTTPException) as oversized:
        items.copy_linked_v2_item(too_large, BENEFICIARY)
    assert oversized.value.status_code == 409
    assert db.destination == {}
