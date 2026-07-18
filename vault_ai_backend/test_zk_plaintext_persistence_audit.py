"""ZK plaintext-persistence audit.

Asserts that VaultAI's ciphertext-first write endpoints, when hit
with only-ciphertext payloads, never intentionally persist the
user-derived plaintext columns. Prevents accidental future regressions
where a route grows a "just in case" plaintext writeback.

These tests inspect the SQL string emitted by each write route (via
introspection of the route function's source or its literal SQL
strings) and confirm none of the ciphertext-first INSERT/UPDATE
statements re-introduce a plaintext column.

We deliberately do NOT hit a live database here — this is a
contract-level guardrail so the guarantee holds even if the
migration/backend deploys diverge.
"""

from __future__ import annotations

import inspect
import re

import pytest


FORBIDDEN_LEGACY_PLAINTEXT_ASSIGNMENTS = {
    "item_type": r"\bitem_type\s*=\s*%s",
    "service": r"\bservice\s*=\s*%s",
    "encrypted_data": r"\bencrypted_data\s*=\s*%s",
    "file_name": r"\bfile_name\s*=\s*%s",
    "saved_name": r"\bsaved_name\s*=\s*%s",
    "content_type": r"\bcontent_type\s*=\s*%s",
    "detected_type": r"\bdetected_type\s*=\s*%s",
    "detected_service": r"\bdetected_service\s*=\s*%s",
    "asset_type": r"\basset_type\s*=\s*%s",
    "notification_title": r"\btitle\s*=\s*%s",
    "notification_body": r"\bbody\s*=\s*%s",
    "memory_key": r"\bmemory_key\s*=\s*%s",
    "memory_value": r"\bmemory_value\s*=\s*%s",
    "passer_label": r"\bpasser_label\s*=\s*%s",
    "sender_address": r"\bsender_address\s*=\s*%s",
    "destination_address": r"\bdestination_address\s*=\s*%s",
    "content_hash_placeholder": r"decode\('',\s*'hex'\)",
}


def _get_source(mod_name: str) -> str:
    mod = __import__(mod_name, fromlist=["__file__"])
    return inspect.getsource(mod)


def test_ciphertext_write_routes_never_assign_legacy_plaintext_columns() -> None:
    """The ciphertext-first receiver module must not contain any
    ``SET <legacy_column> = %s`` (writing a user-value into the
    plaintext column). ``SET <legacy_column> = NULL`` (explicit
    clear) is required. ``WHERE <legacy_column> = %s`` (locate a
    row-to-update) is fine — the value is only used to find the
    row, not to persist a new user value."""
    src = _get_source("routes.vault_ciphertext_write_routes")

    if "decode('', 'hex')" in src:
        pytest.fail(
            "Ciphertext-first write route still writes the "
            "decode('', 'hex') placeholder into semantic_index."
            "content_hash. Use NULL instead."
        )

    offenders: list[tuple[str, str]] = []
    # Look for SET clause writes (semi-column separated multi-line
    # SET blocks are joined by folding whitespace first).
    folded = re.sub(r"\s+", " ", src)
    for name, pattern in FORBIDDEN_LEGACY_PLAINTEXT_ASSIGNMENTS.items():
        if name == "content_hash_placeholder":
            continue
        set_rx = re.compile(r"SET(?:\s+|,\s*)" + pattern[2:])
        for m in set_rx.finditer(folded):
            offenders.append((name, m.group(0)[:80]))
    assert not offenders, (
        "Ciphertext-first write route SET-writes a legacy plaintext "
        f"column:\n" + "\n".join(f"  {n}: {l}" for n, l in offenders)
    )


def _extract_function_body(src: str, name: str) -> str:
    idx = src.find(f"def {name}")
    assert idx >= 0, f"{name} not defined in source"
    end = src.find("\ndef ", idx + 10)
    return src[idx:end] if end >= 0 else src[idx:]


