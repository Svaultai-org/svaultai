

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)


SCHEMA_VERSION: int = 1

                                                                 
DEFAULT_STALE_AFTER_SECONDS: int = 600              


REFRESH_IDLE       = "idle"
REFRESH_REFRESHING = "refreshing"
REFRESH_FAILED     = "failed"
REFRESH_STALE      = "stale"

REFRESH_STATUSES = (
    REFRESH_IDLE, REFRESH_REFRESHING, REFRESH_FAILED, REFRESH_STALE,
)


ERROR_REASON_NO_KEY        = "no_key"
ERROR_REASON_DB            = "db_error"
ERROR_REASON_COMPUTE       = "compute_failed"
ERROR_REASON_ENCRYPT       = "encrypt_failed"
ERROR_REASON_DECRYPT       = "decrypt_failed"

ERROR_REASONS = (
    ERROR_REASON_NO_KEY,
    ERROR_REASON_DB,
    ERROR_REASON_COMPUTE,
    ERROR_REASON_ENCRYPT,
    ERROR_REASON_DECRYPT,
)


@dataclass(frozen=True)
class CachedSnapshotRow:


    available:            bool
    snapshot:             Optional[dict]
    last_refreshed_at:    Optional[float]               
    refresh_status:       str
    refresh_error_class:  Optional[str]
    refresh_error_reason: Optional[str]
    snapshot_hash:        Optional[str]
    reason:               Optional[str] = None                                                


def _key_ok(key: Optional[bytes]) -> bool:
    return isinstance(key, (bytes, bytearray)) and len(key) == 32


