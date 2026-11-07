"""Synthetic owner migration; no real wallet material or network calls."""

import base64
import json

import pytest
from fastapi import HTTPException

from legacy_source_snapshot import source_snapshot
from routes import wallet_v2_routes as route
from routes import crypto_wallet_routes as legacy_wallet_route


VAULT = "00000000-0000-0000-0000-000000000001"
SESSION = "00000000-0000-0000-0000-000000000002"
OTHER_SESSION = "00000000-0000-0000-0000-000000000003"
PRINCIPAL = {"vault_id": VAULT, "token_id": SESSION}
WALLET_ID = "synthetic-wallet-record-1"
LEGACY = {
    "encrypted_data": json.dumps({
        "schema": "crypto_wallet_account_v1",
        "asset": "ETH", "network": "Ethereum Mainnet",
        "publicAddress": "0x0000000000000000000000000000000000000001",
        "walletLabel": "Synthetic wallet",
        "encryptedWalletSecret": "synthetic-inner-ciphertext",
        "backupStatus": "encrypted_backup_saved",
    }),
    "item_type": "crypto_wallet_account", "service": "ETH:ethereum-mainnet",
    "item_type_ciphertext": None, "service_ciphertext": None,
    "payload_ciphertext": None,
}


class FakeDb:
    def __init__(self):
        self.legacy = LEGACY.copy()
        self.wallet = None
        self.commits = 0
        self.proofs = []

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
        self.selected = None
        self.rowcount = 0

    def execute(self, sql, args):
        self.rowcount = 0
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT vault_handle FROM vaults"):
            self.selected = {"vault_handle": "VLT-synthetic"}
        elif normalized.startswith("SELECT encrypted_data,item_type,service"):
            self.selected = self.db.legacy.copy() if self.db.legacy else None
        elif normalized.startswith("SELECT wallet_record_id"):
            self.selected = self.db.wallet.copy() if self.db.wallet else None
        elif normalized.startswith("INSERT INTO wallet_v2_records"):
            self.db.wallet = {
                "wallet_record_id": args[1], "chain": args[2],
                "network": args[3], "asset": args[4],
                "public_address": args[5], "wallet_label": args[6],
                "payload_ciphertext": args[7],
                "envelope_version": "v2", "migration_state": "migration_pending",
                "legacy_item_id": args[8], "legacy_source_snapshot": args[9],
            }
            self.rowcount = 1
        elif normalized.startswith("DELETE FROM vault_items"):
            self.rowcount = 1 if self.db.legacy else 0
            self.db.legacy = None
        elif normalized.startswith("UPDATE wallet_v2_records SET chain="):
            self.rowcount = 1 if self.db.wallet else 0
            if self.db.wallet:
                for key, value in zip((
                    "chain", "network", "asset", "public_address",
                    "wallet_label", "payload_ciphertext",
                    "legacy_source_snapshot",
                ), args[:7]):
                    self.db.wallet[key] = value
        elif normalized.startswith("UPDATE wallet_v2_records SET migration_state="):
            self.rowcount = 1 if self.db.wallet else 0
            if self.db.wallet:
                self.db.wallet["migration_state"] = "v2_verified"
        else:
            raise AssertionError(normalized)

    def fetchone(self):
        return self.selected


