"""Per-vault metadata migration endpoints (lazy backfill after unlock).

The client drives this loop after successful unlock. Each batch is
transactional: the client submits ciphertext values for a set of
legacy plaintext rows; the server writes ciphertext, nulls the
plaintext column, and advances the migration cursor.

Design invariants:

  * Every endpoint requires a valid session for the caller's vault
    (see ``verify_session_token``). No admin path exists.
  * The server never learns which vault key was used to produce the
    ciphertext. Payloads are opaque BYTEA.
  * A single failed batch is idempotent: re-applying the same batch
    is a no-op because the WHERE clause requires plaintext-not-null.
  * The server never reveals the plaintext (or lack thereof) of any
    other vault. Every SELECT is filtered by ``vault_id =
    principal["vault_id"]``.

Only ``uploaded_files``, ``vault_items``, ``notifications``, and
``vault_ai_memory`` are wired into the batch loop this turn.
``vault_document_metadata``, ``beneficiary_links``,
``crypto_*_drafts`` and the wallet-lock hash follow the same shape
and can be added by extending ``_TABLES`` without new endpoints.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth_local import (
    SessionPrincipal,
    verify_session_token,
)
from vault_core import get_db


logger = logging.getLogger(__name__)
router = APIRouter()


BATCH_SIZE_DEFAULT = 100
BATCH_SIZE_MAX = 250

MAX_CIPHERTEXT_BYTES = 128 * 1024


def _b64url_decode(text: str, *, name: str) -> bytes:
    if not isinstance(text, str) or not text:
        raise HTTPException(
            status_code=400, detail=f"{name} is required",
        )
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} is not valid base64url",
        ) from exc
    if len(raw) > MAX_CIPHERTEXT_BYTES:
        raise HTTPException(
            status_code=413, detail=f"{name} exceeds byte limit",
        )
    return raw


class _TableSpec:
    """Describes one table's legacy → ciphertext migration shape."""

    def __init__(
        self,
        *,
        table: str,
        id_column: str,
        plaintext_columns: tuple[str, ...],
        ciphertext_columns: tuple[str, ...],
        cursor_column: str,
    ) -> None:
        self.table = table
        self.id_column = id_column
        self.plaintext_columns = plaintext_columns
        self.ciphertext_columns = ciphertext_columns
        self.cursor_column = cursor_column


_TABLES: dict[str, _TableSpec] = {
    "uploaded_files": _TableSpec(
        table="uploaded_files",
        id_column="id",
        plaintext_columns=(
            "file_name", "saved_name", "content_type",
            "detected_type", "detected_service", "asset_type",
        ),
        ciphertext_columns=(
            "file_name_ciphertext", "saved_name_ciphertext",
            "content_type_ciphertext", "detected_type_ciphertext",
            "detected_service_ciphertext", "asset_type_ciphertext",
        ),
        cursor_column="uploaded_files_done_upto",
    ),
    "vault_items": _TableSpec(
        table="vault_items",
        id_column="id",
        plaintext_columns=("item_type", "service"),
        ciphertext_columns=("item_type_ciphertext", "service_ciphertext"),
        cursor_column="vault_items_done_upto",
    ),
    "notifications": _TableSpec(
        table="notifications",
        id_column="id",
        plaintext_columns=("title", "body", "metadata"),
        ciphertext_columns=(
            "title_ciphertext", "body_ciphertext", "metadata_ciphertext",
        ),
        cursor_column="notifications_done_upto",
    ),
    "vault_ai_memory": _TableSpec(
        table="vault_ai_memory",
        id_column="id",
        plaintext_columns=(
            "memory_key", "memory_value", "memory_normalized_key",
        ),
        ciphertext_columns=("payload_ciphertext",),
        cursor_column="vault_ai_memory_done_upto",
    ),
}


def _ensure_state_row(cur, vault_id: str) -> None:
    cur.execute(
        """
        INSERT INTO vault_metadata_migration_state (vault_id)
        VALUES (%s)
        ON CONFLICT (vault_id) DO NOTHING
        """,
        (vault_id,),
    )


class NextBatchResponse(BaseModel):
    table: str
    rows: list[dict[str, Any]]
    remaining_estimate: int
    completed_tables: list[str]


class ApplyBatchRow(BaseModel):
    row_id: Any = Field(..., description="Primary-key value (int or text).")
    ciphertext: dict[str, str] = Field(
        ..., description="Per-column base64url ciphertext values.",
    )


class ApplyBatchRequest(BaseModel):
    table: str = Field(..., min_length=1, max_length=64)
    rows: list[ApplyBatchRow]


class ApplyBatchResponse(BaseModel):
    applied: int
    skipped: int


class MigrationStatusResponse(BaseModel):
    completed_tables: list[str]
    pending_tables: list[str]
    completed_at: Optional[str]


