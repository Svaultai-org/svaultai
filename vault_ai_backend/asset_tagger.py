

from __future__ import annotations

import logging
from typing import Optional

from vault_core import get_db
                                                                      
                                                                    
from taxonomy import (
    ALLOWED_TAGS as _TAXONOMY_ALLOWED_TAGS,
    DOC_TYPE_TO_TAGS as _TAXONOMY_DOC_TYPE_TO_TAGS,
    ITEM_TYPE_TO_TAGS as _TAXONOMY_ITEM_TYPE_TO_TAGS,
    SERVICE_CATEGORY_TO_TAGS as _TAXONOMY_SERVICE_CATEGORY_TO_TAGS,
)


logger = logging.getLogger(__name__)


ALLOWED_TAGS = _TAXONOMY_ALLOWED_TAGS
DOC_TYPE_TO_TAGS = _TAXONOMY_DOC_TYPE_TO_TAGS


ITEM_TYPE_RULES = _TAXONOMY_ITEM_TYPE_TO_TAGS

_MEDIA_EXTS: tuple[str, ...] = (
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    ".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".bmp",
)
_MEDIA_CONTENT_PREFIXES: tuple[str, ...] = ("image/", "video/", "audio/")
_MEDIA_ASSET_TYPES: tuple[str, ...] = ("image", "video", "audio")

_RULE_CONFIDENCE: float = 1.0


def _resolve_category_safe(
    service_name: Optional[str], user_locale: str,
) -> Optional[str]:


    if not service_name:
        return None
    try:
        from service_resolver import resolve_service_category
        return resolve_service_category(service_name, user_locale)
    except Exception:
        return None


def classify_tags(
    *,
    file_name: Optional[str] = None,
    saved_name: Optional[str] = None,
    asset_type: Optional[str] = None,
    content_type: Optional[str] = None,
    detected_service: Optional[str] = None,
    item_type: Optional[str] = None,
    service: Optional[str] = None,
                                                                    
                                                                     
    doc_type: Optional[str] = None,
    doc_metadata: Optional[dict] = None,
                                                                   
                                                                 
    user_locale: str = "en",
) -> list[tuple[str, float]]:


    result: dict[str, float] = {}

    is_file = any(v is not None for v in (
        file_name, saved_name, asset_type, content_type, detected_service,
    ))
    is_item = any(v is not None for v in (service, item_type))

    if is_file:
                                                        
        if doc_type and doc_type in DOC_TYPE_TO_TAGS:
            for tag in DOC_TYPE_TO_TAGS[doc_type]:
                result[tag] = max(result.get(tag, 0.0), _RULE_CONFIDENCE)
                                                        
            if doc_metadata:
                if doc_metadata.get("country"):
                    result["travel"] = max(
                        result.get("travel", 0.0), _RULE_CONFIDENCE,
                    )
                if doc_metadata.get("merchant"):
                    result["finance"] = max(
                        result.get("finance", 0.0), _RULE_CONFIDENCE,
                    )

                                                                     
        category = _resolve_category_safe(detected_service, user_locale)
        if category:
            for tag in _TAXONOMY_SERVICE_CATEGORY_TO_TAGS.get(category, ()):
                result[tag] = max(result.get(tag, 0.0), _RULE_CONFIDENCE)

                                                              
        fn_lower = (file_name or "").lower()
        ct_lower = (content_type or "").lower()
        if (
            (asset_type or "").lower() in _MEDIA_ASSET_TYPES
            or any(ct_lower.startswith(p) for p in _MEDIA_CONTENT_PREFIXES)
            or any(fn_lower.endswith(ext) for ext in _MEDIA_EXTS)
        ):
            result["media"] = max(result.get("media", 0.0), _RULE_CONFIDENCE)

    if is_item:
                                                
        category = _resolve_category_safe(service, user_locale)
        if category:
            for tag in _TAXONOMY_SERVICE_CATEGORY_TO_TAGS.get(category, ()):
                result[tag] = max(result.get(tag, 0.0), _RULE_CONFIDENCE)

                                                   
        for base_tag in ITEM_TYPE_RULES.get((item_type or "").lower(), ()):
            result[base_tag] = max(result.get(base_tag, 0.0), _RULE_CONFIDENCE)

    return [(t, c) for t, c in result.items() if t in ALLOWED_TAGS]


