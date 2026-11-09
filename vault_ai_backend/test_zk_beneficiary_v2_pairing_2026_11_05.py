"""Synthetic V2 pairing checks; no vault data or real database."""

import asyncio
import base64
import inspect
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main
import security_headers
from routes import auth_zk_routes


OWNER = {"vault_id": "11111111-1111-1111-1111-111111111111", "token_id": "owner-session"}
BENEFICIARY = {"vault_id": "22222222-2222-2222-2222-222222222222", "token_id": "ben-session"}
LABEL_CT = base64.urlsafe_b64encode(bytes(range(40))).rstrip(b"=").decode()


class FakeDb:
    def __init__(self):
        self.link = None
        self.inserts = []
        self.commits = 0
        self.public_key = bytes(range(32))

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
        self.row = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).upper()
        if "FROM VAULTS" in normalized:
            self.row = {"vault_handle": b"synthetic", "opaque_registration_record": b"synthetic",
                        "pk_vault_public": self.db.public_key}
        elif "INSERT INTO BENEFICIARY_LINKS" in normalized:
            self.db.inserts.append(params)
            self.db.link = {
                "id": 9, "passer_vault_id": params[0], "status": "pairing_pending",
                "pairing_expires_at": params[3], "wrapped_vault_key": params[4],
            }
            self.row = {"id": 9}
        elif "FROM BENEFICIARY_LINKS" in normalized:
            self.row = self.db.link
        elif "SELECT (NOW() AT TIME ZONE" in normalized:
            self.row = {"now": datetime.now(timezone.utc)}
        elif "UPDATE BENEFICIARY_LINKS" in normalized:
            self.db.link["status"] = "linked"
            self.row = None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.row


def _run(endpoint, payload, principal):
    return asyncio.run(inspect.unwrap(endpoint)(None, payload, principal))


def test_v2_pairing_off_by_default_and_rejects_pin_field(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", raising=False)
    monkeypatch.setattr(main, "get_db", lambda: pytest.fail("DB reached while disabled"))
    payload = main.ZkCreateBeneficiaryRequest(
        passer_label_ciphertext=LABEL_CT, zk_proof_token="proof",
    )
    with pytest.raises(HTTPException) as denied:
        _run(main.beneficiary_zk_create_endpoint, payload, OWNER)
    assert denied.value.status_code == 404
    with pytest.raises(ValidationError):
        main.ZkCreateBeneficiaryRequest(
            passer_label_ciphertext=LABEL_CT, zk_proof_token="proof", pin="123456",
        )
    with pytest.raises(ValidationError):
        main.ZkLinkBeneficiaryRequest(
            pairing_code="synthetic", zk_proof_token="proof", pin="123456",
        )


def test_mixed_pairing_lookup_is_default_off_and_never_accepts_pin(monkeypatch):
    assert security_headers._is_sensitive_path("/beneficiary/pairing-protocol")
    monkeypatch.delenv("VAULTAI_ZK_MIXED_BENEFICIARY_LINK_LOOKUP_ENABLED", raising=False)
    monkeypatch.setattr(main, "get_db", lambda: pytest.fail("DB reached while disabled"))
    payload = main.BeneficiaryPairingProtocolRequest(pairing_code="synthetic")
    with pytest.raises(HTTPException) as denied:
        _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY)
    assert denied.value.status_code == 404
    with pytest.raises(ValidationError):
        main.BeneficiaryPairingProtocolRequest(
            pairing_code="synthetic", pin="synthetic-pin",
        )


def test_mixed_pairing_lookup_selects_protocol_without_using_pin(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_MIXED_BENEFICIARY_LINK_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db = FakeDb()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(main, "verify_vault_pin", lambda *_: pytest.fail("PIN used"))
    db.link = {
        "status": "pairing_pending",
        "pairing_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "wrapped_vault_key": main._ZK_BENEFICIARY_V2_MARKER,
    }
    payload = main.BeneficiaryPairingProtocolRequest(pairing_code="synthetic")
    assert _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY) == {
        "protocol": "private",
    }
    db.link["wrapped_vault_key"] = "synthetic-old-envelope"
    assert _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY) == {
        "protocol": "legacy",
    }
    db.link["pairing_expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY) == {
        "protocol": "unknown",
    }
    db.link["pairing_expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.link["status"] = "linked"
    assert _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY) == {
        "protocol": "unknown",
    }
    db.link = None
    assert _run(main.beneficiary_pairing_protocol_endpoint, payload, BENEFICIARY) == {
        "protocol": "unknown",
    }
    assert db.commits == 0


