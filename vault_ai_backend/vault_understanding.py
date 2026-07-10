

from __future__ import annotations

import logging
import re
from typing import Optional

                                                             
import vault_document_purpose as vp


logger = logging.getLogger(__name__)


UNDERSTANDING_STATUS_PENDING     = "pending"
UNDERSTANDING_STATUS_PROCESSING  = "processing"
UNDERSTANDING_STATUS_READY       = "ready"
UNDERSTANDING_STATUS_FAILED      = "failed"
UNDERSTANDING_STATUS_STALE       = "stale"
UNDERSTANDING_STATUS_UNSUPPORTED = "unsupported"

UNDERSTANDING_STATUSES: tuple[str, ...] = (
    UNDERSTANDING_STATUS_PENDING,
    UNDERSTANDING_STATUS_PROCESSING,
    UNDERSTANDING_STATUS_READY,
    UNDERSTANDING_STATUS_FAILED,
    UNDERSTANDING_STATUS_STALE,
    UNDERSTANDING_STATUS_UNSUPPORTED,
)

_TERMINAL_UNDERSTANDING_STATUSES = frozenset({
    UNDERSTANDING_STATUS_READY,
    UNDERSTANDING_STATUS_FAILED,
    UNDERSTANDING_STATUS_UNSUPPORTED,
})


CURRENT_ANALYSIS_VERSION = 1


_SCAN_BYTE_CAP = 200_000


_MAX_TERMS = 64
_MAX_TOPICS = 12
_MAX_ENTITIES_PER_FAMILY = 24
_MAX_DATES = 24

                                         
_SAFE_PREVIEW_CAP = 600


_TOPIC_VOCAB: dict[str, tuple[str, ...]] = {
    "travel": (
        "passport", "visa", "boarding pass", "itinerary",
        "departure", "arrival", "airline", "airport",
        "hotel", "reservation", "flight", "train ticket",
    ),
    "finance": (
        "bank statement", "checking account", "routing number",
        "savings account", "wire transfer", "ach",
        "deposit", "withdrawal", "balance", "loan",
        "mortgage", "investment", "401k", "ira",
    ),
    "taxes": (
        "tax year", "internal revenue service", "form 1040",
        "form w-2", "form w2", "form 1099", "form w-4",
        "taxable income", "schedule b", "schedule c",
        "schedule d", "filing status", "tax deduction",
    ),
    "identity": (
        "social security number", "ssn", "passport number",
        "driver license", "driver's license", "national id",
        "date of birth", "place of birth",
    ),
    "legal": (
        "court order", "subpoena", "affidavit",
        "power of attorney", "last will and testament",
        "trust agreement", "settlement agreement", "contract",
        "non-disclosure", "non disclosure", "indemnification",
    ),
    "medical": (
        "patient", "diagnosis", "prescription", "dosage",
        "physician", "medical record", "treatment plan",
        "lab result", "blood work", "x-ray",
    ),
    "insurance": (
        "policy holder", "policy number", "premium",
        "deductible", "coverage", "beneficiary",
        "claim number", "underwriter", "rider",
    ),
    "credentials": (
        "username", "password", "saved login", "credential",
        "api key", "access token", "private key",
        "mnemonic", "seed phrase",
    ),
    "education": (
        "transcript", "degree", "diploma", "certificate",
        "university", "college", "school", "grade point",
        "gpa", "course", "semester",
    ),
    "real_estate": (
        "deed", "mortgage", "lease agreement", "rental agreement",
        "property tax", "title insurance",
    ),
}


_CATEGORY_LABELS = tuple(_TOPIC_VOCAB.keys())


_RAW_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)

                                                                   
_PROPER_NOUN_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
)
_PROPER_NOUN_STOPS = frozenset({
                                
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday", "January", "February", "March",
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
                                                                    
    "Form", "Date", "Name", "Address", "City", "State",
    "Zip", "Page", "Section", "Item", "Total", "Subtotal",
    "Notes", "Phone", "Mobile", "Fax", "Email",
    "Account", "Confidential", "Application", "Reference",
    "Policy", "Claim", "Premium", "Beneficiary", "Witness",
    "Signature", "Declaration", "Department",
                                                
    "Yes", "No", "True", "False", "None", "All",
})


_ISO_DATE_RE = re.compile(
    r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b",
)
_US_DATE_RE = re.compile(
    r"\b(\d{1,2})/(\d{1,2})/(20\d{2}|19\d{2}|\d{2})\b",
)
_MONTH_NAME_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2}|19\d{2})\b",
)


_TRAVEL_DOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "passport":         re.compile(r"(?i)\bpassport\b"),
    "visa":             re.compile(r"(?i)\bvisa\b"),
    "boarding_pass":    re.compile(r"(?i)\bboarding\s+pass\b"),
    "ticket":           re.compile(r"(?i)\b(?:flight|train)\s+ticket\b"),
    "hotel_itinerary":  re.compile(r"(?i)\bhotel\b|\bitinerary\b"),
}


_FINANCIAL_DOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "bank_statement":   re.compile(r"(?i)\bbank\s+statement\b"),
    "tax_return":       re.compile(r"(?i)\btax\s+return\b|\bform\s+1040\b"),
    "w2":               re.compile(r"(?i)\bform\s+w-?2\b"),
    "1099":             re.compile(r"(?i)\bform\s+1099\b"),
    "invoice":          re.compile(r"(?i)\binvoice\b"),
    "receipt":          re.compile(r"(?i)\breceipt\b"),
}


