

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from vault_image_formats import (
    ALL_DECODE_BANDS,
    ALL_FORMAT_LABELS,
    FORMAT_LABEL_AVIF,
    FORMAT_LABEL_HEIC,
    FORMAT_LABEL_HEIF,
    FORMAT_LABEL_OTHER,
    canonicalize_image_mime,
    decoder_availability,
    detect_image_format,
    is_image_row,
    mime_from_extension,
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


def _row_extension(row: dict) -> str:


    name = (row.get("saved_name") or row.get("file_name") or "")
    if not name:
        return ""
    s = str(name).strip().lower()
    dot = s.rfind(".")
    if dot < 0 or dot == len(s) - 1:
        return ""
    return s[dot + 1:]


def _initial_counts() -> dict[str, int]:


    return {label: 0 for label in ALL_FORMAT_LABELS}


def _empty_band_counts() -> dict[str, int]:
    return {band: 0 for band in ALL_DECODE_BANDS}


def _heif_decoder_missing(avail: dict[str, bool]) -> bool:
    return not bool(avail.get("heif"))


def _avif_decoder_missing(avail: dict[str, bool]) -> bool:
    return not bool(avail.get("avif"))


def audit_vault_images(
    *, vault_id: Optional[str] = None,
    rows: Optional[Iterable[dict]] = None,
) -> dict[str, Any]:


    avail = decoder_availability()
    by_format = _initial_counts()
    by_canonical_mime: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    asset_type_image_mismatched = 0
    octet_stream_but_image = 0
    decoder_missing_count = 0
    total_image_like = 0
    total_rows_inspected = 0

    db_unavailable = False
    db_error_class = ""
    row_iter: Iterable[dict]
    if rows is not None:
        row_iter = rows
    else:
        try:
            row_iter = _fetch_rows(vault_id=vault_id)
        except Exception as exc:
            logger.exception(
                "[IMG-AUDIT] db_fetch_failed vault=%s "
                "exception_class=%s",
                (vault_id or "")[:8] + "…" if vault_id else "all",
                type(exc).__name__,
            )
            db_unavailable = True
            db_error_class = type(exc).__name__
            row_iter = []

    for row in row_iter:
        total_rows_inspected += 1
        ctype_raw = str(row.get("content_type") or "").strip()
        ctype = ctype_raw.lower()
        asset = str(row.get("asset_type") or "").strip().lower()
        ext = _row_extension(row)

        if not is_image_row(
            mime=ctype, file_name=row.get("saved_name") or row.get("file_name"),
            asset_type=asset,
        ):
            continue

        total_image_like += 1
        fmt = detect_image_format(
            mime=ctype,
            file_name=row.get("saved_name") or row.get("file_name"),
        )
        by_format[fmt] = by_format.get(fmt, 0) + 1

        canonical = (
            canonicalize_image_mime(ctype)
            or mime_from_extension(
                row.get("saved_name") or row.get("file_name"),
            )
            or "unknown"
        )
        by_canonical_mime[canonical] = (
            by_canonical_mime.get(canonical, 0) + 1
        )

        if ext:
            by_extension[ext] = by_extension.get(ext, 0) + 1

        if asset != "image":
            asset_type_image_mismatched += 1

        if ctype == "application/octet-stream":
            octet_stream_but_image += 1

        if fmt in (FORMAT_LABEL_HEIC, FORMAT_LABEL_HEIF):
            if _heif_decoder_missing(avail):
                decoder_missing_count += 1
        elif fmt == FORMAT_LABEL_AVIF:
            if _avif_decoder_missing(avail):
                decoder_missing_count += 1

    report = {
        "schema_version":              "vault_image_audit.v1",
        "vault_id_prefix":             (
            (vault_id or "")[:8] + "…" if vault_id else "all"
        ),
        "total_rows_inspected":        total_rows_inspected,
        "total_image_like":            total_image_like,
        "by_detected_format":          by_format,
        "by_canonical_mime":           by_canonical_mime,
        "by_extension":                by_extension,
        "asset_type_image_mismatched": asset_type_image_mismatched,
        "octet_stream_but_image":      octet_stream_but_image,
        "decoder_missing_count":       decoder_missing_count,
        "decoder_availability":        avail,
        "db_unavailable":              db_unavailable,
        "db_error_class":              db_error_class or None,
    }

                                                              
    logger.info(
        "[IMG-AUDIT] vault=%s rows=%d image_like=%d "
        "mismatched=%d octet_stream=%d decoder_missing=%d",
        report["vault_id_prefix"],
        total_rows_inspected,
        total_image_like,
        asset_type_image_mismatched,
        octet_stream_but_image,
        decoder_missing_count,
    )
    return report


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


__all__ = [
    "ROW_PROJECTION_COLUMNS",
    "audit_vault_images",
]
