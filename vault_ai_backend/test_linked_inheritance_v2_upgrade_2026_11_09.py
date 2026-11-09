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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
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
            "id": 91, "owner_vault_id": OWNER["vault_id"],
            "crypto_version": 1,
            "encrypted_payload": b"old-encrypted-credential",
            "payload_nonce": b"old-nonce",
            "wrapped_key": b"old-wrapped-key",
            "wrapping_ephemeral_pk": b"old-ephemeral-key",
            "wrapping_nonce": b"old-wrap-nonce",
            "state": "credentials_saved",
            "released_at": None,
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
                "owner_readback_public_key": None,
                "owner_readback_revision": None,
                "owner_readback_commitment": None,
                "owner_readback_at": None,
                "beneficiary_readback_challenge_hash": None,
                "beneficiary_readback_challenge_revision": None,
                "beneficiary_readback_challenge_expires_at": None,
                "beneficiary_readback_revision": None,
                "beneficiary_readback_at": None,
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
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES") and \
                "SET OWNER_READBACK_PUBLIC_KEY=%S" in normalized:
            public_key, revision, commitment, link_id, current_revision = params
            assert (link_id, current_revision) == (41, self.db.stage["stage_revision"])
            self.db.stage.update({
                "owner_readback_public_key": public_key,
                "owner_readback_revision": revision,
                "owner_readback_commitment": commitment,
                "owner_readback_at": datetime.now(timezone.utc),
            })
            self.value = {"stage_revision": revision}
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES") and \
                "SET BENEFICIARY_READBACK_CHALLENGE_HASH=%S" in normalized:
            digest, revision, expiry, link_id, current_revision = params
            assert (link_id, current_revision) == (41, self.db.stage["stage_revision"])
            self.db.stage.update({
                "beneficiary_readback_challenge_hash": digest,
                "beneficiary_readback_challenge_revision": revision,
                "beneficiary_readback_challenge_expires_at": expiry,
            })
        elif normalized.startswith("UPDATE BENEFICIARY_LINK_V2_UPGRADES") and \
                "SET BENEFICIARY_READBACK_REVISION=%S" in normalized:
            revision, link_id, current_revision = params
            assert (link_id, current_revision) == (41, self.db.stage["stage_revision"])
            now = datetime.now(timezone.utc)
            self.db.stage.update({
                "beneficiary_readback_revision": revision,
                "beneficiary_readback_at": now,
                "beneficiary_readback_challenge_hash": None,
                "beneficiary_readback_challenge_revision": None,
                "beneficiary_readback_challenge_expires_at": None,
            })
            self.value = {"beneficiary_readback_at": now}
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
                "owner_readback_public_key": None,
                "owner_readback_revision": None,
                "owner_readback_commitment": None,
                "owner_readback_at": None,
                "beneficiary_readback_challenge_hash": None,
                "beneficiary_readback_challenge_revision": None,
                "beneficiary_readback_challenge_expires_at": None,
                "beneficiary_readback_revision": None,
                "beneficiary_readback_at": None,
            })
            self.value = {"stage_revision": self.db.stage["stage_revision"]}
        elif normalized.startswith("UPDATE INHERITANCE_CREDENTIALS"):
            released_at, credential_id = params
            assert credential_id == self.db.credential["id"]
            self.db.credential["released_at"] = released_at
            self.db.credential["state"] = "released"
        elif normalized.startswith("UPDATE BENEFICIARY_LINKS"):
            assert params == (41,)
            self.db.link["pairing_state"] = "released"
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


def _keychecked_release_ready(ready, monkeypatch):
    from routes import inheritance_release_routes

    db, proof, private, payload = _prepared_beneficiary(ready, monkeypatch)
    challenge = upgrade.issue_beneficiary_key_challenge(41, BENEFICIARY)
    upgrade.complete_beneficiary_key_check(
        _solve_challenge(private, challenge), BENEFICIARY,
    )
    monkeypatch.setenv(upgrade.RELEASE_READBACK_FLAG_NAME, "true")
    limiter = mock.Mock()
    notify = mock.Mock()
    monkeypatch.setattr(upgrade, "enforce_export_rate_limit", limiter)
    monkeypatch.setattr(inheritance_release_routes, "_notify", notify)
    return db, proof, payload, limiter, notify