_LEGAL_DOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "contract":         re.compile(r"(?i)\bcontract\s+agreement\b|\bthis\s+agreement\b"),
    "nda":              re.compile(r"(?i)\bnon[\-\s]disclosure\b"),
    "court_order":      re.compile(r"(?i)\bcourt\s+order\b"),
    "affidavit":        re.compile(r"(?i)\baffidavit\b"),
    "power_of_attorney": re.compile(r"(?i)\bpower\s+of\s+attorney\b"),
    "will":             re.compile(r"(?i)\blast\s+will\s+and\s+testament\b"),
}


_IDENTITY_DOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "passport":         re.compile(r"(?i)\bpassport\s+number\b|\bpassport\s+no\.?\b"),
    "ssn":              re.compile(r"(?i)\bsocial\s+security\s+number\b|\bssn\b"),
    "driver_license":   re.compile(r"(?i)\bdriver'?s?\s+license\b|\bdl\s*no\.?\b"),
    "national_id":      re.compile(r"(?i)\bnational\s+id\b"),
}


_RELATIONSHIP_KEYWORDS = (
    "spouse", "husband", "wife", "mother", "father", "son",
    "daughter", "brother", "sister", "aunt", "uncle", "cousin",
    "grandfather", "grandmother", "grandparent", "next of kin",
    "guardian", "beneficiary", "executor",
)


_SECRET_LOOKING_TOKEN_RE = re.compile(
    r"^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:'\",.<>/?\\|`~]{8,64}$"
)


_INLINE_SECRET_PHRASE_RE = re.compile(
    r"(?i)\b("
    r"(?:my\s+|the\s+|a\s+)?"
    r"(?:password|passcode|passphrase|pass[\s\-]?word|"
    r"pin(?:[\s\-]?code)?|"
    r"ssn|social\s+security(?:\s+number)?|"
    r"api[\s\-]?key|access[\s\-]?token|bearer\s+token|"
    r"secret(?:\s+key)?|private[\s\-]?key|"
    r"mnemonic|seed[\s\-]?phrase|"
    r"account\s+(?:number|#|no\.?)|"
    r"routing\s+number|"
    r"credit[\s\-]?card(?:\s+number)?|"
    r"cvv|cvc|security\s+code"
    r")\s+(?:is|are|=|:|equals)\s+\S+"
    r")"
)


_LANGUAGE_BY_EXT: dict[str, str] = {
    "py":    "Python",
    "js":    "JavaScript",
    "ts":    "TypeScript",
    "jsx":   "JavaScript",
    "tsx":   "TypeScript",
    "sh":    "Shell",
    "bash":  "Shell",
    "zsh":   "Shell",
    "fish":  "Shell",
    "rs":    "Rust",
    "go":    "Go",
    "java":  "Java",
    "kt":    "Kotlin",
    "rb":    "Ruby",
    "lua":   "Lua",
    "swift": "Swift",
    "c":     "C",
    "cpp":   "C++",
    "cc":    "C++",
    "h":     "C",
    "hpp":   "C++",
    "css":   "CSS",
    "scss":  "CSS",
    "less":  "CSS",
    "sql":   "SQL",
}


def detect_inner_file_signals(
    text: Optional[str], *, file_name: str = "",
) -> dict:


    safe_name = str(file_name or "").strip()

    base = {
        "path":                  safe_name,
        "size_chars":            0,
        "is_text":               False,
        "purpose":               vp.PURPOSE_UNKNOWN,
        "purpose_label":         "",
        "is_credential_bearing": False,
        "topics":                [],
        "entity_names":          [],
        "language":              _language_for_path(safe_name),
    }
    if not text or not str(text).strip():
        return base

    snippet = str(text)[:_SCAN_BYTE_CAP]
    base["size_chars"] = len(snippet)
    base["is_text"] = True

    try:
        from vault_inventory import _compute_credential_density_metrics
        metrics = _compute_credential_density_metrics(snippet)
        purpose_decision = vp.classify_document_purpose(
            snippet, metrics=metrics,
        )
    except Exception:
                                                             
                                                        
        return base

    purpose = purpose_decision.get("purpose") or vp.PURPOSE_UNKNOWN
    base["purpose"] = purpose
    base["purpose_label"] = (
        purpose_decision.get("purpose_label") or ""
    )
    base["is_credential_bearing"] = purpose in (
        vp.PURPOSE_SAVED_LOGIN_LIST,
        vp.PURPOSE_CREDENTIAL_EXPORT,
        vp.PURPOSE_CONFIG_SECRETS,
    )

    low = snippet.lower()
    base["topics"] = _detect_topics(low)

                                                                 
    ents = _detect_entities(snippet)
    names = ents.get("names") if isinstance(ents, dict) else []
    safe_names: list[str] = []
    for n in (names or []):
        if not isinstance(n, str):
            continue
        if _SECRET_LOOKING_TOKEN_RE.match(n):
            continue
        safe_names.append(n)
    base["entity_names"] = safe_names[:24]

    return base


def _language_for_path(path: str) -> Optional[str]:
    if not path:
        return None
    low = path.strip().lower()
    dot = low.rfind(".")
    if dot <= 0 or dot >= len(low) - 1:
        return None
    ext = low[dot + 1:]
    return _LANGUAGE_BY_EXT.get(ext)


