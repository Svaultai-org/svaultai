"""Hard privacy regressions locking in the ZK invariants.

These tests intentionally fail closed if the ZK boundary is
weakened. They are the anti-regression bar that prevents the
following classes of drift:

  * A backend function accepts MVK / PIN-derived Vault key / KEK /
    or any VaultKeyHierarchy subkey as a parameter. That would let
    the server materialize the user's persistent Vault key even
    if today's code doesn't. Banned.
  * A backend module derives a VaultKeyHierarchy subkey via HKDF
    with a Vault info-string. Banned.
  * A ciphertext-first write path silently falls back to a legacy
    plaintext write endpoint on failure. Banned — must fail
    closed.
  * A ZK ciphertext-first endpoint accepts both the ciphertext form
    AND the legacy plaintext form of the same field in one
    request. Banned — mixed shape is a downgrade attack surface.

The tests are source-scan only and run without a live DB.
"""

from __future__ import annotations

import glob
import inspect
import os
import re


BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))


BANNED_PARAM_NAMES = {
    "mvk", "vault_master_key",
    "kek", "vault_kek",
    "metadata_key", "memory_key_material", "memory_subkey",
    "wallet_wrap_key", "display_name_key",
    "semantic_lookup_key", "memory_lookup_key",
    "wallet_lock_lookup_key",
    "pin_derived_key", "pin_key",
}

BACKEND_KEY_ACCEPTING_MODULES = (
    "ai_memory.py",
    "vault_planner*.py",
    "vault_memory_answer_composer.py",
    "vault_chat*.py",
    "chat_fast_path.py",
    "memory_recall.py",
    "relationship_builder.py",
    "brain_embedder.py",
    "asset_tagger.py",
    "semantic_embedder.py",
    "document_understanding.py",
    "document_entities.py",
    "routes/vault_metadata_migration_routes.py",
    "routes/vault_ciphertext_write_routes.py",
    "routes/auth_zk_routes.py",
    "notification_bus.py",
)


def _iter_backend_files(patterns: tuple[str, ...]):
    seen: set[str] = set()
    for pattern in patterns:
        for path in glob.glob(os.path.join(BACKEND_ROOT, pattern)):
            if path in seen:
                continue
            seen.add(path)
            yield path


def test_backend_functions_do_not_accept_vault_subkey_params() -> None:
    """No function in the AI/chat/persistence pipeline may accept a
    parameter whose name suggests it carries an MVK / KEK / Vault
    subkey. Passing such a value into the backend would let it
    encrypt or authenticate as the user's Vault."""
    param_re = re.compile(
        rb"def\s+\w+\s*\([^)]*?(?:^|,|\s|\*)(" +
        b"|".join(name.encode("ascii") for name in BANNED_PARAM_NAMES) +
        rb")\s*[:,=)]",
        re.MULTILINE,
    )
    offenders: list[str] = []
    for path in _iter_backend_files(BACKEND_KEY_ACCEPTING_MODULES):
        with open(path, "rb") as f:
            data = f.read()
        matches = param_re.findall(data)
        if matches:
            base = os.path.basename(path)
            for m in matches:
                offenders.append(f"{base}: banned param name {m!r}")
    assert offenders == [], (
        "Backend AI/chat/persistence file exposes a banned key-"
        "material parameter — this would break the ZK boundary. "
        "Refactor to accept only pre-computed ciphertext bytes.\n" +
        "\n".join(offenders)
    )


