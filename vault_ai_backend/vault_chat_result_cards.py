

from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import Any, Optional


logger = logging.getLogger(__name__)


SCHEMA_VERSION: str = "file_search_results.v2"
COPY_VERSION:   str = "sharp_empty_state_2026_06_28"


THUMBNAIL_MAX_SIDE: int = int(
    os.getenv("VAULTAI_RESULT_CARD_THUMB_MAX_SIDE", "256"),
)

                                                                         
THUMBNAIL_JPEG_QUALITY: int = int(
    os.getenv("VAULTAI_RESULT_CARD_THUMB_QUALITY", "70"),
)

                                                                      
MAX_THUMBNAIL_BYTES: int = int(
    os.getenv("VAULTAI_RESULT_CARD_THUMB_MAX_BYTES", str(48 * 1024)),
)

                                                                          
MAX_TOTAL_THUMB_BYTES: int = int(
    os.getenv("VAULTAI_RESULT_CARD_TOTAL_THUMB_BYTES", str(512 * 1024)),
)


def _is_image_mime(mime: Optional[str]) -> bool:
                                                                    
                                                                    
    try:
        from vault_image_formats import is_supported_image_mime
        if is_supported_image_mime(mime):
            return True
    except Exception:
        pass
    return bool(mime) and str(mime).lower().startswith("image/")


def _is_pdf_mime(mime: Optional[str]) -> bool:
    return bool(mime) and str(mime).lower() == "application/pdf"


def _render_image_thumbnail(image_bytes: bytes) -> Optional[bytes]:


    if not image_bytes:
        return None
    try:
        from PIL import Image
    except Exception:
        logger.exception("[RESULT-CARDS] Pillow import failed")
        return None
                                                                  
                                                
    try:
        from vault_image_formats import register_optional_decoders
        register_optional_decoders()
    except Exception:
                                                                    
                                                                  
        pass
    try:
        img = Image.open(io.BytesIO(image_bytes))
                                                  
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail(
            (THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE),
            Image.LANCZOS,
        )
        buf = io.BytesIO()
        img.save(
            buf, format="JPEG",
            quality=THUMBNAIL_JPEG_QUALITY,
            optimize=True,
        )
        return buf.getvalue()
    except Exception:
        logger.exception("[RESULT-CARDS] image thumbnail render failed")
        return None


def _render_pdf_thumbnail(pdf_bytes: bytes) -> Optional[bytes]:


    if not pdf_bytes:
        return None
    try:
        import fitz
    except Exception:
        logger.exception("[RESULT-CARDS] fitz import failed")
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        logger.exception("[RESULT-CARDS] fitz.open failed")
        return None
    try:
        if int(doc.page_count or 0) <= 0:
            return None
                                                                      
                                                                      
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=144)
        png = pix.tobytes("png")
        return _render_image_thumbnail(png)
    except Exception:
        logger.exception("[RESULT-CARDS] pdf thumbnail render failed")
        return None
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _decrypt_file_bytes(
    *, file_id: str, key: bytes,
) -> Optional[bytes]:
    if not file_id or not key:
        return None
    try:
        from main import get_db
        from psycopg2.extras import RealDictCursor
    except Exception:
        logger.exception("[RESULT-CARDS] db helpers unavailable")
        return None
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT encrypted_file_data, storage_mode "
            "FROM uploaded_files WHERE id = %s",
            (file_id,),
        )
        row = cur.fetchone()
    except Exception:
        logger.exception(
            "[RESULT-CARDS] db read failed file_id=%s",
            (file_id or "")[:8],
        )
        return None
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    if not row:
        return None
    if (row.get("storage_mode") or "inline") != "inline":
                                                                
        return None
    enc = row.get("encrypted_file_data")
    if not enc or not isinstance(enc, str):
        return None
    try:
        from vault_core import decrypt_bytes
        return decrypt_bytes(enc, key)
    except Exception:
        logger.exception(
            "[RESULT-CARDS] decrypt failed file_id=%s",
            (file_id or "")[:8],
        )
        return None