def test_v2_create_and_link_have_no_server_key_or_pin(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db = FakeDb()
    proof = mock.Mock()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", proof)
    monkeypatch.setattr(main, "verify_vault_pin", lambda *_: pytest.fail("raw PIN verification"))
    created = _run(main.beneficiary_zk_create_endpoint,
                   main.ZkCreateBeneficiaryRequest(
                       passer_label_ciphertext=LABEL_CT, zk_proof_token="owner-proof",
                   ), OWNER)
    assert created["pairing_protocol"] == "zk-beneficiary-v2"
    assert "label" not in created and "pin" not in created
    inserted = db.inserts[0]
    assert inserted[0] == OWNER["vault_id"]
    assert inserted[1] == bytes(range(40))
    assert inserted[4] == main._ZK_BENEFICIARY_V2_MARKER
    assert "123456" not in repr(inserted)
    linked = _run(main.beneficiary_zk_link_endpoint,
                  main.ZkLinkBeneficiaryRequest(
                      pairing_code=created["pairing_code"],
                      zk_proof_token="beneficiary-proof",
                  ), BENEFICIARY)
    assert linked == {"link_id": 9, "status": "linked",
                      "pairing_protocol": "zk-beneficiary-v2"}
    assert db.link["status"] == "linked"
    assert proof.call_args_list == [
        mock.call("owner-proof", OWNER), mock.call("beneficiary-proof", BENEFICIARY),
    ]


def test_v2_requires_x25519_public_key_before_consuming_proof(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db = FakeDb()
    db.public_key = None
    proof = mock.Mock()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", proof)
    with pytest.raises(HTTPException) as denied:
        _run(main.beneficiary_zk_create_endpoint,
             main.ZkCreateBeneficiaryRequest(
                 passer_label_ciphertext=LABEL_CT, zk_proof_token="proof",
             ), OWNER)
    assert denied.value.status_code == 409
    proof.assert_not_called()
    assert db.inserts == []


def test_v2_link_rejects_expired_and_self_pairing(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db = FakeDb()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", mock.Mock())
    db.link = {"id": 9, "passer_vault_id": OWNER["vault_id"],
               "status": "pairing_pending",
               "pairing_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
               "wrapped_vault_key": main._ZK_BENEFICIARY_V2_MARKER}
    payload = main.ZkLinkBeneficiaryRequest(pairing_code="synthetic", zk_proof_token="proof")
    with pytest.raises(HTTPException) as expired:
        _run(main.beneficiary_zk_link_endpoint, payload, BENEFICIARY)
    assert expired.value.status_code == 410
    db.link["pairing_expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    with pytest.raises(HTTPException) as self_link:
        _run(main.beneficiary_zk_link_endpoint, payload, OWNER)
    assert self_link.value.status_code == 400


def test_legacy_link_and_claim_reject_v2_before_pin_verification(monkeypatch):
    db = FakeDb()
    db.link = {"id": 9, "passer_vault_id": OWNER["vault_id"],
               "beneficiary_vault_id": BENEFICIARY["vault_id"],
               "status": "linked",
               "pairing_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
               "wrapped_vault_key": main._ZK_BENEFICIARY_V2_MARKER}
    monkeypatch.setattr(main, "get_db", lambda: db)
    verify = mock.Mock(side_effect=AssertionError("legacy PIN verified"))
    monkeypatch.setattr(main, "verify_vault_pin", verify)
    with pytest.raises(HTTPException) as legacy_link:
        _run(main.beneficiary_link_endpoint,
             main.LinkBeneficiaryRequest(
                 vault_name="", pin="synthetic", pairing_code="synthetic",
             ), BENEFICIARY)
    assert legacy_link.value.status_code == 409
    with pytest.raises(HTTPException) as legacy_claim:
        _run(main.beneficiary_claim_transfer_endpoint,
             main.ClaimTransferRequest(
                 link_id=9, pin="synthetic", inherited_username_lookup="synthetic",
             ), BENEFICIARY)
    assert legacy_claim.value.status_code == 409
    verify.assert_not_called()


@pytest.mark.parametrize(
    "linked_vault,status,cooldown_elapsed,expected_status",
    [
        (OWNER["vault_id"], "transfer_pending", True, 403),
        (BENEFICIARY["vault_id"], "linked", True, 400),
        (BENEFICIARY["vault_id"], "transfer_pending", False, 400),
    ],
)
def test_legacy_claim_checks_link_before_using_pin(
    monkeypatch, linked_vault, status, cooldown_elapsed, expected_status,
):
    db = FakeDb()
    db.link = {
        "id": 9,
        "passer_vault_id": OWNER["vault_id"],
        "beneficiary_vault_id": linked_vault,
        "status": status,
        "transfer_executes_at": datetime.now(timezone.utc) + timedelta(
            days=-1 if cooldown_elapsed else 1,
        ),
        "wrapped_vault_key": "synthetic-old-envelope",
    }
    monkeypatch.setattr(main, "get_db", lambda: db)
    verify = mock.Mock(side_effect=AssertionError("PIN used before link check"))
    monkeypatch.setattr(main, "verify_vault_pin", verify)
    with pytest.raises(HTTPException) as denied:
        _run(main.beneficiary_claim_transfer_endpoint,
             main.ClaimTransferRequest(
                 link_id=9, pin="synthetic", inherited_username_lookup="synthetic",
             ), BENEFICIARY)
    assert denied.value.status_code == expected_status
    verify.assert_not_called()
    assert db.commits == 0