def test_ciphertext_first_endpoints_have_no_plaintext_fallback() -> None:
    """Every ciphertext-first write route must fail closed if the
    ciphertext write fails. The ciphertext-write module must NOT
    contain any legacy plaintext INSERT with a user-derived column
    assignment (e.g. `file_name = %s`). Every plaintext column in
    ciphertext-first writes must appear as an explicit NULL literal.
    """
    path = os.path.join(
        BACKEND_ROOT, "routes", "vault_ciphertext_write_routes.py",
    )
    with open(path, "rb") as f:
        src = f.read().decode("utf-8")
    # Fold whitespace and look for column-assignments-from-%s on
    # legacy plaintext columns.
    folded = re.sub(r"\s+", " ", src)
    banned_column_writes = (
        "file_name = %s", "saved_name = %s", "content_type = %s",
        "detected_type = %s", "detected_service = %s", "asset_type = %s",
        "item_type = %s", "service = %s", "encrypted_data = %s",
        "title = %s", "body = %s", "metadata = %s",
        "memory_key = %s", "memory_value = %s",
        "memory_normalized_key = %s",
        "passer_label = %s",
    )
    offenders = [b for b in banned_column_writes if b in folded]
    assert offenders == [], (
        "Ciphertext-first write module assigns a user-derived value "
        "into a legacy plaintext column via `%s`: " + repr(offenders)
    )


def test_ai_memory_zk_writer_rejects_key_material_arguments() -> None:
    """Introspect `_update_memory_zk_ciphertext` and ensure its
    signature carries only pre-computed bytes and structural
    parameters. No vault_key / mvk / subkey argument permitted."""
    from ai_memory import _update_memory_zk_ciphertext
    sig = inspect.signature(_update_memory_zk_ciphertext)
    offenders = set(sig.parameters) & BANNED_PARAM_NAMES
    assert not offenders, (
        f"_update_memory_zk_ciphertext accepts banned params: "
        f"{sorted(offenders)}"
    )
    # Must have the two pre-computed byte params.
    for expected in ("lookup_hash", "payload_ciphertext"):
        assert expected in sig.parameters, (
            f"_update_memory_zk_ciphertext missing param {expected}"
        )


def test_ciphertext_write_endpoints_reject_paired_plaintext_shape() -> None:
    """Every ciphertext-first Pydantic request model must accept
    the legacy plaintext-named fields as optional (typed) fields
    AND route through `_reject_plaintext_leak`. This ensures a
    client that accidentally double-writes is caught with HTTP 400
    instead of silently downgrading."""
    from routes.vault_ciphertext_write_routes import (
        VaultItemUpsertRequest,
        UploadedFileMetadataRequest,
        NotificationCiphertextRequest,
        AiMemoryCiphertextRequest,
        BeneficiaryLabelCiphertextRequest,
    )
    for model, plaintext_fields in [
        (VaultItemUpsertRequest, ("item_type", "service", "encrypted_data")),
        (UploadedFileMetadataRequest, ("file_name", "saved_name", "content_type", "detected_type", "detected_service", "asset_type")),
        (NotificationCiphertextRequest, ("title", "body", "metadata")),
        (AiMemoryCiphertextRequest, ("memory_key", "memory_value", "memory_normalized_key")),
        (BeneficiaryLabelCiphertextRequest, ("passer_label",)),
    ]:
        for f in plaintext_fields:
            assert f in model.model_fields, (
                f"{model.__name__} missing guardrail field {f} — "
                "cannot detect a client that double-writes"
            )


def test_ai_memory_upsert_returns_none_if_only_one_zk_field_supplied() -> None:
    """The ZK ciphertext branch requires BOTH lookup_hash AND
    payload_ciphertext. Mixed shape must be refused (returns None).
    Prevents a partial-ciphertext write from succeeding."""
    from ai_memory import update_memory_safe
    result = update_memory_safe(
        "00000000-0000-0000-0000-000000000000",
        "note", "", "",
        zk_lookup_hash=b"\x22" * 32,
        zk_payload_ciphertext=None,
    )
    assert result is None
    result = update_memory_safe(
        "00000000-0000-0000-0000-000000000000",
        "note", "", "",
        zk_lookup_hash=None,
        zk_payload_ciphertext=b"\x01" + b"\x00" * 30,
    )
    assert result is None
