"""New-wallet V2 publish gate with synthetic ciphertext and no transactions."""

import base64

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import wallet_v2_routes as route


VAULT = "00000000-0000-0000-0000-000000000001"
SESSION = "00000000-0000-0000-0000-000000000002"
OTHER_SESSION = "00000000-0000-0000-0000-000000000003"
PRINCIPAL = {"vault_id": VAULT, "token_id": SESSION}
WALLET_ID = "synthetic-new-wallet-record-1"
CIPHERTEXT = b"\x01synthetic-mvk-wallet-envelope"


class FakeDb:
    def __init__(self):
        self.wallets = {}
        self.commits = 0
        self.legacy_service = None

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
        self.rows = []
        self.rowcount = 0

    def execute(self, sql, args):
        sql = " ".join(sql.split())
        self.rowcount = 0
        if sql.startswith("SELECT vault_handle FROM vaults"):
            self.selected = {"vault_handle": "VLT-synthetic"}
        elif sql.startswith("SELECT 1 FROM vault_items"):
            self.selected = {"exists": 1} if args[1] == self.db.legacy_service else None
        elif "migration_state='migration_pending'" in sql and \
                "ORDER BY created_at DESC" in sql:
            fields = ("wallet_record_id", "chain", "network", "asset",
                      "public_address", "wallet_label", "migration_state",
                      "legacy_item_id", "legacy_source_snapshot")
            self.rows = [{field: row[field] for field in fields}
                         for (vault, _), row in self.db.wallets.items()
                         if vault == args[0] and row["migration_state"] == "migration_pending"]
        elif "ORDER BY created_at DESC" in sql:
            self.rows = [row.copy() for (vault, _), row in self.db.wallets.items()
                         if vault == args[0] and row["migration_state"] == "v2_verified"]
        elif sql.startswith("SELECT wallet_record_id"):
            selected = self.db.wallets.get((args[0], args[1]))
            self.selected = selected.copy() if selected else None
        elif sql.startswith("INSERT INTO wallet_v2_records"):
            self.db.wallets[(args[0], args[1])] = {
                "wallet_record_id": args[1], "chain": args[2],
                "network": args[3], "asset": args[4],
                "public_address": args[5], "wallet_label": args[6],
                "payload_ciphertext": args[7], "envelope_version": args[8],
                "migration_state": args[9], "legacy_item_id": None,
                "legacy_source_snapshot": None,
            }
            self.rowcount = 1
        elif sql.startswith("UPDATE wallet_v2_records SET migration_state"):
            row = self.db.wallets.get((args[0], args[1]))
            if row and row["migration_state"] == "migration_pending" and row["legacy_item_id"] is None:
                row["migration_state"] = "v2_verified"
                self.rowcount = 1
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.selected

    def fetchall(self):
        return self.rows


@pytest.fixture
def setup(monkeypatch):
    db = FakeDb()
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-wallet-proof-secret-12345678901234567890")
    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_V2_WRITE_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "require_content_write", lambda _p: None)
    monkeypatch.setattr(route, "require_crypto_access", lambda _p: None)
    return db


def body(ciphertext=CIPHERTEXT):
    return route.WalletV2CreateRequest(
        wallet_record_id=WALLET_ID, chain="evm", network="ethereum_mainnet",
        asset="ETH", public_address="0x0000000000000000000000000000000000000001",
        wallet_label="Synthetic new wallet",
        payload_ciphertext=base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
        envelope_version="v2",
    )


def test_direct_verified_write_rejected_before_db(setup):
    with pytest.raises(ValidationError):
        route.WalletV2CreateRequest(**{
            **body().model_dump(), "migration_state": "v2_verified",
        })
    assert not setup.wallets


