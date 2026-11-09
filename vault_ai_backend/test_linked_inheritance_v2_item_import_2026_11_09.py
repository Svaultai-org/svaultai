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
        self.previews = {}
        self.dependents = False
        self.references = [
            {"table_name": table, "column_names": [column]}
            for table, column in sorted(items._ITEM_REFERENCE_COLUMNS)
        ]
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
        self._before = (
            deepcopy(self.destination), deepcopy(self.copies),
            deepcopy(self.previews), self.next_item_id,
        )
        return ItemCursor(self)

    def commit(self):
        super().commit()
        self._before = None

    def rollback(self):
        if self._before is not None:
            (self.destination, self.copies, self.previews,
             self.next_item_id) = self._before
        self._before = None


class ItemCursor(FakeCursor):
    def execute(self, sql, params):
        normalized = " ".join(sql.split()).upper()
        if "FROM VAULTS" in normalized and "ORDER BY VAULT_ID FOR UPDATE" in normalized:
            self.value = [{"vault_id": OWNER["vault_id"]},
                          {"vault_id": BENEFICIARY_ID}]
            return
        if "FROM PG_CONSTRAINT" in normalized:
            self.value = deepcopy(self.db.references)
            return
        if "AS HAS_DEPENDENTS" in normalized:
            self.value = {"has_dependents": self.db.dependents}
            return
        if normalized.startswith("INSERT INTO LINKED_INHERITANCE_V2_ITEM_RESTART_PREVIEWS"):
            (token_hash, link_id, beneficiary_id, revision, offer,
             old_inventory, current_inventory, copies_hash, count, expiry) = params
            self.db.previews[token_hash] = {
                "old_link_id": link_id,
                "beneficiary_vault_id": beneficiary_id,
                "stage_revision": revision,
                "offer_commitment": offer,
                "old_source_inventory_sha256": old_inventory,
                "current_source_inventory_sha256": current_inventory,
                "copies_sha256": copies_hash,
                "copy_count": count,
                "expires_at": expiry,
                "consumed_at": None,
            }
            self.value = None
            return
        if "FROM LINKED_INHERITANCE_V2_ITEM_RESTART_PREVIEWS" in normalized:
            token_hash, link_id, beneficiary_id = params
            preview = self.db.previews.get(token_hash)
            self.value = deepcopy(preview) if (
                preview and preview["old_link_id"] == link_id and
                preview["beneficiary_vault_id"] == beneficiary_id and
                preview["consumed_at"] is None and
                preview["expires_at"] > datetime.now(timezone.utc)
            ) else None
            return
        if normalized.startswith("UPDATE LINKED_INHERITANCE_V2_ITEM_RESTART_PREVIEWS"):
            self.db.previews[params[0]]["consumed_at"] = datetime.now(timezone.utc)
            self.value = None
            return
        if normalized.startswith("DELETE FROM VAULT_ITEMS"):
            ids, vault_id = params
            removed = []
            for item_id in ids:
                if self.db.destination.get(item_id, {}).get("vault_id") == vault_id:
                    del self.db.destination[item_id]
                    self.db.copies = [c for c in self.db.copies
                                      if c["beneficiary_item_id"] != item_id]
                    removed.append({"id": item_id})
            self.value = removed
            return
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
                **self.db.destination[copy["beneficiary_item_id"]],
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
                "item_type": None,
                "service": None,
                "encrypted_data": None,
                "title_revision": 0,
                "legacy_item_rename_active": False,
            }
            self.value = {"id": item_id, "title_revision": 0,
                          "legacy_item_rename_active": False}
            return
        if normalized.startswith("INSERT INTO LINKED_INHERITANCE_V2_ITEM_COPIES"):
            (link_id, source_id, beneficiary_id, beneficiary_item_id,
             revision, inventory, row_hash, destination_hash) = params
            assert link_id == 41
            self.db.copies.append({
                "source_item_id": source_id,
                "beneficiary_item_id": beneficiary_item_id,
                "beneficiary_vault_id": beneficiary_id,
                "stage_revision": revision,
                "source_inventory_sha256": inventory,
                "source_row_sha256": row_hash,
                "destination_ciphertext_sha256": destination_hash,
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
        "VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_RESTART_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setattr(upgrade, "zk_beneficiary_v2_enabled", lambda: True)
    db = ItemDb()
    monkeypatch.setattr(items, "get_db", lambda: db)
    monkeypatch.setattr(items, "enforce_export_rate_limit", mock.Mock())
    monkeypatch.setattr(items, "require_content_write", mock.Mock())
    monkeypatch.setattr(items, "consume_recent_zk_proof_on_cursor", mock.Mock())
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


def _prepared_restart(db: ItemDb) -> dict:
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    items.copy_linked_v2_item(_copy_payload(db, exported), BENEFICIARY)
    db.source[0]["payload_ciphertext"] = _ct(9)
    return items.prepare_linked_v2_item_restart(41, BENEFICIARY)


def _confirm_restart(preview: dict) -> items.ConfirmLinkedV2ItemRestart:
    return items.ConfirmLinkedV2ItemRestart(
        beneficiary_link_id=preview["beneficiary_link_id"],
        restart_token=preview["restart_token"],
        stage_revision=preview["stage_revision"],
        offer_commitment=preview["offer_commitment"],
        old_source_inventory_sha256=preview["old_source_inventory_sha256"],
        current_source_inventory_sha256=preview["current_source_inventory_sha256"],
        copies_sha256=preview["copies_sha256"],
        copy_count=preview["copy_count"],
        confirmation="DELETE_UNCHANGED_INHERITED_COPIES",
        zk_proof_token="synthetic-fresh-proof",
    )


def test_restart_requires_separate_flag_explicit_confirmation_and_fresh_proof(
        ready, monkeypatch):
    db = ready
    preview = _prepared_restart(db)
    payload = _confirm_restart(preview)
    with pytest.raises(ValidationError):
        items.ConfirmLinkedV2ItemRestart(**{
            **payload.model_dump(), "confirmation": "yes",
        })
    with pytest.raises(ValidationError):
        items.ConfirmLinkedV2ItemRestart(**{
            **payload.model_dump(), "pin": "123456",
        })
    monkeypatch.delenv("VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_RESTART_ENABLED")
    with pytest.raises(HTTPException) as off:
        items.confirm_linked_v2_item_restart(payload, BENEFICIARY)
    assert off.value.status_code == 404
    assert len(db.destination) == len(db.copies) == 1


def test_explicit_restart_removes_only_unchanged_beneficiary_copy(ready):
    db = ready
    old_link = deepcopy(db.link)
    old_credential = deepcopy(db.credential)
    preview = _prepared_restart(db)
    new_source = deepcopy(db.source)
    assert preview["copy_count"] == 1
    assert preview["owner_items_preserved"] is True
    assert preview["legacy_package_preserved"] is True
    assert len(db.destination) == len(db.copies) == 1
    result = items.confirm_linked_v2_item_restart(
        _confirm_restart(preview), BENEFICIARY,
    )
    assert result["removed_unchanged_beneficiary_items"] == 1
    assert db.destination == {}
    assert db.copies == []
    assert db.source == new_source
    assert db.link == old_link
    assert db.credential == old_credential
    items.consume_recent_zk_proof_on_cursor.assert_called_once()
    with pytest.raises(HTTPException) as replay:
        items.confirm_linked_v2_item_restart(
            _confirm_restart(preview), BENEFICIARY,
        )
    assert replay.value.status_code == 409
    fresh = items.export_linked_v2_items(41, BENEFICIARY)
    assert items.copy_linked_v2_item(
        _copy_payload(db, fresh), BENEFICIARY,
    )["created"] is True


@pytest.mark.parametrize("tamper", [
    "edited_ciphertext", "edited_title", "dependent_record",
    "old_copy_without_digest", "new_unknown_fk",
])
def test_restart_refuses_edited_or_referenced_copy_before_preview(ready, tamper):
    db = ready
    exported = items.export_linked_v2_items(41, BENEFICIARY)
    items.copy_linked_v2_item(_copy_payload(db, exported), BENEFICIARY)
    db.source[0]["payload_ciphertext"] = _ct(9)
    if tamper == "edited_ciphertext":
        db.destination[100]["payload_ciphertext"] = _ct(8)
    elif tamper == "edited_title":
        db.destination[100]["title_lookup_hash"] = b"z" * 32
    elif tamper == "dependent_record":
        db.dependents = True
    elif tamper == "old_copy_without_digest":
        db.copies[0]["destination_ciphertext_sha256"] = None
    else:
        db.references.append({
            "table_name": "future_user_content", "column_names": ["item_id"],
        })
    with pytest.raises(HTTPException) as blocked:
        items.prepare_linked_v2_item_restart(41, BENEFICIARY)
    assert blocked.value.status_code == 409
    assert len(db.destination) == len(db.copies) == 1
    assert db.previews == {}


@pytest.mark.parametrize("tamper", [
    "source_changed", "destination_edited", "dependent_added",
    "stage_changed", "link_revoked", "preview_expired",
])
def test_restart_confirm_rechecks_all_state_before_deletion(ready, tamper):
    db = ready
    preview = _prepared_restart(db)
    if tamper == "source_changed":
        db.source[0]["payload_ciphertext"] = _ct(10)
    elif tamper == "destination_edited":
        db.destination[100]["payload_ciphertext"] = _ct(8)
    elif tamper == "dependent_added":
        db.dependents = True
    elif tamper == "stage_changed":
        db.stage["stage_revision"] = 2
    elif tamper == "link_revoked":
        db.link["status"] = "revoked"
    else:
        for value in db.previews.values():
            value["expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(HTTPException):
        items.confirm_linked_v2_item_restart(
            _confirm_restart(preview), BENEFICIARY,
        )
    assert len(db.destination) == len(db.copies) == 1
    items.consume_recent_zk_proof_on_cursor.assert_not_called()


def test_restart_rollback_restores_beneficiary_copy_on_late_error(
        ready, monkeypatch):
    db = ready
    preview = _prepared_restart(db)
    original_execute = ItemCursor.execute

    def fail_after_delete(self, sql, params):
        if "UPDATE linked_inheritance_v2_item_restart_previews" in sql:
            raise RuntimeError("synthetic late transaction failure")
        return original_execute(self, sql, params)

    monkeypatch.setattr(ItemCursor, "execute", fail_after_delete)
    with pytest.raises(RuntimeError):
        items.confirm_linked_v2_item_restart(
            _confirm_restart(preview), BENEFICIARY,
        )
    assert len(db.destination) == len(db.copies) == 1
    assert next(iter(db.previews.values()))["consumed_at"] is None


def test_restart_rejects_wrong_actor_token_and_copy_digest(ready):
    db = ready
    preview = _prepared_restart(db)
    with pytest.raises(HTTPException) as wrong_actor:
        items.prepare_linked_v2_item_restart(41, OWNER)
    assert wrong_actor.value.status_code == 404
    payload = _confirm_restart(preview)
    for altered in (
        payload.model_copy(update={"restart_token": items._b64(b"x" * 32)}),
        payload.model_copy(update={"copies_sha256": items._b64(b"x" * 32)}),
    ):
        with pytest.raises(HTTPException) as denied:
            items.confirm_linked_v2_item_restart(altered, BENEFICIARY)
        assert denied.value.status_code == 409
    assert len(db.destination) == len(db.copies) == 1
    items.consume_recent_zk_proof_on_cursor.assert_not_called()