def _ui_file_kind(*, mime: Optional[str], hit_file_kind: str) -> str:
    if _is_image_mime(mime):
        return "image"
    if _is_pdf_mime(mime):
        return "pdf"
    kind = (hit_file_kind or "").lower().strip()
    if kind in {"image", "pdf", "video", "audio", "archive", "text"}:
        return kind
    return "other"


def _batch_fetch_row_metadata(
    *, file_ids: list[str], vault_id: Optional[str],
) -> dict[str, dict]:


    if not file_ids:
        return {}
    try:
        from main import get_db
        from psycopg2.extras import RealDictCursor
    except Exception:
        logger.exception("[RESULT-CARDS] db helpers unavailable (metadata)")
        return {}
    out: dict[str, dict] = {}
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if vault_id:
            cur.execute(
                "SELECT id, content_type, saved_name, relative_path, "
                "storage_mode "
                "FROM uploaded_files "
                "WHERE id = ANY(%s) AND vault_id = %s",
                (file_ids, vault_id),
            )
        else:
            cur.execute(
                "SELECT id, content_type, saved_name, relative_path, "
                "storage_mode "
                "FROM uploaded_files WHERE id = ANY(%s)",
                (file_ids,),
            )
        for row in cur.fetchall():
            out[str(row["id"])] = {
                "content_type":  row.get("content_type"),
                "saved_name":    row.get("saved_name"),
                "relative_path": row.get("relative_path"),
                "storage_mode":  row.get("storage_mode"),
            }
    except Exception:
        logger.exception("[RESULT-CARDS] metadata batch read failed")
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    return out


def _build_result_row_safe(
    *,
    hit: dict,
    rows_by_id: dict,
    thumbnail_fetcher: Any,
    total_thumb_bytes: int,
    capped: bool,
    thumb_counts: dict[str, int],
) -> dict:


    fid = str(hit.get("file_id") or "")
    row = rows_by_id.get(fid) or {}
    mime = (
        (row.get("content_type") or row.get("mime_type") or "")
        if isinstance(row, dict) else ""
    )
    saved_name = (
        row.get("saved_name") if isinstance(row, dict) else None
    )
    relative_path = (
        row.get("relative_path") if isinstance(row, dict) else None
    )

    file_kind = _ui_file_kind(
        mime=mime, hit_file_kind=str(hit.get("file_kind") or ""),
    )

    try:
        conf = float(hit.get("confidence") or 0.0)
    except Exception:
        conf = 0.0
    if conf >= 0.75:
        conf_band = "strong"
    elif conf >= 0.50:
        conf_band = "medium"
    else:
        conf_band = "weak"

    thumb_b64: Optional[str] = None
    if not capped and file_kind in ("image", "pdf"):
        file_bytes = None
        try:
            file_bytes = thumbnail_fetcher(fid)
        except Exception:
                                                                 
            logger.exception(
                "[RESULT-CARDS] thumbnail_fetcher raised file_id=%s",
                fid[:8],
            )
        if file_bytes:
            try:
                if file_kind == "image":
                    jpeg = _render_image_thumbnail(file_bytes)
                else:
                    jpeg = _render_pdf_thumbnail(file_bytes)
            except Exception:
                                                                  
                                                                     
                logger.exception(
                    "[RESULT-CARDS] thumbnail_render_raised file_id=%s "
                    "kind=%s", fid[:8], file_kind,
                )
                jpeg = None
            if jpeg and len(jpeg) <= MAX_THUMBNAIL_BYTES:
                if total_thumb_bytes + len(jpeg) > MAX_TOTAL_THUMB_BYTES:
                    capped = True
                else:
                    try:
                        thumb_b64 = base64.b64encode(jpeg).decode("ascii")
                        total_thumb_bytes += len(jpeg)
                        thumb_counts[file_kind] = thumb_counts.get(
                            file_kind, 0,
                        ) + 1
                    except Exception:
                                                                  
                                                                
                        thumb_b64 = None

    if thumb_b64 is None:
        thumb_counts["none"] = thumb_counts.get("none", 0) + 1

    result_row = {
        "file_id":          fid,
        "file_name":        str(hit.get("file_name") or ""),
        "saved_name":       saved_name or None,
        "relative_path":    relative_path or None,
        "mime_type":        mime or None,
        "file_kind":        file_kind,
        "asset_type":       file_kind,
        "evidence_type":    str(hit.get("evidence_type") or ""),
        "match_type":       str(hit.get("match_type") or ""),
        "document_type":    str(hit.get("document_type") or "unknown"),
        "matched_name":     hit.get("matched_name") or None,
        "confidence":       round(conf, 2),
        "match_confidence": conf_band,
        "match_reason":     str(hit.get("evidence") or ""),
        "thumbnail_base64": thumb_b64,
        "thumbnail_mime":   "image/jpeg" if thumb_b64 else None,
        "classification_strength": str(
            hit.get("classification_strength") or ""
        ) or None,
        "match_status": str(hit.get("match_status") or "") or None,
    }
    return {
        "row":               result_row,
        "total_thumb_bytes": total_thumb_bytes,
        "capped":            capped,
        "thumb_counts":      thumb_counts,
    }


