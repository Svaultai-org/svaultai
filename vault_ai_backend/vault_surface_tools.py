

from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


MAX_EXPIRING_ITEMS:        int = 50
MAX_ENTITY_RESULTS:        int = 50
MAX_ENTITY_FILES:          int = 30
MAX_RELATIONSHIP_ROWS:     int = 50
MAX_CATEGORY_FILES:        int = 50
MAX_ACTIVITY_ROWS:         int = 25
MAX_WINDOW_DAYS:           int = 3650                                      
                                                                         

_ENTITY_TYPES = (
    "identity", "travel", "government", "finance", "tax",
    "business", "medical", "education", "insurance", "legal",
    "personal", "other",
)

_EXPIRY_SEVERITIES = ("info", "warn", "critical", "expired")


def _err(name: str, **extra: Any) -> str:
    payload = {"error": name}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _iso(value: Any) -> str:
    try:
        return value.isoformat() if value else ""
    except Exception:
        return ""


def _clamp_window_days(window: Any, default: int) -> int:
    try:
        n = int(window)
    except Exception:
        return default
    if n <= 0:
        return default
    return min(n, MAX_WINDOW_DAYS)


SURFACE_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_vault_status",
            "description": (
                "High-level state of the user's vault: vault "
                "name, lock state, total files, total saved "
                "credentials, total bytes, and analysis coverage. "
                "Use this when the user asks 'what does my vault "
                "look like', 'how big is my vault', 'how much "
                "have you analyzed', or before producing any "
                "summary-style answer so the numbers come from "
                "real state."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_expiring_items",
            "description": (
                "List active expiry alerts the vault is tracking: "
                "passports, visas, IDs, driver licenses, "
                "insurance, tax deadlines, contracts, "
                "subscriptions, and custom dates. Returns up to "
                f"{MAX_EXPIRING_ITEMS} items ordered by expiry "
                "date ascending. Each row carries the SOURCE "
                "(file or saved item), expiry_type, expiry_date, "
                "severity, and alert_window_days. Use this when "
                "the user asks 'what's expiring soon', 'do I "
                "have anything expiring', 'what should I "
                "renew'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window_days": {
                        "type": "integer",
                        "description": (
                            "Only include alerts where "
                            "expiry_date is within this many "
                            "days from today. Omit for all "
                            "active alerts."
                        ),
                    },
                    "severity": {
                        "type": "string",
                        "description": (
                            "Optional filter. Closed set: info, "
                            "warn, critical, expired."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expiry_alert",
            "description": (
                "Get the details of ONE expiry alert by alert_id. "
                "Returns the source file or saved-item identity, "
                "expiry_type, expiry_date, severity, and window "
                "configuration. Use this when the user asks "
                "about a specific expiring item surfaced by "
                "list_expiring_items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "integer",
                        "description": "Alert id from list_expiring_items.",
                    },
                },
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vault_entities",
            "description": (
                "List the entities (people, places, organizations, "
                "etc.) the vault has extracted across every "
                "analyzed file. Closed-set entity_type categories: "
                "identity, travel, government, finance, tax, "
                "business, medical, education, insurance, legal, "
                "personal, other. Returns up to "
                f"{MAX_ENTITY_RESULTS} entries with the entity "
                "value, type, and how many files it appears in. "
                "Use this when the user asks 'what people are in "
                "my vault', 'what organizations do I have on "
                "file', 'list everyone the vault knows about'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Optional filter. Closed set: " +
                            ", ".join(_ENTITY_TYPES) + "."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files_for_entity",
            "description": (
                "Find every file in the vault where a specific "
                "entity (person, organization, place) appears. "
                "Returns file_id + name + folder for up to "
                f"{MAX_ENTITY_FILES} files. Pair with "
                "read_file_text / read_image_with_vision / "
                "inspect_uploaded_file to actually inspect the "
                "matching files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_value": {
                        "type": "string",
                        "description": (
                            "The entity to search for "
                            "(case-insensitive)."
                        ),
                    },
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Optional filter. Same closed set as "
                            "list_vault_entities."
                        ),
                    },
                },
                "required": ["entity_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_file_relationships",
            "description": (
                "List the relationships the vault has detected "
                "between files / saved items. Each row is a "
                "(source, target, relation_type) tuple where "
                "relation_type is from a closed set: "
                "travel_related, identity_related, "
                "business_related, finance_related, "
                "tax_related, medical_related, family_related, "
                "security_related, media_related, and others. "
                "Returns up to "
                f"{MAX_RELATIONSHIP_ROWS} rows. Use this when "
                "the user asks 'which files belong together', "
                "'what's related to my passport', 'show me "
                "everything around my tax docs'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": (
                            "Optional. Restrict to relationships "
                            "involving this file as source or "
                            "target."
                        ),
                    },
                    "relation_type": {
                        "type": "string",
                        "description": (
                            "Optional closed-set filter, e.g. "
                            "travel_related, identity_related, "
                            "finance_related."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_document_categories",
            "description": (
                "List the distinct document categories "
                "(document_purpose values) the vault has "
                "classified its files into, with counts per "
                "category. Examples include id_document, "
                "passport, visa, financial_document, "
                "tax_document, medical_document, contract, "
                "credential_export, saved_login_list. Use this "
                "when the user asks 'what categories of "
                "documents do I have', 'show me my document "
                "types', or before listing files of a specific "
                "category."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files_by_category",
            "description": (
                "List the files the vault has classified under a "
                "specific document_purpose. Returns up to "
                f"{MAX_CATEGORY_FILES} files with file_id + name "
                "+ folder + classification confidence. Use this "
                "after list_document_categories to drill into "
                "one category, e.g. 'show me my tax documents' "
                "→ list_files_by_category('tax_document')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_purpose": {
                        "type": "string",
                        "description": (
                            "The category to list. Use the exact "
                            "values returned by "
                            "list_document_categories."
                        ),
                    },
                },
                "required": ["document_purpose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vault_activity",
            "description": (
                "Recent vault activity: file uploads and saved "
                "credentials over the last N days. Returns up to "
                f"{MAX_ACTIVITY_ROWS} items ordered by created_at "
                "descending. Closed-set kinds: file_upload, "
                "credential_save. Use this when the user asks "
                "'what did I recently add', 'what happened this "
                "week in my vault', 'show me my recent uploads "
                "and saves'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window_days": {
                        "type": "integer",
                        "description": (
                            "Look back this many days. Default 30."
                        ),
                    },
                    "kind": {
                        "type": "string",
                        "description": (
                            "Optional closed-set filter: "
                            "file_upload or credential_save."
                        ),
                    },
                },
            },
        },
    },
]


def get_vault_status(*, vault_id: str, key: bytes) -> str:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT vault_name, total_bytes, locked_until,
                       frozen_until, created_at, updated_at
                FROM vaults
                WHERE vault_id = %s
                LIMIT 1
                """,
                (vault_id,),
            )
            vrow = cur.fetchone() or {}
            cur.execute(
                "SELECT COUNT(*) AS n FROM uploaded_files "
                "WHERE vault_id = %s AND upload_status = 'complete'",
                (vault_id,),
            )
            files_row = cur.fetchone() or {}
            cur.execute(
                "SELECT COUNT(*) AS n FROM vault_items "
                "WHERE vault_id = %s",
                (vault_id,),
            )
            items_row = cur.fetchone() or {}
            cur.execute(
                "SELECT COUNT(DISTINCT service) AS n "
                "FROM vault_items WHERE vault_id = %s",
                (vault_id,),
            )
            services_row = cur.fetchone() or {}
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] get_vault_status failed")
        return _err("unavailable")

    locked_until = vrow.get("locked_until")
    unlocked = bool(
        isinstance(key, (bytes, bytearray)) and len(key) == 32,
    )

                                                               
    try:
        from vault_analysis import analysis_coverage_for_vault
        cov = analysis_coverage_for_vault(vault_id) or {}
        coverage = {
            "total":      int(cov.get("total") or 0),
            "analyzed":   int(cov.get("analyzed") or 0),
            "pending":    int(cov.get("pending") or 0),
            "processing": int(cov.get("processing") or 0),
            "failed":     int(cov.get("failed") or 0),
            "unsupported": int(cov.get("unsupported") or 0),
            "is_complete": (
                int(cov.get("total") or 0) > 0
                and int(cov.get("pending") or 0) == 0
                and int(cov.get("processing") or 0) == 0
            ),
        }
    except Exception:
        coverage = {"is_complete": False}

    return json.dumps({
        "vault_name":              str(vrow.get("vault_name") or ""),
        "vault_state":             "unlocked" if unlocked else "locked",
        "total_files":             int(files_row.get("n") or 0),
        "total_saved_credentials": int(items_row.get("n") or 0),
        "distinct_services":       int(services_row.get("n") or 0),
        "total_bytes":             int(vrow.get("total_bytes") or 0),
        "vault_created_at_iso":    _iso(vrow.get("created_at")),
        "vault_updated_at_iso":    _iso(vrow.get("updated_at")),
        "frozen_until_iso":        _iso(vrow.get("frozen_until")),
        "locked_until_iso":        _iso(locked_until),
        "analysis_coverage":       coverage,
    }, ensure_ascii=False)


def list_expiring_items(
    *, vault_id: str, key: bytes,
    window_days: Optional[int] = None,
    severity: Optional[str] = None,
) -> str:


    sev = (severity or "").strip().lower() or None
    if sev not in (None,) + _EXPIRY_SEVERITIES:
        sev = None
    window = (
        _clamp_window_days(window_days, default=0)
        if window_days is not None
        else 0
    )
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            params: list[Any] = [vault_id]
            where = ["a.vault_id = %s", "a.status = 'active'"]
            if window > 0:
                where.append(
                    "a.expiry_date <= (CURRENT_DATE + "
                    "(%s || ' days')::interval)"
                )
                params.append(str(window))
            if sev:
                where.append("a.severity = %s")
                params.append(sev)
            params.append(MAX_EXPIRING_ITEMS)
            cur.execute(
                f"""
                SELECT a.id, a.source_kind, a.source_file_id,
                       a.source_item_id, a.expiry_type,
                       a.expiry_date, a.severity,
                       a.alert_window_days,
                       f.file_name AS f_name,
                       f.saved_name AS f_saved,
                       f.relative_path AS f_path,
                       i.service AS i_service,
                       i.item_type AS i_kind
                FROM vault_expiry_alerts a
                LEFT JOIN uploaded_files f
                       ON f.id = a.source_file_id
                LEFT JOIN vault_items i
                       ON i.id = a.source_item_id
                WHERE {' AND '.join(where)}
                ORDER BY a.expiry_date ASC NULLS LAST,
                         a.severity DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] list_expiring_items failed")
        return _err("unavailable")
    items: list[dict] = []
    for r in rows:
        item: dict[str, Any] = {
            "alert_id":          int(r.get("id") or 0),
            "source_kind":       str(r.get("source_kind") or ""),
            "expiry_type":       str(r.get("expiry_type") or ""),
            "expiry_date_iso":   _iso(r.get("expiry_date")),
            "severity":          str(r.get("severity") or ""),
            "window_days":       int(r.get("alert_window_days") or 0),
        }
        if r.get("source_file_id"):
            item["file_id"]    = str(r.get("source_file_id") or "")
            item["file_name"]  = str(r.get("f_saved") or r.get("f_name") or "")
            item["folder"]     = str(r.get("f_path") or "")
        elif r.get("source_item_id"):
            item["item_id"]    = int(r.get("source_item_id") or 0)
            item["service"]    = str(r.get("i_service") or "")
            item["item_kind"]  = str(r.get("i_kind") or "")
        items.append(item)
    return json.dumps({
        "items":   items,
        "count":   len(items),
        "filter": {
            "window_days": window or None,
            "severity":    sev,
        },
    }, ensure_ascii=False)


def get_expiry_alert(
    *, vault_id: str, key: bytes, alert_id: int,
) -> str:
    if not alert_id:
        return _err("missing_alert_id")
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT a.id, a.source_kind, a.source_file_id,
                       a.source_item_id, a.expiry_type,
                       a.expiry_date, a.severity,
                       a.alert_window_days, a.status,
                       a.created_at, a.updated_at,
                       f.file_name AS f_name,
                       f.saved_name AS f_saved,
                       f.relative_path AS f_path,
                       i.service AS i_service,
                       i.item_type AS i_kind
                FROM vault_expiry_alerts a
                LEFT JOIN uploaded_files f
                       ON f.id = a.source_file_id
                LEFT JOIN vault_items i
                       ON i.id = a.source_item_id
                WHERE a.id = %s AND a.vault_id = %s
                LIMIT 1
                """,
                (alert_id, vault_id),
            )
            r = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] get_expiry_alert failed")
        return _err("unavailable")
    if not r:
        return _err("not_found")
    info: dict[str, Any] = {
        "alert_id":          int(r.get("id") or 0),
        "source_kind":       str(r.get("source_kind") or ""),
        "expiry_type":       str(r.get("expiry_type") or ""),
        "expiry_date_iso":   _iso(r.get("expiry_date")),
        "severity":          str(r.get("severity") or ""),
        "window_days":       int(r.get("alert_window_days") or 0),
        "status":            str(r.get("status") or ""),
        "created_at_iso":    _iso(r.get("created_at")),
        "updated_at_iso":    _iso(r.get("updated_at")),
    }
    if r.get("source_file_id"):
        info["file_id"]   = str(r.get("source_file_id") or "")
        info["file_name"] = str(
            r.get("f_saved") or r.get("f_name") or ""
        )
        info["folder"]    = str(r.get("f_path") or "")
    elif r.get("source_item_id"):
        info["item_id"]   = int(r.get("source_item_id") or 0)
        info["service"]   = str(r.get("i_service") or "")
        info["item_kind"] = str(r.get("i_kind") or "")
    return json.dumps(info, ensure_ascii=False)


def list_vault_entities(
    *, vault_id: str, key: bytes,
    entity_type: Optional[str] = None,
) -> str:


    etype = (entity_type or "").strip().lower() or None
    if etype not in (None,) + _ENTITY_TYPES:
        etype = None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            params: list[Any] = [vault_id]
            where = ["vault_id = %s"]
            if etype:
                where.append("entity_type = %s")
                params.append(etype)
            params.append(MAX_ENTITY_RESULTS)
            cur.execute(
                f"""
                SELECT entity_type, entity_value,
                       COUNT(DISTINCT source_file_id) AS file_count
                FROM vault_document_entities
                WHERE {' AND '.join(where)}
                GROUP BY entity_type, entity_value
                ORDER BY file_count DESC, entity_value ASC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] list_vault_entities failed")
        return _err("unavailable")
    entities = [
        {
            "entity_type":  str(r.get("entity_type") or ""),
            "entity_value": str(r.get("entity_value") or ""),
            "file_count":   int(r.get("file_count") or 0),
        }
        for r in rows
    ]
    return json.dumps({
        "entities": entities,
        "count":    len(entities),
        "filter":   {"entity_type": etype},
    }, ensure_ascii=False)


def find_files_for_entity(
    *, vault_id: str, key: bytes,
    entity_value: str, entity_type: Optional[str] = None,
) -> str:

    val = (entity_value or "").strip()
    if not val:
        return _err("missing_entity_value")
    etype = (entity_type or "").strip().lower() or None
    if etype not in (None,) + _ENTITY_TYPES:
        etype = None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            params: list[Any] = [vault_id, val]
            where = [
                "e.vault_id = %s",
                "LOWER(e.entity_value) = LOWER(%s)",
            ]
            if etype:
                where.append("e.entity_type = %s")
                params.append(etype)
            params.append(MAX_ENTITY_FILES)
            cur.execute(
                f"""
                SELECT DISTINCT
                       e.source_file_id,
                       e.entity_type,
                       e.entity_key,
                       e.confidence,
                       f.file_name,
                       f.saved_name,
                       f.relative_path,
                       f.created_at
                FROM vault_document_entities e
                JOIN uploaded_files f ON f.id = e.source_file_id
                WHERE {' AND '.join(where)}
                ORDER BY e.confidence DESC, f.created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] find_files_for_entity failed")
        return _err("unavailable")
    files = [
        {
            "file_id":         str(r.get("source_file_id") or ""),
            "file_name":       str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":          str(r.get("relative_path") or ""),
            "entity_type":     str(r.get("entity_type") or ""),
            "entity_key":      str(r.get("entity_key") or ""),
            "confidence":      float(r.get("confidence") or 0.0),
            "uploaded_at_iso": _iso(r.get("created_at")),
        }
        for r in rows
    ]
    return json.dumps({
        "entity_value": val,
        "entity_type":  etype,
        "files":        files,
        "count":        len(files),
    }, ensure_ascii=False)


def list_file_relationships(
    *, vault_id: str, key: bytes,
    file_id: Optional[str] = None,
    relation_type: Optional[str] = None,
) -> str:

    rel = (relation_type or "").strip().lower() or None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            params: list[Any] = [vault_id]
            where = ["r.vault_id = %s"]
            if file_id:
                where.append(
                    "(r.source_file_id = %s OR r.target_file_id = %s)"
                )
                params.extend([file_id, file_id])
            if rel:
                where.append("r.relation_type = %s")
                params.append(rel)
            params.append(MAX_RELATIONSHIP_ROWS)
            cur.execute(
                f"""
                SELECT r.id, r.source_kind, r.source_file_id,
                       r.source_item_id, r.target_kind,
                       r.target_file_id, r.target_item_id,
                       r.relation_type, r.confidence,
                       sf.file_name  AS s_name,
                       sf.saved_name AS s_saved,
                       tf.file_name  AS t_name,
                       tf.saved_name AS t_saved,
                       si.service    AS s_service,
                       ti.service    AS t_service
                FROM vault_relationships r
                LEFT JOIN uploaded_files sf
                       ON sf.id = r.source_file_id
                LEFT JOIN uploaded_files tf
                       ON tf.id = r.target_file_id
                LEFT JOIN vault_items si
                       ON si.id = r.source_item_id
                LEFT JOIN vault_items ti
                       ON ti.id = r.target_item_id
                WHERE {' AND '.join(where)}
                ORDER BY r.confidence DESC, r.id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] list_file_relationships failed")
        return _err("unavailable")
    out: list[dict] = []
    for r in rows:
        out.append({
            "relationship_id": int(r.get("id") or 0),
            "relation_type":   str(r.get("relation_type") or ""),
            "confidence":      float(r.get("confidence") or 0.0),
            "source": {
                "kind":    str(r.get("source_kind") or ""),
                "file_id": str(r.get("source_file_id") or ""),
                "file_name": str(
                    r.get("s_saved") or r.get("s_name") or ""
                ),
                "item_id": int(r.get("source_item_id") or 0)
                            if r.get("source_item_id") else 0,
                "service": str(r.get("s_service") or ""),
            },
            "target": {
                "kind":    str(r.get("target_kind") or ""),
                "file_id": str(r.get("target_file_id") or ""),
                "file_name": str(
                    r.get("t_saved") or r.get("t_name") or ""
                ),
                "item_id": int(r.get("target_item_id") or 0)
                            if r.get("target_item_id") else 0,
                "service": str(r.get("t_service") or ""),
            },
        })
    return json.dumps({
        "relationships": out,
        "count":         len(out),
        "filter": {
            "file_id":       file_id or None,
            "relation_type": rel,
        },
    }, ensure_ascii=False)


def list_document_categories(*, vault_id: str, key: bytes) -> str:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT document_purpose,
                       COUNT(*) AS file_count
                FROM vault_file_understanding
                WHERE vault_id = %s
                  AND status   = 'ready'
                  AND document_purpose IS NOT NULL
                GROUP BY document_purpose
                ORDER BY file_count DESC, document_purpose ASC
                LIMIT 50
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] list_document_categories failed")
        return _err("unavailable")
    categories = [
        {
            "document_purpose": str(r.get("document_purpose") or ""),
            "file_count":       int(r.get("file_count") or 0),
        }
        for r in rows
    ]
    return json.dumps({
        "categories": categories,
        "count":      len(categories),
    }, ensure_ascii=False)