@pytest.fixture
def setup(monkeypatch):
    db = FakeDb()
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-wallet-proof-secret-12345678901234567890")
    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_V2_WRITE_ENABLED", "true")
    monkeypatch.setenv("WALLET_V2_MIGRATION_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "require_content_write", lambda _p: None)
    monkeypatch.setattr(route, "require_crypto_access", lambda _p: None)
    monkeypatch.setattr(
        route, "consume_recent_zk_proof",
        lambda proof, principal: db.proofs.append((proof, principal["token_id"])),
    )
    return db


def stage_body(db, ciphertext=b"\x01synthetic-mvk-envelope"):
    return route.WalletV2MigrationStageRequest(
        legacy_item_id=42,
        source_snapshot=source_snapshot(
            "item", db.legacy, vault_id=VAULT, record_id=42,
        ),
        wallet_record_id=WALLET_ID,
        chain="evm", network="ethereum_mainnet", asset="ETH",
        public_address="0x0000000000000000000000000000000000000001",
        wallet_label="Synthetic wallet",
        payload_ciphertext=base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
        envelope_version="v2",
    )


def retire_body(staged, receipt):
    return route.WalletV2MigrationRetireRequest(
        legacy_item_id=42, wallet_record_id=WALLET_ID,
        source_snapshot=staged.source_snapshot,
        readback_receipt=receipt, zk_proof_token="synthetic-opaque-proof",
        client_verified_exact_bytes=True,
    )


def test_exact_readback_then_retire_preserves_old_until_confirmed(setup):
    db = setup
    staged = stage_body(db)
    assert route.stage_legacy_wallet(staged, PRINCIPAL)["migration_state"] == "migration_pending"
    assert db.legacy is not None
    readback = route.read_wallet_v2(WALLET_ID, PRINCIPAL)
    assert readback["payload_ciphertext"] == staged.payload_ciphertext
    assert readback["legacy_source_snapshot"] == staged.source_snapshot
    assert LEGACY["encrypted_data"] not in json.dumps(readback, default=str)
    assert route.retire_legacy_wallet(
        retire_body(staged, readback["readback_receipt"]), PRINCIPAL,
    ) == {"wallet_record_id": WALLET_ID, "retired": True}
    assert db.legacy is None
    assert db.wallet["migration_state"] == "v2_verified"
    assert db.proofs == [("synthetic-opaque-proof", SESSION)]


def test_changed_source_blocks_retire_without_consuming_proof(setup):
    db = setup
    staged = stage_body(db)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    readback = route.read_wallet_v2(WALLET_ID, PRINCIPAL)
    db.legacy["encrypted_data"] += " "
    with pytest.raises(HTTPException) as error:
        route.retire_legacy_wallet(
            retire_body(staged, readback["readback_receipt"]), PRINCIPAL,
        )
    assert error.value.status_code == 409
    assert db.legacy is not None
    assert db.wallet["migration_state"] == "migration_pending"
    assert db.proofs == []


def test_readback_receipt_is_bound_to_session(setup):
    db = setup
    staged = stage_body(db)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    readback = route.read_wallet_v2(WALLET_ID, PRINCIPAL)
    with pytest.raises(HTTPException) as error:
        route.retire_legacy_wallet(
            retire_body(staged, readback["readback_receipt"]),
            {"vault_id": VAULT, "token_id": OTHER_SESSION},
        )
    assert error.value.status_code == 409
    assert db.legacy is not None
    assert db.proofs == []


def test_receipt_expiry_and_retire_replay_are_rejected(setup):
    db = setup
    staged = stage_body(db)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    readback = route.read_wallet_v2(WALLET_ID, PRINCIPAL)
    receipt = readback["readback_receipt"]
    expiry = int(receipt.split(".")[1])
    assert not route._receipt_valid(
        receipt, "w", PRINCIPAL, WALLET_ID,
        route._wallet_digest(db.wallet), now_ts=expiry,
    )
    request = retire_body(staged, receipt)
    route.retire_legacy_wallet(request, PRINCIPAL)
    with pytest.raises(HTTPException) as error:
        route.retire_legacy_wallet(request, PRINCIPAL)
    assert error.value.status_code == 409
    assert db.proofs == [("synthetic-opaque-proof", SESSION)]


def test_other_vault_cannot_stage_same_source_snapshot(setup):
    db = setup
    staged = stage_body(db)
    with pytest.raises(HTTPException) as error:
        route.stage_legacy_wallet(
            staged,
            {"vault_id": "00000000-0000-0000-0000-000000000099",
             "token_id": SESSION},
        )
    assert error.value.status_code == 409
    assert db.wallet is None


def test_wallet_engine_outer_json_identity_is_checked_before_stage(setup):
    db = setup
    wrong = json.loads(db.legacy["encrypted_data"])
    wrong["publicAddress"] = "synthetic-other-address"
    db.legacy["encrypted_data"] = json.dumps(wrong)
    with pytest.raises(HTTPException) as error:
        route.stage_legacy_wallet(stage_body(db), PRINCIPAL)
    assert error.value.status_code == 409
    assert db.wallet is None


def test_distinct_outer_encrypted_variant_uses_snapshot_without_server_decrypt(setup):
    db = setup
    db.legacy["encrypted_data"] = "c3ludGhldGljLW9wYXF1ZS1BRTItR0NNLWVudmVsb3Bl"
    staged = stage_body(db)
    assert route.stage_legacy_wallet(staged, PRINCIPAL)["migration_state"] == "migration_pending"
    assert db.legacy is not None


def test_generic_delete_cannot_remove_retired_migrated_wallet(setup, monkeypatch):
    db = setup
    staged = stage_body(db)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    receipt = route.read_wallet_v2(WALLET_ID, PRINCIPAL)["readback_receipt"]
    route.retire_legacy_wallet(retire_body(staged, receipt), PRINCIPAL)

    class Cursor:
        def execute(self, sql, _args):
            assert sql.startswith("SELECT legacy_item_id")

        def fetchone(self):
            return (42,)

    class Conn:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(route, "get_db", lambda: Conn())
    with pytest.raises(HTTPException) as error:
        route.delete_wallet_v2(WALLET_ID, PRINCIPAL)
    assert error.value.status_code == 409
    assert db.wallet["migration_state"] == "v2_verified"


def test_identical_stage_retry_is_idempotent_but_different_bytes_conflict(setup):
    db = setup
    staged = stage_body(db)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    route.stage_legacy_wallet(staged, PRINCIPAL)
    with pytest.raises(HTTPException) as error:
        route.stage_legacy_wallet(stage_body(db, b"\x01different"), PRINCIPAL)
    assert error.value.status_code == 409
    assert db.legacy is not None


def test_changed_legacy_source_replaces_only_pending_stage(setup):
    db = setup
    first = stage_body(db)
    route.stage_legacy_wallet(first, PRINCIPAL)
    old_receipt = route.read_wallet_v2(WALLET_ID, PRINCIPAL)["readback_receipt"]
    db.legacy["encrypted_data"] += " "
    second = stage_body(db, b"\x01fresh-synthetic-envelope")
    route.stage_legacy_wallet(second, PRINCIPAL)
    assert db.wallet["legacy_source_snapshot"] == second.source_snapshot
    assert db.wallet["payload_ciphertext"] != base64.urlsafe_b64decode(
        first.payload_ciphertext + "=" * (-len(first.payload_ciphertext) % 4)
    )
    with pytest.raises(HTTPException) as error:
        route.retire_legacy_wallet(retire_body(second, old_receipt), PRINCIPAL)
    assert error.value.status_code == 409
    assert db.legacy is not None
    assert db.proofs == []


def test_legacy_wallet_read_falls_back_only_to_verified_matching_v2(monkeypatch):
    class Cursor:
        def execute(self, sql, _args):
            self.legacy_query = "FROM vault_items" in sql

        def fetchone(self):
            return None

        def fetchall(self):
            return [
                {"wallet_record_id": "other-network", "chain": "evm",
                 "network": "ethereum_sepolia", "asset": "ETH",
                 "public_address": "synthetic-sepolia", "wallet_label": "Other",
                 "migration_state": "v2_verified"},
                {"wallet_record_id": WALLET_ID, "chain": "evm",
                 "network": "ethereum_mainnet", "asset": "ETH",
                 "public_address": "synthetic-mainnet", "wallet_label": "Match",
                 "migration_state": "v2_verified"},
            ]

    class Conn:
        def cursor(self, **_kwargs):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setattr(legacy_wallet_route, "get_db", lambda: Conn())
    mainnet = legacy_wallet_route._load_wallet_account_record(
        VAULT, "ETH:ethereum_mainnet",
    )
    assert mainnet["walletRecordId"] == WALLET_ID
    sepolia = legacy_wallet_route._load_wallet_account_record(VAULT, "ETH")
    assert sepolia["walletRecordId"] == "other-network"
