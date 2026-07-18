"""Contract tests for the ciphertext-first write endpoints.

These tests do not require a live database — they exercise the
request-model validation and the plaintext-leak guardrail. The
DB-side integration is covered separately by the migration
end-to-end suite (which runs in Docker/CI where the pyo3 wheel
is available).
"""

from __future__ import annotations

import pytest

from routes.vault_ciphertext_write_routes import (
    AiMemoryCiphertextRequest,
    NotificationCiphertextRequest,
    UploadedFileMetadataRequest,
    VaultItemUpsertRequest,
    _reject_plaintext_leak,
    router,
)


def test_router_registers_all_ciphertext_write_paths() -> None:
    paths = {getattr(r, "path", None) for r in router.routes}
    expected = {
        "/vault/ciphertext/vault-items",
        "/vault/ciphertext/uploaded-files",
        "/vault/ciphertext/notifications",
        "/vault/ciphertext/vault-ai-memory",
        "/vault/ciphertext/semantic-index",
        "/vault/ciphertext/crypto-drafts",
        "/vault/ciphertext/crypto-history",
    }
    missing = expected - paths
    assert not missing, f"missing ciphertext-write routes: {sorted(missing)}"


def test_crypto_ciphertext_endpoints_reject_wrong_hash_length() -> None:
    from routes.vault_ciphertext_write_routes import (
        _b64url_decode,
    )
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _b64url_decode("", name="test", max_bytes=64)


def test_vault_item_upsert_rejects_plaintext_leak() -> None:
    from fastapi import HTTPException
    req = VaultItemUpsertRequest(
        item_id=None,
        item_type_ciphertext="AA",
        service_ciphertext="BB",
        payload_ciphertext="CC",
        item_type="login",  # LEGACY PLAINTEXT — MUST BE REJECTED
    )
    with pytest.raises(HTTPException) as excinfo:
        _reject_plaintext_leak(
            req, ("item_type", "service", "encrypted_data"),
        )
    assert excinfo.value.status_code == 400
    assert "item_type" in excinfo.value.detail


def test_vault_item_upsert_accepts_ciphertext_only() -> None:
    req = VaultItemUpsertRequest(
        item_id=None,
        item_type_ciphertext="AA",
        service_ciphertext="BB",
        payload_ciphertext="CC",
    )
    _reject_plaintext_leak(
        req, ("item_type", "service", "encrypted_data"),
    )


def test_uploaded_file_metadata_rejects_plaintext_leak() -> None:
    from fastapi import HTTPException
    req = UploadedFileMetadataRequest(
        file_id="abc123",
        file_name_ciphertext="AA",
        saved_name="My Passport",  # LEGACY PLAINTEXT
    )
    with pytest.raises(HTTPException) as excinfo:
        _reject_plaintext_leak(req, (
            "file_name", "saved_name", "content_type",
            "detected_type", "detected_service", "asset_type",
        ))
    assert excinfo.value.status_code == 400
    assert "saved_name" in excinfo.value.detail


def test_notification_ciphertext_rejects_plaintext_leak() -> None:
    from fastapi import HTTPException
    req = NotificationCiphertextRequest(
        kind="storage_warning",
        title_ciphertext="AA",
        body_ciphertext="BB",
        title="You are almost out of storage.",  # LEGACY PLAINTEXT
    )
    with pytest.raises(HTTPException):
        _reject_plaintext_leak(req, ("title", "body", "metadata"))


def test_ai_memory_ciphertext_rejects_plaintext_leak() -> None:
    from fastapi import HTTPException
    req = AiMemoryCiphertextRequest(
        memory_type="preference",
        memory_lookup_hash="AA",
        payload_ciphertext="BB",
        memory_value="I like tea.",  # LEGACY PLAINTEXT
    )
    with pytest.raises(HTTPException):
        _reject_plaintext_leak(
            req, ("memory_key", "memory_value", "memory_normalized_key"),
        )


def test_all_ciphertext_write_endpoints_require_auth() -> None:
    """None of the ciphertext-write endpoints may be reachable
    without a valid session token. Verified by checking each route's
    dependency graph includes verify_session_token."""
    from auth_local import verify_session_token
    for route in router.routes:
        deps = getattr(route, "dependant", None)
        if deps is None:
            continue
        found = False
        for dep in deps.dependencies:
            if getattr(dep, "call", None) is verify_session_token:
                found = True
                break
        assert found, (
            f"Route {getattr(route, 'path', '<unknown>')} does not "
            "require verify_session_token — every ciphertext-write "
            "endpoint must be per-vault authenticated"
        )