ERROR_BAND_SYSTEM_ERROR:   str = "system_error"
ERROR_BAND_BUDGET_HIT:     str = "budget_exceeded"
ERROR_BAND_TOOL_RAISED:    str = "tool_raised"


def build_system_error_envelope(
    *,
    query: str,
    query_kind: str = "id_photo_visual",
    error_slug: str = "tool_raised",
    exception_class: Optional[str] = None,
) -> str:


    message = (
        "Something went wrong while searching your vault. "
        "Please try again."
    )
    payload = {
        "type":                 "file_search_results",
        "schema_version":       SCHEMA_VERSION,
        "copy_version":         COPY_VERSION,
        "query":                str(query or ""),
        "count":                0,
        "results":              [],
        "message":              message,
        "pending_count":        0,
        "stale_count":          0,
        "pending_embedding_count": 0,
        "semantic_available":   True,
        "is_complete":          False,
        "incomplete_reason":    error_slug or "tool_raised",
        "query_kind":           query_kind or "generic",
        "weak_hits_dropped":    0,
        "candidate_id_docs_count": 0,
        "name_mismatch_count":  0,
        "requested_person_name": None,
                                                                  
                                                                 
        "error_band":           ERROR_BAND_SYSTEM_ERROR,
        "exception_class":      str(exception_class or "") or None,
    }
    logger.warning(
        "[RESULT-CARDS] system_error_envelope shipped error_slug=%s "
        "exception_class=%s",
        error_slug or "tool_raised",
        exception_class or "none",
    )
    return json.dumps(payload, ensure_ascii=False)


def build_find_in_vault_envelope(
    *,
    query: str,
    find_result: dict,
    key: Optional[bytes],
    vault_id: Optional[str] = None,
    rows_by_id: Optional[dict] = None,
    thumbnail_fetcher: Optional[Any] = None,
) -> str:


    try:
        return _build_find_in_vault_envelope_inner(
            query=query, find_result=find_result, key=key,
            vault_id=vault_id, rows_by_id=rows_by_id,
            thumbnail_fetcher=thumbnail_fetcher,
        )
    except Exception as exc:
        logger.exception(
            "[RESULT-CARDS] envelope_build_raised query_kind=%s",
            (
                str(find_result.get("query_kind"))
                if isinstance(find_result, dict) else "unknown"
            ),
        )
        qk = "generic"
        if isinstance(find_result, dict):
            qk = str(find_result.get("query_kind") or "generic")
        return build_system_error_envelope(
            query=query, query_kind=qk,
            error_slug="envelope_build_raised",
            exception_class=type(exc).__name__,
        )