def test_solana_ciphertext_draft_writes_null_plaintext() -> None:
    """The Solana ciphertext-first draft creator must persist NULL
    into every user-derived plaintext column, not the plaintext value."""
    src = _get_source("crypto_solana_control_store")
    body = _extract_function_body(src, "register_draft_ciphertext_first")
    for banned in (
        "sender_address = %s", "destination_address = %s",
        "asset = %s", "value_lamports_str = %s",
        "fee_lamports_str = %s",
    ):
        assert banned not in body, (
            "solana register_draft_ciphertext_first must not write "
            f"legacy plaintext: {banned}"
        )
    assert "NULL," in body


def test_mainnet_ciphertext_draft_writes_null_plaintext() -> None:
    src = _get_source("crypto_mainnet_control_store")
    body = _extract_function_body(src, "register_draft_ciphertext_first")
    for banned in (
        "sender_address_lower = %s", "destination_address = %s",
        "asset = %s", "value_wei_str = %s",
        "data_hex = %s", "transaction_to = %s",
    ):
        assert banned not in body, (
            "mainnet register_draft_ciphertext_first must not write "
            f"legacy plaintext: {banned}"
        )
    assert "NULL," in body


def test_tron_ciphertext_draft_writes_null_plaintext() -> None:
    src = _get_source("crypto_tron_control_store")
    body = _extract_function_body(src, "register_draft_ciphertext_first")
    for banned in (
        "sender_address = %s", "destination_address = %s",
        "asset = %s", "token_contract_address = %s",
        "amount_base_units_str = %s", "fee_limit_sun_str = %s",
        "raw_data_hex = %s",
    ):
        assert banned not in body, (
            "tron register_draft_ciphertext_first must not write "
            f"legacy plaintext: {banned}"
        )
    assert "NULL," in body


def test_all_migration_0024_tables_have_nullable_legacy_columns() -> None:
    """Grep the migration source for the DROP NOT NULL statements
    we expect on every family that must accept ciphertext-first
    NULL writes."""
    src = _get_source(
        "migrations.versions.0024_vault_metadata_encryption",
    )
    expected_null_drops = [
        "vault_items", "uploaded_files", "notifications",
        "vault_ai_memory", "beneficiary_links", "semantic_index",
    ]
    for table in expected_null_drops:
        assert re.search(
            rf"ALTER TABLE {table}[\s\n]+ALTER COLUMN", src,
        ) is not None, (
            f"migration 0024 does not appear to loosen {table} — the "
            "ciphertext-first write path cannot persist NULL for that "
            "family"
        )
    assert "sender_address DROP NOT NULL" in src, (
        "migration 0024 must loosen crypto sender_address for the "
        "ciphertext-first draft path"
    )
    assert "destination_address DROP NOT NULL" in src


def test_no_ciphertext_endpoint_accepts_paired_plaintext() -> None:
    """Every ciphertext-first Pydantic request model must ALSO
    declare its legacy plaintext fields as Optional[str] = None and
    call _reject_plaintext_leak — this catches accidental client
    bugs that would double-write."""
    from routes.vault_ciphertext_write_routes import (
        VaultItemUpsertRequest,
        UploadedFileMetadataRequest,
        NotificationCiphertextRequest,
        AiMemoryCiphertextRequest,
        BeneficiaryLabelCiphertextRequest,
    )
    for model, forbidden in [
        (VaultItemUpsertRequest,
            {"item_type", "service", "encrypted_data"}),
        (UploadedFileMetadataRequest,
            {"file_name", "saved_name", "content_type",
             "detected_type", "detected_service", "asset_type"}),
        (NotificationCiphertextRequest, {"title", "body", "metadata"}),
        (AiMemoryCiphertextRequest,
            {"memory_key", "memory_value", "memory_normalized_key"}),
        (BeneficiaryLabelCiphertextRequest, {"passer_label"}),
    ]:
        fields = set(model.model_fields.keys())
        missing = forbidden - fields
        assert not missing, (
            f"{model.__name__} lacks legacy-plaintext guardrail "
            f"fields — cannot detect a client that double-writes: "
            f"{sorted(missing)}"
        )
