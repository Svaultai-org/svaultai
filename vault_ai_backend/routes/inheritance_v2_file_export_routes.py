"""Default-off, ciphertext-only file export after private inheritance release.

The beneficiary can decrypt these bytes locally with the released owner MVK.
This is a read path, not a claim or import: it never changes an owner vault,
exposes plaintext metadata, or treats a partly migrated vault as complete.
"""

from __future__ import annotations

import base64
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from inheritance_protocol import (
    ZK_BENEFICIARY_V2_CRYPTO_VERSION,
    ZK_BENEFICIARY_V2_MARKER,
    zk_beneficiary_v2_enabled,
)
from routes.file_v2_routes import (
    GCM_FRAMING_BYTES,
    MAX_CHUNK_BYTES,
    MAX_CHUNKS,
    MAX_FILE_BYTES,
    MAX_EXTRA_V3_MANIFEST_CIPHERTEXT_BYTES,
)
from subscription_entitlement import require_file_read
from vault_core import get_db

router = APIRouter()
FLAG_NAME = "VAULTAI_ZK_BENEFICIARY_V2_FILE_EXPORT_ENABLED"
MAX_PAGE = 100


def _enabled() -> None:
    if not zk_beneficiary_v2_enabled() or os.getenv(
        FLAG_NAME, "false",
    ).strip().lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")


def _file_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(status_code=404, detail="Not found")
    return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(value)).rstrip(b"=").decode("ascii")


def _released_owner(cur, *, link_id: int, beneficiary_vault_id: str) -> str:
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="Not found")
    cur.execute(
        """SELECT bl.passer_vault_id, bl.wrapped_vault_key,
                  bl.pairing_state, ic.crypto_version
             FROM beneficiary_links bl
             JOIN inheritance_credentials ic
               ON ic.beneficiary_link_id = bl.id
              AND ic.deleted_at IS NULL
            WHERE bl.id = %s AND bl.beneficiary_vault_id = %s""",
        (link_id, beneficiary_vault_id),
    )
    link = cur.fetchone()
    if (not link or link["wrapped_vault_key"] != ZK_BENEFICIARY_V2_MARKER or
            link["pairing_state"] != "released" or
            int(link["crypto_version"]) != ZK_BENEFICIARY_V2_CRYPTO_VERSION):
        raise HTTPException(status_code=404, detail="Inheritance export unavailable")
    return str(link["passer_vault_id"])


def _require_all_owner_files_ready(cur, owner_vault_id: str) -> None:
    # A released saved-item package is not evidence that files have moved.
    # Require every visible file marker to have a complete V2 ciphertext
    # replacement before returning any file inventory or bytes.
    cur.execute(
        """SELECT 1
             FROM uploaded_files u
             LEFT JOIN file_v2_records r
               ON r.file_id = u.id AND r.vault_id = u.vault_id::text
            WHERE u.vault_id = %s
              AND (u.upload_status <> 'complete'
                   OR u.encrypted_file_data IS NOT NULL
                   OR r.file_id IS NULL
                   OR r.crypto_version <> 'client_mvk_v2'
                   OR r.verification_state <> 'client_verified'
                   OR r.lifecycle_state NOT IN
                      ('legacy_migration_retired', 'client_v2_ready')
                   OR r.total_bytes <> u.file_size)
            LIMIT 1""",
        (owner_vault_id,),
    )
    if cur.fetchone():
        raise HTTPException(
            status_code=409, detail="owner_files_need_private_migration",
        )


