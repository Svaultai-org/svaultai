"""Synthetic owner-side staging keeps linked legacy inheritance intact."""

from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import linked_inheritance_v2_upgrade_routes as upgrade


OWNER = {"vault_id": "11111111-1111-1111-1111-111111111111", "token_id": "owner"}
BENEFICIARY_ID = "22222222-2222-2222-2222-222222222222"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class FakeDb:
    def __init__(self):
        self.link = {
            "id": 41, "passer_vault_id": OWNER["vault_id"],
            "beneficiary_vault_id": BENEFICIARY_ID,
            "passer_label": "synthetic-old-label",
            "passer_label_ciphertext": None,
            "wrapped_vault_key": "synthetic-old-pin-wrap",
            "status": "linked", "pairing_state": "credentials_saved",
            "transfer_requested_at": None, "transfer_executes_at": None,
            "access_requested_at": None, "cooldown_ends_at": None,
            "decision_at": None,
        }
        self.credential = {
            "id": 91, "crypto_version": 1,
            "encrypted_payload": b"old-encrypted-credential",
            "payload_nonce": b"old-nonce",
            "wrapped_key": b"old-wrapped-key",
            "wrapping_ephemeral_pk": b"old-ephemeral-key",
            "wrapping_nonce": b"old-wrap-nonce",
            "state": "credentials_saved",
        }
        self.pk = bytes(range(32))
        self.stage = None
        self.queries = []
        self.commits = 0

    def cursor(self, **_kwargs):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.value = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split()).upper()
        self.db.queries.append((normalized, params))
        if "FROM BENEFICIARY_LINKS" in normalized:
            self.value = self.db.link if params == (41, OWNER["vault_id"]) else None
        elif "FROM INHERITANCE_CREDENTIALS" in normalized:
            self.value = self.db.credential
        elif "FROM VAULTS" in normalized:
            self.value = {
                "pk_vault_public": self.db.pk, "vault_handle": b"synthetic",
                "opaque_registration_record": b"synthetic",
                "wrapped_mvk": b"synthetic",
            }
        elif (normalized.startswith("SELECT ") and
              "FROM BENEFICIARY_LINK_V2_UPGRADES" in normalized):
            self.value = self.db.stage
        elif normalized.startswith("INSERT INTO BENEFICIARY_LINK_V2_UPGRADES"):
            (link_id, owner_id, beneficiary_id, snapshot, pk_hash,
             encrypted, nonce, wrapped, eph, wrap_nonce) = params
            self.db.stage = {
                "old_link_id": link_id,
                "owner_vault_id": owner_id,
                "beneficiary_vault_id": beneficiary_id,
                "old_source_snapshot": snapshot,
                "beneficiary_pk_sha256": pk_hash,
                "encrypted_payload": encrypted,
                "payload_nonce": nonce,
                "wrapped_key": wrapped,
                "wrapping_ephemeral_pk": eph,
                "wrapping_nonce": wrap_nonce,
                "stage_revision": 1, "state": "staged",
            }
            self.value = {"stage_revision": 1}
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES"):
            (snapshot, pk_hash, encrypted, nonce, wrapped, eph, wrap_nonce,
             link_id, owner_id, expected_revision) = params
            assert (link_id, owner_id, expected_revision) == (
                41, OWNER["vault_id"], self.db.stage["stage_revision"],
            )
            self.db.stage.update({
                "old_source_snapshot": snapshot,
                "beneficiary_pk_sha256": pk_hash,
                "encrypted_payload": encrypted,
                "payload_nonce": nonce,
                "wrapped_key": wrapped,
                "wrapping_ephemeral_pk": eph,
                "wrapping_nonce": wrap_nonce,
                "stage_revision": self.db.stage["stage_revision"] + 1,
            })
            self.value = {"stage_revision": self.db.stage["stage_revision"]}
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.value


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv(upgrade.FLAG_NAME, "true")
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db = FakeDb()
    proof = mock.Mock()
    monkeypatch.setattr(upgrade, "get_db", lambda: db)
    monkeypatch.setattr(upgrade, "require_content_write", mock.Mock())
    monkeypatch.setattr(upgrade, "consume_recent_zk_proof_on_cursor", proof)
    return db, proof


def _payload(*, expected_revision=None, encrypted=b"n" * 48):
    return upgrade.StageLinkedV2Package(
        beneficiary_link_id=41,
        crypto_version=2,
        expected_beneficiary_pk_sha256=hashlib.sha256(bytes(range(32))).hexdigest(),
        expected_stage_revision=expected_revision,
        zk_proof_token="synthetic-proof",
        encrypted_payload=_b64(encrypted),
        payload_nonce=_b64(b"a" * 12),
        wrapped_key=_b64(b"b" * 48),
        wrapping_ephemeral_pk=_b64(b"c" * 32),
        wrapping_nonce=_b64(b"d" * 12),
    )


