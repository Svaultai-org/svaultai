"""Default-off foundation for atomic MVK-blinded file conflict decisions.

An unlocked client must derive 32-byte, vault-keyed tokens for whole-file
content and for each effective (relative path, filename/saved name) pair.
This module never receives readable names, content, PINs, or the vault key.
The caller must keep the same transaction open through the V2 marker INSERT.
The new-file release gate stays closed until client and old-file parity exist.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from fastapi import HTTPException
from legacy_source_snapshot import FILE_SOURCE_FIELDS, source_snapshot


@dataclass(frozen=True)
class FileConflict:
    kind: str
    existing_file_id: str | None = None


def _tokens(content_token: bytes, name_tokens: tuple[bytes, ...]) -> tuple[bytes, ...]:
    if (not isinstance(content_token, bytes) or len(content_token) != 32 or
            not isinstance(name_tokens, tuple) or
            not 1 <= len(name_tokens) <= 2 or
            any(not isinstance(token, bytes) or len(token) != 32
                for token in name_tokens)):
        raise HTTPException(400, detail="private_file_conflict_tokens_invalid")
    return tuple(sorted(set(name_tokens)))


def _state_lock(cur, vault_id: str) -> dict:
    cur.execute(
        "INSERT INTO file_private_conflict_state(vault_id) VALUES (%s) "
        "ON CONFLICT (vault_id) DO NOTHING",
        (vault_id,),
    )
    cur.execute(
        "SELECT inventory_generation, indexed_generation, enforced "
        "FROM file_private_conflict_state WHERE vault_id=%s FOR UPDATE",
        (vault_id,),
    )
    state = cur.fetchone()
    if state is None:
        raise HTTPException(409, detail="private_file_conflict_state_missing")
    return state


def index_existing_file(
    cur, *, vault_id: str, file_id: str, file_size: int,
    content_token: bytes, name_tokens: tuple[bytes, ...],
    expected_source_snapshot: str,
) -> None:
    """Store client-derived tags for one current row; keep the gate closed.

    An authenticated, readback-bound route must call this later. The trigger
    serializes concurrent older writes through the state row; a write after
    this function removes the stale tags and invalidates completeness.
    """
    names = _tokens(content_token, name_tokens)
    _state_lock(cur, vault_id)
    cur.execute(
        f"SELECT {', '.join(FILE_SOURCE_FIELDS)}, upload_status "
        "FROM uploaded_files WHERE vault_id=%s AND id=%s",
        (vault_id, file_id),
    )
    row = cur.fetchone()
    if (row is None or row["upload_status"] != "complete" or
            row["encrypted_file_data"] is None or
            int(row["file_size"]) != file_size or
            source_snapshot("file", row, vault_id=vault_id,
                            record_id=file_id) != expected_source_snapshot):
        raise HTTPException(409, detail="private_file_source_changed")
    cur.execute(
        "INSERT INTO file_private_conflict_index "
        "(vault_id,file_id,file_size,content_token) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (vault_id,file_id) DO UPDATE SET "
        "file_size=EXCLUDED.file_size, content_token=EXCLUDED.content_token",
        (vault_id, file_id, file_size, content_token),
    )
    cur.execute(
        "DELETE FROM file_private_conflict_names "
        "WHERE vault_id=%s AND file_id=%s",
        (vault_id, file_id),
    )
    for token in names:
        cur.execute(
            "INSERT INTO file_private_conflict_names "
            "(vault_id,file_id,name_token) VALUES (%s,%s,%s)",
            (vault_id, file_id, token),
        )
    cur.execute(
        "UPDATE file_private_conflict_state SET indexed_generation=NULL "
        "WHERE vault_id=%s",
        (vault_id,),
    )


def ready_file_source_revision(
    row: dict, *, vault_id: str, file_id: str,
) -> str:
    """Bind a ready V2 file's immutable ciphertext and current name override.

    Ready chunks cannot be changed through the file API. The manifest and
    versioned name override are sufficient to detect an owner rename or file
    replacement between client readback and blinded-tag submission.
    """
    if (row is None or row["file_id"] != file_id or
            row["verification_state"] != "client_verified" or
            row["lifecycle_state"] not in
            ("legacy_migration_retired", "client_v2_ready") or
            bool(row["migrating_legacy"]) !=
            (row["lifecycle_state"] == "legacy_migration_retired") or
            row["has_legacy"] is not False or
            row["upload_status"] != "complete" or
            row["storage_mode"] != "inline" or
            int(row["marker_size"]) != int(row["total_bytes"]) or
            any(row[field] is not None for field in
                ("file_name", "saved_name", "content_type", "relative_path"))):
        raise HTTPException(409, detail="private_file_ready_source_unavailable")
    digest = hashlib.sha256(b"private-file-ready-source/v1\x00")
    for value in (
        vault_id, file_id, row["manifest_ciphertext"],
        row["saved_name_override_ciphertext"], row["name_version"],
        row["total_bytes"], row["chunk_size"], row["chunk_count"],
        row["migration_metadata_version"], row["lifecycle_state"],
    ):
        if value is None:
            digest.update(b"\x00")
            continue
        raw = (bytes(value) if isinstance(value, (bytes, bytearray, memoryview))
               else str(value).encode("utf-8"))
        digest.update(b"\x01" + len(raw).to_bytes(8, "big") + raw)
    return base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")


def index_ready_file(
    cur, *, vault_id: str, file_id: str, source_row: dict,
    expected_source_revision: str, content_token: bytes,
    name_tokens: tuple[bytes, ...],
) -> None:
    """Index a locked, client-read V2 file without exposing its contents."""
    names = _tokens(content_token, name_tokens)
    if ready_file_source_revision(
        source_row, vault_id=vault_id, file_id=file_id,
    ) != expected_source_revision:
        raise HTTPException(409, detail="private_file_ready_source_changed")
    _state_lock(cur, vault_id)
    cur.execute(
        "INSERT INTO file_private_conflict_index "
        "(vault_id,file_id,file_size,content_token) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (vault_id,file_id) DO UPDATE SET "
        "file_size=EXCLUDED.file_size, content_token=EXCLUDED.content_token",
        (vault_id, file_id, int(source_row["total_bytes"]), content_token),
    )
    cur.execute(
        "DELETE FROM file_private_conflict_names "
        "WHERE vault_id=%s AND file_id=%s",
        (vault_id, file_id),
    )
    for token in names:
        cur.execute(
            "INSERT INTO file_private_conflict_names "
            "(vault_id,file_id,name_token) VALUES (%s,%s,%s)",
            (vault_id, file_id, token),
        )
    cur.execute(
        "UPDATE file_private_conflict_state SET indexed_generation=NULL "
        "WHERE vault_id=%s",
        (vault_id,),
    )


def mark_index_complete(cur, *, vault_id: str) -> int:
    """Record coverage without activating the legacy-writer block."""
    state = _state_lock(cur, vault_id)
    cur.execute(
        "SELECT uf.id FROM uploaded_files uf "
        "LEFT JOIN file_private_conflict_index ci "
        "ON ci.vault_id=uf.vault_id AND ci.file_id=uf.id "
        "AND ci.file_size=uf.file_size "
        "WHERE uf.vault_id=%s AND uf.upload_status='complete' "
        "AND (ci.file_id IS NULL OR NOT EXISTS ("
        "SELECT 1 FROM file_private_conflict_names cn "
        "WHERE cn.vault_id=uf.vault_id AND cn.file_id=uf.id)) "
        "LIMIT 1",
        (vault_id,),
    )
    if cur.fetchone() is not None:
        raise HTTPException(409, detail="private_file_index_incomplete")
    generation = int(state["inventory_generation"])
    cur.execute(
        "UPDATE file_private_conflict_state "
        "SET indexed_generation=inventory_generation WHERE vault_id=%s",
        (vault_id,),
    )
    return generation


def inspect_and_reserve_new_file(
    cur, *, vault_id: str, file_id: str, file_size: int,
    content_token: bytes, name_tokens: tuple[bytes, ...],
    keep_content_duplicate: bool = False,
) -> FileConflict:
    """Make the conflict decision while holding the state row to commit.

    The caller must insert the ready V2 marker and commit in this transaction;
    an aborted transaction rolls this reservation back. An older writer's DB
    trigger waits on the same row and rejects while enforcement is active.
    """
    names = _tokens(content_token, name_tokens)
    state = _state_lock(cur, vault_id)
    if (state["enforced"] is not True or
            state["indexed_generation"] is None or
            state["indexed_generation"] != state["inventory_generation"]):
        raise HTTPException(409, detail="private_file_conflict_index_unavailable")
    cur.execute(
        "SELECT ci.file_id FROM file_private_conflict_index ci "
        "JOIN uploaded_files uf ON uf.vault_id=ci.vault_id AND uf.id=ci.file_id "
        "WHERE ci.vault_id=%s AND ci.content_token=%s AND ci.file_size=%s "
        "AND uf.upload_status='complete' "
        "ORDER BY (uf.duplicate_of_file_id IS NOT NULL), uf.created_at, uf.id "
        "LIMIT 1",
        (vault_id, content_token, file_size),
    )
    row = cur.fetchone()
    duplicate_id = row["file_id"] if row is not None else None
    if duplicate_id is not None and not keep_content_duplicate:
        return FileConflict("duplicate", row["file_id"])
    # The older keep-both path versions the name server-side. The private
    # server cannot read the name, so even a kept duplicate must arrive with
    # a nonconflicting client-selected name before it can be published.
    cur.execute(
        "SELECT cn.file_id FROM file_private_conflict_names cn "
        "JOIN uploaded_files uf ON uf.vault_id=cn.vault_id "
        "AND uf.id=cn.file_id "
        "WHERE cn.vault_id=%s AND cn.name_token=ANY(%s) "
        "AND uf.upload_status='complete' ORDER BY uf.created_at LIMIT 1",
        (vault_id, list(names)),
    )
    row = cur.fetchone()
    if row is not None:
        return FileConflict("name_conflict", row["file_id"])
    cur.execute(
        "INSERT INTO file_private_conflict_index "
        "(vault_id,file_id,file_size,content_token) VALUES (%s,%s,%s,%s)",
        (vault_id, file_id, file_size, content_token),
    )
    for token in names:
        cur.execute(
            "INSERT INTO file_private_conflict_names "
            "(vault_id,file_id,name_token) VALUES (%s,%s,%s)",
            (vault_id, file_id, token),
        )
    return FileConflict("available", duplicate_id)