def _ready_file(cur, *, owner_vault_id: str, file_id: str) -> dict:
    cur.execute(
        """SELECT r.file_id, r.crypto_version, r.manifest_ciphertext,
                  r.total_bytes, r.chunk_size, r.chunk_count,
                  r.lifecycle_state, r.verification_state,
                  r.saved_name_override_ciphertext, r.name_version,
                  r.migration_metadata_version
             FROM file_v2_records r
             JOIN uploaded_files u
               ON u.id = r.file_id AND u.vault_id::text = r.vault_id
            WHERE r.file_id = %s AND r.vault_id = %s
              AND u.upload_status = 'complete'
              AND u.encrypted_file_data IS NULL
              AND u.file_size = r.total_bytes
              AND r.crypto_version = 'client_mvk_v2'
              AND r.verification_state = 'client_verified'
              AND r.lifecycle_state IN
                  ('legacy_migration_retired', 'client_v2_ready')""",
        (file_id, owner_vault_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Inherited file unavailable")
    total = int(row["total_bytes"])
    size = int(row["chunk_size"])
    count = int(row["chunk_count"])
    manifest = bytes(row["manifest_ciphertext"])
    if (total < 0 or total > MAX_FILE_BYTES or size <= 0 or
            size > MAX_CHUNK_BYTES or count < 0 or count > MAX_CHUNKS or
            count != (total + size - 1) // size or
            not GCM_FRAMING_BYTES < len(manifest) <=
                MAX_EXTRA_V3_MANIFEST_CIPHERTEXT_BYTES):
        raise HTTPException(status_code=409, detail="inherited_file_invalid_framing")
    return row


@router.get("/inheritance/v2/{link_id}/files")
def list_released_v2_files(
    link_id: int,
    after_file_id: str = Query(default="", max_length=128),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if after_file_id:
        _file_id(after_file_id)
    if not 1 <= limit <= MAX_PAGE:
        raise HTTPException(status_code=400, detail="Invalid page size")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        owner = _released_owner(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        _require_all_owner_files_ready(cur, owner)
        cur.execute(
            """SELECT r.file_id, r.total_bytes, r.chunk_size, r.chunk_count
                 FROM uploaded_files u
                 JOIN file_v2_records r
                   ON r.file_id = u.id AND r.vault_id = u.vault_id::text
                WHERE u.vault_id = %s AND u.id > %s
                  AND u.upload_status = 'complete'
                  AND u.encrypted_file_data IS NULL
                  AND u.file_size = r.total_bytes
                  AND r.crypto_version = 'client_mvk_v2'
                  AND r.verification_state = 'client_verified'
                  AND r.lifecycle_state IN
                      ('legacy_migration_retired', 'client_v2_ready')
                ORDER BY u.id ASC LIMIT %s""",
            (owner, after_file_id, limit + 1),
        )
        rows = cur.fetchall() or []
        page = rows[:limit]
        return {
            "owner_vault_id": owner,
            "beneficiary_link_id": link_id,
            "files": [
                {
                    "file_id": row["file_id"],
                    "total_bytes": int(row["total_bytes"]),
                    "chunk_size": int(row["chunk_size"]),
                    "chunk_count": int(row["chunk_count"]),
                }
                for row in page
            ],
            "next_after_file_id": page[-1]["file_id"] if len(rows) > limit else None,
        }
    finally:
        conn.close()


@router.get("/inheritance/v2/{link_id}/files/{file_id}/manifest")
def get_released_v2_file_manifest(
    link_id: int,
    file_id: str,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    _file_id(file_id)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        owner = _released_owner(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        _require_all_owner_files_ready(cur, owner)
        row = _ready_file(cur, owner_vault_id=owner, file_id=file_id)
        require_file_read(principal, int(row["total_bytes"]))
        override = row["saved_name_override_ciphertext"]
        return {
            "owner_vault_id": owner,
            "beneficiary_link_id": link_id,
            **{key: row[key] for key in (
                "file_id", "crypto_version", "total_bytes", "chunk_size",
                "chunk_count", "lifecycle_state", "verification_state",
                "name_version", "migration_metadata_version",
            )},
            "manifest_ciphertext": _b64(row["manifest_ciphertext"]),
            "saved_name_override_ciphertext": (
                _b64(override) if override is not None else None
            ),
        }
    finally:
        conn.close()


@router.get("/inheritance/v2/{link_id}/files/{file_id}/chunk/{chunk_index}")
def get_released_v2_file_chunk(
    link_id: int,
    file_id: str,
    chunk_index: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    _file_id(file_id)
    if chunk_index < 0:
        raise HTTPException(status_code=404, detail="Inherited chunk unavailable")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        owner = _released_owner(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        _require_all_owner_files_ready(cur, owner)
        row = _ready_file(cur, owner_vault_id=owner, file_id=file_id)
        if chunk_index >= int(row["chunk_count"]):
            raise HTTPException(status_code=404, detail="Inherited chunk unavailable")
        require_file_read(principal, int(row["total_bytes"]))
        cur.execute(
            """SELECT c.ciphertext
                 FROM file_v2_chunks c
                 JOIN file_v2_records r ON r.file_id = c.file_id
                WHERE c.file_id = %s AND c.chunk_index = %s
                  AND r.vault_id = %s
                  AND r.verification_state = 'client_verified'
                  AND r.lifecycle_state IN
                      ('legacy_migration_retired', 'client_v2_ready')""",
            (file_id, chunk_index, owner),
        )
        chunk = cur.fetchone()
        if chunk is None:
            raise HTTPException(status_code=409, detail="Inherited file incomplete")
        encoded = bytes(chunk["ciphertext"])
        plain_size = min(
            int(row["chunk_size"]),
            int(row["total_bytes"]) - chunk_index * int(row["chunk_size"]),
        )
        if len(encoded) != plain_size + GCM_FRAMING_BYTES:
            raise HTTPException(status_code=409, detail="Inherited chunk invalid")
        return {
            "owner_vault_id": owner,
            "beneficiary_link_id": link_id,
            "file_id": file_id,
            "chunk_index": chunk_index,
            "ciphertext": _b64(encoded),
        }
    finally:
        conn.close()