def test_stage_off_by_default_and_rejects_pin_field(monkeypatch):
    monkeypatch.delenv(upgrade.FLAG_NAME, raising=False)
    monkeypatch.setattr(upgrade, "get_db", lambda: pytest.fail("DB reached"))
    with pytest.raises(HTTPException) as off:
        upgrade.stage_linked_v2_package(_payload(), OWNER)
    assert off.value.status_code == 404
    with pytest.raises(ValidationError):
        upgrade.StageLinkedV2Package(**{
            **_payload().model_dump(), "pin": "synthetic-123456",
        })


def test_stage_and_readback_preserve_old_link_and_package(ready):
    db, proof = ready
    old_link, old_credential = deepcopy(db.link), deepcopy(db.credential)
    staged = upgrade.stage_linked_v2_package(_payload(), OWNER)
    assert staged["state"] == "staged"
    assert staged["legacy_link_unchanged"] is True
    assert staged["stage_revision"] == 1
    readback = upgrade.readback_linked_v2_package(41, OWNER)
    assert readback["encrypted_payload"] == _payload().encrypted_payload
    assert readback["old_source_snapshot"] == staged["old_source_snapshot"]
    assert db.link == old_link
    assert db.credential == old_credential
    assert db.commits == 1
    assert proof.call_count == 1
    assert all(not sql.startswith((
        "UPDATE BENEFICIARY_LINKS", "DELETE FROM BENEFICIARY_LINKS",
        "UPDATE INHERITANCE_CREDENTIALS",
    )) for sql, _ in db.queries)
    assert "synthetic-123456" not in str(db.queries)


def test_exact_retry_is_idempotent_and_changed_package_needs_revision(ready):
    db, proof = ready
    first = upgrade.stage_linked_v2_package(_payload(), OWNER)
    second = upgrade.stage_linked_v2_package(_payload(), OWNER)
    assert second["stage_revision"] == first["stage_revision"] == 1
    with pytest.raises(HTTPException) as conflict:
        upgrade.stage_linked_v2_package(_payload(encrypted=b"z" * 48), OWNER)
    assert conflict.value.status_code == 409
    replaced = upgrade.stage_linked_v2_package(
        _payload(expected_revision=1, encrypted=b"z" * 48), OWNER,
    )
    assert replaced["stage_revision"] == 2
    assert db.link["wrapped_vault_key"] == "synthetic-old-pin-wrap"
    assert db.credential["crypto_version"] == 1
    assert proof.call_count == 3


def test_changed_old_link_or_beneficiary_key_fails_closed(ready):
    db, proof = ready
    upgrade.stage_linked_v2_package(_payload(), OWNER)
    db.link["transfer_executes_at"] = "future"
    with pytest.raises(HTTPException) as in_flight:
        upgrade.readback_linked_v2_package(41, OWNER)
    assert in_flight.value.status_code == 409
    db.link["transfer_executes_at"] = None
    db.pk = b"x" * 32
    with pytest.raises(HTTPException) as changed:
        upgrade.readback_linked_v2_package(41, OWNER)
    assert changed.value.status_code == 409
    assert proof.call_count == 1


def test_key_mismatch_blocks_before_proof_or_write(ready):
    db, proof = ready
    wrong = _payload().model_copy(
        update={"expected_beneficiary_pk_sha256": "0" * 64},
    )
    with pytest.raises(HTTPException) as changed:
        upgrade.stage_linked_v2_package(wrong, OWNER)
    assert changed.value.status_code == 409
    assert db.stage is None
    proof.assert_not_called()


def test_beneficiary_cannot_read_staged_owner_package(ready):
    db, _ = ready
    upgrade.stage_linked_v2_package(_payload(), OWNER)
    with pytest.raises(HTTPException) as denied:
        upgrade.readback_linked_v2_package(
            41, {"vault_id": BENEFICIARY_ID, "token_id": "beneficiary"},
        )
    assert denied.value.status_code == 409
    assert db.stage is not None


def test_linked_old_link_without_credential_can_stage_without_creating_one(ready):
    db, _ = ready
    db.link["pairing_state"] = "paired_no_credentials"
    db.credential = None
    staged = upgrade.stage_linked_v2_package(_payload(), OWNER)
    assert staged["state"] == "staged"
    assert db.credential is None
    assert db.link["wrapped_vault_key"] == "synthetic-old-pin-wrap"
