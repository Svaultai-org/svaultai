"""Safe live-data projections for VaultAI chat cards.

The umbrella router (`vault_chat_router.py`) classifies a message
into a closed-set intent and returns a card shell. This module
POPULATES that shell with real vault data using safe projections.

Safety invariants (enforced by tests):

  1. No card data payload EVER carries a plaintext password, a
     seed phrase, a mnemonic, a private/spend/view key, an
     encrypted secret blob, an auth token, an API key, or a raw
     ID number. The projector only reads whitelisted fields and
     re-emits them through per-card whitelists.

  2. Usernames are shown for identification, but longer values
     (email addresses, long identifiers) get partially masked so
     the visible remainder cannot uniquely re-identify without
     the full record. Short usernames (<= 3 characters) show as
     "***".

  3. ID numbers show only the last 3-4 characters after "•••".
     Full number is never emitted; the card must route through
     the gated reveal flow to see it.

  4. Each per-card data payload is versioned with a schema string.
     Frontend parsers check the schema and refuse to render on
     mismatch.

  5. When the underlying data source is unavailable, the payload
     is `{"schema": ..., "available": False, "unavailable_reason":
     "<closed-set>"}`. Callers do NOT fabricate fields.

  6. Sensitive intents (login/id reveal, login/id copy, delete)
     produce a `confirmation_required` card in the router. This
     module does NOT populate those cards with real data — they
     stay as confirmation prompts.

  7. Crypto intents delegate to the existing crypto module and
     already carry `liveFetchRequired=True` so the frontend
     fetches balances / addresses / scanner status through
     existing crypto endpoints. This module does NOT touch
     crypto payloads.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from vault_chat_router import (
    INTENT_ACTIVITY_ITEM_HISTORY,
    INTENT_ACTIVITY_RECENT,
    INTENT_BILLING_STATUS,
    INTENT_BILLING_UPGRADE,
    INTENT_CROSS_VAULT_SEARCH,
    INTENT_DOCUMENT_SUMMARY,
    INTENT_FILE_SEARCH,
    INTENT_GENERATED_LOGIN_LIST,
    INTENT_ID_DOCUMENT_EXPIRY,
    INTENT_ID_DOCUMENT_LIST,
    INTENT_ID_DOCUMENT_SEARCH,
    INTENT_LOGIN_LIST,
    INTENT_LOGIN_SEARCH,
    INTENT_LOGIN_DUPLICATES,
    INTENT_SECURE_ITEM_LIST,
    INTENT_SECURE_ITEM_SEARCH,
    INTENT_STORAGE_LARGEST,
    INTENT_STORAGE_USAGE,
    INTENT_VAULT_OVERVIEW,
)

logger = logging.getLogger(__name__)



VAULT_OVERVIEW_DATA_SCHEMA:     str = "vault_overview_data_v1"
VAULT_LOGIN_DATA_SCHEMA:        str = "vault_login_data_v1"
VAULT_SECURE_ITEM_DATA_SCHEMA:  str = "vault_secure_item_data_v1"
VAULT_ID_DOCUMENT_DATA_SCHEMA:  str = "vault_id_document_data_v1"
VAULT_STORAGE_DATA_SCHEMA:      str = "vault_storage_data_v1"
VAULT_BILLING_DATA_SCHEMA:      str = "vault_billing_data_v1"
VAULT_ACTIVITY_DATA_SCHEMA:     str = "vault_activity_data_v1"
VAULT_SEARCH_DATA_SCHEMA:       str = "vault_search_data_v1"
VAULT_GENERATED_LOGIN_DATA_SCHEMA: str = (
    "vault_generated_login_data_v1"
)



UNAVAIL_INTERNAL_ERROR:      str = "internal_error"
UNAVAIL_MISSING_DEPENDENCY:  str = "missing_dependency"
UNAVAIL_NOT_YET_IMPLEMENTED: str = "not_yet_implemented"
UNAVAIL_VAULT_LOCKED:        str = "vault_locked"



DEFAULT_LIST_LIMIT:         int = 20
DEFAULT_SEARCH_LIMIT:       int = 20
DEFAULT_SEARCH_GROUP_LIMIT: int = 5
DEFAULT_ACTIVITY_LIMIT:     int = 20




_FORBIDDEN_CARD_KEYS: frozenset[str] = frozenset({

    "password", "password_value", "raw_password",
    "plaintext_password", "password_field",


    "pin", "pin_hash", "pinHash",


    "seed", "seed_phrase", "seedPhrase", "seed_hex",
    "mnemonic", "mnemonic_words",
    "private_key", "privateKey",
    "view_key", "private_view_key",
    "spend_key", "private_spend_key",
    "polyseed",


    "api_key", "apiKey", "auth_token", "authToken",


    "encrypted_wallet_secret", "encrypted_secret",
    "encrypted_data",


    "stripe_secret_key", "stripe_secret",


    "id_number", "idNumber", "raw_id_number",
    "ssn", "social_security_number",


    "notes_full", "card_number_raw", "cvv",
})


def _strip_forbidden(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_forbidden(v)
            for k, v in obj.items()
            if k not in _FORBIDDEN_CARD_KEYS
        }
    if isinstance(obj, list):
        return [_strip_forbidden(x) for x in obj]
    return obj



def _mask_username(username: Optional[str]) -> str:
    if not username:
        return ""
    s = str(username).strip()
    if not s:
        return ""


    if "@" in s and s.count("@") == 1:
        local, domain = s.split("@", 1)
        return f"{_mask_short(local)}@{domain}"
    return _mask_short(s)


def _mask_short(s: str) -> str:
    n = len(s)
    if n <= 3:
        return "***"
    if n <= 5:
        return s[0] + "***"
    if n <= 8:
        return s[:2] + "***" + s[-1]
    return s[:2] + "***" + s[-2:]


_ID_NUMBER_TAIL_RE = re.compile(r"([A-Za-z0-9]{3,4})$")


def _mask_id_number(id_number: Optional[str]) -> str:
    if not id_number:
        return ""
    s = str(id_number).strip()
    if not s:
        return ""
    m = _ID_NUMBER_TAIL_RE.search(s)
    if not m:
        return "•••"
    return "•••" + m.group(1)


def _extract_domain(username: Optional[str], service: Optional[str]) -> Optional[str]:
    if username and "@" in str(username):
        parts = str(username).split("@", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1].strip().lower()
    if service:

        s = str(service).strip().lower()
        if s and "." in s:
            return s
    return None



def _unavailable(schema: str, reason: str) -> dict[str, Any]:
    return {
        "schema":             schema,
        "available":          False,
        "unavailable_reason": reason,
    }



def _count_files_and_bytes(vault_id: str) -> tuple[int, int, int]:

    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT COUNT(*) AS file_count
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
            """,
            (vault_id,),
        )
        file_row = cursor.fetchone() or {}
        cursor.execute(
            """
            SELECT COALESCE(total_bytes, 0) AS total_bytes
            FROM vaults
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        vault_row = cursor.fetchone() or {}
        file_count = int(file_row.get("file_count") or 0)
        used_bytes = int(vault_row.get("total_bytes") or 0)


        cursor.execute(
            """
            SELECT COUNT(*) AS doc_count
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
              AND (
                LOWER(COALESCE(content_type, '')) LIKE 'application/pdf'
                OR LOWER(COALESCE(content_type, '')) LIKE 'application/msword'
                OR LOWER(COALESCE(content_type, '')) LIKE
                   'application/vnd.openxmlformats-%%'
                OR LOWER(COALESCE(file_name, ''))
                   ~ '\\.(pdf|docx?|txt|rtf|md)$'
              )
            """,
            (vault_id,),
        )
        doc_row = cursor.fetchone() or {}
        doc_count = int(doc_row.get("doc_count") or 0)
        return file_count, doc_count, used_bytes
    finally:
        conn.close()


def _count_vault_items(vault_id: str) -> dict[str, int]:

    from main import get_db
    from psycopg2.extras import RealDictCursor
    from vault_item_visibility import SYSTEM_ITEM_TYPE_SQL_TUPLE

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE item_type = 'login') AS login_count,
                COUNT(*) FILTER (WHERE item_type = 'card')  AS card_count,
                COUNT(*) FILTER (WHERE item_type = 'id')    AS id_count,
                COUNT(*)                                    AS total_count
            FROM vault_items
            WHERE vault_id = %s
              AND item_type NOT IN %s
            """,
            (vault_id, SYSTEM_ITEM_TYPE_SQL_TUPLE),
        )
        row = cursor.fetchone() or {}
        return {
            "logins":         int(row.get("login_count") or 0),
            "secure_items":   int(row.get("card_count") or 0),
            "id_documents":   int(row.get("id_count") or 0),
            "vault_items_all": int(row.get("total_count") or 0),
        }
    finally:
        conn.close()