def _delete_tags_for_file(cur, vault_id: str, file_id: str) -> None:
    cur.execute(
        """DELETE FROM vault_asset_tags
           WHERE vault_id = %s AND uploaded_file_id = %s""",
        (vault_id, file_id),
    )


def _delete_tags_for_item(cur, vault_id: str, item_id: int) -> None:
    cur.execute(
        """DELETE FROM vault_asset_tags
           WHERE vault_id = %s AND vault_item_id = %s""",
        (vault_id, item_id),
    )


def _insert_tags_for_file(cur, vault_id, file_id, tags) -> None:
    cur.executemany(
        """INSERT INTO vault_asset_tags
              (vault_id, source_kind, uploaded_file_id, tag, confidence)
           VALUES (%s, 'uploaded_file', %s, %s, %s)
           ON CONFLICT (vault_id, uploaded_file_id, tag)
                WHERE uploaded_file_id IS NOT NULL DO NOTHING""",
        [(vault_id, file_id, t, c) for t, c in tags],
    )


def _insert_tags_for_item(cur, vault_id, item_id, tags) -> None:
    cur.executemany(
        """INSERT INTO vault_asset_tags
              (vault_id, source_kind, vault_item_id, tag, confidence)
           VALUES (%s, 'vault_item', %s, %s, %s)
           ON CONFLICT (vault_id, vault_item_id, tag)
                WHERE vault_item_id IS NOT NULL DO NOTHING""",
        [(vault_id, item_id, t, c) for t, c in tags],
    )


def _fetch_doc_metadata_for_file(
    vault_id: str, file_id: str,
) -> tuple[Optional[str], Optional[dict]]:


    try:
        import json as _json
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT doc_type, metadata_json
                       FROM vault_document_metadata
                       WHERE vault_id=%s
                         AND uploaded_file_id=%s""",
                    (vault_id, file_id),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None, None
        doc_type_val = row[0]
        raw = row[1]
        if isinstance(raw, dict):
            md = raw
        else:
            try:
                md = _json.loads(raw or "{}")
            except Exception:
                md = {}
        return doc_type_val, md
    except Exception as e:
        logger.warning(
            "_fetch_doc_metadata_for_file failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )
        return None, None


def tag_uploaded_file_safe(
    vault_id: str, file_id: str, *,
    file_name: Optional[str] = None, saved_name: Optional[str] = None,
    asset_type: Optional[str] = None, content_type: Optional[str] = None,
    detected_service: Optional[str] = None, replace: bool = False,
                                                                    
                                                                    
    doc_type: Optional[str] = None,
    doc_metadata: Optional[dict] = None,
                                                                   
                                                                    
    user_locale: str = "en",
) -> None:


    try:
                                                                 
        if doc_type is None and doc_metadata is None:
            doc_type, doc_metadata = _fetch_doc_metadata_for_file(
                vault_id, file_id,
            )
        tags = classify_tags(
            file_name=file_name, saved_name=saved_name,
            asset_type=asset_type, content_type=content_type,
            detected_service=detected_service,
            doc_type=doc_type, doc_metadata=doc_metadata,
            user_locale=user_locale,
        )
        if not tags and not replace:
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_tags_for_file(cur, vault_id, file_id)
                if tags:
                    _insert_tags_for_file(cur, vault_id, file_id, tags)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "tag_uploaded_file_safe failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def tag_vault_item_safe(
    vault_id: str, item_id: int, *,
    service: Optional[str] = None, item_type: Optional[str] = None,
    replace: bool = False,
    user_locale: str = "en",
) -> None:


    try:
        tags = classify_tags(
            service=service, item_type=item_type, user_locale=user_locale,
        )
        if not tags and not replace:
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_tags_for_item(cur, vault_id, item_id)
                if tags:
                    _insert_tags_for_item(cur, vault_id, item_id, tags)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "tag_vault_item_safe failed vault=%s item=%s: %s",
            vault_id, item_id, e,
        )
