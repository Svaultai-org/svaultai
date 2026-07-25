

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Optional


logger = logging.getLogger(__name__)


MAX_TEXT_CHARS_RETURNED = 12_000
MAX_SEARCH_HITS = 12
MAX_SNIPPET_CHARS = 320
MAX_IMAGE_BYTES = 5 * 1024 * 1024                                  
MAX_VISION_RESPONSE_CHARS = 4_000

_VISION_TIMEOUT_SECONDS = int(os.getenv("VAULTAI_VISION_TIMEOUT_S", "30"))


def _resolve_vision_model() -> str:


    try:
        from vault_config import ai as _ai_cfg
        return _ai_cfg().chat_model
    except Exception:
        return os.getenv("VAULTAI_VISION_MODEL") or ""


def _key_ok(key: Optional[bytes]) -> bool:
    return isinstance(key, (bytes, bytearray)) and len(key) == 32


def _err(name: str, **extra: Any) -> str:


    payload = {"error": name}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


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
    ws = cut.rfind(" ")
    if ws > cap * 0.7:
        cut = cut[:ws]
    return cut + "…"


def _iso(value: Any) -> str:
    try:
        return value.isoformat() if value else ""
    except Exception:
        return ""


def _fetch_file_row(vault_id: str, file_id: str) -> Optional[dict]:


    if not vault_id or not file_id:
        return None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, vault_id, file_name, saved_name,
                       relative_path, content_type, asset_type,
                       file_size, created_at, detected_type,
                       detected_service, upload_status,
                       analysis_status,
                       encrypted_file_data,
                       extracted_text, extracted_text_encrypted,
                       extracted_text_source,
                       extracted_text_status
                FROM uploaded_files
                WHERE id = %s
                  AND vault_id = %s
                LIMIT 1
                """,
                (file_id, vault_id),
            )
            return cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[INSPECT] _fetch_file_row failed file_id=%s",
            (file_id or "")[:8] + "...",
        )
        return None


def _decrypt_extracted_text(row: dict, key: bytes) -> Optional[str]:

    raw = row.get("extracted_text")
    enc = bool(row.get("extracted_text_encrypted"))
    if not raw:
        return None
    if not enc:
        return raw if isinstance(raw, str) else None
    try:
        from vault_core import decrypt_message
        return decrypt_message(raw, key)
    except Exception:
        return None


def _decrypt_file_bytes(row: dict, key: bytes) -> Optional[bytes]:


    enc = row.get("encrypted_file_data")
    if not enc or not isinstance(enc, str):
        return None
    try:
        from vault_core import decrypt_bytes
        return decrypt_bytes(enc, key)
    except Exception:
        return None


INSPECTION_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file_text",
            "description": (
                "Open ONE file by file_id and return its decrypted "
                "extracted text plus metadata. Use this whenever "
                "the user asks 'what does this file say', 'show me "
                "the contents', 'what's inside', or when you need "
                "to verify a name/number actually appears in a "
                "specific file. The reply is REDACTED — passwords / "
                "OTPs / emails are masked. Text is capped at "
                f"{MAX_TEXT_CHARS_RETURNED} characters; longer "
                "files are truncated. Returns "
                "``{\"error\":\"vault_locked\"}`` when the vault is "
                "locked, ``{\"error\":\"not_found\"}`` when the "
                "file_id doesn't belong to this vault, and "
                "``{\"error\":\"no_text\"}`` when the file has no "
                "extracted text yet (image without OCR, audio not "
                "transcribed, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": (
                            "The file_id returned by "
                            "list_vault_files / search_vault_content "
                            "/ search_extracted_text. ALWAYS pass "
                            "an exact id, never a guess."
                        ),
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_image_with_vision",
            "description": (
                "Open ONE image file (or PDF page) by file_id and "
                "ask GPT-4o vision a focused question about it. Use "
                "this when the user wants you to actually LOOK at a "
                "photo, scan, ID card, receipt, screenshot, or "
                "passport image — when text extraction alone won't "
                "answer (e.g. 'whose face is on this ID?', 'what "
                "does the photo show?', 'is this Louis's "
                "passport?'). The tool returns the model's textual "
                "answer; the raw image is NEVER streamed to the "
                "user. ``question`` should be a precise prompt — "
                "the more specific the better."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file_id to inspect.",
                    },
                    "question": {
                        "type": "string",
                        "description": (
                            "What you want vision to answer about "
                            "the image. E.g. 'Is this an ID card "
                            "showing the name Louis Iodato? "
                            "Describe the document type and any "
                            "names visible.'"
                        ),
                    },
                },
                "required": ["file_id", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_extracted_text",
            "description": (
                "Search the decrypted extracted-text of every file "
                "in the vault for a query string. Returns up to "
                f"{MAX_SEARCH_HITS} hits with file_id, file_name, "
                "and a redacted snippet showing the match. Use "
                "this as a focused fast pre-filter: 'where is X "
                "mentioned' → search_extracted_text(X) → pick the "
                "best file_id → read_file_text or "
                "read_image_with_vision on it for the real answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Phrase, name, or keyword.",
                    },
                    "file_kind": {
                        "type": "string",
                        "description": (
                            "Optional filter. Closed set: "
                            "document, image, video, audio, "
                            "archive, other. Omit for any kind."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_uploaded_file",
            "description": (
                "Comprehensive single-file inspection. Returns "
                "metadata, understanding row (document_purpose, "
                "purpose_label, confidence), entities seen "
                "(people, organizations, places), classification, "
                "analysis status, and any active expiry alerts on "
                "the file. Use this when you want a structured "
                "picture of one file WITHOUT reading its full "
                "extracted text. Cheaper than read_file_text when "
                "you only need the shape."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file_id to inspect.",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_metadata",
            "description": (
                "Lightweight metadata for ONE file: file_name, "
                "kind, size_bytes, folder, uploaded_at_iso, "
                "analysis_status. No extracted text, no entities. "
                "Use when you just need to confirm a file exists "
                "and grab its display attributes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file_id.",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_saved_credentials",
            "description": (
                "List the services for which the user has saved "
                "credentials. Returns service names + record "
                "counts ONLY — NEVER plaintext passwords, PINs, "
                "or seed phrases. Use this when the user asks "
                "'what accounts do I have saved', 'do I have a "
                "login for Chase', or before generating a new "
                "credential (to check whether one already exists)."
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
            "name": "get_credential_metadata",
            "description": (
                "Metadata for ONE saved-credential service. "
                "Returns ``{exists, service, record_count, "
                "secret_types}`` — closed-set, NEVER the secret. "
                "Use this to confirm a service exists before "
                "calling retrieve_secret, or before offering to "
                "generate a replacement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name (case-insensitive).",
                    },
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_media_transcript",
            "description": (
                "Read the transcript of an audio or video file. "
                "Use this for 'what was said in this video', "
                "'transcribe this audio', 'what did the recording "
                "cover'. Refuses non-media files so you can route "
                "correctly. Returns the redacted transcript plus "
                "the source it was produced from (audio_transcript "
                "/ video_transcript). If the transcript isn't "
                "ready yet, the reply tells you the file's "
                "analysis_status so you can say 'I'm still "
                "transcribing — try again in a moment.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": (
                            "The file_id of an audio or video "
                            "file."
                        ),
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_file_chunks",
            "description": (
                "List the chunk index for ONE file. Each chunk "
                "row carries its extraction_source — pdf_text, "
                "ocr, image_ocr, docx, txt, html, json, csv, "
                "xlsx, archive, audio_transcript, video_transcript, "
                "video_frame, plain_text — plus the character "
                "range. Use this to navigate long media / long "
                "documents at segment granularity ('how many "
                "transcript chunks', 'show me the PDF pages')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file_id.",
                    },
                    "extraction_source": {
                        "type": "string",
                        "description": (
                            "Optional closed-set filter on the "
                            "chunk source, e.g. video_transcript "
                            "or ocr."
                        ),
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_chunk",
            "description": (
                "Read ONE chunk of a file by (file_id, "
                "chunk_index). Returns the decrypted, redacted "
                "text of that segment plus its char_start / "
                "char_end / extraction_source. Use this to spot-"
                "check a specific transcript segment, PDF page "
                "region, or OCR block without pulling the full "
                "file text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file_id.",
                    },
                    "chunk_index": {
                        "type": "integer",
                        "description": (
                            "Chunk index from list_file_chunks. "
                            "Starts at 0."
                        ),
                    },
                },
                "required": ["file_id", "chunk_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_in_vault",
            "description": (
                "Complete document / entity search across the "
                "vault in ONE call. Pass ``doc_kind=\"id_photo\"`` "
                "for ID / driver license / passport / identity "
                "card queries — the tool will restrict candidates "
                "to images + PDFs and require each hit to be "
                "CLASSIFIED as an ID-class document (a text file "
                "that merely mentions the word 'ID' is rejected). "
                "Returns ``{complete, hits[], coverage}`` where "
                "every hit carries ``file_name``, ``file_kind`` "
                "(image|pdf|text), ``evidence_type`` "
                "(extracted_text|image_vision|pdf_page_vision|"
                "ocr_text), ``document_type`` "
                "(id_photo|passport|driver_license|unknown), "
                "``matched_name``, and ``confidence``. PREFER "
                "this over ``search_extracted_text`` / "
                "``find_files_for_entity`` / "
                "``read_image_with_vision`` for any 'find me a "
                "person / ID / photo / document' query — it is "
                "the only tool that completes the search "
                "end-to-end. NEVER end your reply on 'review is "
                "still in progress' when ``complete: true``. "
                "When ``complete: false`` the vision budget ran "
                "out — say the search took too long, NOT that "
                "the file is missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The person name / entity / phrase "
                            "to find. For broad searches like "
                            "'show all my ID photos' pass the "
                            "user's full request verbatim — the "
                            "tool strips category words and "
                            "runs a broad ID-class listing when "
                            "no person name remains."
                        ),
                    },
                    "doc_kind": {
                        "type": "string",
                        "description": (
                            "Optional kind hint. Closed-set: "
                            "id, id_photo, passport, "
                            "driver_license, identity_card, "
                            "license, photo, image, document, "
                            "pdf, any. The tool auto-infers "
                            "``id_photo`` when the query "
                            "carries category words; pass it "
                            "explicitly for unambiguous "
                            "ID-class queries."
                        ),
                    },
                    "fuzzy_distance": {
                        "type": "integer",
                        "description": (
                            "Optional Levenshtein ceiling for "
                            "token matches. Default 2; valid "
                            "range 0-4."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_credential_draft",
            "description": (
                "Generate a secure credential draft. When the user "
                "supplied an explicit username / password / email / "
                "url / title in their message, PASS THOSE VALUES "
                "along with the service name — the backend uses the "
                "supplied values verbatim (case, punctuation, and "
                "special characters preserved) and generates ONLY "
                "the fields the user did not provide. Explicit "
                "user value > generated value, always. Never "
                "substitute or 'normalize' a user-supplied value.\n\n"
                "Returns ``{service_name, username, password, "
                "email?, url?, title?, draft_id, expires_at, "
                "saved: false, explicit_fields: [...]}``. Surface "
                "the returned username and password to the user "
                "exactly once in the CREDENTIAL CREATION DRAFT "
                "shape and ask them to say 'save it now'. NEVER "
                "claim the credential is saved after this tool "
                "call — only "
                "``save_generated_credential_after_confirmation`` "
                "actually saves. When generating a username (i.e. "
                "the user did NOT supply one), the generated value "
                "NEVER contains the service name, the word 'vault', "
                "the user's name/handle, or any personal info.\n\n"
                "USERNAME KINDS ACCEPTED: any string the user "
                "supplied — email addresses ('alice@example.com'), "
                "plain handles ('alice42'), dotted / underscored "
                "handles ('alice.smith', 'alice_smith'), phone-"
                "number style handles ('+15551234567'), or quoted "
                "multi-word handles ('\"alice smith\"'). Do NOT "
                "restrict to email format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Public service name as the user "
                            "phrased it (e.g. 'Union Bank', "
                            "'Capital One', 'Gmail'). Used as a "
                            "lookup key for the per-service "
                            "username policy and as the display "
                            "label."
                        ),
                    },
                    "username": {
                        "type": "string",
                        "description": (
                            "Optional. The username the user "
                            "explicitly supplied in their message "
                            "('use alice@example.com as my "
                            "username', 'username: alice42', "
                            "'account name is alice.smith'). When "
                            "provided, the backend uses this "
                            "value VERBATIM and does NOT generate "
                            "a username. Omit ONLY when the user "
                            "did not supply one — do NOT invent."
                        ),
                    },
                    "password": {
                        "type": "string",
                        "description": (
                            "Optional. The password the user "
                            "explicitly supplied ('use \"Secr3t!\" "
                            "as the password', 'password: X'). "
                            "When provided, the backend uses this "
                            "value VERBATIM and does NOT generate "
                            "one. Omit ONLY when the user did not "
                            "supply one — do NOT invent."
                        ),
                    },
                    "email": {
                        "type": "string",
                        "description": (
                            "Optional. Explicit email if the user "
                            "gave one AND intends it as an email "
                            "field alongside a separate username. "
                            "Most 'use my email X as my username' "
                            "cases should pass X in username, not "
                            "email."
                        ),
                    },
                    "url": {
                        "type": "string",
                        "description": (
                            "Optional. Explicit URL / login site "
                            "the user supplied."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "Optional. Explicit title / label the "
                            "user gave for this credential (rare)."
                        ),
                    },
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_generated_credential_after_confirmation",
            "description": (
                "Save a generated credential ONLY after the user "
                "has explicitly confirmed. Hard-gated: the tool "
                "REFUSES unless ``user_confirmed`` is exactly "
                "``true``. Pass ``user_confirmed=true`` only when "
                "the user has said 'save it now', 'save it', "
                "'generate and save', or an equivalent explicit "
                "phrase IN THE CURRENT MESSAGE. Do NOT save on "
                "ambient yeses or implied consent. Pass the "
                "``draft_id`` returned by "
                "``generate_credential_draft`` when available — "
                "the backend looks up the pending draft and the "
                "model does NOT need to echo the password "
                "values. If no draft_id is on hand, pass the "
                "``service`` + ``fields.username`` + "
                "``fields.password`` directly (legacy path)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "Draft id returned by "
                            "``generate_credential_draft``. "
                            "Preferred. When provided, "
                            "``service`` / ``fields`` are "
                            "optional — the backend reads the "
                            "values from the pending draft."
                        ),
                    },
                    "service": {
                        "type": "string",
                        "description": (
                            "Service name. Optional when "
                            "``draft_id`` is passed."
                        ),
                    },
                    "fields": {
                        "type": "object",
                        "description": (
                            "Credential fields. Closed set: "
                            "username, email, password, notes. "
                            "Optional when ``draft_id`` is "
                            "passed."
                        ),
                        "additionalProperties": True,
                    },
                    "user_confirmed": {
                        "type": "boolean",
                        "description": (
                            "MUST be true. Set this only when the "
                            "user has said 'save it'/'save it "
                            "now'/'generate and save' in the "
                            "current turn."
                        ),
                    },
                },
                "required": ["user_confirmed"],
            },
        },
    },
]


def read_file_text(
    *, vault_id: str, key: bytes, file_id: str,
) -> str:
    if not _key_ok(key):
        return _err("vault_locked")
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    asset = (row.get("asset_type") or "").strip().lower()
    text = _decrypt_extracted_text(row, key)
    if not text:
                                                                 
                                               
        if asset == "image":
            hint = (
                "This image has no OCR text yet. Call "
                "read_image_with_vision(file_id, question) to "
                "read it visually."
            )
        elif asset in ("audio", "video"):
            hint = (
                "This media file has no transcript yet. Check "
                "analysis_status — it may still be transcribing."
            )
        else:
            hint = (
                "This file has no extracted text yet. Check "
                "analysis_status."
            )
        return _err(
            "no_text",
            file_name=str(row.get("saved_name")
                          or row.get("file_name") or ""),
            asset_type=asset,
            analysis_status=str(row.get("analysis_status") or ""),
            extracted_text_status=str(
                row.get("extracted_text_status") or ""
            ),
            hint=hint,
        )
    text = _redact(text)
    truncated = False
    if len(text) > MAX_TEXT_CHARS_RETURNED:
        text = text[:MAX_TEXT_CHARS_RETURNED]
        truncated = True
    return json.dumps({
        "file_id":         file_id,
        "file_name":       str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "folder":          str(row.get("relative_path") or ""),
        "content_type":    str(row.get("content_type") or ""),
        "asset_type":      asset,
        "size_bytes":      int(row.get("file_size") or 0),
        "uploaded_at_iso": _iso(row.get("created_at")),
        "text":            text,
        "truncated":       truncated,
                                                                
                                                              
        "extracted_text_source": str(
            row.get("extracted_text_source") or ""
        ),
        "extracted_text_status": str(
            row.get("extracted_text_status") or ""
        ),
    }, ensure_ascii=False)


def read_media_transcript(
    *, vault_id: str, key: bytes, file_id: str,
) -> str:


    if not _key_ok(key):
        return _err("vault_locked")
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    asset = (row.get("asset_type") or "").strip().lower()
    ctype = (row.get("content_type") or "").strip().lower()
    is_media = (
        asset in ("audio", "video")
        or ctype.startswith("audio/")
        or ctype.startswith("video/")
    )
    if not is_media:
        return _err(
            "not_media",
            file_name=str(
                row.get("saved_name") or row.get("file_name") or ""
            ),
            asset_type=asset,
            hint=(
                "This file isn't audio or video. Use "
                "read_file_text for documents and "
                "read_image_with_vision for images."
            ),
        )
    text = _decrypt_extracted_text(row, key)
    if not text:
        return _err(
            "transcript_not_ready",
            file_name=str(
                row.get("saved_name") or row.get("file_name") or ""
            ),
            asset_type=asset,
            analysis_status=str(row.get("analysis_status") or ""),
            extracted_text_status=str(
                row.get("extracted_text_status") or ""
            ),
            hint=(
                "The transcript hasn't been written yet. Check "
                "again after analysis_status is 'ready'."
            ),
        )
    text = _redact(text)
    truncated = False
    if len(text) > MAX_TEXT_CHARS_RETURNED:
        text = text[:MAX_TEXT_CHARS_RETURNED]
        truncated = True
    return json.dumps({
        "file_id":            file_id,
        "file_name":          str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "folder":             str(row.get("relative_path") or ""),
        "asset_type":         asset,
        "content_type":       ctype,
        "transcript":         text,
        "truncated":          truncated,
        "transcript_source":  str(
            row.get("extracted_text_source") or "transcript"
        ),
    }, ensure_ascii=False)


def list_file_chunks(
    *, vault_id: str, key: bytes,
    file_id: str,
    extraction_source: Optional[str] = None,
) -> str:


    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    src_filter = (extraction_source or "").strip().lower() or None
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            params: list[Any] = [vault_id, file_id]
            where = [
                "c.vault_id = %s",
                "c.file_id  = %s",
            ]
            if src_filter:
                where.append("c.extraction_source = %s")
                params.append(src_filter)
            params.append(200)
            cur.execute(
                f"""
                SELECT c.chunk_index, c.extraction_source,
                       c.char_start, c.char_end,
                       c.char_length
                FROM vault_content_chunks c
                WHERE {' AND '.join(where)}
                ORDER BY c.chunk_index ASC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception("[INSPECT] list_file_chunks failed")
        return _err("unavailable")
    chunks = [
        {
            "chunk_index":       int(r.get("chunk_index") or 0),
            "extraction_source": str(r.get("extraction_source") or ""),
            "char_start":        int(r.get("char_start") or 0),
            "char_end":          int(r.get("char_end") or 0),
            "char_length":       int(r.get("char_length") or 0),
        }
        for r in rows
    ]
    return json.dumps({
        "file_id":      file_id,
        "file_name":    str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "asset_type":   str(row.get("asset_type") or ""),
        "chunks":       chunks,
        "chunk_count":  len(chunks),
        "filter":       {"extraction_source": src_filter},
    }, ensure_ascii=False)


