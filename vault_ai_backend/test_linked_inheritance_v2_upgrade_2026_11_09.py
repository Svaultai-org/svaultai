"""Synthetic owner-side staging keeps linked legacy inheritance intact."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from routes import linked_inheritance_v2_upgrade_routes as upgrade


OWNER = {"vault_id": "11111111-1111-1111-1111-111111111111", "token_id": "owner"}
BENEFICIARY_ID = "22222222-2222-2222-2222-222222222222"
BENEFICIARY = {"vault_id": BENEFICIARY_ID, "token_id": "beneficiary"}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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
            role = ("PASSER_VAULT_ID=%S" if params == (41, OWNER["vault_id"])
                    else "BENEFICIARY_VAULT_ID=%S")
            self.value = self.db.link if (
                params in ((41, OWNER["vault_id"]), (41, BENEFICIARY_ID))
                and role in normalized
            ) else None
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
                "beneficiary_challenge_hash": None,
                "beneficiary_challenge_revision": None,
                "beneficiary_challenge_expires_at": None,
                "beneficiary_keycheck_revision": None,
                "beneficiary_keycheck_at": None,
            }
            self.value = {"stage_revision": 1}
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES") and \
                "SET BENEFICIARY_CHALLENGE_HASH=%S" in normalized:
            digest, revision, expiry, link_id, current_revision = params
            assert (link_id, current_revision) == (41, self.db.stage["stage_revision"])
            self.db.stage.update({
                "beneficiary_challenge_hash": digest,
                "beneficiary_challenge_revision": revision,
                "beneficiary_challenge_expires_at": expiry,
            })
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES") and \
                "SET BENEFICIARY_KEYCHECK_REVISION=%S" in normalized:
            revision, link_id, current_revision = params
            assert (link_id, current_revision) == (41, self.db.stage["stage_revision"])
            self.db.stage.update({
                "beneficiary_keycheck_revision": revision,
                "beneficiary_keycheck_at": "now",
                "beneficiary_challenge_hash": None,
                "beneficiary_challenge_revision": None,
                "beneficiary_challenge_expires_at": None,
            })
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
                "beneficiary_challenge_hash": None,
                "beneficiary_challenge_revision": None,
                "beneficiary_challenge_expires_at": None,
                "beneficiary_keycheck_revision": None,
                "beneficiary_keycheck_at": None,
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


def _prepared_beneficiary(ready, monkeypatch):
    db, proof = ready
    private = X25519PrivateKey.generate()
    db.pk = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    payload = _payload().model_copy(update={
        "expected_beneficiary_pk_sha256": hashlib.sha256(db.pk).hexdigest(),
    })
    upgrade.stage_linked_v2_package(payload, OWNER)
    monkeypatch.setenv(upgrade.KEYCHECK_FLAG_NAME, "true")
    return db, proof, private, payload


def _solve_challenge(private, challenge):
    eph = _unb64(challenge["challenge_ephemeral_pk"])
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=eph,
        info=upgrade._KEYCHECK_INFO,
    ).derive(private.exchange(X25519PublicKey.from_public_bytes(eph)))
    aad = upgrade._challenge_aad(
        challenge["beneficiary_link_id"], challenge["stage_revision"],
        challenge["offer_commitment"],
    )
    secret = AESGCM(key).decrypt(
        _unb64(challenge["challenge_nonce"]),
        _unb64(challenge["challenge_ciphertext"]), aad,
    )
    assert len(secret) == 32
    return upgrade.CompleteBeneficiaryKeyCheck(
        beneficiary_link_id=challenge["beneficiary_link_id"],
        stage_revision=challenge["stage_revision"],
        offer_commitment=challenge["offer_commitment"],
        challenge_secret=_b64(secret),
        expected_beneficiary_pk_sha256=challenge["beneficiary_pk_sha256"],
        zk_proof_token="synthetic-beneficiary-proof",
    )


def test_beneficiary_keycheck_disabled_separately_from_stage(ready, monkeypatch):
    db, _, _, _ = _prepared_beneficiary(ready, monkeypatch)
    monkeypatch.delenv(upgrade.KEYCHECK_FLAG_NAME)
    with pytest.raises(HTTPException) as off:
        upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    assert off.value.status_code == 404
    assert db.stage["beneficiary_challenge_hash"] is None


def test_beneficiary_proves_own_private_key_without_old_link_mutation(
        ready, monkeypatch):
    db, proof, private, _ = _prepared_beneficiary(ready, monkeypatch)
    old_link, old_credential = deepcopy(db.link), deepcopy(db.credential)
    challenge = upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    assert challenge["stage_revision"] == 1
    assert "encrypted_payload" not in challenge
    assert "wrapped_key" not in challenge
    assert "pin" not in challenge
    response = _solve_challenge(private, challenge)
    assert response.challenge_secret not in str(db.queries)
    result = upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert result["beneficiary_key_possession_confirmed"] is True
    assert result["package_decryption_verified"] is False
    assert db.stage["beneficiary_keycheck_revision"] == 1
    assert db.stage["beneficiary_challenge_hash"] is None
    assert db.link == old_link and db.credential == old_credential
    assert proof.call_count == 2  # Owner stage and beneficiary completion.
    with pytest.raises(HTTPException) as replay:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert replay.value.status_code == 409
    assert proof.call_count == 2


def test_keycheck_rejects_wrong_actor_expiry_and_stage_replacement(
        ready, monkeypatch):
    db, proof, private, payload = _prepared_beneficiary(ready, monkeypatch)
    with pytest.raises(HTTPException):
        upgrade.issue_beneficiary_key_challenge(41, OWNER)
    challenge = upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    response = _solve_challenge(private, challenge)
    db.stage["beneficiary_challenge_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    with pytest.raises(HTTPException) as expired:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert expired.value.status_code == 409
    assert proof.call_count == 1
    db.stage["beneficiary_challenge_expires_at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    )
    upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert db.stage["beneficiary_keycheck_revision"] == 1
    changed = payload.model_copy(update={
        "expected_stage_revision": 1,
        "encrypted_payload": _b64(b"z" * 48),
    })
    upgrade.stage_linked_v2_package(changed, OWNER)
    assert db.stage["stage_revision"] == 2
    assert db.stage["beneficiary_keycheck_revision"] is None
    with pytest.raises(HTTPException) as stale:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert stale.value.status_code == 409
    assert proof.call_count == 3


def test_keycheck_models_reject_pin_and_wrong_beneficiary_key(ready, monkeypatch):
    db, proof, private, _ = _prepared_beneficiary(ready, monkeypatch)
    challenge = upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    with pytest.raises(ValidationError):
        upgrade.CompleteBeneficiaryKeyCheck(**{
            **_solve_challenge(private, challenge).model_dump(),
            "pin": "synthetic-only",
        })
    response = _solve_challenge(private, challenge).model_copy(update={
        "challenge_secret": _b64(b"wrong" * 6 + b"!!"),
    })
    with pytest.raises(HTTPException) as wrong:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert wrong.value.status_code == 409
    assert db.stage["beneficiary_keycheck_revision"] is None
    assert proof.call_count == 1


def test_keycheck_fails_when_link_or_registered_key_changes(ready, monkeypatch):
    db, proof, private, _ = _prepared_beneficiary(ready, monkeypatch)
    challenge = upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    response = _solve_challenge(private, challenge)
    db.pk = b"q" * 32
    with pytest.raises(HTTPException) as changed_key:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert changed_key.value.status_code == 409
    db.pk = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    db.link["cooldown_ends_at"] = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as active_link:
        upgrade.complete_beneficiary_key_check(response, BENEFICIARY)
    assert active_link.value.status_code == 409
    assert db.stage["beneficiary_keycheck_revision"] is None
    assert proof.call_count == 1
