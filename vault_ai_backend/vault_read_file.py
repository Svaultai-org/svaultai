

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

                                                                 
_MAX_DISAMBIGUATION_CANDIDATES = 5
                                                                     
                                                         
try:
    from vault_config import brain as _brain_cfg
    _DEFAULT_CHAT_EXCERPT_CHARS = _brain_cfg().read_file_excerpt_chars
except Exception:
    _DEFAULT_CHAT_EXCERPT_CHARS = 4000


def resolve_file_by_name(
    vault_id: str, name_query: str,
) -> tuple[Optional[dict], list[dict]]:


    if not vault_id or not name_query or not name_query.strip():
        return None, []
    needle = name_query.strip()
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
                                         
        cur.execute(
            """
            SELECT id, file_name, content_type, analysis_status
            FROM uploaded_files
            WHERE vault_id = %s AND LOWER(file_name) = LOWER(%s)
            LIMIT 2
            """,
            (vault_id, needle),
        )
        rows = cur.fetchall() or []
        if len(rows) == 1:
            r = rows[0]
            return _row_to_dict(r), []
        if len(rows) > 1:
                                                                
                                                        
            return None, [_row_to_dict(r) for r in rows]
                           
        cur.execute(
            """
            SELECT id, file_name, content_type, analysis_status
            FROM uploaded_files
            WHERE vault_id = %s
              AND LOWER(file_name) LIKE LOWER(%s)
            ORDER BY file_name
            LIMIT %s
            """,
            (vault_id, f"%{needle}%", _MAX_DISAMBIGUATION_CANDIDATES + 1),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    if len(rows) == 1:
        return _row_to_dict(rows[0]), []
    if len(rows) == 0:
        return None, []
    return None, [_row_to_dict(r) for r in rows[:_MAX_DISAMBIGUATION_CANDIDATES]]


def _row_to_dict(row) -> dict:
    return {
        "id":              row[0],
        "file_name":       row[1],
        "content_type":    row[2],
        "analysis_status": row[3],
    }


def _reply_no_match(name_query: str) -> str:
    return (
        f"I don't see a file named '{name_query}' in your vault. "
        f"Try the exact filename or open the files list."
    )


def _reply_disambiguate(name_query: str, candidates: list[dict]) -> str:
    lines = [
        f"I found {len(candidates)} files matching '{name_query}'. "
        f"Which one do you mean?",
    ]
    for c in candidates:
        lines.append(f"  • {c['file_name']}")
    return "\n".join(lines)


def _reply_not_analyzed(file_name: str, status: str,
                       analysis_last_error: Optional[str]) -> str:
    msg = (
        f"I'm still reading '{file_name}'. Current status: {status}. "
        f"I'll have the text once the analyzer finishes."
    )
    if analysis_last_error:
                                                                      
                                            
        msg += f" Last error: {analysis_last_error}."
    return msg


def _reply_no_text(file_name: str) -> str:
    return (
        f"'{file_name}' has been analyzed but the extractor didn't "
        f"find readable text. It may be an image-only document that "
        f"needs OCR, or an unsupported format."
    )


def _reply_with_text(file_name: str, text: str, truncated: bool) -> str:
    header = f"Here's the text from '{file_name}':\n\n"
    body = text
    if truncated:
        body += (
            "\n\n[…showing first part only — open the file to see the rest.]"
        )
    return header + body


def handle_read_file_text_intent(
    *, vault_id: str, query_name: str, key: bytes,
    max_chars: int = _DEFAULT_CHAT_EXCERPT_CHARS,
) -> str:


    if not vault_id or not query_name or not query_name.strip():
        return "I need a filename to read. Try 'what is in <filename>?'"
    file_row, candidates = resolve_file_by_name(vault_id, query_name)
    if file_row is None and not candidates:
        return _reply_no_match(query_name)
    if file_row is None:
        return _reply_disambiguate(query_name, candidates)

    file_id = file_row["id"]
    file_name = file_row["file_name"]
                                                                 
                                                               
    try:
        from routes.file_text_routes import load_extracted_text
        payload = load_extracted_text(
            vault_id=vault_id, file_id=file_id, key=key,
            max_chars=max_chars,
        )
    except Exception:
                                                                      
                          
        logger.exception("read_file_text helper crashed")
        return (
            f"I couldn't read '{file_name}' right now. "
            f"Try again or check the file's analysis status."
        )

    status = payload.get("analysis_status")
    note = payload.get("note")
    if status != "analyzed":
        return _reply_not_analyzed(
            file_name, status or "unknown",
            payload.get("analysis_last_error"),
        )
    text = payload.get("text") or ""
    if not text or note == "analyzed_but_no_text":
        return _reply_no_text(file_name)
    return _reply_with_text(
        file_name, text, bool(payload.get("truncated")),
    )


__all__ = [
    "resolve_file_by_name",
    "handle_read_file_text_intent",
]