def _build_find_in_vault_envelope_inner(
    *,
    query: str,
    find_result: dict,
    key: Optional[bytes],
    vault_id: Optional[str] = None,
    rows_by_id: Optional[dict] = None,
    thumbnail_fetcher: Optional[Any] = None,
) -> str:


    hits = find_result.get("hits") if isinstance(find_result, dict) else None
    if not isinstance(hits, list):
        hits = []

    hit_ids: list[str] = []
    seen_for_batch: set[str] = set()
    for h in hits:
        if not isinstance(h, dict):
            continue
        fid = str(h.get("file_id") or "")
        if fid and fid not in seen_for_batch:
            seen_for_batch.add(fid)
            hit_ids.append(fid)

    if rows_by_id is None:
        rows_by_id = _batch_fetch_row_metadata(
            file_ids=hit_ids, vault_id=vault_id,
        )

    if thumbnail_fetcher is None:
        def _default_fetcher(fid: str) -> Optional[bytes]:
            return _decrypt_file_bytes(file_id=fid, key=key or b"")
        thumbnail_fetcher = _default_fetcher

    results: list[dict] = []
    total_thumb_bytes = 0
    capped = False
    thumb_counts: dict[str, int] = {"image": 0, "pdf": 0, "none": 0}

    seen_ids: set[str] = set()
    per_hit_failures = 0
    for h in hits:
        if not isinstance(h, dict):
            continue
        fid = str(h.get("file_id") or "")
        if not fid:
            continue
        if fid in seen_ids:
            continue
        seen_ids.add(fid)

                                                                   
        try:
            _row_built = _build_result_row_safe(
                hit=h, rows_by_id=rows_by_id,
                thumbnail_fetcher=thumbnail_fetcher,
                total_thumb_bytes=total_thumb_bytes,
                capped=capped, thumb_counts=thumb_counts,
            )
        except Exception:
            per_hit_failures += 1
            logger.exception(
                "[RESULT-CARDS] per_hit_build_failed file_id=%s",
                fid[:8],
            )
                                                             
            results.append({
                "file_id":          fid,
                "file_name":        str(h.get("file_name") or ""),
                "saved_name":       None,
                "relative_path":    None,
                "mime_type":        None,
                "file_kind":        str(h.get("file_kind") or "other"),
                "asset_type":       str(h.get("file_kind") or "other"),
                "evidence_type":    str(h.get("evidence_type") or ""),
                "match_type":       str(h.get("match_type") or ""),
                "document_type":    str(h.get("document_type") or "unknown"),
                "matched_name":     h.get("matched_name") or None,
                "confidence":       0.0,
                "match_confidence": "weak",
                "match_reason":     "",
                "thumbnail_base64": None,
                "thumbnail_mime":   None,
                "classification_strength": None,
                "match_status":     None,
            })
            thumb_counts["none"] += 1
            continue
                               
        results.append(_row_built["row"])
        total_thumb_bytes = _row_built["total_thumb_bytes"]
        capped = _row_built["capped"]
        thumb_counts = _row_built["thumb_counts"]

    is_complete = bool(find_result.get("complete", True)) \
        if isinstance(find_result, dict) else True
    coverage = find_result.get("coverage") \
        if isinstance(find_result, dict) else None
                                                                
                                                              
    query_kind = (
        str(find_result.get("query_kind") or "")
        if isinstance(find_result, dict) else ""
    ) or "generic"
    weak_hits_dropped = 0
    candidate_id_docs_count = 0
    name_mismatch_count = 0
    requested_person_name = ""
    requested_doc_type = ""
    requested_doc_type_label = ""
    other_id_docs_count = 0
    other_id_doc_types: list[str] = []
    if isinstance(find_result, dict):
        try:
            candidate_id_docs_count = int(
                find_result.get("candidate_id_docs_count") or 0
            )
        except Exception:
            candidate_id_docs_count = 0
        try:
            name_mismatch_count = int(
                find_result.get("name_mismatch_count") or 0
            )
        except Exception:
            name_mismatch_count = 0
        requested_person_name = str(
            find_result.get("requested_person_name") or ""
        )
                                                             
        requested_doc_type = str(
            find_result.get("requested_doc_type") or ""
        )
        requested_doc_type_label = str(
            find_result.get("requested_doc_type_label") or ""
        )
        try:
            other_id_docs_count = int(
                find_result.get("other_id_docs_count") or 0
            )
        except Exception:
            other_id_docs_count = 0
        raw_other_types = find_result.get("other_id_doc_types") or []
        if isinstance(raw_other_types, list):
            other_id_doc_types = [
                str(t) for t in raw_other_types if isinstance(t, str)
            ]
    if isinstance(coverage, dict):
        try:
            weak_hits_dropped = int(
                coverage.get("weak_hits_dropped") or 0
            )
        except Exception:
            weak_hits_dropped = 0

    message = _build_summary_message(
        results=results,
        is_complete=is_complete,
        query=query,
        query_kind=query_kind,
        weak_hits_dropped=weak_hits_dropped,
        candidate_id_docs_count=candidate_id_docs_count,
        name_mismatch_count=name_mismatch_count,
        requested_person_name=requested_person_name,
        requested_doc_type=requested_doc_type,
        requested_doc_type_label=requested_doc_type_label,
        other_id_docs_count=other_id_docs_count,
        other_id_doc_types=other_id_doc_types,
    )

    payload = {
        "type":                 "file_search_results",
                                                                  
                                          
        "schema_version":       SCHEMA_VERSION,
        "copy_version":         COPY_VERSION,
        "query":                str(query or ""),
        "count":                len(results),
        "results":              results,
        "message":              message,
        "pending_count":        0,
        "stale_count":          0,
        "pending_embedding_count": 0,
        "semantic_available":   True,
                                                                  
                                                         
        "is_complete":          is_complete,
        "incomplete_reason": (
            None if is_complete else "budget_exceeded"
        ),
                                                                
                                                             
        "query_kind":           query_kind,
        "weak_hits_dropped":    weak_hits_dropped,
                                                             
                                                       
        "candidate_id_docs_count": candidate_id_docs_count,
        "name_mismatch_count":     name_mismatch_count,
        "requested_person_name":   (
            requested_person_name or None
        ),
                                                                 
                                                                
        "requested_doc_type":      requested_doc_type or None,
        "requested_doc_type_label": (
            requested_doc_type_label or None
        ),
        "other_id_docs_count":     other_id_docs_count,
        "other_id_doc_types":      other_id_doc_types,
    }

    logger.info(
        "[RESULT-CARDS] hits=%d cards=%d thumbs_image=%d "
        "thumbs_pdf=%d thumbs_none=%d total_thumb_bytes=%d "
        "capped=%s complete=%s",
        len(hits),
        len(results),
        thumb_counts["image"],
        thumb_counts["pdf"],
        thumb_counts["none"],
        total_thumb_bytes,
        capped,
        is_complete,
    )
                                                                   
                                                                   
    if isinstance(coverage, dict):
        try:
            logger.debug(
                "[RESULT-CARDS] coverage=%s",
                json.dumps({
                    k: v for k, v in coverage.items()
                    if isinstance(k, str)
                }),
            )
        except Exception:
            pass

    return json.dumps(payload, ensure_ascii=False)


