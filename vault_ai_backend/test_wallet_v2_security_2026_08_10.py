import inspect

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routes.wallet_v2_routes as route
from routes import crypto_wallet_routes as legacy


VALID = {
    "wallet_record_id": "opaque_wallet_record_1234567890",
    "chain": "evm",
    "network": "ethereum-mainnet",
    "asset": "ETH",
    "public_address": "0x0000000000000000000000000000000000000001",
    "wallet_label": "Zero balance QA",
    "payload_ciphertext": "AQIDBA",
    "envelope_version": "v2",
    "migration_state": "v2_verified",
}


@pytest.mark.parametrize("field", [
    "private_key", "privateKey", "seed", "seed_phrase", "mnemonic",
    "spend_key", "wallet_secret", "secret", "pin", "mvk", "key_material",
])
def test_plaintext_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        route.WalletV2CreateRequest(**VALID, **{field: "forbidden"})


def test_backend_has_no_decrypt_or_sign_primitive():
    source = inspect.getsource(route).lower()
    assert "decrypt_message" not in source
    assert "aesgcm" not in source
    assert "cryptography" not in source
    assert "sign_transaction" not in source
    assert "private_key" not in route.WalletV2CreateRequest.model_fields
    assert "pin" not in route.WalletV2CreateRequest.model_fields
    assert "mvk" not in route.WalletV2CreateRequest.model_fields


def test_ciphertext_roundtrip_and_vault_scope(monkeypatch):
    rows = {}

    class Cursor:
        rowcount = 0

        def execute(self, sql, args):
            if sql.lstrip().startswith("INSERT"):
                rows[(args[0], args[1])] = args[1:]
            elif sql.lstrip().startswith("SELECT wallet_record_id"):
                self.selected = rows.get((args[0], args[1]))

        def fetchone(self):
            selected = getattr(self, "selected", None)
            if not selected:
                return None
            return {
                "wallet_record_id": selected[0], "chain": selected[1],
                "network": selected[2], "asset": selected[3],
                "public_address": selected[4], "wallet_label": selected[5],
                "payload_ciphertext": selected[6],
                "envelope_version": selected[7],
                "migration_state": selected[8],
                "created_at": None, "updated_at": None,
            }

    class Conn:
        def cursor(self, **kwargs):
            return Cursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_V2_WRITE_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: Conn())
    payload = route.WalletV2CreateRequest(**VALID)
    route.create_wallet_v2(payload, {"vault_id": "vault-a"})
    read = route.read_wallet_v2(VALID["wallet_record_id"], {"vault_id": "vault-a"})
    assert read["payload_ciphertext"] == VALID["payload_ciphertext"]
    with pytest.raises(HTTPException) as exc:
        route.read_wallet_v2(VALID["wallet_record_id"], {"vault_id": "vault-b"})
    assert exc.value.status_code == 404


def test_legacy_wallet_write_is_blocked_when_v2_enabled(monkeypatch):
    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_V2_WRITE_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        legacy._reject_legacy_wallet_write_when_v2_enabled()
    assert exc.value.status_code == 410