def test_released_package_requires_feature_flag_and_beneficiary(ready, monkeypatch):
    release_route = next(
        route for route in upgrade.router.routes
        if route.path == "/inheritance/old-link-v2/{link_id}/released-package"
    )
    assert release_route.methods == {"POST"}
    db, _, _, _, _ = _keychecked_release_ready(ready, monkeypatch)
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    monkeypatch.delenv(upgrade.RELEASE_READBACK_FLAG_NAME)
    with pytest.raises(HTTPException) as off:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert off.value.status_code == 404
    monkeypatch.setenv(upgrade.RELEASE_READBACK_FLAG_NAME, "true")
    with pytest.raises(HTTPException) as outsider:
        upgrade.read_released_linked_v2_package(41, OWNER)
    assert outsider.value.status_code == 404
    assert db.link["pairing_state"] == "approved"


def test_approved_release_returns_same_v2_ciphertext_and_keeps_old_package(
        ready, monkeypatch):
    db, _, payload, limiter, notify = _keychecked_release_ready(
        ready, monkeypatch,
    )
    stable = upgrade._source_snapshot(db.link, db.credential)
    old_link_key = db.link["wrapped_vault_key"]
    old_ciphertext = db.credential["encrypted_payload"]
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    assert upgrade._source_snapshot(db.link, db.credential) == stable
    released = upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert released["crypto_version"] == 2
    assert released["encrypted_payload"] == payload.encrypted_payload
    assert released["wrapped_key"] == payload.wrapped_key
    assert released["pairing_state"] == "released"
    assert released["legacy_package_preserved"] is True
    assert released["package_decryption_verified"] is False
    assert db.link["wrapped_vault_key"] == old_link_key
    assert db.credential["encrypted_payload"] == old_ciphertext
    assert db.link["pairing_state"] == db.credential["state"] == "released"
    limiter.assert_called_once()
    notify.assert_called_once()
    again = upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert again["offer_commitment"] == released["offer_commitment"]
    notify.assert_called_once()