def _pluralize_doc_noun(noun: str, n: int) -> str:


    if n == 1 or not noun:
        return noun
                                                     
    if noun.endswith("y"):
        return noun[:-1] + "ies"
    if noun.endswith("s") or noun.endswith("x") or noun.endswith("ch"):
        return noun + "es"
    return noun + "s"


def _humanize_other_id_types(types: list[str]) -> str:


    from vault_complete_search import DOC_TYPE_NOUN
    if not types:
        return ""
    names: list[str] = []
    for t in types:
        n = DOC_TYPE_NOUN.get(t)
        if not n or n in names:
            continue
                                                                 
                            
        names.append(_pluralize_doc_noun(n, 2))
    if not names:
        return ""
    if len(names) == 1:
        return f"like {names[0]}"
    if len(names) == 2:
        return f"like {names[0]} and {names[1]}"
    return f"like {', '.join(names[:-1])}, and {names[-1]}"


def _build_summary_message(
    *, results: list[dict], is_complete: bool, query: str,
    query_kind: str = "generic",
    weak_hits_dropped: int = 0,
    candidate_id_docs_count: int = 0,
    name_mismatch_count: int = 0,
    requested_person_name: str = "",
    requested_doc_type: str = "",
    requested_doc_type_label: str = "",
    other_id_docs_count: int = 0,
    other_id_doc_types: Optional[list[str]] = None,
) -> str:


    n = len(results)
    is_strict = query_kind == "id_photo_visual"
    person_label = (requested_person_name or "").strip()

    if n == 0:
        if not is_complete:
                                                                
                                                           
            return (
                "Something went wrong while searching your vault. "
                "Please try again."
            )

                                                               
        if name_mismatch_count > 0 and person_label:
            return (
                f"I found ID documents in your vault, but none "
                f"matched {person_label}."
            )
                                                                   
                                                                 
        if requested_doc_type and requested_doc_type_label:
            label = requested_doc_type_label
            article = (
                "an" if label[:1].lower() in {"a", "e", "i", "o", "u"}
                else "a"
            )
            base = (
                f"I couldn't find {article} {label} in your vault."
            )
            others = other_id_doc_types or []
            if other_id_docs_count > 0 and others:
                tail = _humanize_other_id_types(others)
                if tail:
                    return (
                        f"{base} I found other ID documents "
                        f"{tail}, but no {label}."
                    )
                return (
                    f"{base} I found other ID documents, but no "
                    f"{label}."
                )
            return base
        if candidate_id_docs_count > 0:
                                                              
                                                              
            if person_label:
                return (
                    f"I found ID documents in your vault, but "
                    f"none matched {person_label}."
                )
            return (
                "I found ID documents in your vault, but none "
                "matched your request."
            )

        if is_strict:
            if weak_hits_dropped > 0:
                return (
                    "No actual ID photo found in your vault. "
                    "Some files only mentioned an ID in passing "
                    "— ask for \"documents that mention my "
                    "license\" to include those."
                )
                                                               
                                                                 
            return "I couldn't find any ID documents in your vault."

        if person_label:
            return (
                f"I couldn't find any files matching {person_label}."
            )
        return "No matching files found in your vault."

                            
    suffix = "s" if n != 1 else ""

    if is_strict:
                                                                  
                                                                
        if requested_doc_type and requested_doc_type_label:
            label_plural = _pluralize_doc_noun(
                requested_doc_type_label, n,
            )
            msg = (
                f"I found {n} matching {label_plural}."
            )
            if not is_complete:
                msg = (
                    f"Search incomplete — found {n} matching "
                    f"{label_plural} so far."
                )
            return msg
                                                          
                                                        
        msg = f"I found {n} matching ID photo{suffix}."
        if not is_complete:
            msg = (
                f"Search incomplete — found {n} matching ID "
                f"photo{suffix} so far."
            )
        return msg

    types = {(r.get("document_type") or "").lower() for r in results}
    types.discard("unknown")
    types.discard("")
    type_phrase = "matching"
    if len(types) == 1:
        t = next(iter(types))
        type_phrase = {
            "driver_license": "driver-license",
            "passport":       "passport",
            "id_photo":       "ID-photo",
        }.get(t, t.replace("_", "-"))

    msg = (
        f"I found {n} {type_phrase} file{suffix} in your vault."
    )
    if not is_complete:
        msg = (
            f"Search incomplete — found {n} {type_phrase} "
            f"file{suffix} so far."
        )
    return msg


__all__ = [
    "THUMBNAIL_MAX_SIDE",
    "THUMBNAIL_JPEG_QUALITY",
    "MAX_THUMBNAIL_BYTES",
    "MAX_TOTAL_THUMB_BYTES",
    "SCHEMA_VERSION",
    "COPY_VERSION",
    "ERROR_BAND_SYSTEM_ERROR",
    "ERROR_BAND_BUDGET_HIT",
    "ERROR_BAND_TOOL_RAISED",
    "build_find_in_vault_envelope",
    "build_system_error_envelope",
    "_render_image_thumbnail",
    "_render_pdf_thumbnail",
    "_decrypt_file_bytes",
    "_build_summary_message",
    "_ui_file_kind",
]
