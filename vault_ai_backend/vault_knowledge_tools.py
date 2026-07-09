

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional


logger = logging.getLogger(__name__)


MAX_FILES_RETURNED:        int = 25
MAX_SEARCH_HITS:           int = 8
MAX_SNIPPET_CHARS:         int = 320
MAX_RECENT_FILES:          int = 5


def _key_ok(key: Optional[bytes]) -> bool:
    return isinstance(key, (bytes, bytearray)) and len(key) == 32


def _redact(text: str) -> str:
    try:
        from extractor import redact_message
        return redact_message(text or "")
    except Exception:
        return text or ""


def _short(s: str, cap: int) -> str:
    if not s:
        return ""
    s = s.strip()
    if len(s) <= cap:
        return s
    cut = s[:cap]
    last_ws = cut.rfind(" ")
    if last_ws > cap * 0.7:
        cut = cut[:last_ws]
    return cut + "…"


VAULT_KNOWLEDGE_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_vault_intelligence",
            "description": (
                "ONE comprehensive snapshot of EVERYTHING the vault "
                "knows about itself. Returns coverage (how many "
                "files reviewed of total), files-by-kind, recent "
                "uploads, verified credential files + record "
                "counts, saved-credential services, sensitive "
                "documents (IDs, financial, legal, medical), "
                "expiring-soon items, files needing attention "
                "(pending/processing/failed/unsupported), and the "
                "top entities seen across the vault. Call this "
                "FIRST for any broad vault question — 'what's in "
                "my vault?', 'what do you know about me?', 'what "
                "should I pay attention to?', 'which files have "
                "credentials?', 'what expires soon?', 'what's "
                "important?'. One call replaces 5 narrow ones. "
                "Always safe. Never returns secrets, never returns "
                "file contents — only counts, identity columns, "
                "categories, dates."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vault_overview",
            "description": (
                "Get a high-level summary of what's in the user's "
                "vault: total file count, files grouped by kind "
                "(document / image / video / audio / archive / "
                "other), the most-recent uploads, the count of "
                "saved credential services, and current analysis "
                "coverage. Use this when the user asks general "
                "questions like 'what's in my vault?', 'what do "
                "you have for me?', 'summarize my vault', 'how "
                "much have you analyzed?'. Always safe to call. "
                "Never returns secrets, never returns file "
                "contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vault_files",
            "description": (
                "List files in the user's vault, optionally "
                "filtered. Use this when the user asks 'list my "
                "files', 'what files do I have for X', 'show me "
                "my recent uploads', 'what PDFs do I have'. "
                "Returns up to 25 entries: file name, folder, "
                "kind, size, upload date. Never returns file "
                "contents — for that, call get_file_summary on a "
                "specific file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": (
                            "Optional filter by file kind. "
                            "Closed set: document, image, video, "
                            "audio, archive, other. Omit to "
                            "list all kinds."
                        ),
                    },
                    "recent_only": {
                        "type": "boolean",
                        "description": (
                            "When true, restrict to the 5 most "
                            "recent uploads. Useful for 'what did "
                            "I just upload?'."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional case-insensitive substring "
                            "to match against file names and "
                            "folder paths. Useful for 'do I have "
                            "any Wells Fargo files'."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_vault_content",
            "description": (
                "Semantic + lexical search across the readable "
                "text of every file in the user's vault. Use "
                "this when the user asks 'find anything about "
                "X', 'what files mention Y', 'do I have notes "
                "on Z'. Returns up to 8 snippets with file name "
                "and a redacted excerpt (passwords / OTPs / "
                "emails are masked). Never returns raw "
                "credentials."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to search for. Be specific: "
                            "a topic, a person, a brand, a "
                            "phrase."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def get_vault_overview(*, vault_id: str, key: bytes) -> str:


    try:
        from main import list_uploaded_files
        from vault_analysis import analysis_coverage_for_vault
        from psycopg2.extras import RealDictCursor
        from main import get_db
    except Exception:
        return json.dumps({"error": "unavailable"})

    try:
        files = list_uploaded_files(vault_id) or []
    except Exception:
        files = []

    files_by_kind: dict[str, int] = {
        "document": 0, "image": 0, "video": 0, "audio": 0,
        "archive": 0, "other": 0,
    }
    for f in files:
        kind = _classify_file_kind(f)
        files_by_kind[kind] = files_by_kind.get(kind, 0) + 1

    recent = []
    for f in files[:MAX_RECENT_FILES]:
        recent.append({
            "file_name": str(
                f.get("saved_name") or f.get("file_name") or ""
            ),
            "kind":      _classify_file_kind(f),
            "uploaded_at_iso": _iso(f.get("created_at")),
        })

                                             
    services_count = 0
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT COUNT(DISTINCT service) AS n
                FROM vault_items
                WHERE vault_id = %s
                """,
                (vault_id,),
            )
            row = cur.fetchone()
            services_count = int((row or {}).get("n") or 0)
        finally:
            conn.close()
    except Exception:
        services_count = 0

    coverage = {}
    try:
        cov = analysis_coverage_for_vault(vault_id) or {}
        analyzed   = int(cov.get("analyzed") or 0)
        pending    = int(cov.get("pending") or 0)
        processing = int(cov.get("processing") or 0)
        failed     = int(cov.get("failed") or 0)
        unsupported = int(cov.get("unsupported") or 0)
        total      = int(cov.get("total") or len(files))
        coverage = {
            "total":       total,
            "analyzed":    analyzed,
            "pending":     pending,
            "processing":  processing,
            "failed":      failed,
            "unsupported": unsupported,
            "is_complete": (
                total > 0 and pending == 0 and processing == 0
            ),
        }
    except Exception:
        coverage = {"is_complete": False}

    payload = {
        "total_files":    len(files),
        "files_by_kind":  files_by_kind,
        "recent_files":   recent,
        "saved_credential_services_count": services_count,
        "analysis_coverage": coverage,
    }
    return json.dumps(payload, ensure_ascii=False)


def list_vault_files(
    *,
    vault_id: str,
    key: bytes,
    kind: Optional[str] = None,
    recent_only: Optional[bool] = None,
    query: Optional[str] = None,
) -> str:


    try:
        from main import list_uploaded_files
    except Exception:
        return json.dumps({"error": "unavailable"})

    try:
        rows = list_uploaded_files(vault_id) or []
    except Exception:
        rows = []

    kind_filter = (kind or "").strip().lower() or None
    if kind_filter not in (None, "document", "image", "video", "audio",
                           "archive", "other"):
        kind_filter = None
    q = (query or "").strip().lower() or None

    out: list[dict] = []
    for r in rows:
        row_kind = _classify_file_kind(r)
        if kind_filter and row_kind != kind_filter:
            continue
        name = str(r.get("saved_name") or r.get("file_name") or "")
        path = str(r.get("relative_path") or "")
        if q and (q not in name.lower()) and (q not in path.lower()):
            continue
        out.append({
            "file_id":   str(r.get("id") or ""),
            "file_name": name,
            "kind":      row_kind,
            "folder":    path,
            "size_bytes": int(r.get("file_size") or 0),
            "uploaded_at_iso": _iso(r.get("created_at")),
        })
        if len(out) >= MAX_FILES_RETURNED:
            break

    if recent_only:
        out = out[:MAX_RECENT_FILES]

    payload = {
        "files":              out,
        "returned":           len(out),
        "total_in_vault":     len(rows),
        "filter": {
            "kind":            kind_filter,
            "recent_only":     bool(recent_only),
            "query":           q,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def search_vault_content(
    *,
    vault_id: str,
    key: bytes,
    query: str,
) -> str:


    if not _key_ok(key):
        return json.dumps({"error": "vault_locked"})
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "empty_query"})

    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        from vault_core import decrypt_message as _decrypt
    except Exception:
        return json.dumps({"error": "unavailable"})

    q_lower = q.lower()
    q_tokens = [
        t for t in re.split(r"\s+", q_lower) if t and len(t) >= 2
    ]
    seen_file_ids: set[str] = set()
    snippets: list[dict] = []
    sources_attempted = 0
    sources_failed = 0

                                                                        
    sources_attempted += 1
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT c.file_id, c.encrypted_chunk_text,
                       c.extraction_source,
                       f.file_name, f.saved_name, f.relative_path
                FROM vault_content_chunks c
                JOIN uploaded_files f ON f.id = c.file_id
                WHERE c.vault_id = %s
                  AND c.chunk_text_encrypted = TRUE
                ORDER BY f.created_at DESC
                LIMIT 400
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        rows = []
        sources_failed += 1

    for r in rows:
        if len(snippets) >= MAX_SEARCH_HITS:
            break
        enc = r.get("encrypted_chunk_text")
        if not enc:
            continue
        try:
            plain = _decrypt(enc, key)
        except Exception:
            continue
        if not plain:
            continue
        if not _content_matches(plain, q_lower, q_tokens):
            continue
        idx = plain.lower().find(q_lower)
        if idx < 0 and q_tokens:
            idx = plain.lower().find(q_tokens[0])
        if idx < 0:
            idx = 0
        start = max(0, idx - 80)
        end = min(len(plain), idx + 240)
        snippet = plain[start:end]
        snippet = _redact(snippet)
        snippet = _short(snippet, MAX_SNIPPET_CHARS)
        fid = str(r.get("file_id") or "")
        if fid in seen_file_ids:
            continue
        seen_file_ids.add(fid)
        snippets.append({
            "file_id":    fid,
            "file_name":  str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":     str(r.get("relative_path") or ""),
            "snippet":    snippet,
            "source":     "content_chunk",
            "extraction": str(r.get("extraction_source") or ""),
        })

                                                                        
    if len(snippets) < MAX_SEARCH_HITS:
        sources_attempted += 1
        try:
            from main import _list_uploaded_files_for_credential_search
            files_with_text = (
                _list_uploaded_files_for_credential_search(vault_id, key)
                or []
            )
        except Exception:
            files_with_text = []
            sources_failed += 1

        for f in files_with_text:
            if len(snippets) >= MAX_SEARCH_HITS:
                break
            fid = str(f.get("id") or "")
            if fid in seen_file_ids:
                continue
            plain = f.get("extracted_text")
            if not isinstance(plain, str) or not plain:
                continue
            if not _content_matches(plain, q_lower, q_tokens):
                continue
            idx = plain.lower().find(q_lower)
            if idx < 0 and q_tokens:
                idx = plain.lower().find(q_tokens[0])
            if idx < 0:
                idx = 0
            start = max(0, idx - 80)
            end = min(len(plain), idx + 240)
            snippet = _short(_redact(plain[start:end]), MAX_SNIPPET_CHARS)
            seen_file_ids.add(fid)
            snippets.append({
                "file_id":   fid,
                "file_name": str(
                    f.get("saved_name") or f.get("file_name") or ""
                ),
                "folder":    str(f.get("relative_path") or ""),
                "snippet":   snippet,
                "source":    "extracted_text",
                "extraction": "",
            })

                                                                        
    if len(snippets) < MAX_SEARCH_HITS:
        sources_attempted += 1
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT u.file_id,
                           u.entities_jsonb,
                           u.purpose_label,
                           u.document_purpose,
                           f.file_name,
                           f.saved_name,
                           f.relative_path
                    FROM vault_file_understanding u
                    JOIN uploaded_files f ON f.id = u.file_id
                    WHERE u.vault_id = %s
                      AND u.status   = 'ready'
                    ORDER BY f.created_at DESC
                    LIMIT 400
                    """,
                    (vault_id,),
                )
                erows = cur.fetchall() or []
            finally:
                conn.close()
        except Exception:
            erows = []
            sources_failed += 1

        for r in erows:
            if len(snippets) >= MAX_SEARCH_HITS:
                break
            fid = str(r.get("file_id") or "")
            if fid in seen_file_ids:
                continue
            ents = r.get("entities_jsonb") or {}
            entity_blob = _entity_blob(ents)
            if not _content_matches(entity_blob, q_lower, q_tokens):
                continue
            label = (
                str(r.get("purpose_label") or "")
                or str(r.get("document_purpose") or "")
                or "this file"
            )
            seen_file_ids.add(fid)
            snippets.append({
                "file_id":   fid,
                "file_name": str(
                    r.get("saved_name") or r.get("file_name") or ""
                ),
                "folder":    str(r.get("relative_path") or ""),
                "snippet":   _short(
                    _redact(f"Mentions {q}. Document type: {label}."),
                    MAX_SNIPPET_CHARS,
                ),
                "source":    "entities",
                "extraction": "",
            })

                                                                       
    if len(snippets) < MAX_SEARCH_HITS:
        sources_attempted += 1
        try:
            from main import list_uploaded_files
            files_meta = list_uploaded_files(vault_id) or []
        except Exception:
            files_meta = []
            sources_failed += 1

        for f in files_meta:
            if len(snippets) >= MAX_SEARCH_HITS:
                break
            fid = str(f.get("id") or "")
            if fid in seen_file_ids:
                continue
            name = str(
                f.get("saved_name") or f.get("file_name") or ""
            )
            folder = str(f.get("relative_path") or "")
            blob = f"{name} {folder}".lower()
            if not _content_matches(blob, q_lower, q_tokens):
                continue
            seen_file_ids.add(fid)
            snippets.append({
                "file_id":    fid,
                "file_name":  name,
                "folder":     folder,
                "snippet":    _short(
                    _redact(f"File name or path matches {q}: {name}"),
                    MAX_SNIPPET_CHARS,
                ),
                "source":     "identity",
                "extraction": "",
            })

                                                                   
    if not snippets and sources_failed > 0 and sources_failed >= sources_attempted:
        return json.dumps({"error": "unavailable"})

                                                                   
    try:
        from vault_analysis import analysis_coverage_for_vault
        cov = analysis_coverage_for_vault(vault_id) or {}
        coverage = {
            "total":      int(cov.get("total") or 0),
            "analyzed":   int(cov.get("analyzed") or 0),
            "pending":    int(cov.get("pending") or 0),
            "processing": int(cov.get("processing") or 0),
            "is_complete": (
                int(cov.get("total") or 0) > 0
                and int(cov.get("pending") or 0) == 0
                and int(cov.get("processing") or 0) == 0
            ),
        }
    except Exception:
        coverage = {"is_complete": False}

    return json.dumps({
        "query":    q,
        "hits":     snippets,
        "returned": len(snippets),
        "coverage": coverage,
        "sources_searched": [
            "content_chunks", "extracted_text",
            "entities", "identity",
        ],
    }, ensure_ascii=False)


def _content_matches(
    haystack: str, q_lower: str, q_tokens: list[str],
) -> bool:


    if not haystack:
        return False
    hay = haystack.lower()
    if q_lower and q_lower in hay:
        return True
    if not q_tokens:
        return False
    return all(tok in hay for tok in q_tokens)


def _entity_blob(ents: Any) -> str:


    if not isinstance(ents, dict):
        return ""
    out: list[str] = []
    for cat in ("people", "organizations", "places"):
        for t in (ents.get(cat) or []):
            if isinstance(t, str):
                out.append(t)
    return " | ".join(out)


def _iso(value: Any) -> str:

    try:
        return value.isoformat() if value else ""
    except Exception:
        return ""


def _classify_file_kind(row: dict) -> str:


    asset = (row.get("asset_type") or "").strip().lower()
    if asset in ("document", "image", "video", "audio", "archive"):
        return asset
    mime = (row.get("content_type") or "").strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("application/zip") or mime.startswith("application/x-"):
        return "archive"
    if mime.startswith("text/") or mime in (
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return "document"
    name = (row.get("saved_name") or row.get("file_name") or "").lower()
    if name.endswith((".pdf", ".doc", ".docx", ".txt", ".md", ".rtf")):
        return "document"
    if name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic")):
        return "image"
    if name.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
        return "video"
    if name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
        return "audio"
    if name.endswith((".zip", ".tar", ".gz", ".7z", ".rar")):
        return "archive"
    return "other"


_MAX_SENSITIVE_DOCS:    int = 12
_MAX_EXPIRING_ITEMS:    int = 12
_MAX_NEEDS_ATTENTION:   int = 12
_MAX_ENTITY_LIST:       int = 12

                                                                
_SENSITIVE_PURPOSES = (
    "id_document",
    "credential_export",
    "saved_login_list",
    "config_secrets",
    "financial_document",
    "tax_document",
    "legal_document",
    "contract",
    "insurance_form",
    "medical_document",
    "government_legal_financial",
    "passport",
    "visa",
)


def get_vault_intelligence(*, vault_id: str, key: bytes) -> str:


    try:
        from vault_intelligence_cache import read_cache
        cached = read_cache(vault_id, key)
    except Exception:
        cached = None

    if cached is not None and cached.available and cached.snapshot is not None:
        stale = cached.reason == "stale"
        if stale:
                                                              
                                                      
            try:
                from vault_intelligence_updater import (
                    mark_vault_dirty, TRIGGER_CHAT_FALLBACK,
                )
                mark_vault_dirty(
                    vault_id, trigger_kind=TRIGGER_CHAT_FALLBACK,
                )
            except Exception:
                pass
        snap_with_meta = dict(cached.snapshot)
        snap_with_meta["cache"] = {
            "source":               "cache",
            "stale":                stale,
            "last_refreshed_at_unix": cached.last_refreshed_at,
        }
        return json.dumps(snap_with_meta, ensure_ascii=False)

                                                               
    snap: dict = {
        "schema_version": 1,
        "coverage":              _coverage_block(vault_id),
        "files_by_kind":         _files_by_kind_block(vault_id),
        "recent_uploads":        _recent_uploads_block(vault_id),
        "credentials":           _credentials_block(vault_id, key),
        "sensitive_documents":   _sensitive_docs_block(vault_id),
        "expiring_soon":         _expiring_soon_block(vault_id),
        "needs_attention":       _needs_attention_block(vault_id),
        "top_entities":          _top_entities_block(vault_id),
        "cache": {
            "source":               "live",
            "stale":                False,
            "last_refreshed_at_unix": None,
        },
    }

                                                                
    if _key_ok(key):
        try:
            from vault_intelligence_updater import (
                mark_vault_dirty, TRIGGER_CHAT_FALLBACK,
            )
            mark_vault_dirty(
                vault_id, trigger_kind=TRIGGER_CHAT_FALLBACK,
            )
        except Exception:
            pass

    return json.dumps(snap, ensure_ascii=False)


def _coverage_block(vault_id: str) -> dict:
    try:
        from vault_analysis import analysis_coverage_for_vault
        cov = analysis_coverage_for_vault(vault_id) or {}
    except Exception:
        return {"available": False, "reason": "unavailable"}
    total       = int(cov.get("total") or 0)
    analyzed    = int(cov.get("analyzed") or 0)
    pending     = int(cov.get("pending") or 0)
    processing  = int(cov.get("processing") or 0)
    failed      = int(cov.get("failed") or 0)
    unsupported = int(cov.get("unsupported") or 0)
    percent = (
        round(100.0 * analyzed / total, 1) if total > 0 else 0.0
    )
    return {
        "available":    True,
        "total":        total,
        "analyzed":     analyzed,
        "pending":      pending,
        "processing":   processing,
        "failed":       failed,
        "unsupported":  unsupported,
        "percent":      percent,
        "is_complete": (
            total > 0 and pending == 0 and processing == 0
        ),
    }


def _files_by_kind_block(vault_id: str) -> dict:
    try:
        from main import list_uploaded_files
        rows = list_uploaded_files(vault_id) or []
    except Exception:
        return {"available": False, "reason": "unavailable"}
    counts: dict[str, int] = {
        "document": 0, "image": 0, "video": 0, "audio": 0,
        "archive": 0, "other": 0,
    }
    for r in rows:
        counts[_classify_file_kind(r)] += 1
    return {"available": True, "counts": counts, "total": len(rows)}


def _recent_uploads_block(vault_id: str) -> dict:
    try:
        from main import list_uploaded_files
        rows = list_uploaded_files(vault_id) or []
    except Exception:
        return {"available": False, "reason": "unavailable"}
    out: list[dict] = []
    for r in rows[:MAX_RECENT_FILES]:
        out.append({
            "file_name": str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "kind":      _classify_file_kind(r),
            "folder":    str(r.get("relative_path") or ""),
            "uploaded_at_iso": _iso(r.get("created_at")),
        })
    return {"available": True, "files": out}


def _credentials_block(vault_id: str, key: bytes) -> dict:


    if not _key_ok(key):
        return {
            "available":    False,
            "reason":       "vault_locked",
            "saved_credential_services_count": _saved_services_count(vault_id),
        }
    try:
        from main import _list_uploaded_files_for_credential_search
        from vault_inventory import verified_credential_files_report
        from vault_analysis import analysis_coverage_for_vault
        from vault_deep_answer import build_coverage_report
        rows = _list_uploaded_files_for_credential_search(vault_id, key)
        raw_cov = analysis_coverage_for_vault(vault_id) or {}
        coverage = build_coverage_report(raw_cov)
        report = verified_credential_files_report(rows, coverage=coverage)
    except Exception:
        return {
            "available": False, "reason": "unavailable",
            "saved_credential_services_count": _saved_services_count(vault_id),
        }
    files: list[dict] = []
    for m in (report.get("matches") or []):
        files.append({
            "file_name":         str(
                m.get("saved_name") or m.get("file_name") or ""
            ),
            "folder":            str(m.get("relative_path") or ""),
            "record_count":      int(m.get("record_count") or 0),
            "safe_service_names": list(m.get("safe_service_names") or [])[:5],
            "password_present":  bool(m.get("password_present")),
            "duplicate_paths":   list(m.get("duplicate_paths") or []),
        })
    return {
        "available":          True,
        "verified_files":     files,
        "verified_file_count": len(files),
        "total_records_across_files": sum(
            int(f.get("record_count") or 0) for f in files
        ),
        "is_partial":         bool(report.get("is_partial")),
        "scanned_count":      int(report.get("scanned_count") or 0),
        "not_scanned_count":  int(report.get("not_scanned_count") or 0),
        "saved_credential_services_count": _saved_services_count(vault_id),
    }


def _saved_services_count(vault_id: str) -> int:
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT COUNT(DISTINCT service) AS n FROM vault_items "
                "WHERE vault_id = %s",
                (vault_id,),
            )
            row = cur.fetchone()
            return int((row or {}).get("n") or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def _sensitive_docs_block(vault_id: str) -> dict:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT u.file_id,
                       u.document_purpose,
                       u.purpose_label,
                       u.purpose_confidence,
                       f.file_name,
                       f.saved_name,
                       f.relative_path,
                       f.created_at
                FROM vault_file_understanding u
                JOIN uploaded_files f ON f.id = u.file_id
                WHERE u.vault_id = %s
                  AND u.status = 'ready'
                  AND u.document_purpose = ANY(%s)
                ORDER BY u.purpose_confidence DESC NULLS LAST,
                         f.created_at DESC
                LIMIT %s
                """,
                (
                    vault_id,
                    list(_SENSITIVE_PURPOSES),
                    _MAX_SENSITIVE_DOCS,
                ),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {"available": False, "reason": "unavailable", "files": []}
    out: list[dict] = []
    for r in rows:
        out.append({
            "file_name":        str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":           str(r.get("relative_path") or ""),
            "document_purpose": str(r.get("document_purpose") or ""),
            "purpose_label":    str(r.get("purpose_label") or ""),
            "confidence":       float(r.get("purpose_confidence") or 0.0),
        })
    return {
        "available": True,
        "files":     out,
        "count":     len(out),
    }


def _expiring_soon_block(vault_id: str) -> dict:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT a.source_kind,
                       a.source_file_id,
                       a.source_item_id,
                       a.expiry_type,
                       a.expiry_date,
                       a.severity,
                       a.alert_window_days,
                       f.file_name,
                       f.saved_name,
                       f.relative_path
                FROM vault_expiry_alerts a
                LEFT JOIN uploaded_files f
                       ON f.id = a.source_file_id
                WHERE a.vault_id = %s
                  AND a.status   = 'active'
                ORDER BY a.expiry_date ASC NULLS LAST
                LIMIT %s
                """,
                (vault_id, _MAX_EXPIRING_ITEMS),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {"available": False, "reason": "unavailable", "items": []}
    out: list[dict] = []
    for r in rows:
        out.append({
            "file_name": str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":            str(r.get("relative_path") or ""),
            "source_kind":       str(r.get("source_kind") or ""),
            "expiry_type":       str(r.get("expiry_type") or ""),
            "expiry_date_iso":   _iso(r.get("expiry_date")),
            "severity":          str(r.get("severity") or ""),
            "window_days":       int(r.get("alert_window_days") or 0),
        })
    return {
        "available": True,
        "items":     out,
        "count":     len(out),
    }


def _needs_attention_block(vault_id: str) -> dict:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, file_name, saved_name, relative_path,
                       analysis_status, content_type, asset_type,
                       created_at
                FROM uploaded_files
                WHERE vault_id = %s
                  AND upload_status = 'complete'
                  AND analysis_status IN ('pending', 'processing',
                                          'failed', 'unsupported')
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, _MAX_NEEDS_ATTENTION),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {"available": False, "reason": "unavailable", "files": []}
    out: list[dict] = []
    for r in rows:
        out.append({
            "file_name": str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":          str(r.get("relative_path") or ""),
            "kind":            _classify_file_kind(r),
            "analysis_status": str(r.get("analysis_status") or ""),
        })
    return {
        "available": True,
        "files":     out,
        "count":     len(out),
    }


def _top_entities_block(vault_id: str) -> dict:


    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT entities_jsonb
                FROM vault_file_understanding
                WHERE vault_id = %s
                  AND status = 'ready'
                  AND entities_jsonb IS NOT NULL
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {"available": False, "reason": "unavailable"}
    tallies: dict[str, dict[str, int]] = {
        "people": {}, "organizations": {}, "places": {},
    }
    for r in rows:
        ents = r.get("entities_jsonb") or {}
        if not isinstance(ents, dict):
            continue
        for cat in ("people", "organizations", "places"):
            for token in (ents.get(cat) or []):
                if not isinstance(token, str):
                    continue
                t = token.strip()
                if not t or len(t) > 80:
                    continue
                tallies[cat][t] = tallies[cat].get(t, 0) + 1
    def _top(d: dict[str, int]) -> list[dict]:
        ranked = sorted(
            d.items(), key=lambda p: (-p[1], p[0])
        )[:_MAX_ENTITY_LIST]
        return [
            {"name": name, "files_seen_in": count}
            for name, count in ranked
        ]
    return {
        "available":     True,
        "people":        _top(tallies["people"]),
        "organizations": _top(tallies["organizations"]),
        "places":        _top(tallies["places"]),
    }


VAULT_KNOWLEDGE_DISPATCH = {
    "get_vault_intelligence": get_vault_intelligence,
    "get_vault_overview":     get_vault_overview,
    "list_vault_files":       list_vault_files,
    "search_vault_content":   search_vault_content,
}


try:
    from vault_inspection_tools import (
        INSPECTION_DISPATCH as _INSPECTION_DISPATCH,
        INSPECTION_FUNCTIONS as _INSPECTION_FUNCTIONS,
    )
    VAULT_KNOWLEDGE_DISPATCH.update(_INSPECTION_DISPATCH)
    VAULT_KNOWLEDGE_FUNCTIONS = (
        VAULT_KNOWLEDGE_FUNCTIONS + list(_INSPECTION_FUNCTIONS)
    )
except Exception:
    logger.exception(
        "[KNOWLEDGE-TOOLS] failed to merge inspection tools",
    )


try:
    from vault_surface_tools import (
        SURFACE_DISPATCH as _SURFACE_DISPATCH,
        SURFACE_FUNCTIONS as _SURFACE_FUNCTIONS,
    )
    VAULT_KNOWLEDGE_DISPATCH.update(_SURFACE_DISPATCH)
    VAULT_KNOWLEDGE_FUNCTIONS = (
        VAULT_KNOWLEDGE_FUNCTIONS + list(_SURFACE_FUNCTIONS)
    )
except Exception:
    logger.exception(
        "[KNOWLEDGE-TOOLS] failed to merge surface tools",
    )


__all__ = [
    "VAULT_KNOWLEDGE_FUNCTIONS",
    "VAULT_KNOWLEDGE_DISPATCH",
    "MAX_FILES_RETURNED",
    "MAX_SEARCH_HITS",
    "MAX_SNIPPET_CHARS",
    "MAX_RECENT_FILES",
    "get_vault_intelligence",
    "get_vault_overview",
    "list_vault_files",
    "search_vault_content",
]
