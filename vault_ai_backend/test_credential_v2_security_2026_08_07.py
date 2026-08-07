from __future__ import annotations

import base64
import inspect
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import routes.credential_v2_routes as route
from zk_migration_adapters import VersionedDomainAdapter


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _payload() -> dict[str, object]:
    return {
        "record_id": "credential-synthetic-1",
        "crypto_version": "client_mvk_v2",
        "cipher_suite": "aes_256_gcm_v1",
        "key_domain": "credential",
        "nonce": _b64(b"n" * 12),
        "ciphertext": _b64(b"opaque-ciphertext"),
        "authentication_tag": _b64(b"t" * 16),
        "blind_indexes": {"service": _b64(b"i" * 32)},
    }


def test_valid_opaque_schema_contains_no_plaintext_or_key_material() -> None:
    parsed = route.CredentialV2WriteRequest.model_validate(_payload())
    values = parsed.model_dump(exclude_none=True)
    assert set(values) == {
        "record_id", "crypto_version", "cipher_suite", "key_domain",
        "nonce", "ciphertext", "authentication_tag", "blind_indexes",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        "pin", "vault_pin", "plaintext_pin", "mvk", "content_key",
        "derived_key", "password", "username", "url", "notes",
        "totp_secret", "custom_fields",
    ],
)
def test_sensitive_request_fields_are_rejected(forbidden: str) -> None:
    payload = _payload()
    payload[forbidden] = "must-never-reach-backend"
    with pytest.raises(ValidationError) as exc:
        route.CredentialV2WriteRequest.model_validate(payload)
    assert any(error["type"] == "extra_forbidden" for error in exc.value.errors())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("nonce", _b64(b"short")),
        ("authentication_tag", _b64(b"short")),
        ("ciphertext", "not!base64"),
        ("blind_indexes", {"password": _b64(b"i" * 32)}),
        ("blind_indexes", {"username": _b64(b"short")}),
    ],
)
def test_framing_and_blind_index_validation_fail_closed(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        route.CredentialV2WriteRequest.model_validate(payload)


def test_feature_flags_default_off_and_invalid_dependency_fails_closed(monkeypatch) -> None:
    for name in ("ZK_V2_READ_ENABLED", "ZK_V2_WRITE_ENABLED", "ZK_V2_MIGRATION_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as exc:
        route._require("read")
    assert exc.value.status_code == 404
    monkeypatch.setenv("ZK_V2_MIGRATION_ENABLED", "true")
    with pytest.raises(ValueError):
        route._require("migration")


def test_pin_boundary_has_no_backend_argument_or_pin_verification_call() -> None:
    functions = (
        route.write_credential_v2,
        route.read_credential_v2,
        route.list_credentials_v2,
        route.verify_credential_v2,
        route.rollback_credential_v2,
        route.delete_credential_v2,
        route.finalize_generated_draft_v2,
        route.cancel_generated_draft_v2,
    )
    for function in functions:
        assert "pin" not in inspect.signature(function).parameters
    source = inspect.getsource(route)
    assert "verify_vault_pin" not in source
    assert "PBKDF2" not in source
    assert "pbkdf2" not in source


def test_backend_compromise_bundle_has_no_v2_decryption_capability() -> None:
    database_row = _payload()
    backend_environment = dict(os.environ)
    session_token = "synthetic-session-token"
    assert database_row["ciphertext"]
    assert session_token
    assert "MVK" not in backend_environment
    assert "CREDENTIAL_CONTENT_KEY" not in backend_environment
    assert not hasattr(route, "decrypt_credential_v2")
    assert not hasattr(VersionedDomainAdapter, "decrypt")
    source = inspect.getsource(route)
    assert "AESGCM" not in source
    assert "AesGcm" not in source
    assert "SecretKey" not in source


class _DraftFinalizeCursor:
    def __init__(self, envelope_exists: bool) -> None:
        self.envelope_exists = envelope_exists

    def execute(self, sql: str, params=()) -> None:
        assert "SELECT 1 FROM vault_crypto_envelopes" in sql
        assert len(params) == 2

    def fetchone(self):
        return (1,) if self.envelope_exists else None


class _DraftFinalizeConnection:
    def __init__(self, envelope_exists: bool) -> None:
        self.envelope_exists = envelope_exists

    def cursor(self):
        return _DraftFinalizeCursor(self.envelope_exists)

    def close(self) -> None:
        pass


def test_generated_draft_finalize_requires_opaque_record_before_clear(monkeypatch) -> None:
    monkeypatch.setenv("ZK_V2_READ_ENABLED", "true")
    monkeypatch.setenv("ZK_V2_WRITE_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: _DraftFinalizeConnection(False))
    consumed: list[str] = []
    monkeypatch.setattr(route, "consume_draft", lambda **kw: consumed.append(kw["draft_id"]))
    with pytest.raises(HTTPException) as exc:
        route.finalize_generated_draft_v2(
            "generated-opaque-1", "draft-1", {"vault_id": "vault-1"}
        )
    assert exc.value.status_code == 409
    assert consumed == []


def test_generated_draft_finalize_is_exact_and_retry_safe(monkeypatch) -> None:
    monkeypatch.setenv("ZK_V2_READ_ENABLED", "true")
    monkeypatch.setenv("ZK_V2_WRITE_ENABLED", "true")
    monkeypatch.setattr(route, "get_db", lambda: _DraftFinalizeConnection(True))
    state = {"present": True}
    draft = object()
    monkeypatch.setattr(
        route, "get_draft", lambda **_kw: draft if state["present"] else None
    )
    def _consume(**_kw):
        state["present"] = False
        return draft
    monkeypatch.setattr(route, "consume_draft", _consume)
    first = route.finalize_generated_draft_v2(
        "generated-opaque-1", "draft-1", {"vault_id": "vault-1"}
    )
    second = route.finalize_generated_draft_v2(
        "generated-opaque-1", "draft-1", {"vault_id": "vault-1"}
    )
    assert first.status == "finalized"
    assert second.status == "already_finalized"


def test_response_is_exact_opaque_envelope_without_legacy_transform() -> None:
    payload = _payload()
    row = {
        **payload,
        "nonce_b64": payload["nonce"],
        "ciphertext_b64": payload["ciphertext"],
        "authentication_tag_b64": payload["authentication_tag"],
        "migration_state": "v2_written",
        "verification_state": "not_verified",
    }
    response = route._response(row)
    assert response.nonce == payload["nonce"]
    assert response.ciphertext == payload["ciphertext"]
    assert response.authentication_tag == payload["authentication_tag"]
    assert not hasattr(response, "legacy_value")


def test_client_verification_attestation_cannot_be_false() -> None:
    with pytest.raises(ValidationError):
        route.ClientVerificationRequest.model_validate({
            "operation_id": str(uuid4()),
            "semantic_equality_verified": False,
        })


def test_route_is_mounted_without_changing_legacy_route_source() -> None:
    source = (Path(route.__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    assert "app.include_router(credential_v2_router)" in source
    assert "verify_vault_pin" not in inspect.getsource(route)


class _SyntheticCursor:
    def __init__(self, state: dict) -> None:
        self.state = state
        self.rowcount = 0
        self._one = None

    def execute(self, sql: str, params=()) -> None:
        compact = " ".join(sql.split())
        if compact.startswith("INSERT INTO vault_crypto_envelopes"):
            vault_id, record_id, nonce, ciphertext, tag, indexes, migration_state = params
            self._one = {
                "id": uuid4(), "vault_id": vault_id,
                "record_id": record_id, "record_domain": "credential",
                "crypto_version": "client_mvk_v2",
                "cipher_suite": "aes_256_gcm_v1", "key_domain": "credential",
                "nonce_b64": nonce, "ciphertext_b64": ciphertext,
                "authentication_tag_b64": tag,
                "blind_indexes": indexes.adapted,
                "migration_state": migration_state,
                "verification_state": "not_verified",
            }
            self.state[record_id] = self._one
            self.rowcount = 1
        elif compact.startswith("SELECT * FROM vault_crypto_envelopes"):
            self._one = self.state.get(params[1])
            self.rowcount = int(self._one is not None)
        else:
            raise AssertionError(f"unexpected synthetic SQL: {compact[:80]}")

    def fetchone(self):
        return self._one


class _SyntheticConnection:
    def __init__(self, state: dict) -> None:
        self.state = state

    def cursor(self, **_kwargs):
        return _SyntheticCursor(self.state)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_actual_http_write_then_read_returns_identical_opaque_envelope(monkeypatch) -> None:
    monkeypatch.setenv("ZK_V2_READ_ENABLED", "true")
    monkeypatch.setenv("ZK_V2_WRITE_ENABLED", "true")
    monkeypatch.setenv("ZK_V2_MIGRATION_ENABLED", "false")
    state: dict = {}
    monkeypatch.setattr(route, "get_db", lambda: _SyntheticConnection(state))
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[route.verify_session_token] = lambda: {
        "vault_id": uuid4(), "session_id": "synthetic"
    }
    client = TestClient(app)
    payload = _payload()
    written = client.put(
        "/vault/v2/credentials/credential-synthetic-1", json=payload
    )
    assert written.status_code == 200, written.text
    fetched = client.get("/vault/v2/credentials/credential-synthetic-1")
    assert fetched.status_code == 200, fetched.text
    for field in (
        "record_id", "crypto_version", "cipher_suite", "key_domain",
        "nonce", "ciphertext", "authentication_tag", "blind_indexes",
    ):
        assert fetched.json()[field] == payload[field]


def test_actual_http_rejects_pin_before_storage(monkeypatch) -> None:
    monkeypatch.setenv("ZK_V2_READ_ENABLED", "true")
    monkeypatch.setenv("ZK_V2_WRITE_ENABLED", "true")
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[route.verify_session_token] = lambda: {
        "vault_id": uuid4(), "session_id": "synthetic"
    }
    payload = _payload()
    payload["pin"] = "synthetic-pin"
    response = TestClient(app).put(
        "/vault/v2/credentials/credential-synthetic-1", json=payload
    )
    assert response.status_code == 422