def list_files_by_category(
    *, vault_id: str, key: bytes, document_purpose: str,
) -> str:

    dp = (document_purpose or "").strip()
    if not dp:
        return _err("missing_document_purpose")
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT u.file_id,
                       u.purpose_label,
                       u.purpose_confidence,
                       f.file_name,
                       f.saved_name,
                       f.relative_path,
                       f.created_at,
                       f.asset_type,
                       f.content_type
                FROM vault_file_understanding u
                JOIN uploaded_files f ON f.id = u.file_id
                WHERE u.vault_id = %s
                  AND u.status   = 'ready'
                  AND u.document_purpose = %s
                ORDER BY u.purpose_confidence DESC NULLS LAST,
                         f.created_at DESC
                LIMIT %s
                """,
                (vault_id, dp, MAX_CATEGORY_FILES),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] list_files_by_category failed")
        return _err("unavailable")
    files = [
        {
            "file_id":         str(r.get("file_id") or ""),
            "file_name":       str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":          str(r.get("relative_path") or ""),
            "purpose_label":   str(r.get("purpose_label") or ""),
            "confidence":      float(r.get("purpose_confidence") or 0.0),
            "asset_type":      str(r.get("asset_type") or ""),
            "content_type":    str(r.get("content_type") or ""),
            "uploaded_at_iso": _iso(r.get("created_at")),
        }
        for r in rows
    ]
    return json.dumps({
        "document_purpose": dp,
        "files":            files,
        "count":            len(files),
    }, ensure_ascii=False)


def get_vault_activity(
    *, vault_id: str, key: bytes,
    window_days: Optional[int] = None,
    kind: Optional[str] = None,
) -> str:

    window = _clamp_window_days(window_days, default=30)
    k = (kind or "").strip().lower() or None
    if k not in (None, "file_upload", "credential_save"):
        k = None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            entries: list[dict] = []
            if k in (None, "file_upload"):
                cur.execute(
                    """
                    SELECT id, file_name, saved_name,
                           relative_path, asset_type,
                           created_at
                    FROM uploaded_files
                    WHERE vault_id = %s
                      AND upload_status = 'complete'
                      AND created_at >=
                          (NOW() - (%s || ' days')::interval)
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (vault_id, str(window), MAX_ACTIVITY_ROWS),
                )
                for r in (cur.fetchall() or []):
                    entries.append({
                        "kind":          "file_upload",
                        "occurred_at_iso": _iso(r.get("created_at")),
                        "file_id":       str(r.get("id") or ""),
                        "file_name":     str(
                            r.get("saved_name")
                            or r.get("file_name") or ""
                        ),
                        "folder":        str(r.get("relative_path") or ""),
                        "asset_type":    str(r.get("asset_type") or ""),
                    })
            if k in (None, "credential_save"):
                cur.execute(
                    """
                    SELECT id, service, item_type, created_at
                    FROM vault_items
                    WHERE vault_id = %s
                      AND created_at >=
                          (NOW() - (%s || ' days')::interval)
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (vault_id, str(window), MAX_ACTIVITY_ROWS),
                )
                for r in (cur.fetchall() or []):
                    entries.append({
                        "kind":          "credential_save",
                        "occurred_at_iso": _iso(r.get("created_at")),
                        "item_id":       int(r.get("id") or 0),
                        "service":       str(r.get("service") or ""),
                        "item_type":     str(r.get("item_type") or ""),
                    })
        finally:
            conn.close()
    except Exception:
        logger.exception("[SURFACE] get_vault_activity failed")
        return _err("unavailable")
    entries.sort(
        key=lambda e: e.get("occurred_at_iso", ""),
        reverse=True,
    )
    entries = entries[:MAX_ACTIVITY_ROWS]
    return json.dumps({
        "entries":     entries,
        "count":       len(entries),
        "window_days": window,
        "filter":      {"kind": k},
    }, ensure_ascii=False)


SURFACE_DISPATCH = {
    "get_vault_status":         get_vault_status,
    "list_expiring_items":      list_expiring_items,
    "get_expiry_alert":         get_expiry_alert,
    "list_vault_entities":      list_vault_entities,
    "find_files_for_entity":    find_files_for_entity,
    "list_file_relationships":  list_file_relationships,
    "list_document_categories": list_document_categories,
    "list_files_by_category":   list_files_by_category,
    "get_vault_activity":       get_vault_activity,
}


__all__ = [
    "SURFACE_DISPATCH",
    "SURFACE_FUNCTIONS",
    "MAX_EXPIRING_ITEMS",
    "MAX_ENTITY_RESULTS",
    "MAX_ENTITY_FILES",
    "MAX_RELATIONSHIP_ROWS",
    "MAX_CATEGORY_FILES",
    "MAX_ACTIVITY_ROWS",
    "get_vault_status",
    "list_expiring_items",
    "get_expiry_alert",
    "list_vault_entities",
    "find_files_for_entity",
    "list_file_relationships",
    "list_document_categories",
    "list_files_by_category",
    "get_vault_activity",
]