def canonical_snapshot_hash(snapshot: dict) -> str:


    blob = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def read_cache(
    vault_id: str,
    key: Optional[bytes],
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> CachedSnapshotRow:


    from main import get_db
    from psycopg2.extras import RealDictCursor

    if not vault_id:
        return _empty_row("invalid_vault_id")

    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT vault_id, schema_version, coverage_jsonb,
                       file_counts_jsonb, saved_services_count,
                       encrypted_snapshot, snapshot_hash,
                       EXTRACT(EPOCH FROM last_refreshed_at)::DOUBLE PRECISION
                           AS last_refreshed_epoch,
                       refresh_status, refresh_error_class,
                       refresh_error_reason
                FROM vault_intelligence_summary
                WHERE vault_id = %s
                LIMIT 1
                """,
                (vault_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[INTEL-CACHE] read failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return _empty_row("db_error")

    if not row:
        return _empty_row("cache_miss")

    if int(row.get("schema_version") or 0) != SCHEMA_VERSION:
                                                                
                                                      
        return _empty_row("schema_mismatch")

    last_refreshed = row.get("last_refreshed_epoch")
    is_stale = bool(
        last_refreshed is None
        or (time.time() - float(last_refreshed)) > stale_after_seconds
    )

    encrypted = row.get("encrypted_snapshot")
    snapshot: Optional[dict] = None
    if not encrypted:
        return CachedSnapshotRow(
            available=False,
            snapshot=None,
            last_refreshed_at=last_refreshed,
            refresh_status=str(row.get("refresh_status") or REFRESH_IDLE),
            refresh_error_class=row.get("refresh_error_class"),
            refresh_error_reason=row.get("refresh_error_reason"),
            snapshot_hash=row.get("snapshot_hash"),
            reason="encrypted_snapshot_missing",
        )

    if not _key_ok(key):
                                                                  
                                                               
        return CachedSnapshotRow(
            available=False,
            snapshot=None,
            last_refreshed_at=last_refreshed,
            refresh_status=str(row.get("refresh_status") or REFRESH_IDLE),
            refresh_error_class=row.get("refresh_error_class"),
            refresh_error_reason=row.get("refresh_error_reason"),
            snapshot_hash=row.get("snapshot_hash"),
            reason="vault_locked",
        )

    try:
        from vault_core import decrypt_message
        plaintext = decrypt_message(str(encrypted), key)
        snapshot = json.loads(plaintext)
    except Exception:
        logger.warning(
            "[INTEL-CACHE] decrypt/parse failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return CachedSnapshotRow(
            available=False,
            snapshot=None,
            last_refreshed_at=last_refreshed,
            refresh_status=str(row.get("refresh_status") or REFRESH_IDLE),
            refresh_error_class=row.get("refresh_error_class"),
            refresh_error_reason=row.get("refresh_error_reason"),
            snapshot_hash=row.get("snapshot_hash"),
            reason="decrypt_failed",
        )

    return CachedSnapshotRow(
        available=True,
        snapshot=snapshot,
        last_refreshed_at=last_refreshed,
        refresh_status=str(row.get("refresh_status") or REFRESH_IDLE),
        refresh_error_class=row.get("refresh_error_class"),
        refresh_error_reason=row.get("refresh_error_reason"),
        snapshot_hash=row.get("snapshot_hash"),
        reason=("stale" if is_stale else None),
    )


def write_cache(
    vault_id: str,
    key: bytes,
    snapshot: dict,
) -> bool:


    if not vault_id:
        return False
    if not _key_ok(key):
        _mark_refresh_failed(
            vault_id,
            error_class="ValueError",
            error_reason=ERROR_REASON_NO_KEY,
        )
        return False
    if not isinstance(snapshot, dict):
        _mark_refresh_failed(
            vault_id,
            error_class="TypeError",
            error_reason=ERROR_REASON_COMPUTE,
        )
        return False

    try:
        snapshot_blob = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, default=str,
        )
        snap_hash = hashlib.sha256(
            snapshot_blob.encode("utf-8"),
        ).hexdigest()
    except Exception:
        _mark_refresh_failed(
            vault_id,
            error_class="JSONError",
            error_reason=ERROR_REASON_COMPUTE,
        )
        return False

    try:
        from vault_core import encrypt_message
        ciphertext = encrypt_message(snapshot_blob, key)
    except Exception as exc:
        logger.warning(
            "[INTEL-CACHE] encrypt failed vault=%s class=%s",
            (vault_id or "")[:8] + "...",
            type(exc).__name__,
        )
        _mark_refresh_failed(
            vault_id,
            error_class=type(exc).__name__,
            error_reason=ERROR_REASON_ENCRYPT,
        )
        return False

                                                            
    coverage = snapshot.get("coverage") or {}
    file_counts = (snapshot.get("files_by_kind") or {}).get("counts") or {}
    services_count = int(
        (snapshot.get("credentials") or {})
        .get("saved_credential_services_count") or 0
    )

    try:
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_intelligence_summary
                    (vault_id, schema_version, coverage_jsonb,
                     file_counts_jsonb, saved_services_count,
                     encrypted_snapshot, snapshot_hash,
                     last_refreshed_at, refresh_status,
                     refresh_error_class, refresh_error_reason,
                     created_at, updated_at)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s,
                        NOW(), %s, NULL, NULL, NOW(), NOW())
                ON CONFLICT (vault_id) DO UPDATE SET
                    schema_version       = EXCLUDED.schema_version,
                    coverage_jsonb       = EXCLUDED.coverage_jsonb,
                    file_counts_jsonb    = EXCLUDED.file_counts_jsonb,
                    saved_services_count = EXCLUDED.saved_services_count,
                    encrypted_snapshot   = EXCLUDED.encrypted_snapshot,
                    snapshot_hash        = EXCLUDED.snapshot_hash,
                    last_refreshed_at    = NOW(),
                    refresh_status       = %s,
                    refresh_error_class  = NULL,
                    refresh_error_reason = NULL,
                    updated_at           = NOW()
                """,
                (
                    vault_id, SCHEMA_VERSION,
                    json.dumps(coverage, default=str),
                    json.dumps(file_counts, default=str),
                    services_count,
                    ciphertext, snap_hash,
                    REFRESH_IDLE,
                    REFRESH_IDLE,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(
            "[INTEL-CACHE] write failed vault=%s class=%s",
            (vault_id or "")[:8] + "...",
            type(exc).__name__,
        )
        _mark_refresh_failed(
            vault_id,
            error_class=type(exc).__name__,
            error_reason=ERROR_REASON_DB,
        )
        return False

    logger.info(
        "[INTEL-CACHE] write_ok vault=%s hash=%s services=%d",
        (vault_id or "")[:8] + "...",
        (snap_hash or "")[:8],
        services_count,
    )
    return True


def mark_stale(vault_id: str) -> None:


    if not vault_id:
        return
    try:
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_intelligence_summary
                    (vault_id, refresh_status, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON CONFLICT (vault_id) DO UPDATE SET
                    refresh_status = %s,
                    updated_at = NOW()
                """,
                (vault_id, REFRESH_STALE, REFRESH_STALE),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[INTEL-CACHE] mark_stale failed vault=%s",
            (vault_id or "")[:8] + "...",
        )


def mark_refreshing(vault_id: str) -> None:


    if not vault_id:
        return
    try:
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_intelligence_summary
                    (vault_id, refresh_status, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON CONFLICT (vault_id) DO UPDATE SET
                    refresh_status = %s,
                    updated_at = NOW()
                """,
                (vault_id, REFRESH_REFRESHING, REFRESH_REFRESHING),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[INTEL-CACHE] mark_refreshing failed vault=%s",
            (vault_id or "")[:8] + "...",
        )


def _mark_refresh_failed(
    vault_id: str, *, error_class: str, error_reason: str,
) -> None:
    if not vault_id:
        return
    safe_reason = (
        error_reason if error_reason in ERROR_REASONS
        else ERROR_REASON_COMPUTE
    )
    try:
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_intelligence_summary
                    (vault_id, refresh_status, refresh_error_class,
                     refresh_error_reason, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (vault_id) DO UPDATE SET
                    refresh_status       = %s,
                    refresh_error_class  = %s,
                    refresh_error_reason = %s,
                    updated_at           = NOW()
                """,
                (
                    vault_id, REFRESH_FAILED,
                    error_class[:128], safe_reason,
                    REFRESH_FAILED, error_class[:128], safe_reason,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[INTEL-CACHE] mark_failed failed vault=%s",
            (vault_id or "")[:8] + "...",
        )


def _empty_row(reason: str) -> CachedSnapshotRow:
    return CachedSnapshotRow(
        available=False,
        snapshot=None,
        last_refreshed_at=None,
        refresh_status=REFRESH_IDLE,
        refresh_error_class=None,
        refresh_error_reason=None,
        snapshot_hash=None,
        reason=reason,
    )


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_STALE_AFTER_SECONDS",
    "REFRESH_IDLE", "REFRESH_REFRESHING", "REFRESH_FAILED", "REFRESH_STALE",
    "REFRESH_STATUSES",
    "ERROR_REASON_NO_KEY", "ERROR_REASON_DB", "ERROR_REASON_COMPUTE",
    "ERROR_REASON_ENCRYPT", "ERROR_REASON_DECRYPT", "ERROR_REASONS",
    "CachedSnapshotRow",
    "canonical_snapshot_hash",
    "read_cache",
    "write_cache",
    "mark_stale",
    "mark_refreshing",
]