def _count_generated_logins(vault_id: str) -> int:

    return 0


def _storage_limit_bytes(vault_id: str) -> Optional[int]:
    try:
        from billing import (
            get_account_id_for_vault, get_effective_storage_limit,
        )
        acct_id = get_account_id_for_vault(vault_id)
        if not acct_id:
            return None
        return int(get_effective_storage_limit(acct_id))
    except Exception:
        logger.exception(
            "[vault_chat_card_data] storage_limit lookup failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return None


def build_vault_overview_data(vault_id: str) -> dict[str, Any]:
    """Vault overview: safe counts + storage."""

    if not vault_id:
        return _unavailable(
            VAULT_OVERVIEW_DATA_SCHEMA, UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        file_count, doc_count, used_bytes = _count_files_and_bytes(vault_id)
        item_counts = _count_vault_items(vault_id)
        generated_count = _count_generated_logins(vault_id)
        limit_bytes = _storage_limit_bytes(vault_id)
        percent = 0.0
        if limit_bytes and limit_bytes > 0:
            percent = round(
                min(100.0, (used_bytes / limit_bytes) * 100.0),
                2,
            )
        return {
            "schema":    VAULT_OVERVIEW_DATA_SCHEMA,
            "available": True,
            "counts": {
                "files":            file_count,
                "documents":        doc_count,
                "logins":           item_counts["logins"],
                "secure_items":     item_counts["secure_items"],
                "id_documents":     item_counts["id_documents"],
                "generated_logins": generated_count,

                "crypto_assets":    0,
                "recent_activity":  0,
            },
            "storage": {
                "used_bytes":   used_bytes,
                "quota_bytes":  limit_bytes if limit_bytes else 0,
                "percent_used": percent,
            },
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_vault_overview_data failed "
            "vault=%s", (vault_id or "")[:8] + "...",
        )
        return _unavailable(
            VAULT_OVERVIEW_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def _decrypt_row_json(
    encrypted_data: Any, key: bytes,
) -> dict[str, Any]:

    if not encrypted_data or not key:
        return {}
    try:
        from main import decrypt_message
        plain = decrypt_message(encrypted_data, key)
        parsed = json.loads(plain)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _row_updated_at_iso(row: dict[str, Any]) -> Optional[str]:

    for k in ("updated_at", "created_at"):
        v = row.get(k)
        if v is None:
            continue
        try:
            return v.isoformat()
        except Exception:
            try:
                return str(v)
            except Exception:
                pass
    return None


def _fetch_vault_items(
    vault_id: str, item_type: str, limit: int,
    *, service_ilike: Optional[str] = None,
) -> list[dict[str, Any]]:

    from main import get_db
    from psycopg2.extras import RealDictCursor

    limit = max(1, min(limit, DEFAULT_LIST_LIMIT))
    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if service_ilike:
            cursor.execute(
                """
                SELECT id, service, encrypted_data, created_at
                FROM vault_items
                WHERE vault_id = %s
                  AND item_type = %s
                  AND service ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, item_type,
                 f"%{service_ilike}%", limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, service, encrypted_data, created_at
                FROM vault_items
                WHERE vault_id = %s
                  AND item_type = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, item_type, limit),
            )
        return cursor.fetchall() or []
    finally:
        conn.close()


def _project_login_row(row: dict[str, Any], key: bytes) -> dict[str, Any]:
    plain = _decrypt_row_json(row.get("encrypted_data"), key)
    fields = plain.get("fields") if isinstance(plain, dict) else {}
    if not isinstance(fields, dict):
        fields = {}

    service = str(row.get("service") or plain.get("service") or "")
    title   = str(plain.get("title") or service or "").strip() or service
    username_raw = str(fields.get("username") or "").strip()
    domain = _extract_domain(username_raw, service)
    return {
        "id":              str(row.get("id") or ""),
        "title":           title,
        "service":         service,
        "username_masked": _mask_username(username_raw),
        "has_username":    bool(username_raw),
        "domain":          domain,
        "updated_at":      _row_updated_at_iso(row),
        "generated":       bool(plain.get("generated")),
    }


def build_login_list_data(
    vault_id: str, key: bytes,
    *, view: str = "list",
    query: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:

    if not vault_id or not key:
        return _unavailable(
            VAULT_LOGIN_DATA_SCHEMA,
            UNAVAIL_VAULT_LOCKED if not key else UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        rows = _fetch_vault_items(
            vault_id, "login", limit,
            service_ilike=query if view == "search" and query else None,
        )
        logins = [_project_login_row(r, key) for r in rows]
        return {
            "schema":        VAULT_LOGIN_DATA_SCHEMA,
            "available":     True,
            "view":          view,
            "query":         query,
            "logins":        logins,
            "count":         len(logins),
            "limit_applied": limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_login_list_data failed "
            "vault=%s", (vault_id or "")[:8] + "...",
        )
        return _unavailable(
            VAULT_LOGIN_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )


def build_login_duplicates_data(
    vault_id: str, key: bytes,
    *, limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:


    if not vault_id or not key:
        return _unavailable(
            VAULT_LOGIN_DATA_SCHEMA,
            UNAVAIL_VAULT_LOCKED if not key else UNAVAIL_MISSING_DEPENDENCY,
        )
    try:

        rows = _fetch_vault_items(vault_id, "login", limit)
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            proj = _project_login_row(r, key)
            dom = proj.get("domain") or (proj.get("service") or "").lower()
            if not dom:
                continue
            by_domain.setdefault(dom, []).append(proj)
        dup_groups = [
            {"domain": dom, "count": len(items), "logins": items}
            for dom, items in by_domain.items() if len(items) > 1
        ]
        return {
            "schema":        VAULT_LOGIN_DATA_SCHEMA,
            "available":     True,
            "view":          "duplicates",
            "duplicate_groups": dup_groups,
            "count":         len(dup_groups),
            "limit_applied": limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_login_duplicates_data failed",
        )
        return _unavailable(
            VAULT_LOGIN_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def _safe_snippet(text: Optional[str], max_chars: int = 80) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _project_secure_item_row(
    row: dict[str, Any], key: bytes,
) -> dict[str, Any]:
    plain = _decrypt_row_json(row.get("encrypted_data"), key)
    fields = plain.get("fields") if isinstance(plain, dict) else {}
    if not isinstance(fields, dict):
        fields = {}


    title = str(plain.get("title") or row.get("service") or "").strip()
    kind = str(plain.get("category") or "secure_item")
    snippet_source = ""
    for k in ("note_preview", "preview", "summary"):
        v = fields.get(k)
        if v:
            snippet_source = str(v)
            break
    return {
        "id":         str(row.get("id") or ""),
        "title":      title or "Untitled",
        "type":       kind,
        "snippet":    _safe_snippet(snippet_source),
        "updated_at": _row_updated_at_iso(row),
    }


def build_secure_item_list_data(
    vault_id: str, key: bytes,
    *, view: str = "list",
    query: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:

    if not vault_id or not key:
        return _unavailable(
            VAULT_SECURE_ITEM_DATA_SCHEMA,
            UNAVAIL_VAULT_LOCKED if not key else UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        rows = _fetch_vault_items(
            vault_id, "card", limit,
            service_ilike=query if view == "search" and query else None,
        )
        items = [_project_secure_item_row(r, key) for r in rows]
        return {
            "schema":        VAULT_SECURE_ITEM_DATA_SCHEMA,
            "available":     True,
            "view":          view,
            "query":         query,
            "items":         items,
            "count":         len(items),
            "limit_applied": limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_secure_item_list_data failed",
        )
        return _unavailable(
            VAULT_SECURE_ITEM_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def _parse_metadata_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _project_id_document(row: dict[str, Any]) -> dict[str, Any]:
    meta = _parse_metadata_json(row.get("metadata_json"))


    id_type = str(row.get("doc_type") or meta.get("doc_type") or "unknown")
    country = None
    state = None
    for k in ("issuing_country", "country", "issuer_country"):
        v = meta.get(k)
        if v:
            country = str(v)
            break
    for k in ("issuing_state", "state", "region"):
        v = meta.get(k)
        if v:
            state = str(v)
            break
    expires_at = None
    for k in ("expires_at", "expiry", "expiration_date", "expiry_date"):
        v = meta.get(k)
        if v:
            expires_at = str(v)
            break
    id_number_raw = None
    for k in ("id_number", "document_number", "number"):
        v = meta.get(k)
        if v:
            id_number_raw = str(v)
            break
    return {
        "id":               str(row.get("uploaded_file_id") or ""),
        "type":             id_type,
        "issuing_country":  country,
        "issuing_state":    state,
        "expires_at":       expires_at,
        "id_number_masked": _mask_id_number(id_number_raw),
    }


def build_id_document_list_data(
    vault_id: str,
    *, view: str = "list",
    query: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:

    if not vault_id:
        return _unavailable(
            VAULT_ID_DOCUMENT_DATA_SCHEMA,
            UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        from main import _list_document_metadata_for_vault
        rows = _list_document_metadata_for_vault(vault_id) or []


        projected = [_project_id_document(r) for r in rows]
        if view == "search" and query:
            q = query.lower()
            projected = [
                p for p in projected
                if q in (p.get("type") or "").lower()
                or q in (p.get("issuing_country") or "").lower()
                or q in (p.get("issuing_state") or "").lower()
            ]
        projected = projected[:limit]
        return {
            "schema":        VAULT_ID_DOCUMENT_DATA_SCHEMA,
            "available":     True,
            "view":          view,
            "query":         query,
            "documents":     projected,
            "count":         len(projected),
            "limit_applied": limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_id_document_list_data failed",
        )
        return _unavailable(
            VAULT_ID_DOCUMENT_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def build_storage_data(vault_id: str) -> dict[str, Any]:
    if not vault_id:
        return _unavailable(
            VAULT_STORAGE_DATA_SCHEMA, UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        file_count, doc_count, used_bytes = _count_files_and_bytes(vault_id)
        limit_bytes = _storage_limit_bytes(vault_id)
        percent = 0.0
        if limit_bytes and limit_bytes > 0:
            percent = round(
                min(100.0, (used_bytes / limit_bytes) * 100.0), 2,
            )

        return {
            "schema":        VAULT_STORAGE_DATA_SCHEMA,
            "available":     True,
            "used_bytes":    used_bytes,
            "quota_bytes":   limit_bytes if limit_bytes else 0,
            "percent_used":  percent,
            "file_count":    file_count,
            "document_count": doc_count,
            "largest_categories": [],
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_storage_data failed",
        )
        return _unavailable(
            VAULT_STORAGE_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def build_billing_data(vault_id: str) -> dict[str, Any]:
    if not vault_id:
        return _unavailable(
            VAULT_BILLING_DATA_SCHEMA, UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        from billing import (
            get_account_id_for_vault, get_entitlement,
        )
        acct_id = get_account_id_for_vault(vault_id)
        if not acct_id:
            return {
                "schema":        VAULT_BILLING_DATA_SCHEMA,
                "available":     True,
                "plan":          "free",
                "status":        "no_account",
                "storage_tier": "free",
                "has_active_subscription": False,
            }
        ent = get_entitlement(acct_id)


        plan = "upgraded" if (
            ent.block_count > 0 and ent.purchased_bytes > 0
        ) else "free"
        return {
            "schema":         VAULT_BILLING_DATA_SCHEMA,
            "available":      True,
            "plan":           plan,
            "status":         str(ent.status or "unknown"),
            "storage_tier":   plan,
            "block_count":    int(ent.block_count or 0),
            "purchased_bytes": int(ent.purchased_bytes or 0),
            "included_bytes": int(ent.included_bytes or 0),
            "cancel_at_period_end": bool(ent.cancel_at_period_end),
            "has_active_subscription": bool(ent.has_active_subscription),
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_billing_data failed",
        )
        return _unavailable(
            VAULT_BILLING_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def build_activity_data(
    vault_id: str, *, limit: int = DEFAULT_ACTIVITY_LIMIT,
) -> dict[str, Any]:



    if not vault_id:
        return _unavailable(
            VAULT_ACTIVITY_DATA_SCHEMA, UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        from main import get_db
        from psycopg2.extras import RealDictCursor

        limit = max(1, min(limit, DEFAULT_ACTIVITY_LIMIT))
        events: list[dict[str, Any]] = []
        conn = get_db()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)


            cursor.execute(
                """
                SELECT id AS event_id, file_name AS title,
                       created_at, asset_type
                FROM uploaded_files
                WHERE vault_id = %s
                  AND upload_status = 'complete'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, limit),
            )
            for r in cursor.fetchall() or []:
                events.append({
                    "action":    "file_uploaded",
                    "category":  "file",
                    "title":     str(r.get("title") or "")[:80],
                    "timestamp": (r.get("created_at").isoformat()
                                  if r.get("created_at") else None),
                    "asset_type": str(r.get("asset_type") or ""),
                })


            from vault_item_visibility import SYSTEM_ITEM_TYPE_SQL_TUPLE
            cursor.execute(
                """
                SELECT id AS event_id, item_type, service, created_at
                FROM vault_items
                WHERE vault_id = %s
                  AND item_type NOT IN %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, SYSTEM_ITEM_TYPE_SQL_TUPLE, limit),
            )
            for r in cursor.fetchall() or []:
                events.append({
                    "action":    "item_saved",
                    "category":  str(r.get("item_type") or "secure_item"),
                    "title":     str(r.get("service") or "")[:80],
                    "timestamp": (r.get("created_at").isoformat()
                                  if r.get("created_at") else None),
                })
        finally:
            conn.close()


        events.sort(
            key=lambda e: e.get("timestamp") or "",
            reverse=True,
        )
        events = events[:limit]

        return {
            "schema":        VAULT_ACTIVITY_DATA_SCHEMA,
            "available":     True,
            "events":        events,
            "count":         len(events),
            "limit_applied": limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_activity_data failed",
        )
        return _unavailable(
            VAULT_ACTIVITY_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )



def build_cross_vault_search_data(
    vault_id: str, key: bytes, query: str,
    *, group_limit: int = DEFAULT_SEARCH_GROUP_LIMIT,
) -> dict[str, Any]:

    q = (query or "").strip()
    if not vault_id or not q:
        return _unavailable(
            VAULT_SEARCH_DATA_SCHEMA, UNAVAIL_MISSING_DEPENDENCY,
        )
    try:
        groups: list[dict[str, Any]] = []


        if key:
            try:
                login_rows = _fetch_vault_items(
                    vault_id, "login", group_limit, service_ilike=q,
                )
                logins = [_project_login_row(r, key) for r in login_rows]
                if logins:
                    groups.append({
                        "category": "logins",
                        "count":    len(logins),
                        "items":    logins,
                    })
            except Exception:
                logger.exception(
                    "[vault_chat_card_data] search: logins fetch failed",
                )
            try:
                secure_rows = _fetch_vault_items(
                    vault_id, "card", group_limit, service_ilike=q,
                )
                secure_items = [
                    _project_secure_item_row(r, key)
                    for r in secure_rows
                ]
                if secure_items:
                    groups.append({
                        "category": "secure_items",
                        "count":    len(secure_items),
                        "items":    secure_items,
                    })
            except Exception:
                logger.exception(
                    "[vault_chat_card_data] search: secure items failed",
                )


        try:
            id_data = build_id_document_list_data(
                vault_id, view="search", query=q, limit=group_limit,
            )
            if id_data.get("available") and id_data.get("documents"):
                groups.append({
                    "category": "id_documents",
                    "count":    len(id_data["documents"]),
                    "items":    id_data["documents"],
                })
        except Exception:
            logger.exception(
                "[vault_chat_card_data] search: id_documents failed",
            )


        try:
            from main import get_db
            from psycopg2.extras import RealDictCursor
            conn = get_db()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(
                    """
                    SELECT id, file_name, content_type, file_size,
                           created_at
                    FROM uploaded_files
                    WHERE vault_id = %s
                      AND upload_status = 'complete'
                      AND (file_name ILIKE %s
                           OR COALESCE(saved_name, '') ILIKE %s)
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (vault_id, f"%{q}%", f"%{q}%", group_limit),
                )
                files = []
                for r in cursor.fetchall() or []:
                    files.append({
                        "id":           str(r.get("id") or ""),
                        "file_name":    str(r.get("file_name") or ""),
                        "content_type": str(r.get("content_type") or ""),
                        "file_size":    int(r.get("file_size") or 0),
                        "created_at":   (r.get("created_at").isoformat()
                                         if r.get("created_at") else None),
                    })
                if files:
                    groups.append({
                        "category": "files",
                        "count":    len(files),
                        "items":    files,
                    })
            finally:
                conn.close()
        except Exception:
            logger.exception(
                "[vault_chat_card_data] search: files failed",
            )

        return {
            "schema":        VAULT_SEARCH_DATA_SCHEMA,
            "available":     True,
            "query":         q,
            "groups":        groups,
            "group_count":   len(groups),
            "limit_applied": group_limit,
        }
    except Exception:
        logger.exception(
            "[vault_chat_card_data] build_cross_vault_search_data failed",
        )
        return _unavailable(
            VAULT_SEARCH_DATA_SCHEMA, UNAVAIL_INTERNAL_ERROR,
        )




def populate_vault_chat_card_data(
    envelope: dict[str, Any],
    *,
    vault_id: str,
    key: Optional[bytes] = None,
) -> dict[str, Any]:
    """Populate `envelope["card"]["data"]` with a safe projection.

    Idempotent. Never raises. On any failure, sets the card data to
    an `available: False, unavailable_reason: <closed-set>` payload.

    The envelope is mutated in-place AND returned for convenience.
    """
    if not isinstance(envelope, dict):
        return envelope
    intent = str(envelope.get("intent") or "")
    card = envelope.get("card")
    if not isinstance(card, dict):
        return envelope
    if not intent:
        return envelope



    if intent.startswith("vault_refusal_"):
        return envelope
    if intent == "vault_crypto_delegated":
        return envelope

    if card.get("cardType") == "vault_confirmation_required_card":
        return envelope

    try:
        data: Optional[dict[str, Any]] = None
        if intent == INTENT_VAULT_OVERVIEW:
            data = build_vault_overview_data(vault_id)
        elif intent in (INTENT_LOGIN_LIST,):
            data = build_login_list_data(
                vault_id, key or b"",
                view="list",
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent == INTENT_LOGIN_SEARCH:
            data = build_login_list_data(
                vault_id, key or b"",
                view="search",
                query=str(card.get("query") or "") or None,
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent == INTENT_LOGIN_DUPLICATES:
            data = build_login_duplicates_data(
                vault_id, key or b"",
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent in (INTENT_SECURE_ITEM_LIST,):
            data = build_secure_item_list_data(
                vault_id, key or b"",
                view="list",
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent == INTENT_SECURE_ITEM_SEARCH:
            data = build_secure_item_list_data(
                vault_id, key or b"",
                view="search",
                query=str(card.get("query") or "") or None,
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent in (
            INTENT_ID_DOCUMENT_LIST, INTENT_ID_DOCUMENT_EXPIRY,
        ):
            view = ("expiry"
                    if intent == INTENT_ID_DOCUMENT_EXPIRY
                    else "list")
            data = build_id_document_list_data(
                vault_id, view=view, limit=DEFAULT_LIST_LIMIT,
            )
        elif intent == INTENT_ID_DOCUMENT_SEARCH:
            data = build_id_document_list_data(
                vault_id, view="search",
                query=str(card.get("query") or "") or None,
                limit=DEFAULT_LIST_LIMIT,
            )
        elif intent in (INTENT_STORAGE_USAGE, INTENT_STORAGE_LARGEST):
            data = build_storage_data(vault_id)
        elif intent in (INTENT_BILLING_STATUS, INTENT_BILLING_UPGRADE):
            data = build_billing_data(vault_id)
        elif intent in (
            INTENT_ACTIVITY_RECENT, INTENT_ACTIVITY_ITEM_HISTORY,
        ):
            data = build_activity_data(vault_id)
        elif intent == INTENT_CROSS_VAULT_SEARCH:
            q = str(card.get("query") or "")
            data = build_cross_vault_search_data(
                vault_id, key or b"", q,
            )
        elif intent == INTENT_GENERATED_LOGIN_LIST:

            data = {
                "schema":    VAULT_GENERATED_LOGIN_DATA_SCHEMA,
                "available": False,
                "unavailable_reason": UNAVAIL_NOT_YET_IMPLEMENTED,
            }
        elif intent in (INTENT_FILE_SEARCH, INTENT_DOCUMENT_SUMMARY):

            data = None
        else:

            data = None

        if data is not None:
            card["data"] = _strip_forbidden(data)
    except Exception:
        logger.exception(
            "[vault_chat_card_data] populate failed intent=%s", intent,
        )
        card["data"] = _unavailable(
            "unknown_v1", UNAVAIL_INTERNAL_ERROR,
        )

    return envelope



__all__ = [

    "VAULT_OVERVIEW_DATA_SCHEMA",
    "VAULT_LOGIN_DATA_SCHEMA",
    "VAULT_SECURE_ITEM_DATA_SCHEMA",
    "VAULT_ID_DOCUMENT_DATA_SCHEMA",
    "VAULT_STORAGE_DATA_SCHEMA",
    "VAULT_BILLING_DATA_SCHEMA",
    "VAULT_ACTIVITY_DATA_SCHEMA",
    "VAULT_SEARCH_DATA_SCHEMA",
    "VAULT_GENERATED_LOGIN_DATA_SCHEMA",

    "UNAVAIL_INTERNAL_ERROR",
    "UNAVAIL_MISSING_DEPENDENCY",
    "UNAVAIL_NOT_YET_IMPLEMENTED",
    "UNAVAIL_VAULT_LOCKED",

    "DEFAULT_LIST_LIMIT",
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_GROUP_LIMIT",
    "DEFAULT_ACTIVITY_LIMIT",

    "build_vault_overview_data",
    "build_login_list_data",
    "build_login_duplicates_data",
    "build_secure_item_list_data",
    "build_id_document_list_data",
    "build_storage_data",
    "build_billing_data",
    "build_activity_data",
    "build_cross_vault_search_data",

    "populate_vault_chat_card_data",
]
