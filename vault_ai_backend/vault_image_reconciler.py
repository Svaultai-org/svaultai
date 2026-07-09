

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from vault_image_formats import (
    ALL_FORMAT_LABELS,
    detect_image_format,
    is_image_row,
)


logger = logging.getLogger(__name__)


ROW_PROJECTION_COLUMNS: tuple[str, ...] = (
    "id",
    "vault_id",
    "content_type",
    "asset_type",
    "saved_name",
    "file_name",
)


def _initial_counts() -> dict[str, int]:
    return {label: 0 for label in ALL_FORMAT_LABELS}


def _column_exists(conn, table: str, column: str) -> bool:


    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        return cur.fetchone() is not None
    except Exception:
        logger.exception(
            "[IMG-RECONCILER] column_probe_failed table=%s col=%s",
            table, column,
        )
        return False


def reconcile_vault_images(
    *,
    vault_id: Optional[str] = None,
    dry_run: bool = True,
    rows: Optional[Iterable[dict]] = None,
    db_executor: Optional[Any] = None,
) -> dict[str, Any]:


    by_format = _initial_counts()
    candidates: list[dict] = []

    if rows is not None:
        row_iter: Iterable[dict] = rows
    else:
        try:
            row_iter = _fetch_rows(vault_id=vault_id)
        except Exception as exc:
            logger.exception(
                "[IMG-RECONCILER] db_fetch_failed vault=%s "
                "exception_class=%s",
                (vault_id or "")[:8] + "…" if vault_id else "all",
                type(exc).__name__,
            )
            return _empty_report(
                vault_id=vault_id, dry_run=dry_run,
                db_unavailable=True,
                db_error_class=type(exc).__name__,
            )

    total_rows_inspected = 0
    for row in row_iter:
        total_rows_inspected += 1
        ctype = str(row.get("content_type") or "").strip().lower()
        asset = str(row.get("asset_type") or "").strip().lower()

        if not is_image_row(
            mime=ctype,
            file_name=row.get("saved_name") or row.get("file_name"),
            asset_type=asset,
        ):
            continue
        if asset == "image":
            continue

        fmt = detect_image_format(
            mime=ctype,
            file_name=row.get("saved_name") or row.get("file_name"),
        )
        by_format[fmt] = by_format.get(fmt, 0) + 1
        candidates.append({
            "id": row.get("id"),
            "from_asset_type": asset or "",
            "detected_format": fmt,
        })

    would_update = len(candidates)

    applied_updates = 0
    failed_rows: list[dict] = []

    if not dry_run and candidates:
        if db_executor is not None:
            exec_report = db_executor(candidates)
            applied_updates = int(exec_report.get("updated") or 0)
            failed_rows = list(exec_report.get("failed") or [])
        else:
            try:
                applied_updates, failed_rows = _apply_updates(
                    candidates=candidates,
                )
            except Exception as exc:
                logger.exception(
                    "[IMG-RECONCILER] apply_failed "
                    "exception_class=%s", type(exc).__name__,
                )
                failed_rows = [
                    {
                        "id":              c.get("id"),
                        "exception_class": type(exc).__name__,
                    }
                    for c in candidates
                ]
                applied_updates = 0

    report = {
        "schema_version":        "vault_image_reconciler.v1",
        "vault_id_prefix":       (
            (vault_id or "")[:8] + "…" if vault_id else "all"
        ),
        "dry_run":               dry_run,
        "total_rows_inspected":  total_rows_inspected,
        "would_update":          would_update,
        "updated":               applied_updates,
        "failed":                len(failed_rows),
        "by_detected_format":    by_format,
                                                               
                                                     
        "failure_classes": sorted({
            str(f.get("exception_class") or "Unknown")
            for f in failed_rows
        }),
        "db_unavailable":        False,
        "db_error_class":        None,
    }
    logger.info(
        "[IMG-RECONCILER] vault=%s dry_run=%s rows=%d "
        "would_update=%d updated=%d failed=%d",
        report["vault_id_prefix"], dry_run,
        total_rows_inspected, would_update, applied_updates,
        len(failed_rows),
    )
    return report


def _empty_report(
    *, vault_id: Optional[str], dry_run: bool,
    db_unavailable: bool, db_error_class: Optional[str],
) -> dict[str, Any]:
    return {
        "schema_version":       "vault_image_reconciler.v1",
        "vault_id_prefix":      (
            (vault_id or "")[:8] + "…" if vault_id else "all"
        ),
        "dry_run":              dry_run,
        "total_rows_inspected": 0,
        "would_update":         0,
        "updated":              0,
        "failed":                0,
        "by_detected_format":   _initial_counts(),
        "failure_classes":      [],
        "db_unavailable":       db_unavailable,
        "db_error_class":       db_error_class,
    }


def _fetch_rows(
    *, vault_id: Optional[str],
) -> Iterable[dict]:
    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cols = ", ".join(ROW_PROJECTION_COLUMNS)
        if vault_id:
            cur.execute(
                f"SELECT {cols} FROM uploaded_files "
                "WHERE vault_id = %s AND upload_status = 'complete'",
                (vault_id,),
            )
        else:
            cur.execute(
                f"SELECT {cols} FROM uploaded_files "
                "WHERE upload_status = 'complete'",
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _apply_updates(
    *, candidates: list[dict],
) -> tuple[int, list[dict]]:


    if not candidates:
        return 0, []
    from main import get_db

    conn = get_db()
    has_format_col = _column_exists(
        conn, "uploaded_files", "detected_image_format",
    )

    updated = 0
    failed: list[dict] = []
    try:
        cur = conn.cursor()
        for c in candidates:
            try:
                if has_format_col:
                    cur.execute(
                        "UPDATE uploaded_files "
                        "SET asset_type = 'image', "
                        "    detected_image_format = %s "
                        "WHERE id = %s",
                        (c.get("detected_format"), c.get("id")),
                    )
                else:
                    cur.execute(
                        "UPDATE uploaded_files "
                        "SET asset_type = 'image' "
                        "WHERE id = %s",
                        (c.get("id"),),
                    )
                updated += 1
            except Exception as exc:
                failed.append({
                    "id":              c.get("id"),
                    "exception_class": type(exc).__name__,
                })
        if failed and updated == 0:
                                                              
            conn.rollback()
        else:
            conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return updated, failed


__all__ = [
    "ROW_PROJECTION_COLUMNS",
    "reconcile_vault_images",
]