def test_new_wallet_invisible_until_exact_readback_and_publish(setup):
    staged = route.create_wallet_v2(body(), PRINCIPAL)
    assert staged["migration_state"] == "migration_pending"
    assert route.list_wallet_v2(PRINCIPAL)["wallets"] == []
    pending = route.list_pending_wallet_v2(PRINCIPAL)["wallets"]
    assert [row["wallet_record_id"] for row in pending] == [WALLET_ID]
    assert "payload_ciphertext" not in pending[0]
    readback = route.read_wallet_v2(WALLET_ID, PRINCIPAL)
    assert readback["payload_ciphertext"] == body().payload_ciphertext
    assert readback["readback_receipt"]
    assert route.publish_new_wallet_v2(
        WALLET_ID, route.WalletV2PublishNewRequest(
            readback_receipt=readback["readback_receipt"],
            client_verified_exact_bytes=True,
        ), PRINCIPAL,
    )["migration_state"] == "v2_verified"
    assert len(route.list_wallet_v2(PRINCIPAL)["wallets"]) == 1
    assert route.list_pending_wallet_v2(PRINCIPAL)["wallets"] == []
    with pytest.raises(HTTPException) as error:
        route.publish_new_wallet_v2(
            WALLET_ID, route.WalletV2PublishNewRequest(
                readback_receipt=readback["readback_receipt"],
                client_verified_exact_bytes=True,
            ), PRINCIPAL,
        )
    assert error.value.status_code == 409


def test_publish_rejects_other_session_and_changed_ciphertext(setup):
    route.create_wallet_v2(body(), PRINCIPAL)
    receipt = route.read_wallet_v2(WALLET_ID, PRINCIPAL)["readback_receipt"]
    request = route.WalletV2PublishNewRequest(
        readback_receipt=receipt, client_verified_exact_bytes=True,
    )
    with pytest.raises(HTTPException) as error:
        route.publish_new_wallet_v2(
            WALLET_ID, request, {"vault_id": VAULT, "token_id": OTHER_SESSION},
        )
    assert error.value.status_code == 409
    setup.wallets[(VAULT, WALLET_ID)]["payload_ciphertext"] += b"changed"
    with pytest.raises(HTTPException) as error:
        route.publish_new_wallet_v2(WALLET_ID, request, PRINCIPAL)
    assert error.value.status_code == 409
    assert setup.wallets[(VAULT, WALLET_ID)]["migration_state"] == "migration_pending"


def test_stage_retry_requires_identical_bytes_and_same_vault(setup):
    route.create_wallet_v2(body(), PRINCIPAL)
    assert route.create_wallet_v2(body(), PRINCIPAL)["migration_state"] == "migration_pending"
    with pytest.raises(HTTPException) as error:
        route.create_wallet_v2(body(b"different"), PRINCIPAL)
    assert error.value.status_code == 409
    other = {"vault_id": "00000000-0000-0000-0000-000000000099", "token_id": SESSION}
    route.create_wallet_v2(body(), other)
    assert len(setup.wallets) == 2


def test_existing_legacy_account_blocks_new_wallet_stage(setup):
    setup.legacy_service = "ETH:ethereum_mainnet"
    with pytest.raises(HTTPException) as error:
        route.create_wallet_v2(body(), PRINCIPAL)
    assert error.value.status_code == 409
    assert error.value.detail == "legacy_wallet_exists"
    assert not setup.wallets


def test_noncanonical_network_cannot_create_duplicate_slot(setup):
    with pytest.raises(HTTPException) as error:
        route.create_wallet_v2(body().model_copy(update={
            "network": "Ethereum Mainnet",
        }), PRINCIPAL)
    assert error.value.status_code == 400
    assert not setup.wallets


def test_generic_delete_rejects_newly_published_and_pending_wallets(setup, monkeypatch):
    route.create_wallet_v2(body(), PRINCIPAL)

    class Cursor:
        def execute(self, sql, _args):
            assert sql.startswith("SELECT legacy_item_id")

        def fetchone(self):
            return (None,)

    class Conn:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(route, "get_db", lambda: Conn())
    for state in ("migration_pending", "v2_verified"):
        setup.wallets[(VAULT, WALLET_ID)]["migration_state"] = state
        with pytest.raises(HTTPException) as error:
            route.delete_wallet_v2(WALLET_ID, PRINCIPAL)
        assert error.value.status_code == 409
        assert error.value.detail == "wallet_delete_proof_required"
        assert setup.wallets[(VAULT, WALLET_ID)]["migration_state"] == state