def read_file_chunk(
    *, vault_id: str, key: bytes,
    file_id: str, chunk_index: int,
) -> str:


    if not _key_ok(key):
        return _err("vault_locked")
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        from vault_core import decrypt_message
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT chunk_index, encrypted_chunk_text,
                       extraction_source,
                       char_start, char_end, char_length
                FROM vault_content_chunks
                WHERE vault_id    = %s
                  AND file_id     = %s
                  AND chunk_index = %s
                LIMIT 1
                """,
                (vault_id, file_id, int(chunk_index)),
            )
            crow = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception("[INSPECT] read_file_chunk failed")
        return _err("unavailable")
    if not crow:
        return _err("chunk_not_found")
    enc = crow.get("encrypted_chunk_text")
    if not enc:
        return _err("chunk_empty")
    try:
        plain = decrypt_message(enc, key)
    except Exception:
        return _err("decrypt_failed")
    if not plain:
        return _err("chunk_empty")
    plain = _redact(plain)
    truncated = False
    if len(plain) > MAX_TEXT_CHARS_RETURNED:
        plain = plain[:MAX_TEXT_CHARS_RETURNED]
        truncated = True
    return json.dumps({
        "file_id":           file_id,
        "file_name":         str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "chunk_index":       int(crow.get("chunk_index") or 0),
        "extraction_source": str(crow.get("extraction_source") or ""),
        "char_start":        int(crow.get("char_start") or 0),
        "char_end":          int(crow.get("char_end") or 0),
        "text":              plain,
        "truncated":         truncated,
    }, ensure_ascii=False)


def read_image_with_vision(
    *, vault_id: str, key: bytes,
    file_id: str, question: str,
) -> str:
    if not _key_ok(key):
        return _err("vault_locked")
    q = (question or "").strip()
    if not q:
        return _err("empty_question")
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")

    ctype = (row.get("content_type") or "").strip().lower()
    asset = (row.get("asset_type") or "").strip().lower()
    saved = str(row.get("saved_name") or row.get("file_name") or "")
                                                                      
                                                               
    try:
        from vault_image_formats import is_image_row
    except Exception:
        is_image_row = None                
    looks_image = False
    if is_image_row is not None:
        try:
            looks_image = bool(
                is_image_row(
                    mime=ctype, file_name=saved, asset_type=asset,
                )
            )
        except Exception:
            looks_image = False
    legacy_image_check = (
        asset == "image" or ctype.startswith("image/")
    )
    if not (looks_image or legacy_image_check):
        return _err(
            "not_an_image",
            file_name=saved,
            hint=(
                "This file isn't an image. Use read_file_text "
                "for text-bearing files."
            ),
        )

    raw_bytes = _decrypt_file_bytes(row, key)
    if not raw_bytes:
        return _err("decrypt_failed")
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        return _err(
            "image_too_large",
            size_bytes=len(raw_bytes),
            limit_bytes=MAX_IMAGE_BYTES,
        )

                                                  
    vision_bytes = None
    mime = None
    decode_band = "ok"
    canonical_for_vision = ctype or None
    try:
        from vault_image_formats import (
            canonicalize_image_mime,
            normalize_for_vision,
        )
        canonical_for_vision = (
            canonicalize_image_mime(ctype) or ctype or None
        )
        native = normalize_for_vision(
            raw_bytes, mime_hint=canonical_for_vision,
        )
        if native is not None:
            vision_bytes, mime = native
    except Exception:
        logger.exception(
            "[INSPECT] vision normalisation raised file_id=%s",
            (file_id or "")[:8],
        )
        vision_bytes, mime = None, None
        decode_band = "decode_failed"

    if vision_bytes is None:
                                                                 
                                                         
        if decode_band == "ok":
            try:
                from vault_image_formats import normalize_with_reason
                _, _, decode_band = normalize_with_reason(
                    raw_bytes, mime_hint=canonical_for_vision,
                )
            except Exception:
                decode_band = "decode_failed"
        logger.warning(
            "[INSPECT] vision_skip_unsupported file_id=%s "
            "decode_band=%s mime=%s",
            (file_id or "")[:8], decode_band,
            canonical_for_vision or "unknown",
        )
        return _err(
            "unsupported_image",
            file_name=saved,
            decode_band=decode_band,
            hint=(
                "This image format is recognised but the server "
                "could not decode it. Skipping."
            ),
        )
    if not mime:
        mime = "image/jpeg"
    b64 = base64.b64encode(vision_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

                                                             
    try:
        from openai import OpenAI
    except Exception:
        return _err("unavailable")

    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        return _err("unavailable")

    vision_model = _resolve_vision_model()
    if not vision_model:
        return _err("unavailable")
    try:
        sync_client = OpenAI(
            api_key=api_key, timeout=_VISION_TIMEOUT_SECONDS,
        )
        resp = sync_client.chat.completions.create(
            model=vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are inspecting an image stored in "
                            "a private user vault. Be precise. If "
                            "the image shows an ID document, "
                            "passport, card, or receipt, describe "
                            "the document type, any visible names, "
                            "and whether the image content "
                            "matches the user's question. Do NOT "
                            "invent data. If you can't tell, say "
                            "so plainly.\n\n"
                            f"User's question: {q}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }],
            max_tokens=600,
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("[INSPECT] vision call failed")
        return _err("vision_failed")

    if not text:
        return _err("vision_empty")
    text = _redact(text)
    text = _short(text, MAX_VISION_RESPONSE_CHARS)
    return json.dumps({
        "file_id":   file_id,
        "file_name": str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "analysis": text,
        "model":    vision_model,
    }, ensure_ascii=False)


def search_extracted_text(
    *, vault_id: str, key: bytes,
    query: str, file_kind: Optional[str] = None,
) -> str:
    if not _key_ok(key):
        return _err("vault_locked")
    q = (query or "").strip()
    if not q:
        return _err("empty_query")

    try:
        from main import _list_uploaded_files_for_credential_search
        rows = (
            _list_uploaded_files_for_credential_search(vault_id, key)
            or []
        )
    except Exception:
        return _err("unavailable")

    kind_filter = (file_kind or "").strip().lower() or None
    if kind_filter not in (
        None, "document", "image", "video", "audio",
        "archive", "other",
    ):
        kind_filter = None

    try:
        from vault_knowledge_tools import _classify_file_kind
    except Exception:
        def _classify_file_kind(r):                
            return "other"

    q_lower = q.lower()
    tokens = [t for t in re.split(r"\s+", q_lower) if t and len(t) >= 2]
    hits: list[dict] = []
    for r in rows:
        if len(hits) >= MAX_SEARCH_HITS:
            break
        kind = _classify_file_kind(r)
        if kind_filter and kind != kind_filter:
            continue
        text = r.get("extracted_text")
        if not isinstance(text, str) or not text:
            continue
        blob = text.lower()
        if q_lower in blob:
            idx = blob.find(q_lower)
        elif tokens and all(t in blob for t in tokens):
            idx = blob.find(tokens[0])
        else:
            continue
        start = max(0, idx - 80)
        end = min(len(text), idx + 240)
        snippet = _short(_redact(text[start:end]), MAX_SNIPPET_CHARS)
        hits.append({
            "file_id":   str(r.get("id") or ""),
            "file_name": str(
                r.get("saved_name") or r.get("file_name") or ""
            ),
            "folder":    str(r.get("relative_path") or ""),
            "kind":      kind,
            "snippet":   snippet,
        })

    try:
        from vault_analysis import analysis_coverage_for_vault
        cov = analysis_coverage_for_vault(vault_id) or {}
        _total = int(cov.get("total") or 0)
        _pending = int(cov.get("pending") or 0)
        _processing = int(cov.get("processing") or 0)
                                                                   
                                                                    
        coverage = {
            "total":      _total,
            "analyzed":   int(cov.get("analyzed") or 0),
            "pending":    _pending,
            "is_complete": (
                _total == 0
                or (_pending == 0 and _processing == 0)
            ),
            "vault_empty": (_total == 0),
        }
    except Exception:
        coverage = {"is_complete": False}

    return json.dumps({
        "query":    q,
        "hits":     hits,
        "returned": len(hits),
        "coverage": coverage,
    }, ensure_ascii=False)


def inspect_uploaded_file(
    *, vault_id: str, key: bytes, file_id: str,
) -> str:
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    info: dict[str, Any] = {
        "file_id":         file_id,
        "file_name":       str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "folder":          str(row.get("relative_path") or ""),
        "content_type":    str(row.get("content_type") or ""),
        "asset_type":      str(row.get("asset_type") or ""),
        "size_bytes":      int(row.get("file_size") or 0),
        "uploaded_at_iso": _iso(row.get("created_at")),
        "upload_status":   str(row.get("upload_status") or ""),
        "analysis_status": str(row.get("analysis_status") or ""),
    }

                        
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT document_purpose, purpose_label,
                       purpose_confidence, status,
                       entities_jsonb, summary_short
                FROM vault_file_understanding
                WHERE vault_id = %s
                  AND file_id  = %s
                LIMIT 1
                """,
                (vault_id, file_id),
            )
            urow = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        urow = None

    if urow:
        info["document_purpose"] = str(urow.get("document_purpose") or "")
        info["purpose_label"]    = str(urow.get("purpose_label") or "")
        info["purpose_confidence"] = float(
            urow.get("purpose_confidence") or 0.0
        )
        info["understanding_status"] = str(urow.get("status") or "")
        info["summary_short"] = _redact(
            str(urow.get("summary_short") or "")
        )
        ents = urow.get("entities_jsonb") or {}
        if isinstance(ents, dict):
            info["entities"] = {
                "people":        list(ents.get("people") or [])[:20],
                "organizations": list(ents.get("organizations") or [])[:20],
                "places":        list(ents.get("places") or [])[:20],
            }
        else:
            info["entities"] = {
                "people": [], "organizations": [], "places": [],
            }
    else:
        info["understanding_status"] = "unanalyzed"
        info["entities"] = {
            "people": [], "organizations": [], "places": [],
        }

                                 
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT expiry_type, expiry_date, severity,
                       alert_window_days
                FROM vault_expiry_alerts
                WHERE vault_id = %s
                  AND source_file_id = %s
                  AND status = 'active'
                ORDER BY expiry_date ASC NULLS LAST
                LIMIT 5
                """,
                (vault_id, file_id),
            )
            alerts = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        alerts = []

    info["active_expiry_alerts"] = [
        {
            "expiry_type":     str(a.get("expiry_type") or ""),
            "expiry_date_iso": _iso(a.get("expiry_date")),
            "severity":        str(a.get("severity") or ""),
            "window_days":     int(a.get("alert_window_days") or 0),
        }
        for a in alerts
    ]
    return json.dumps(info, ensure_ascii=False)


def get_file_metadata(
    *, vault_id: str, key: bytes, file_id: str,
) -> str:
    row = _fetch_file_row(vault_id, file_id)
    if row is None:
        return _err("not_found")
    try:
        from vault_knowledge_tools import _classify_file_kind
        kind = _classify_file_kind(row)
    except Exception:
        kind = "other"
    return json.dumps({
        "file_id":         file_id,
        "file_name":       str(
            row.get("saved_name") or row.get("file_name") or ""
        ),
        "kind":            kind,
        "folder":          str(row.get("relative_path") or ""),
        "size_bytes":      int(row.get("file_size") or 0),
        "uploaded_at_iso": _iso(row.get("created_at")),
        "analysis_status": str(row.get("analysis_status") or ""),
    }, ensure_ascii=False)


def list_saved_credentials(*, vault_id: str, key: bytes) -> str:
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT service, item_type, COUNT(*) AS n
                FROM vault_items
                WHERE vault_id = %s
                GROUP BY service, item_type
                ORDER BY service ASC
                LIMIT 200
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return _err("unavailable")

    services: list[dict] = []
    for r in rows:
        services.append({
            "service":      str(r.get("service") or ""),
            "secret_type":  str(r.get("item_type") or ""),
            "record_count": int(r.get("n") or 0),
        })
    return json.dumps({
        "services":     services,
        "count":        len(services),
        "safety_floor": "metadata only — no secrets included",
    }, ensure_ascii=False)


def get_credential_metadata(
    *, vault_id: str, key: bytes, service: str,
) -> str:
    svc = (service or "").strip()
    if not svc:
        return _err("missing_service")
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT item_type, COUNT(*) AS n
                FROM vault_items
                WHERE vault_id = %s
                  AND LOWER(service) = LOWER(%s)
                GROUP BY item_type
                """,
                (vault_id, svc),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return _err("unavailable")
    if not rows:
        return json.dumps({
            "exists":       False,
            "service":      svc,
            "record_count": 0,
            "secret_types": [],
        }, ensure_ascii=False)
    return json.dumps({
        "exists":       True,
        "service":      svc,
        "record_count": sum(int(r.get("n") or 0) for r in rows),
        "secret_types": [
            str(r.get("item_type") or "") for r in rows
        ],
        "safety_floor": "metadata only — no secrets included",
    }, ensure_ascii=False)