def test_release_rejects_early_cooldown_or_changed_source(ready, monkeypatch):
    db, _, _, limiter, _ = _keychecked_release_ready(ready, monkeypatch)
    db.link["pairing_state"] = "cooldown_active"
    db.link["access_requested_at"] = datetime.now(timezone.utc)
    db.link["cooldown_ends_at"] = (
        datetime.now(timezone.utc) + timedelta(days=30)
    )
    db.credential["state"] = "cooldown_active"
    with pytest.raises(HTTPException) as early:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert early.value.status_code == 409
    db.link["pairing_state"] = "claimable"
    db.credential["state"] = "claimable"
    with pytest.raises(HTTPException) as forged_claim:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert forged_claim.value.status_code == 409
    db.link["cooldown_ends_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.credential["encrypted_payload"] = b"changed-old-source"
    with pytest.raises(HTTPException) as changed:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert changed.value.status_code == 409
    assert db.link["pairing_state"] == "claimable"
    limiter.assert_not_called()


def test_release_rejects_unverified_stage_or_revoked_link(ready, monkeypatch):
    db, _, _, limiter, _ = _keychecked_release_ready(ready, monkeypatch)
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    db.stage["beneficiary_keycheck_revision"] = None
    with pytest.raises(HTTPException) as unverified:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert unverified.value.status_code == 409
    db.stage["beneficiary_keycheck_revision"] = db.stage["stage_revision"]
    db.link["status"] = "revoked"
    with pytest.raises(HTTPException) as revoked:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert revoked.value.status_code == 404
    limiter.assert_not_called()


def test_completed_cooldown_can_release_without_old_credential_retrieval(
        ready, monkeypatch):
    db, _, _, _, _ = _keychecked_release_ready(ready, monkeypatch)
    db.link["pairing_state"] = "claimable"
    db.link["access_requested_at"] = (
        datetime.now(timezone.utc) - timedelta(days=31)
    )
    db.link["cooldown_ends_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    )
    db.credential["state"] = "claimable"
    released = upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert released["pairing_state"] == "released"
    assert db.link["pairing_state"] == "released"


def _registered_readback(ready, monkeypatch):
    db, proof, _, limiter, _ = _keychecked_release_ready(
        ready, monkeypatch,
    )
    monkeypatch.setenv(upgrade.READBACK_PROOF_FLAG_NAME, "true")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    commitment = upgrade._offer_commitment(41, db.stage)
    register = upgrade.RegisterOwnerReadbackVerifier(
        beneficiary_link_id=41,
        stage_revision=1,
        offer_commitment=commitment,
        expected_beneficiary_pk_sha256=hashlib.sha256(db.pk).hexdigest(),
        readback_public_key=_b64(public),
        zk_proof_token="synthetic-owner-proof",
    )
    result = upgrade.register_owner_readback_verifier(register, OWNER)
    assert result["owner_readback_verifier_registered"] is True
    assert result["package_decryption_verified"] is False
    assert db.stage["owner_readback_public_key"] == public
    return db, proof, limiter, private, register


def test_readback_public_key_derivation_matches_client_vector():
    context = "41:2:" + "A" * 43 + ":synthetic-owner:synthetic-beneficiary"
    seed = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=b"svaultai:linked-old-v2-readback-salt:v1",
        info=("svaultai:linked-old-v2-readback-seed:v1:" + context)
        .encode("ascii"),
    ).derive(bytes([27] * 32))
    public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    assert _b64(public) == "L3zXtTlNHP2GsXNfzt7wKbEWHO-aeX_IRb5UkCx2VQk"


def test_readback_proof_off_by_default_and_rejects_raw_key_fields(
        ready, monkeypatch):
    db, _ = ready
    upgrade.stage_linked_v2_package(_payload(), OWNER)
    commitment = upgrade._offer_commitment(41, db.stage)
    register = upgrade.RegisterOwnerReadbackVerifier(
        beneficiary_link_id=41, stage_revision=1,
        offer_commitment=commitment,
        expected_beneficiary_pk_sha256=hashlib.sha256(db.pk).hexdigest(),
        readback_public_key=_b64(b"p" * 32),
        zk_proof_token="synthetic-proof",
    )
    with pytest.raises(HTTPException) as off:
        upgrade.register_owner_readback_verifier(register, OWNER)
    assert off.value.status_code == 404
    with pytest.raises(ValidationError):
        upgrade.RegisterOwnerReadbackVerifier(**{
            **register.model_dump(), "owner_mvk": "synthetic-secret",
        })
    with pytest.raises(ValidationError):
        upgrade.CompleteBeneficiaryReadback(
            beneficiary_link_id=41, stage_revision=1,
            offer_commitment=commitment,
            challenge_nonce=_b64(b"n" * 32),
            signature=_b64(b"s" * 64),
            zk_proof_token="synthetic-proof", pin="123456",
        )


def test_proof_mode_requires_owner_verifier_before_new_release(
        ready, monkeypatch):
    db, _, _, _, _ = _keychecked_release_ready(ready, monkeypatch)
    monkeypatch.setenv(upgrade.READBACK_PROOF_FLAG_NAME, "true")
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    with pytest.raises(HTTPException) as missing:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert missing.value.status_code == 409
    assert db.link["pairing_state"] == db.credential["state"] == "approved"


def test_registered_offer_commitment_rejects_changed_stage_ciphertext(
        ready, monkeypatch):
    db, _, _, _, _ = _registered_readback(ready, monkeypatch)
    db.stage["encrypted_payload"] = b"different-stage-ciphertext"
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    with pytest.raises(HTTPException) as changed:
        upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    assert changed.value.status_code == 409
    assert db.link["pairing_state"] == db.credential["state"] == "approved"


def test_readback_receipt_requires_release_and_valid_stage(
        ready, monkeypatch):
    db, _, limiter, private, register = _registered_readback(
        ready, monkeypatch,
    )
    old_key = db.link["wrapped_vault_key"]
    old_ciphertext = db.credential["encrypted_payload"]
    with pytest.raises(HTTPException) as early:
        upgrade.issue_beneficiary_readback_challenge(41, BENEFICIARY)
    assert early.value.status_code == 409
    assert db.stage["beneficiary_readback_challenge_hash"] is None
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    with pytest.raises(HTTPException) as outsider:
        upgrade.issue_beneficiary_readback_challenge(41, OWNER)
    assert outsider.value.status_code == 404
    challenge = upgrade.issue_beneficiary_readback_challenge(41, BENEFICIARY)
    assert challenge["readback_public_key"] == register.readback_public_key
    assert challenge["package_decryption_verified"] is False
    message = upgrade._readback_message(
        link_id=41, revision=1,
        commitment=register.offer_commitment,
        owner_vault_id=OWNER["vault_id"],
        beneficiary_vault_id=BENEFICIARY_ID,
        nonce=challenge["challenge_nonce"],
    )
    payload = upgrade.CompleteBeneficiaryReadback(
        beneficiary_link_id=41, stage_revision=1,
        offer_commitment=register.offer_commitment,
        challenge_nonce=challenge["challenge_nonce"],
        signature=_b64(private.sign(message)),
        zk_proof_token="synthetic-beneficiary-proof",
    )
    receipt = upgrade.complete_beneficiary_readback_proof(payload, BENEFICIARY)
    assert receipt["package_decryption_verified"] is True
    assert receipt["legacy_package_preserved"] is True
    assert db.stage["beneficiary_readback_revision"] == 1
    assert db.stage["beneficiary_readback_challenge_hash"] is None
    assert db.link["wrapped_vault_key"] == old_key
    assert db.credential["encrypted_payload"] == old_ciphertext
    assert db.link["pairing_state"] == db.credential["state"] == "released"
    with pytest.raises(HTTPException) as replay:
        upgrade.complete_beneficiary_readback_proof(payload, BENEFICIARY)
    assert replay.value.status_code == 409
    assert limiter.call_count == 2  # Released package, then challenge.


def test_readback_proof_rejects_bad_signature_expiry_and_changed_source(
        ready, monkeypatch):
    db, proof, _, _, register = _registered_readback(ready, monkeypatch)
    db.link["pairing_state"] = "approved"
    db.link["decision_at"] = datetime.now(timezone.utc)
    db.credential["state"] = "approved"
    upgrade.read_released_linked_v2_package(41, BENEFICIARY)
    challenge = upgrade.issue_beneficiary_readback_challenge(41, BENEFICIARY)
    payload = upgrade.CompleteBeneficiaryReadback(
        beneficiary_link_id=41, stage_revision=1,
        offer_commitment=register.offer_commitment,
        challenge_nonce=challenge["challenge_nonce"],
        signature=_b64(Ed25519PrivateKey.generate().sign(b"wrong")),
        zk_proof_token="synthetic-beneficiary-proof",
    )
    prior_proofs = proof.call_count
    with pytest.raises(HTTPException) as invalid:
        upgrade.complete_beneficiary_readback_proof(payload, BENEFICIARY)
    assert invalid.value.status_code == 409
    assert proof.call_count == prior_proofs
    db.stage["beneficiary_readback_challenge_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    with pytest.raises(HTTPException) as expired:
        upgrade.complete_beneficiary_readback_proof(payload, BENEFICIARY)
    assert expired.value.status_code == 409
    db.credential["encrypted_payload"] = b"changed-old-source"
    with pytest.raises(HTTPException) as changed:
        upgrade.issue_beneficiary_readback_challenge(41, BENEFICIARY)
    assert changed.value.status_code == 409