@router.get(
    "/vault/metadata-migration/next-batch",
    response_model=NextBatchResponse,
)
def next_batch(
    principal: SessionPrincipal = Depends(verify_session_token),
    limit: int = BATCH_SIZE_DEFAULT,
) -> NextBatchResponse:
    if limit < 1 or limit > BATCH_SIZE_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {BATCH_SIZE_MAX}",
        )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_state_row(cur, principal["vault_id"])
        cur.execute(
            "SELECT * FROM vault_metadata_migration_state WHERE vault_id = %s",
            (principal["vault_id"],),
        )
        state = cur.fetchone() or {}

        completed: list[str] = [
            name
            for name, spec in _TABLES.items()
            if state.get(spec.cursor_column) is not None
        ]

        for name, spec in _TABLES.items():
            if state.get(spec.cursor_column) is not None:
                continue

            plaintext_filter = " OR ".join(
                f"{col} IS NOT NULL" for col in spec.plaintext_columns
            )
            columns_selected = [spec.id_column, *spec.plaintext_columns]
            cur.execute(
                f"""
                SELECT {', '.join(columns_selected)}
                  FROM {spec.table}
                  WHERE vault_id = %s
                    AND ({plaintext_filter})
                  LIMIT %s
                """,
                (principal["vault_id"], limit),
            )
            rows_raw = cur.fetchall() or []

            if not rows_raw:
                cur.execute(
                    f"""
                    UPDATE vault_metadata_migration_state
                       SET {spec.cursor_column} = NOW(),
                           updated_at = NOW()
                     WHERE vault_id = %s
                    """,
                    (principal["vault_id"],),
                )
                conn.commit()
                completed.append(name)
                continue

            cur.execute(
                f"""
                SELECT COUNT(*) AS n
                  FROM {spec.table}
                  WHERE vault_id = %s
                    AND ({plaintext_filter})
                """,
                (principal["vault_id"],),
            )
            remaining = int((cur.fetchone() or {}).get("n") or 0)

            rows_out: list[dict[str, Any]] = []
            for r in rows_raw:
                rows_out.append({
                    "row_id": r[spec.id_column],
                    "plaintext": {
                        col: r[col] for col in spec.plaintext_columns
                        if r[col] is not None
                    },
                })

            conn.commit()
            return NextBatchResponse(
                table=name,
                rows=rows_out,
                remaining_estimate=remaining,
                completed_tables=completed,
            )

        cur.execute(
            """
            UPDATE vault_metadata_migration_state
               SET completed_at = COALESCE(completed_at, NOW()),
                   updated_at = NOW()
             WHERE vault_id = %s
            """,
            (principal["vault_id"],),
        )
        conn.commit()

        return NextBatchResponse(
            table="",
            rows=[],
            remaining_estimate=0,
            completed_tables=completed,
        )
    finally:
        conn.close()


@router.post(
    "/vault/metadata-migration/apply-batch",
    response_model=ApplyBatchResponse,
)
def apply_batch(
    payload: ApplyBatchRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> ApplyBatchResponse:
    spec = _TABLES.get(payload.table)
    if spec is None:
        raise HTTPException(
            status_code=400, detail="unknown migration table",
        )
    if not payload.rows:
        return ApplyBatchResponse(applied=0, skipped=0)
    if len(payload.rows) > BATCH_SIZE_MAX:
        raise HTTPException(
            status_code=413,
            detail=f"batch exceeds {BATCH_SIZE_MAX} rows",
        )

    applied = 0
    skipped = 0

    conn = get_db()
    try:
        cur = conn.cursor()
        for row in payload.rows:
            ct_map: dict[str, bytes] = {}
            for ct_col in spec.ciphertext_columns:
                raw_val = row.ciphertext.get(ct_col)
                if raw_val is None:
                    continue
                ct_map[ct_col] = _b64url_decode(raw_val, name=ct_col)

            if not ct_map:
                skipped += 1
                continue

            set_ciphertext_parts = [
                f"{col} = %s" for col in ct_map
            ]
            set_plaintext_parts = [
                f"{col} = NULL" for col in spec.plaintext_columns
            ]
            plaintext_not_null_parts = " OR ".join(
                f"{col} IS NOT NULL" for col in spec.plaintext_columns
            )

            params: list[Any] = [
                *ct_map.values(),
                row.row_id, principal["vault_id"],
            ]
            cur.execute(
                f"""
                UPDATE {spec.table}
                   SET {', '.join(set_ciphertext_parts)},
                       {', '.join(set_plaintext_parts)}
                 WHERE {spec.id_column} = %s
                   AND vault_id = %s
                   AND ({plaintext_not_null_parts})
                """,
                params,
            )
            if cur.rowcount == 1:
                applied += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()

    return ApplyBatchResponse(applied=applied, skipped=skipped)


@router.get(
    "/vault/metadata-migration/status",
    response_model=MigrationStatusResponse,
)
def status(
    principal: SessionPrincipal = Depends(verify_session_token),
) -> MigrationStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_state_row(cur, principal["vault_id"])
        cur.execute(
            "SELECT * FROM vault_metadata_migration_state WHERE vault_id = %s",
            (principal["vault_id"],),
        )
        state = cur.fetchone() or {}
        conn.commit()
    finally:
        conn.close()

    completed = [
        name for name, spec in _TABLES.items()
        if state.get(spec.cursor_column) is not None
    ]
    pending = [name for name in _TABLES if name not in completed]

    completed_at = state.get("completed_at")
    completed_at_iso = completed_at.isoformat() if completed_at else None

    return MigrationStatusResponse(
        completed_tables=completed,
        pending_tables=pending,
        completed_at=completed_at_iso,
    )


__all__ = ["router"]