def _clean_supplied_field(value: Optional[str]) -> Optional[str]:
    """2026-07-26 explicit-field acceptance: strip outer whitespace and
    matched outer quotes, drop obvious sentinel/None/empty values.
    Preserves case and punctuation. Rejects values that look like
    the LLM parroted a placeholder (e.g. 'null', 'None')."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Trim outer matching quotes if the LLM added them.
    for lq, rq in (("\"", "\""), ("'", "'"), ("`", "`")):
        if len(s) >= 2 and s.startswith(lq) and s.endswith(rq):
            s = s[1:-1].strip()
            break
    if not s:
        return None
    # Reject placeholder tokens.
    if s.lower() in {"none", "null", "n/a", "na", "undefined", "-"}:
        return None
    # Cap length to prevent pathological inputs from being written to
    # the credential store.
    return s[:512]


def generate_credential_draft(
    *, vault_id: str, key: bytes,
    service_name: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    email:    Optional[str] = None,
    url:      Optional[str] = None,
    title:    Optional[str] = None,
) -> str:


    # 2026-07-25 diagnostic: this tool is where the OpenAI planner
    # produces the "birchcove2083" style random username seen in the
    # production Bug 2 reproduction. Log entry so prod traces confirm
    # this is the true code path (not the intent-branch
    # generate_login handler in main.py). Never logs the service name
    # verbatim — only its length. The generated draft's username and
    # password are already redacted by the caller's telemetry.
    #
    # 2026-07-26 explicit-fields extension: log booleans indicating
    # whether the LLM passed each optional field. Never logs the
    # values themselves — only presence.
    _supplied_username = _clean_supplied_field(username)
    _supplied_password = _clean_supplied_field(password)
    _supplied_email    = _clean_supplied_field(email)
    _supplied_url      = _clean_supplied_field(url)
    _supplied_title    = _clean_supplied_field(title)
    print(
        f"[BRAIN-TRACE-DXR] site=generate_credential_draft "
        f"vault={(vault_id or '')[:8]} "
        f"service_len={len((service_name or '').strip())} "
        f"supplied_username={_supplied_username is not None} "
        f"supplied_password={_supplied_password is not None} "
        f"supplied_email={_supplied_email is not None} "
        f"supplied_url={_supplied_url is not None} "
        f"supplied_title={_supplied_title is not None}",
        flush=True,
    )

    if not _key_ok(key):
        return _err("vault_locked")
    svc_display = (service_name or "").strip()
    if not svc_display:
        return _err("missing_service")
    if len(svc_display) > 200:
        svc_display = svc_display[:200]

    try:
        from username_policy import (
            generate_username,
            conservative_default,
        )
        from main import generate_strong_password
        from vault_credential_draft import store_draft
    except Exception:
        logger.exception("[INSPECT] draft generator import failed")
        return _err("unavailable")

    # 2026-07-26 explicit > generated. If the user supplied a
    # username, use it VERBATIM (case, dots, hyphens, +digits, quoted
    # words — all preserved). Only generate when the user did NOT
    # supply one. Same rule for password.
    explicit_fields: list[str] = []
    if _supplied_username:
        username = _supplied_username
        explicit_fields.append("username")
    else:
        policy = conservative_default(svc_display)
        try:
            username = generate_username(
                policy,
                # never leak the service name into the generated
                # handle (existing behavior).
                forbidden_substrings={svc_display.lower()},
            )
        except Exception:
            logger.exception("[INSPECT] username generation failed")
            return _err("unavailable")
        if not username:
            return _err("unavailable")

    if _supplied_password:
        password = _supplied_password
        explicit_fields.append("password")
    else:
        try:
            password = generate_strong_password(length=20)
        except Exception:
            logger.exception("[INSPECT] password generation failed")
            return _err("unavailable")

    # Additional user-supplied fields flow into the draft as-is.
    # The current store_draft signature only accepts service /
    # username / password; email/url/title are surfaced back to the
    # planner via the returned dict so the DRAFT reply reflects them
    # and the confirmation-save path can pick them up when we extend
    # the store schema. Stored durably by save_secret_tool at
    # confirmation time (kept in the returned dict for symmetry now;
    # a follow-up commit will thread them through store_draft when
    # the schema is extended).
    if _supplied_email:
        explicit_fields.append("email")
    if _supplied_url:
        explicit_fields.append("url")
    if _supplied_title:
        explicit_fields.append("title")

    try:
        draft = store_draft(
            vault_id=vault_id,
            service_name=svc_display,
            username=username,
            password=password,
        )
    except Exception:
        logger.exception("[INSPECT] draft store failed")
        return _err("unavailable")

    logger.info(
        "[INSPECT] credential_draft_generated vault=%s "
        "service_len=%d username_len=%d password_len=%d "
        "draft_id_prefix=%s explicit_fields=%s",
        (vault_id or "")[:8] + "...",
        len(svc_display),
        len(username),
        len(password),
        draft.draft_id[:8],
        ",".join(explicit_fields) or "none",
    )

    # Attach explicit_fields + optional supplied values to the returned
    # payload so the LLM can format the DRAFT reply honestly ("you
    # supplied X" vs "I generated X") and the future confirm-save can
    # surface all supplied fields.
    payload = dict(draft.to_public_dict())
    payload["explicit_fields"] = list(explicit_fields)
    if _supplied_email:
        payload["email"] = _supplied_email
    if _supplied_url:
        payload["url"] = _supplied_url
    if _supplied_title:
        payload["title"] = _supplied_title
    return json.dumps(payload, ensure_ascii=False)


def save_generated_credential_after_confirmation(
    *, vault_id: str, key: bytes,
    service: Optional[str] = None,
    fields: Optional[dict] = None,
    user_confirmed: Optional[bool] = None,
    draft_id: Optional[str] = None,
) -> str:


    if user_confirmed is not True:
        return _err(
            "confirmation_required",
            hint=(
                "Set user_confirmed=true only after the user "
                "explicitly says 'save it', 'save it now', or "
                "'generate and save'."
            ),
        )
    if not _key_ok(key):
        return _err("vault_locked")

    svc: str = ""
    save_fields: dict = {}

                                                         
    try:
        from vault_credential_draft import consume_draft
        draft = consume_draft(
            vault_id=vault_id,
            draft_id=(draft_id or None),
            service_name=(service or None),
        )
    except Exception:
        logger.exception("[INSPECT] draft consume failed")
        draft = None

    if draft is not None:
        svc = draft.service_name
        save_fields = {
            "username": draft.username,
            "password": draft.password,
        }
    else:
        svc = (service or "").strip()
        if not svc:
            return _err("missing_service")
        if not isinstance(fields, dict):
            return _err("missing_fields")
        if not fields.get("username") and not fields.get("email"):
            return _err("missing_identity")
        if not fields.get("password"):
            return _err("missing_password")
        save_fields = {
            k: v for k, v in fields.items()
            if k in ("username", "email", "password", "notes")
            and v is not None
        }

    try:
        from main import save_secret_tool
        result = save_secret_tool(
            vault_id,
            {
                "service":     svc,
                "secret_type": "login",
                "fields":      save_fields,
            },
            key,
        )
                                                                  
                                                            
        return json.dumps({
            "saved":   True,
            "service": svc,
            "message": str(result or ""),
            "draft_consumed": bool(draft is not None),
        }, ensure_ascii=False)
    except Exception:
        logger.exception("[INSPECT] save tool failed")
        return _err("save_failed")


def _find_in_vault_proxy(*, vault_id, key, query, doc_kind=None, fuzzy_distance=None):


    # 2026-07-25 diagnostic: this is the OpenAI planner's entry into
    # the semantic/vision search. Log with query length only (not the
    # phrase itself) so we can confirm this is the true production
    # path for the "show me naim id" retrieval bug. If this trace
    # appears in prod logs for the naim test, the intent-branch
    # _try_exact_saved_name_early_return probe never got a chance to
    # run and the fix must live earlier in the pipeline.
    print(
        f"[BRAIN-TRACE-DXR] site=find_in_vault_proxy "
        f"vault={(vault_id or '')[:8]} "
        f"query_len={len((query or '').strip())} "
        f"doc_kind={doc_kind or 'none'}",
        flush=True,
    )
    from vault_complete_search import find_in_vault
    return find_in_vault(
        vault_id=vault_id, key=key, query=query,
        doc_kind=doc_kind, fuzzy_distance=fuzzy_distance,
    )


INSPECTION_DISPATCH = {
    "read_file_text":                              read_file_text,
    "read_image_with_vision":                      read_image_with_vision,
    "read_media_transcript":                       read_media_transcript,
    "list_file_chunks":                            list_file_chunks,
    "read_file_chunk":                             read_file_chunk,
    "search_extracted_text":                       search_extracted_text,
    "inspect_uploaded_file":                       inspect_uploaded_file,
    "get_file_metadata":                           get_file_metadata,
    "list_saved_credentials":                      list_saved_credentials,
    "get_credential_metadata":                     get_credential_metadata,
    "find_in_vault":                               _find_in_vault_proxy,
    "generate_credential_draft":                   generate_credential_draft,
    "save_generated_credential_after_confirmation":
        save_generated_credential_after_confirmation,
}


def find_in_vault(*, vault_id, key, query, doc_kind=None, fuzzy_distance=None):
    return _find_in_vault_proxy(
        vault_id=vault_id, key=key, query=query,
        doc_kind=doc_kind, fuzzy_distance=fuzzy_distance,
    )


__all__ = [
    "INSPECTION_DISPATCH",
    "INSPECTION_FUNCTIONS",
    "MAX_TEXT_CHARS_RETURNED",
    "MAX_SEARCH_HITS",
    "MAX_IMAGE_BYTES",
    "MAX_VISION_RESPONSE_CHARS",
    "read_file_text",
    "read_image_with_vision",
    "read_media_transcript",
    "list_file_chunks",
    "read_file_chunk",
    "search_extracted_text",
    "inspect_uploaded_file",
    "get_file_metadata",
    "list_saved_credentials",
    "get_credential_metadata",
    "generate_credential_draft",
    "save_generated_credential_after_confirmation",
    "find_in_vault",
]