def build_understanding(
    text: Optional[str],
    *,
    metrics: Optional[dict] = None,
    purpose_decision: Optional[dict] = None,
    file_name: Optional[str] = None,
    content_type: Optional[str] = None,
    archive_signals: Optional[dict] = None,
) -> dict:


    if metrics is None:
                                                             
                                                                 
        from vault_inventory import _compute_credential_density_metrics
        metrics = _compute_credential_density_metrics(text)
    if purpose_decision is None:
        purpose_decision = vp.classify_document_purpose(
            text, metrics=metrics,
        )

    if not text or not text.strip():
        return _record(
            status=UNDERSTANDING_STATUS_UNSUPPORTED,
            purpose_decision=purpose_decision,
            summary="",
            safe_preview="",
            topics=[],
            entities={},
            dates=[],
            categories=[],
            credential_signals={},
            travel_signals={},
            financial_signals={},
            legal_signals={},
            identity_signals={},
            relationship_signals={},
            searchable_terms=[],
            confidence={"purpose": 0.0},
            archive_signals=archive_signals or {},
        )

    snippet = text[:_SCAN_BYTE_CAP]
    low = snippet.lower()

    purpose = purpose_decision.get("purpose") or vp.PURPOSE_UNKNOWN

    topics = _detect_topics(low)
    entities = _detect_entities(snippet)
    dates = _detect_dates(snippet)
    categories = _detect_categories(topics, purpose)

    credential_signals = _credential_signals(metrics, purpose)
    travel_signals = _travel_signals(snippet)
    financial_signals = _financial_signals(snippet)
    legal_signals = _legal_signals(snippet)
    identity_signals = _identity_signals(snippet)
    relationship_signals = _relationship_signals(snippet)

    searchable_terms = _build_searchable_terms(
        topics=topics,
        entities=entities,
        categories=categories,
        purpose=purpose,
        file_name=file_name,
    )

    summary = _build_summary(
        purpose_decision=purpose_decision,
        metrics=metrics,
        topics=topics,
        entities=entities,
        file_name=file_name,
    )

    safe_preview = _build_safe_preview(snippet, purpose=purpose)

    confidence = {
        "purpose":   float(purpose_decision.get("confidence") or 0.0),
        "topics":    1.0 if topics else 0.0,
        "entities":  1.0 if entities else 0.0,
        "dates":     1.0 if dates else 0.0,
    }

    return _record(
        status=UNDERSTANDING_STATUS_READY,
        purpose_decision=purpose_decision,
        summary=summary,
        safe_preview=safe_preview,
        topics=topics,
        entities=entities,
        dates=dates,
        categories=categories,
        credential_signals=credential_signals,
        travel_signals=travel_signals,
        financial_signals=financial_signals,
        legal_signals=legal_signals,
        identity_signals=identity_signals,
        relationship_signals=relationship_signals,
        searchable_terms=searchable_terms,
        confidence=confidence,
        archive_signals=archive_signals or {},
    )


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def upsert_understanding(
    *,
    vault_id: str,
    file_id: str,
    record: dict,
    source_text_version: int = 0,
    summary_encrypted: Optional[str] = None,
    safe_preview_encrypted: Optional[str] = None,
) -> None:


    from psycopg2.extras import RealDictCursor
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO vault_file_understanding (
                vault_id, file_id,
                source_text_version, analysis_version,
                status,
                document_purpose, purpose_label, purpose_confidence,
                summary_encrypted, summary_is_encrypted,
                safe_preview_encrypted, safe_preview_is_encrypted,
                topics_jsonb,
                entities_jsonb,
                dates_jsonb,
                detected_categories_jsonb,
                credential_signals_jsonb,
                travel_signals_jsonb,
                financial_signals_jsonb,
                legal_signals_jsonb,
                identity_signals_jsonb,
                relationship_signals_jsonb,
                searchable_terms_jsonb,
                confidence_jsonb,
                archive_signals_jsonb,
                last_error,
                created_at, updated_at
            ) VALUES (
                %s, %s,
                %s, %s,
                %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb,
                NULL,
                %s, %s
            )
            ON CONFLICT (vault_id, file_id) DO UPDATE SET
                source_text_version       = EXCLUDED.source_text_version,
                analysis_version          = EXCLUDED.analysis_version,
                status                    = EXCLUDED.status,
                document_purpose          = EXCLUDED.document_purpose,
                purpose_label             = EXCLUDED.purpose_label,
                purpose_confidence        = EXCLUDED.purpose_confidence,
                summary_encrypted         = EXCLUDED.summary_encrypted,
                summary_is_encrypted      = EXCLUDED.summary_is_encrypted,
                safe_preview_encrypted    = EXCLUDED.safe_preview_encrypted,
                safe_preview_is_encrypted = EXCLUDED.safe_preview_is_encrypted,
                topics_jsonb              = EXCLUDED.topics_jsonb,
                entities_jsonb            = EXCLUDED.entities_jsonb,
                dates_jsonb               = EXCLUDED.dates_jsonb,
                detected_categories_jsonb = EXCLUDED.detected_categories_jsonb,
                credential_signals_jsonb  = EXCLUDED.credential_signals_jsonb,
                travel_signals_jsonb      = EXCLUDED.travel_signals_jsonb,
                financial_signals_jsonb   = EXCLUDED.financial_signals_jsonb,
                legal_signals_jsonb       = EXCLUDED.legal_signals_jsonb,
                identity_signals_jsonb    = EXCLUDED.identity_signals_jsonb,
                relationship_signals_jsonb = EXCLUDED.relationship_signals_jsonb,
                searchable_terms_jsonb    = EXCLUDED.searchable_terms_jsonb,
                confidence_jsonb          = EXCLUDED.confidence_jsonb,
                archive_signals_jsonb     = EXCLUDED.archive_signals_jsonb,
                last_error                = NULL,
                updated_at                = EXCLUDED.updated_at
            """,
            (
                vault_id, file_id,
                int(source_text_version),
                int(record.get("analysis_version") or CURRENT_ANALYSIS_VERSION),
                normalize_understanding_status(record.get("status")),
                record.get("document_purpose"),
                record.get("purpose_label") or None,
                float(record.get("purpose_confidence") or 0.0),
                summary_encrypted,
                bool(summary_encrypted is not None),
                safe_preview_encrypted,
                bool(safe_preview_encrypted is not None),
                _json_dump(record.get("topics") or []),
                _json_dump(record.get("entities") or {}),
                _json_dump(record.get("dates") or []),
                _json_dump(record.get("detected_categories") or []),
                _json_dump(record.get("credential_signals") or {}),
                _json_dump(record.get("travel_signals") or {}),
                _json_dump(record.get("financial_signals") or {}),
                _json_dump(record.get("legal_signals") or {}),
                _json_dump(record.get("identity_signals") or {}),
                _json_dump(record.get("relationship_signals") or {}),
                _json_dump(record.get("searchable_terms") or []),
                _json_dump(record.get("confidence") or {}),
                _json_dump(record.get("archive_signals") or {}),
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_understanding_failed(
    *, vault_id: str, file_id: str, error: str,
) -> None:


    from datetime import datetime, timezone

    try:
        import vault_analysis as va
        scrubbed = va._truncate_error(error)
    except Exception:
        scrubbed = (error or "")[:500]
    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_file_understanding (
                vault_id, file_id, status, last_error,
                created_at, updated_at
            ) VALUES (%s, %s, 'failed', %s, %s, %s)
            ON CONFLICT (vault_id, file_id) DO UPDATE SET
                status     = 'failed',
                last_error = EXCLUDED.last_error,
                updated_at = EXCLUDED.updated_at
            """,
            (vault_id, file_id, scrubbed, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def mark_stale_understandings_for_changed_text(
    vault_id: str,
    *,
    file_id: Optional[str] = None,
    current_analysis_version: Optional[int] = None,
) -> dict:


    from datetime import datetime, timezone

    target_version = (
        int(current_analysis_version)
        if current_analysis_version is not None
        else CURRENT_ANALYSIS_VERSION
    )
    now = datetime.now(timezone.utc)

    where_extra = ""
    params: list = [target_version, vault_id]
    if file_id is not None:
        where_extra = " AND v.file_id = %s"
        params.append(file_id)

    stale_file_ids: list[str] = []
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE vault_file_understanding AS v
            SET    status     = 'stale',
                   updated_at = %s
            FROM   uploaded_files AS u
            WHERE  u.id = v.file_id::text
              AND  u.vault_id = v.vault_id
              AND  v.vault_id = %s
              AND  v.status IN ('pending', 'ready', 'stale')
              AND  (
                    COALESCE(v.source_text_version, 0)
                      < COALESCE(u.extracted_text_version, 0)
                 OR COALESCE(v.analysis_version, 0)
                      < %s
                  )
                  {where_extra}
            RETURNING v.file_id
            """,
            tuple([now, vault_id, target_version] + (
                [file_id] if file_id is not None else []
            )),
        )
        rows = cur.fetchall() or []
        for row in rows:
            stale_file_ids.append(str(row[0]))
        conn.commit()
    finally:
        conn.close()

                                                                
    jobs_enqueued = 0
    if stale_file_ids:
        try:
            import vault_analysis as va
            for fid in stale_file_ids:
                try:
                    job_id = va.enqueue_analysis_job(
                        vault_id=vault_id,
                        file_id=fid,
                        stage=va.STAGE_FILE_UNDERSTANDING,
                    )
                    if job_id:
                        jobs_enqueued += 1
                except Exception:
                                                                     
                                                                  
                    logger.exception(
                        "[stale-understandings] enqueue failed "
                        "vault=%s file=%s",
                        vault_id, fid,
                    )
        except Exception:
            logger.exception(
                "[stale-understandings] vault_analysis import failed "
                "vault=%s", vault_id,
            )

    return {
        "vault_id":      vault_id,
        "stale_marked":  len(stale_file_ids),
        "jobs_enqueued": jobs_enqueued,
        "file_ids":      stale_file_ids,
        "ran_at":        now.isoformat(),
    }


def mark_stale_embeddings_for_changed_text(
    vault_id: str,
    *,
    file_id: Optional[str] = None,
    current_analysis_version: Optional[int] = None,
    current_model: Optional[str] = None,
) -> dict:


    from datetime import datetime, timezone

                                                
    try:
        import vault_embedding as ve
    except Exception:
                                                                  
                                                               
        return {
            "vault_id":      vault_id,
            "stale_marked":  0,
            "jobs_enqueued": 0,
            "file_ids":      [],
            "ran_at":        datetime.now(timezone.utc).isoformat(),
        }

    target_version = (
        int(current_analysis_version)
        if current_analysis_version is not None
        else ve.CURRENT_EMBEDDING_ANALYSIS_VERSION
    )
    target_model = current_model or ve.EMBEDDING_MODEL_DEFAULT
    now = datetime.now(timezone.utc)

    where_extra = ""
    params: list = [now, vault_id, target_version, target_model]
    if file_id is not None:
        where_extra = " AND e.file_id = %s"
        params.append(file_id)

    stale_file_ids: list[str] = []
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE vault_file_embeddings AS e
            SET    status     = 'stale',
                   updated_at = %s
            FROM   uploaded_files AS u
            WHERE  u.id = e.file_id::text
              AND  u.vault_id = e.vault_id
              AND  e.vault_id = %s
              AND  e.status IN ('pending', 'ready', 'stale')
              AND  (
                    COALESCE(e.source_text_version, 0)
                      < COALESCE(u.extracted_text_version, 0)
                 OR COALESCE(e.analysis_version, 0)
                      < %s
                 OR COALESCE(e.embedding_model, '')
                      <> %s
                  )
                  {where_extra}
            RETURNING e.file_id
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []
        for row in rows:
            stale_file_ids.append(str(row[0]))
        conn.commit()
    finally:
        conn.close()

    jobs_enqueued = 0
    if stale_file_ids:
        try:
            import vault_analysis as va
            for fid in stale_file_ids:
                try:
                    job_id = va.enqueue_analysis_job(
                        vault_id=vault_id,
                        file_id=fid,
                        stage=va.STAGE_FILE_EMBEDDING,
                    )
                    if job_id:
                        jobs_enqueued += 1
                except Exception:
                    logger.exception(
                        "[stale-embeddings] enqueue failed "
                        "vault=%s file=%s",
                        vault_id, fid,
                    )
        except Exception:
            logger.exception(
                "[stale-embeddings] vault_analysis import failed "
                "vault=%s", vault_id,
            )

    return {
        "vault_id":      vault_id,
        "stale_marked":  len(stale_file_ids),
        "jobs_enqueued": jobs_enqueued,
        "file_ids":      stale_file_ids,
        "ran_at":        now.isoformat(),
    }


def backfill_archive_signals(vault_id: str) -> dict:


    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result = {
        "vault_id":                    vault_id,
        "matched_archives":            0,
        "marked_stale":                0,
        "archive_jobs_enqueued":       0,
        "skipped_processing":          0,
        "skipped_already_has_signals": 0,
        "ran_at":                      now.isoformat(),
    }

                                                              
    candidates: list[tuple] = []
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id::text AS file_id,
                   v.status AS understanding_status,
                   v.archive_signals_jsonb
            FROM uploaded_files u
            LEFT JOIN vault_file_understanding v
              ON v.vault_id = u.vault_id
             AND v.file_id::text = u.id
            WHERE u.vault_id = %s
              AND u.upload_status = 'complete'
              AND (
                u.extracted_text_source = 'archive_index'
                OR LOWER(u.file_name) ~
                   '\\.(zip|tar|tgz)$'
                OR LOWER(u.file_name) LIKE '%%.tar.gz'
              )
            """,
            (vault_id,),
        )
        candidates = list(cur.fetchall() or [])
    finally:
        conn.close()

    result["matched_archives"] = len(candidates)

    for row in candidates:
        file_id, understanding_status, archive_signals = (
            row[0], row[1], row[2],
        )
        status = (
            str(understanding_status or "").strip().lower()
        )

                                                           
        if status == UNDERSTANDING_STATUS_PROCESSING:
            result["skipped_processing"] += 1
            continue

                                                        
        if _archive_signals_already_populated(archive_signals):
            result["skipped_already_has_signals"] += 1
            continue

                                                            
        if status in (
            UNDERSTANDING_STATUS_READY,
            UNDERSTANDING_STATUS_PENDING,
            UNDERSTANDING_STATUS_STALE,
        ):
            try:
                _mark_understanding_stale_direct(
                    vault_id=vault_id, file_id=file_id, now=now,
                )
                result["marked_stale"] += 1
            except Exception:
                logger.exception(
                    "[backfill-archive] direct stale mark failed "
                    "vault=%s file=%s", vault_id, file_id,
                )

                                                   
        try:
            import vault_analysis as va
            job_id = va.enqueue_analysis_job(
                vault_id=vault_id,
                file_id=file_id,
                stage=va.STAGE_ARCHIVE_INDEXING,
            )
            if job_id:
                result["archive_jobs_enqueued"] += 1
        except Exception:
            logger.exception(
                "[backfill-archive] enqueue failed "
                "vault=%s file=%s", vault_id, file_id,
            )

    return result


