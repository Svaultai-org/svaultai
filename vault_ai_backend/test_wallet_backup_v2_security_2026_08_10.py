import inspect

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routes.wallet_backup_v2_routes as route
from routes.login_routes import (
    RevealSensitiveBackupRequest,
    SaveCryptoSensitiveBackupRequest,
    reveal_sensitive_backup,
    save_crypto_sensitive_backup,
)


VALID = {
    "backup_record_id": "opaque_record_id_1234567890",
    "secret_type": "private_key",
    "payload_ciphertext": "AQIDBA",
    "envelope_version": "client_mvk_v2",
}


@pytest.mark.parametrize("field", [
    "pin", "secret", "secretValue", "private_key", "privateKey", "seed",
    "seed_phrase", "seedPhrase", "mnemonic", "recovery_phrase",
    "recoveryPhrase", "wallet_password", "mvk", "key_material",
])
def test_plaintext_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        route.WalletBackupV2CreateRequest(**VALID, **{field: "forbidden"})


def test_backend_has_no_decrypt_primitive():
    assert not hasattr(route, "decrypt_wallet_backup_v2")
    source = inspect.getsource(route).lower()
    assert "decrypt_message" not in source
    assert "verify_vault_pin" not in source
    assert "pin" not in route.WalletBackupV2CreateRequest.model_fields
    assert "mvk" not in route.WalletBackupV2CreateRequest.model_fields


def test_ciphertext_roundtrip_and_vault_scope(monkeypatch):
    rows = {}

    class Cursor:
        rowcount = 0
        def execute(self, sql, args):
            if sql.lstrip().startswith("INSERT"):
                vault, record, secret_type, ciphertext, version = args
                rows[(vault, record)] = (record, secret_type, ciphertext, version)
            elif sql.lstrip().startswith("SELECT backup_record_id,secret_type,payload"):
                self.selected = rows.get((args[0], args[1]))
        def fetchone(self):
            if not getattr(self, "selected", None): return None
            record, secret_type, ciphertext, version = self.selected
            return {"backup_record_id": record, "secret_type": secret_type,
                    "payload_ciphertext": ciphertext, "envelope_version": version,
                    "created_at": None, "updated_at": None}
    class Conn:
        def cursor(self, **kwargs): return Cursor()
        def commit(self): pass
        def close(self): pass

    monkeypatch.setenv("WALLET_BACKUP_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_BACKUP_V2_WRITE_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: Conn())
    payload = route.WalletBackupV2CreateRequest(**VALID)
    route.create_wallet_backup_v2(payload, {"vault_id": "vault-a"})
    read = route.read_wallet_backup_v2(VALID["backup_record_id"], {"vault_id": "vault-a"})
    assert read["payload_ciphertext"] == VALID["payload_ciphertext"]
    with pytest.raises(HTTPException) as exc:
        route.read_wallet_backup_v2(VALID["backup_record_id"], {"vault_id": "vault-b"})
    assert exc.value.status_code == 404


def test_legacy_plaintext_paths_disabled_by_v2_flags(monkeypatch):
    monkeypatch.setenv("WALLET_BACKUP_V2_READ_ENABLED", "true")
    monkeypatch.setenv("WALLET_BACKUP_V2_WRITE_ENABLED", "true")
    with pytest.raises(HTTPException) as save_exc:
        save_crypto_sensitive_backup(SaveCryptoSensitiveBackupRequest(
            pin="123456", walletLabel="synthetic", secretType="private_key",
            secretValue="synthetic", warningConfirmed=True), {"vault_id": "v"})
    assert save_exc.value.status_code == 410
    with pytest.raises(HTTPException) as reveal_exc:
        reveal_sensitive_backup(RevealSensitiveBackupRequest(
            pin="123456", service="synthetic", item_type="crypto_private_key"),
            {"vault_id": "v"})
    assert reveal_exc.value.status_code == 410
