"""Synthetic owner upgrade contract; no account or invitation is touched."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routes import beneficiary_pending_upgrade_routes as route


VAULT = "00000000-0000-0000-0000-000000000007"
PRINCIPAL = {"vault_id": VAULT, "token_id": "synthetic-session"}
LABEL = base64.urlsafe_b64encode(bytes(range(30))).rstrip(b"=").decode()


class _Db:
    def __init__(self):
        self.old = {
            "id": 7, "passer_vault_id": VAULT,
            "beneficiary_vault_id": None, "passer_label": "Family",
            "passer_label_ciphertext": None,
            "wrapped_vault_key": "synthetic-old-pin-wrap",
            "status": "pairing_pending", "pairing_state": "paired_no_credentials",
            "pairing_code_hash": "old-code-hash",
            "pairing_expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
            "transfer_requested_at": None, "transfer_executes_at": None,
            "access_requested_at": None, "cooldown_ends_at": None,
            "decision_at": None,
        }
        self.new = None
        self.binding = None
        self.active_package = False
        self.answer = None
        self.rowcount = 0
        self.commits = 0
        self.rollbacks = 0
        self.proofs = []
        self.receipt_digest = None

    def cursor(self, **_kwargs):
        return self

    def execute(self, sql, args=()):
        q = " ".join(sql.lower().split())
        self.answer = None
        self.rowcount = 0
        if q.startswith("select 1 from inheritance_credentials"):
            self.answer = {"exists": 1} if self.active_package else None
        elif q.startswith("select new_link_id from beneficiary_pending_upgrades"):
            self.answer = ({"new_link_id": self.binding["new_link_id"]}
                           if self.binding else None)
        elif q.startswith("select old_link_id,new_link_id,owner_vault_id"):
            self.answer = self.binding
        elif q.startswith("select") and "from beneficiary_links" in q:
            self.answer = self.old if args[0] == 7 else self.new
        elif q.startswith("insert into beneficiary_links"):
            self.new = {
                "id": 8, "passer_vault_id": args[0],
                "beneficiary_vault_id": None,
                "passer_label_ciphertext": args[1],
                "pairing_code_hash": args[2],
                "pairing_expires_at": args[3],
                "wrapped_vault_key": args[4],
                "status": "pairing_pending",
                "pairing_state": "paired_no_credentials",
            }
            self.answer = {"id": 8}
            self.rowcount = 1
        elif q.startswith("insert into beneficiary_pending_upgrades"):
            self.binding = {
                "old_link_id": args[0], "new_link_id": args[1],
                "owner_vault_id": args[2], "old_source_snapshot": args[3],
            }
            self.rowcount = 1
        elif q.startswith("delete from beneficiary_links"):
            if args[0] == 7 and self.old:
                self.old = None
                self.binding = None  # FK ON DELETE CASCADE
                self.rowcount = 1
            elif args[0] == 8 and self.new:
                self.new = None
                self.binding = None
                self.rowcount = 1
        else:
            raise AssertionError(f"Unexpected SQL: {q}")

    def fetchone(self):
        return self.answer

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def setup(monkeypatch):
    db = _Db()
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "_enabled", lambda: None)
    monkeypatch.setattr(route, "require_content_write", lambda _: None)
    monkeypatch.setattr(route, "_require_zk_owner", lambda *_: None)
    monkeypatch.setattr(route, "generate_pairing_code", lambda: "ABC-DEFG-HJKL")
    monkeypatch.setattr(
        route, "consume_recent_zk_proof_on_cursor",
        lambda proof, _principal, _cur: db.proofs.append(proof),
    )

    def receipt(_kind, _principal, _id, digest):
        db.receipt_digest = digest
        return "session-bound-receipt", datetime.now(timezone.utc) + timedelta(minutes=5)

    monkeypatch.setattr(route, "_new_receipt", receipt)
    monkeypatch.setattr(
        route, "_receipt_valid",
        lambda value, _kind, _principal, _id, digest:
        value == "session-bound-receipt" and digest == db.receipt_digest,
    )
    return db


def _stage():
    return route.PendingUpgradeStage(
        old_link_id=7, passer_label_ciphertext=LABEL,
        zk_proof_token="opaque-stage-proof",
    )


def _retire(readback):
    return route.PendingUpgradeRetire(
        old_link_id=7, new_link_id=8,
        old_source_snapshot=readback["old_source_snapshot"],
        readback_receipt=readback["readback_receipt"],
        client_verified_exact_bytes=True,
        zk_proof_token="opaque-retire-proof",
    )


def test_stage_readback_and_retire_preserve_then_remove_exact_old_row(setup):
    staged = route.stage_pending_upgrade(_stage(), PRINCIPAL)
    assert staged["new_link_id"] == 8
    assert staged["pairing_code"] == "ABC-DEFG-HJKL"
    assert setup.old is not None
    assert setup.new is not None
    assert setup.proofs == ["opaque-stage-proof"]

    readback = route.readback_pending_upgrade(7, PRINCIPAL)
    assert readback["passer_label_ciphertext"] == LABEL
    assert readback["pairing_code_hash"] == route.hash_pairing_code(
        staged["pairing_code"])
    assert setup.old is not None

    retired = route.retire_pending_upgrade(_retire(readback), PRINCIPAL)
    assert retired == {"old_link_id": 7, "new_link_id": 8, "retired": True}
    assert setup.old is None
    assert setup.new is not None
    assert setup.proofs == ["opaque-stage-proof", "opaque-retire-proof"]


def test_changed_new_row_or_old_source_never_retires_original(setup):
    route.stage_pending_upgrade(_stage(), PRINCIPAL)
    readback = route.readback_pending_upgrade(7, PRINCIPAL)
    setup.new["pairing_code_hash"] = "changed"
    with pytest.raises(HTTPException) as exc:
        route.retire_pending_upgrade(_retire(readback), PRINCIPAL)
    assert exc.value.status_code == 409
    assert setup.old is not None
    assert setup.proofs == ["opaque-stage-proof"]

    setup.new["pairing_code_hash"] = route.hash_pairing_code("ABC-DEFG-HJKL")
    setup.old["wrapped_vault_key"] = "changed-old-wrap"
    with pytest.raises(HTTPException) as exc:
        route.retire_pending_upgrade(_retire(readback), PRINCIPAL)
    assert exc.value.status_code == 409
    assert setup.old is not None


@pytest.mark.parametrize("change", [
    {"status": "linked", "beneficiary_vault_id": VAULT},
    {"status": "transfer_pending"},
])
def test_only_empty_unpaired_old_link_can_stage(setup, change):
    setup.old.update(change)
    with pytest.raises(HTTPException) as exc:
        route.stage_pending_upgrade(_stage(), PRINCIPAL)
    assert exc.value.status_code == 409
    assert setup.new is None
    assert setup.old is not None
    assert setup.proofs == []


def test_old_credential_package_blocks_replacement(setup):
    setup.active_package = True
    with pytest.raises(HTTPException) as exc:
        route.stage_pending_upgrade(_stage(), PRINCIPAL)
    assert exc.value.status_code == 409
    assert setup.old is not None
    assert setup.new is None


def test_lost_stage_response_can_be_restarted_without_touching_old(setup):
    first = route.stage_pending_upgrade(_stage(), PRINCIPAL)
    second = route.stage_pending_upgrade(_stage(), PRINCIPAL)
    assert first["new_link_id"] == second["new_link_id"] == 8
    assert setup.old is not None
    assert setup.new is not None
    assert setup.binding is not None


def test_claimed_stage_cannot_be_replaced_or_abort_old(setup):
    route.stage_pending_upgrade(_stage(), PRINCIPAL)
    setup.new["status"] = "linked"
    setup.new["beneficiary_vault_id"] = VAULT
    with pytest.raises(HTTPException) as exc:
        route.stage_pending_upgrade(_stage(), PRINCIPAL)
    assert exc.value.status_code == 409
    assert setup.old is not None
    assert setup.new is not None


def test_expired_stage_can_be_aborted_without_deleting_old(setup):
    route.stage_pending_upgrade(_stage(), PRINCIPAL)
    setup.new["pairing_expires_at"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    result = route.abort_pending_upgrade(route.PendingUpgradeAbort(
        old_link_id=7, zk_proof_token="opaque-abort-proof",
    ), PRINCIPAL)
    assert result == {"old_link_id": 7, "aborted": True}
    assert setup.old is not None
    assert setup.new is None
    assert setup.binding is None


def test_upgrade_route_is_disabled_without_explicit_server_flag(monkeypatch):
    for name in (
        "VAULTAI_ZK_LEGACY_BENEFICIARY_UPGRADE_ENABLED",
        "VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED",
        "VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as exc:
        route._enabled()
    assert exc.value.status_code == 404
