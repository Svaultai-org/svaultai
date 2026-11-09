"""Commitments to the still-active legacy source during MVK staging.

The digest is an integrity token, not a PIN verifier. It covers the stored
ciphertext and every legacy metadata field that can affect migration. Both
export and stage compute it from one locked database row.
"""

from __future__ import annotations

import base64
import hashlib


ITEM_SOURCE_FIELDS = (
    "encrypted_data", "item_type", "service",
    "item_type_ciphertext", "service_ciphertext",
)
# A delete must also be bound to the staged V2 copy. Keep the migration
# source_snapshot contract unchanged for older export and staging clients.
ITEM_DELETE_FIELDS = ITEM_SOURCE_FIELDS + (
    "payload_ciphertext", "title_lookup_hash", "title_revision",
    "legacy_item_rename_active",
)
FILE_SOURCE_FIELDS = (
    "encrypted_file_data", "file_size", "file_name", "saved_name",
    "content_type", "detected_type", "detected_service", "asset_type",
    "relative_path", "extracted_text", "file_name_ciphertext",
    "saved_name_ciphertext", "content_type_ciphertext",
    "detected_type_ciphertext", "detected_service_ciphertext",
    "asset_type_ciphertext",
)
MAX_SOURCE_CIPHERTEXT_CHARS = 64 * 1024 * 1024


def _feed(hasher, value: object) -> None:
    if value is None:
        hasher.update(b"\x00")
        return
    hasher.update(b"\x01")
    if isinstance(value, (str, int)):
        raw = str(value).encode("utf-8")
    else:
        raw = bytes(value)
    hasher.update(len(raw).to_bytes(8, "big"))
    hasher.update(raw)


def source_digest(
    kind: str, row: dict, *, vault_id: str, record_id: str | int,
) -> bytes:
    if kind == "item":
        fields = ITEM_SOURCE_FIELDS
    elif kind == "file":
        fields = FILE_SOURCE_FIELDS
    else:
        raise ValueError("invalid legacy source kind")
    hasher = hashlib.sha256(f"legacy-{kind}-source/v1\x00".encode("ascii"))
    _feed(hasher, vault_id)
    _feed(hasher, str(record_id))
    for field in fields:
        _feed(hasher, row.get(field))
    return hasher.digest()


def source_snapshot(
    kind: str, row: dict, *, vault_id: str, record_id: str | int,
) -> str:
    return base64.urlsafe_b64encode(
        source_digest(kind, row, vault_id=vault_id, record_id=record_id),
    ).decode("ascii").rstrip("=")


def item_delete_snapshot(
    row: dict, *, vault_id: str, record_id: int,
) -> str:
    """Bind a delete confirmation to both legacy and staged item state."""
    hasher = hashlib.sha256(b"legacy-item-delete/v1\x00")
    _feed(hasher, vault_id)
    _feed(hasher, str(record_id))
    for field in ITEM_DELETE_FIELDS:
        _feed(hasher, row.get(field))
    return base64.urlsafe_b64encode(hasher.digest()).decode("ascii").rstrip("=")