def _archive_signals_already_populated(archive_signals) -> bool:


    if archive_signals is None:
        return False
    if isinstance(archive_signals, str):
        try:
            import json
            archive_signals = json.loads(archive_signals)
        except Exception:
            return False
    if not isinstance(archive_signals, dict):
        return False
    inner = archive_signals.get("inner_files")
    return isinstance(inner, list) and len(inner) > 0


def _mark_understanding_stale_direct(
    *, vault_id: str, file_id: str, now,
) -> None:


    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_file_understanding
            SET    status     = 'stale',
                   updated_at = %s
            WHERE  vault_id = %s
              AND  file_id  = %s
              AND  status IN ('pending', 'ready', 'stale')
            """,
            (now, vault_id, file_id),
        )
        conn.commit()
    finally:
        conn.close()


def stale_understanding_count_for_vault(vault_id: str) -> int:


    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)::INT
            FROM vault_file_understanding
            WHERE vault_id = %s
              AND status = %s
            """,
            (vault_id, UNDERSTANDING_STATUS_STALE),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        conn.close()


def get_understanding_for_file(
    vault_id: str, file_id: str,
) -> Optional[dict]:


    from psycopg2.extras import RealDictCursor

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT understanding_id, vault_id, file_id,
                   source_text_version, analysis_version, status,
                   document_purpose, purpose_label, purpose_confidence,
                   summary_encrypted, safe_preview_encrypted,
                   topics_jsonb, entities_jsonb, dates_jsonb,
                   detected_categories_jsonb,
                   credential_signals_jsonb, travel_signals_jsonb,
                   financial_signals_jsonb, legal_signals_jsonb,
                   identity_signals_jsonb, relationship_signals_jsonb,
                   searchable_terms_jsonb, confidence_jsonb,
                   archive_signals_jsonb,
                   last_error, created_at, updated_at
            FROM vault_file_understanding
            WHERE vault_id = %s AND file_id = %s
            LIMIT 1
            """,
            (vault_id, file_id),
        )
        return cur.fetchone()
    finally:
        conn.close()


def coverage_for_vault(vault_id: str) -> dict:


    from psycopg2.extras import RealDictCursor

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT COUNT(*)::INT AS n
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
            """,
            (vault_id,),
        )
        total = int(cur.fetchone()["n"] or 0)

        cur.execute(
            """
            SELECT status, COUNT(*)::INT AS n
            FROM vault_file_understanding
            WHERE vault_id = %s
            GROUP BY status
            """,
            (vault_id,),
        )
        understanding_counts = {
            row["status"]: int(row["n"] or 0) for row in cur.fetchall()
        }

                                                                   
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE LOWER(file_name) ~
                          '\\.(jpg|jpeg|png|gif|webp|heic|tiff|bmp)$'
                      AND (extracted_text_status IS NULL
                           OR extracted_text_status <> 'available')
                )::INT AS image_count,
                COUNT(*) FILTER (
                    WHERE LOWER(file_name) ~
                          '\\.(mp3|m4a|wav|ogg|flac|aac|mp4|mov|avi|mkv|webm|m4v)$'
                      AND (extracted_text_status IS NULL
                           OR extracted_text_status <> 'available')
                )::INT AS av_count,
                COUNT(*) FILTER (
                    WHERE extracted_text_status = 'available'
                )::INT AS extracted_count,
                COUNT(*) FILTER (
                    WHERE analysis_status = 'unsupported'
                )::INT AS unsupported_count
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
            """,
            (vault_id,),
        )
        type_counts = cur.fetchone() or {}
    finally:
        conn.close()

    files_understood = int(understanding_counts.get(
        UNDERSTANDING_STATUS_READY, 0
    ))
    files_stale = int(understanding_counts.get(
        UNDERSTANDING_STATUS_STALE, 0
    ))
    files_pending = (
        int(understanding_counts.get(
            UNDERSTANDING_STATUS_PENDING, 0
        ))
        + int(understanding_counts.get(
            UNDERSTANDING_STATUS_PROCESSING, 0
        ))
        + files_stale
    )

    extracted = int(type_counts.get("extracted_count") or 0)
                                                               
                                        
    text_only = max(0, extracted - files_understood - files_pending)

    return {
        "total_files":          total,
        "files_understood":     files_understood,
        "files_pending":        files_pending,
                                                                      
                                                               
        "files_being_refreshed": files_stale,
        "files_text_only":      text_only,
        "files_needing_ocr":    int(type_counts.get("image_count") or 0),
        "files_needing_transcription": int(type_counts.get("av_count") or 0),
        "files_unsupported":    int(type_counts.get("unsupported_count") or 0),
    }


def format_coverage_for_chat(coverage: dict) -> str:


    total = int(coverage.get("total_files") or 0)
    understood = int(coverage.get("files_understood") or 0)
    pending = int(coverage.get("files_pending") or 0)
    being_refreshed = int(coverage.get("files_being_refreshed") or 0)
    text_only = int(coverage.get("files_text_only") or 0)
    needing_ocr = int(coverage.get("files_needing_ocr") or 0)
    needing_transcription = int(
        coverage.get("files_needing_transcription") or 0
    )
    unsupported = int(coverage.get("files_unsupported") or 0)

    if total == 0:
        return "I haven't analyzed any files yet — your vault is empty."

                                                                
    truly_pending = max(0, pending - being_refreshed)

    leading = f"I have analyzed {understood} of {total} files."
    bits: list[str] = []
    if truly_pending:
        bits.append(f"{truly_pending} pending")
    if being_refreshed:
        bits.append(
            f"{being_refreshed} being re-analyzed"
        )
    if text_only:
        bits.append(f"{text_only} text-extracted but not yet understood")
    if needing_ocr or needing_transcription:
        ocr_av = needing_ocr + needing_transcription
        bits.append(
            f"{ocr_av} still need OCR/transcription"
        )
    if unsupported:
        bits.append(f"{unsupported} unsupported (e.g. archives)")
    if bits:
        return leading + " " + ", ".join(bits) + "."
    return leading


def normalize_understanding_status(status: Optional[str]) -> str:
    if status is None:
        return UNDERSTANDING_STATUS_PENDING
    candidate = str(status).strip().lower()
    if candidate in UNDERSTANDING_STATUSES:
        return candidate
    return UNDERSTANDING_STATUS_PENDING


def is_terminal_understanding_status(status: Optional[str]) -> bool:
    return normalize_understanding_status(status) in _TERMINAL_UNDERSTANDING_STATUSES


def _detect_topics(low_text: str) -> list[str]:
    out: list[str] = []
    for topic, keywords in _TOPIC_VOCAB.items():
        if any(kw in low_text for kw in keywords):
            out.append(topic)
        if len(out) >= _MAX_TOPICS:
            break
    return out


def _detect_categories(topics: list[str], purpose: str) -> list[str]:


    cats: list[str] = []
    if "travel" in topics:
        cats.append("travel")
    if "finance" in topics or "taxes" in topics:
        cats.append("finance")
    if "taxes" in topics:
        cats.append("tax")
    if "legal" in topics:
        cats.append("legal")
    if "medical" in topics:
        cats.append("medical")
    if "education" in topics:
        cats.append("education")
    if "insurance" in topics:
        cats.append("insurance")
    if "identity" in topics:
        cats.append("identity")
    if "credentials" in topics or purpose in (
        vp.PURPOSE_SAVED_LOGIN_LIST,
        vp.PURPOSE_CREDENTIAL_EXPORT,
        vp.PURPOSE_CONFIG_SECRETS,
    ):
        cats.append("security")
    if "real_estate" in topics:
        cats.append("real_estate")
                              
    seen: set[str] = set()
    out: list[str] = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _detect_entities(text: str) -> dict:


    email_domains: dict[str, int] = {}
    email_count = 0
    for m in _RAW_EMAIL_RE.finditer(text):
        email_count += 1
        addr = m.group(0)
        at = addr.rfind("@")
        if at >= 0 and at < len(addr) - 1:
            dom = addr[at + 1:].lower()
            email_domains[dom] = email_domains.get(dom, 0) + 1
        if email_count >= 10_000:
            break

                                                                  
    names: dict[str, int] = {}
    for m in _PROPER_NOUN_RE.finditer(text):
        candidate = m.group(0)
                                                                
                              
        words = candidate.split(" ")
        if not words:
            continue
        first = words[0]
        if candidate in _PROPER_NOUN_STOPS:
            continue
        if first in _PROPER_NOUN_STOPS:
            continue
                                 
        names[candidate] = names.get(candidate, 0) + 1
                                                                 
                                                                   
        if len(words) >= 3 and words[1] not in _PROPER_NOUN_STOPS:
            prefix2 = " ".join(words[:2])
            names[prefix2] = names.get(prefix2, 0) + 1
        if len(names) >= _MAX_ENTITIES_PER_FAMILY * 4:
            break

                                     
    top_names = [
        n for n, _ in sorted(
            names.items(), key=lambda kv: -kv[1]
        )[:_MAX_ENTITIES_PER_FAMILY]
    ]
    top_domains = [
        d for d, _ in sorted(
            email_domains.items(), key=lambda kv: -kv[1]
        )[:_MAX_ENTITIES_PER_FAMILY]
    ]
    return {
        "names":         top_names,
        "email_count":   email_count,
        "email_domains": top_domains,
    }


def _detect_dates(text: str) -> list[str]:


    seen: set[str] = set()
    out: list[str] = []
    for m in _ISO_DATE_RE.finditer(text):
        iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if iso not in seen:
            seen.add(iso)
            out.append(iso)
            if len(out) >= _MAX_DATES:
                return out
    for m in _US_DATE_RE.finditer(text):
        mm = int(m.group(1))
        dd = int(m.group(2))
        year = m.group(3)
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            continue
        if len(year) == 2:
            year = "20" + year
        iso = f"{int(year):04d}-{mm:02d}-{dd:02d}"
        if iso not in seen:
            seen.add(iso)
            out.append(iso)
            if len(out) >= _MAX_DATES:
                return out
    _MONTHS = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }
    for m in _MONTH_NAME_DATE_RE.finditer(text):
        mm = _MONTHS.get(m.group(1), 0)
        dd = int(m.group(2))
        year = int(m.group(3))
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            continue
        iso = f"{year:04d}-{mm:02d}-{dd:02d}"
        if iso not in seen:
            seen.add(iso)
            out.append(iso)
            if len(out) >= _MAX_DATES:
                return out
    return out


def _credential_signals(metrics: dict, purpose: str) -> dict:

    if not metrics:
        return {}
    return {
        "is_credential_bearing":   purpose in (
            vp.PURPOSE_SAVED_LOGIN_LIST,
            vp.PURPOSE_CREDENTIAL_EXPORT,
            vp.PURPOSE_CONFIG_SECRETS,
        ),
        "credential_block_count":  int(metrics.get("credential_block_count") or 0),
        "service_count":           int(metrics.get("service_count") or 0),
        "credential_density":      float(metrics.get("credential_density") or 0.0),
        "mostly_credentials":      bool(metrics.get("mostly_credentials") or False),
        "credential_like_lines":   int(metrics.get("credential_like_lines") or 0),
        "meaningful_lines":        int(metrics.get("meaningful_lines") or 0),
    }


def _travel_signals(text: str) -> dict:
    return _doc_type_signal_bag(_TRAVEL_DOC_PATTERNS, text)


def _financial_signals(text: str) -> dict:
    return _doc_type_signal_bag(_FINANCIAL_DOC_PATTERNS, text)


def _legal_signals(text: str) -> dict:
    return _doc_type_signal_bag(_LEGAL_DOC_PATTERNS, text)


def _identity_signals(text: str) -> dict:
    return _doc_type_signal_bag(_IDENTITY_DOC_PATTERNS, text)


def _doc_type_signal_bag(
    patterns: dict, text: str,
) -> dict:
    hits: dict[str, bool] = {}
    found_any = False
    for key, pat in patterns.items():
        if pat.search(text):
            hits[key] = True
            found_any = True
    return {
        "doc_types": sorted(hits.keys()),
        "any_present": bool(found_any),
    }


def _relationship_signals(text: str) -> dict:
    low = text.lower()
    found = [kw for kw in _RELATIONSHIP_KEYWORDS if kw in low]
    return {
        "kinship_terms": sorted(set(found)),
        "any_present":   bool(found),
    }


def _build_searchable_terms(
    *,
    topics: list[str],
    entities: dict,
    categories: list[str],
    purpose: str,
    file_name: Optional[str],
) -> list[str]:


    bag: dict[str, None] = {}

    def _add(token: Optional[str]) -> None:
        if not token:
            return
        t = str(token).strip()
        if not t:
            return
        if _SECRET_LOOKING_TOKEN_RE.match(t):
            return
        low = t.lower()
        bag[low] = None

    for t in topics:
        _add(t)
    for c in categories:
        _add(c)

    if isinstance(entities, dict):
        for n in entities.get("names") or []:
            _add(n)
        for d in entities.get("email_domains") or []:
            _add(d)

    if purpose:
        _add(purpose)

    if file_name:
        base = file_name.rsplit(".", 1)[0]
                                                                    
        for tok in re.split(r"[^A-Za-z0-9]+", base or ""):
            if tok and not tok.isdigit():
                _add(tok)

                                    
    return list(bag.keys())[:_MAX_TERMS]


def _build_summary(
    *,
    purpose_decision: dict,
    metrics: dict,
    topics: list[str],
    entities: dict,
    file_name: Optional[str],
) -> str:


    purpose = purpose_decision.get("purpose") or vp.PURPOSE_UNKNOWN
    purpose_label = purpose_decision.get("purpose_label") or ""
    fname = (file_name or "this file").strip() or "this file"

    if purpose == vp.PURPOSE_SAVED_LOGIN_LIST:
        blocks = int(metrics.get("credential_block_count") or 0)
        return (
            f"{fname} appears to be {purpose_label}. "
            f"Approximately {blocks} repeated credential record"
            f"{'s' if blocks != 1 else ''} detected."
        )
    if purpose == vp.PURPOSE_CREDENTIAL_EXPORT:
        return (
            f"{fname} appears to be a password-manager export. "
            "Credential values are deliberately not surfaced in "
            "this summary."
        )
    if purpose == vp.PURPOSE_CONFIG_SECRETS:
        return (
            f"{fname} appears to be a configuration / secrets "
            "file. API key / token / password labels detected; "
            "values not surfaced."
        )
    if purpose == vp.PURPOSE_APPLICATION_FORM:
        return f"{fname} appears to be an application form."
    if purpose == vp.PURPOSE_INSURANCE_FORM:
        return f"{fname} appears to be an insurance form."
    if purpose == vp.PURPOSE_GOVERNMENT_LEGAL:
        return (
            f"{fname} appears to be a government, legal, or "
            "financial document."
        )
    if topics:
        topic_words = ", ".join(topics[:3])
        return f"{fname} mentions: {topic_words}."
    return f"{fname} appears to be a general text document."


def _build_safe_preview(text: str, *, purpose: str) -> str:


    if purpose in (
        vp.PURPOSE_SAVED_LOGIN_LIST,
        vp.PURPOSE_CREDENTIAL_EXPORT,
        vp.PURPOSE_CONFIG_SECRETS,
    ):
        return "[credential records — values withheld]"

    out_lines: list[str] = []
    used = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
                                                                
                                      
        if _SECRET_LOOKING_TOKEN_RE.match(stripped):
            continue
                                                           
                                                              
        if _INLINE_SECRET_PHRASE_RE.search(stripped):
            continue
        out_lines.append(stripped)
        used += len(stripped) + 1
        if used >= _SAFE_PREVIEW_CAP:
            break
    preview = "\n".join(out_lines)[:_SAFE_PREVIEW_CAP]
    return preview


def _record(
    *,
    status: str,
    purpose_decision: dict,
    summary: str,
    safe_preview: str,
    topics: list,
    entities: dict,
    dates: list,
    categories: list,
    credential_signals: dict,
    travel_signals: dict,
    financial_signals: dict,
    legal_signals: dict,
    identity_signals: dict,
    relationship_signals: dict,
    searchable_terms: list,
    confidence: dict,
    archive_signals: Optional[dict] = None,
) -> dict:
    return {
        "status":               status,
        "analysis_version":     CURRENT_ANALYSIS_VERSION,
        "document_purpose":     purpose_decision.get("purpose") or vp.PURPOSE_UNKNOWN,
        "purpose_label":        purpose_decision.get("purpose_label") or "",
        "purpose_confidence":   float(purpose_decision.get("confidence") or 0.0),
        "summary":              summary,
        "safe_preview":         safe_preview,
        "topics":               topics,
        "entities":             entities,
        "dates":                dates,
        "detected_categories":  categories,
        "credential_signals":   credential_signals,
        "travel_signals":       travel_signals,
        "financial_signals":    financial_signals,
        "legal_signals":        legal_signals,
        "identity_signals":     identity_signals,
        "relationship_signals": relationship_signals,
        "searchable_terms":     searchable_terms,
        "confidence":           confidence,
        "archive_signals":      archive_signals or {},
    }
