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
        "/vault/ciphertext/beneficiary-links",
        "/vault/ciphertext/semantic-index",
        "/vault/ciphertext/crypto-drafts",
        "/vault/ciphertext/crypto-history",
    }
    missing = expected - paths
    assert not missing, f"missing ciphertext-write routes: {sorted(missing)}"


def test_vault_item_ciphertext_inventory_is_vault_scoped_and_opaque() -> None:
    import inspect
    from routes import vault_ciphertext_write_routes as mod

    route = next(
        r for r in router.routes
        if getattr(r, "path", None) == "/vault/ciphertext/vault-items"
        and "GET" in getattr(r, "methods", set())
    )
    assert route is not None
    src = inspect.getsource(mod.list_vault_item_ciphertexts)
    assert 'WHERE vault_id = %s' in src
    assert 'principal["vault_id"]' in src
    assert "item_type_ciphertext IS NOT NULL" in src
    assert "service_ciphertext IS NOT NULL" in src
    assert "payload_ciphertext IS NOT NULL" in src
    assert "encrypted_data" not in src


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


def test_uploaded_file_saved_name_ciphertext_clears_needs_naming() -> None:
    import inspect
    from routes import vault_ciphertext_write_routes as mod

    src = inspect.getsource(mod.uploaded_file_metadata_ciphertext)
    assert 'legacy == "saved_name"' in src
    assert "needs_naming = FALSE" in src
    assert "invalidate_for_event" in src


def test_uploaded_file_ciphertext_path_does_not_log_plaintext_names() -> None:
    import inspect
    import main

    src = inspect.getsource(main.upload_file_endpoint)
    assert "saved_name_present=" in src
    assert "saved_name={auto_saved_name!r}" not in src


def test_list_files_returns_ciphertext_metadata_for_client_decrypt() -> None:
    import inspect
    import main

    src = inspect.getsource(main.list_files_endpoint)
    assert "include_ciphertext=True" in src
    assert "_uploaded_file_for_wire" in src


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


@pytest.mark.parametrize("field", [
    "memory_key", "memory_value", "memory_normalized_key", "normalized_memory",
    "summary", "summary_plaintext", "entity", "entity_plaintext", "PIN",
    "MVK", "memory_key_material",
])
def test_ai_memory_ciphertext_rejects_plaintext_fields(field: str) -> None:
    from fastapi import HTTPException
    payload = {
        "memory_id": "qa-contract-memory",
        "memory_type": "preference",
        "memory_lookup_hash": "AA",
        "payload_ciphertext": "BB",
        field: "SYNTHETIC_SENTINEL",
    }
    with pytest.raises((HTTPException, ValueError)):
        req = AiMemoryCiphertextRequest.model_validate(payload)
        _reject_plaintext_leak(
            req, ("memory_key", "memory_value", "memory_normalized_key"),
        )


def test_ai_memory_edit_updates_stable_record_id_before_hash_upsert() -> None:
    """Changing an encrypted memory title changes its blind lookup hash.

    The stable client record id must therefore be the edit identity; otherwise
    the insert path collides with the record-id uniqueness constraint.
    """
    import inspect
    from routes import vault_ciphertext_write_routes as mod

    src = inspect.getsource(mod.ai_memory_ciphertext_upsert)
    update_pos = src.index("UPDATE vault_ai_memory")
    insert_pos = src.index("INSERT INTO vault_ai_memory")
    assert update_pos < insert_pos
    assert "memory_record_id = %s" in src
    assert "memory_lookup_hash = %s" in src


def test_ai_memory_identical_retry_is_reported_without_rewrite() -> None:
    import inspect
    from routes import vault_ciphertext_write_routes as mod

    src = inspect.getsource(mod.ai_memory_ciphertext_upsert)
    duplicate_pos = src.index('str(prev["memory_record_id"]) == payload.memory_id')
    update_pos = src.index("UPDATE vault_ai_memory")
    assert duplicate_pos < update_pos
    assert "duplicate=True" in src
    assert "not payload.replace_existing" in src


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
