

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from vault_core import get_db


logger = logging.getLogger(__name__)


ALLOWED_ENTITY_TYPES: tuple[str, ...] = (
    "identity", "travel", "government", "finance", "tax", "business",
    "medical", "education", "insurance", "legal", "personal", "other",
)


_DOC_TYPE_OWNER: dict[str, str] = {
    "passport":         "identity",
    "visa":             "travel",
    "id_card":          "identity",
    "driver_license":   "identity",
    "boarding_pass":    "travel",
    "hotel_itinerary":  "travel",
    "ticket":           "personal",
    "invoice":          "finance",
    "receipt":          "finance",
    "contract":         "legal",
    "agreement":        "legal",
    "degree":           "education",
    "certificate":      "education",
    "insurance":        "insurance",
    "tax_document":     "tax",
    "medical_record":   "medical",
}


_ENTITY_MAP: dict[tuple[str, str], str] = {
              
    ("passport", "country"):                 "identity",
    ("passport", "nationality"):             "identity",
    ("passport", "issue_date"):              "identity",
    ("passport", "expiry_date"):             "identity",
    ("passport", "passport_number_last4"):   "identity",

          
    ("visa", "country"):                     "travel",
    ("visa", "expiry_date"):                 "travel",
    ("visa", "entry_type"):                  "travel",
    ("visa", "visa_type"):                   "travel",
    ("visa", "issue_date"):                  "travel",

             
    ("id_card", "country"):                  "identity",
    ("id_card", "id_number_last4"):          "identity",
    ("id_card", "expiry_date"):              "identity",

                    
    ("driver_license", "country"):           "identity",
    ("driver_license", "license_number_last4"): "identity",
    ("driver_license", "license_class"):     "identity",
    ("driver_license", "expiry_date"):       "identity",

                   
    ("boarding_pass", "airline"):            "travel",
    ("boarding_pass", "flight_number"):      "travel",
    ("boarding_pass", "departure_date"):     "travel",
    ("boarding_pass", "origin"):             "travel",
    ("boarding_pass", "destination"):        "travel",

                     
    ("hotel_itinerary", "hotel"):            "travel",
    ("hotel_itinerary", "location"):         "travel",
    ("hotel_itinerary", "check_in"):         "travel",
    ("hotel_itinerary", "check_out"):        "travel",

            
    ("ticket", "vendor"):                    "personal",
    ("ticket", "event_date"):                "personal",
    ("ticket", "location"):                  "personal",

             
    ("invoice", "merchant"):                 "finance",
    ("invoice", "vendor"):                   "finance",
    ("invoice", "invoice_number"):           "finance",
    ("invoice", "amount"):                   "finance",
    ("invoice", "currency"):                 "finance",
    ("invoice", "due_date"):                 "finance",

             
    ("receipt", "merchant"):                 "finance",
    ("receipt", "amount"):                   "finance",
    ("receipt", "currency"):                 "finance",
    ("receipt", "purchase_date"):            "finance",

              
    ("contract", "parties"):                 "legal",
    ("contract", "effective_date"):          "legal",
    ("contract", "renewal_date"):            "legal",
    ("contract", "expiry_date"):             "legal",

               
    ("agreement", "parties"):                "legal",
    ("agreement", "effective_date"):         "legal",
    ("agreement", "expiry_date"):            "legal",

                    
    ("medical_record", "provider"):          "medical",
    ("medical_record", "record_type"):       "medical",
    ("medical_record", "record_date"):       "medical",

            
    ("degree", "institution"):               "education",
    ("degree", "year"):                      "education",
    ("degree", "field"):                     "education",
    ("degree", "graduation_date"):           "education",

                 
    ("certificate", "issuer"):               "education",
    ("certificate", "issue_date"):           "education",
    ("certificate", "expiry_date"):          "education",

               
    ("insurance", "provider"):               "insurance",
    ("insurance", "policy_number_last4"):    "insurance",
    ("insurance", "expiry_date"):            "insurance",

         
    ("tax_document", "country"):             "tax",
    ("tax_document", "tax_year"):            "tax",
    ("tax_document", "form_type"):           "tax",
    ("tax_document", "due_date"):            "tax",
    ("tax_document", "filing_date"):         "tax",
}


@dataclass(frozen=True)
class EntitySpec:

    entity_type: str
    entity_key: str
    entity_value: str
    confidence: float = 1.0


def is_enabled() -> bool:


    return os.getenv(
        "VAULTAI_DOCUMENT_ENTITIES_ENABLED", "true",
    ).lower() == "true"


def _coerce_value(v) -> Optional[str]:


    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    if isinstance(v, list):
        parts = []
        for item in v:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                parts.append(s)
            if len(parts) >= 5:
                break
        joined = " | ".join(parts)
        return joined if joined else None
    return str(v).strip() or None


def _doc_type_entity(doc_type: str) -> Optional[EntitySpec]:


    owner = _DOC_TYPE_OWNER.get(doc_type)
    if not owner:
        return None
    return EntitySpec(
        entity_type=owner,
        entity_key="document_type",
        entity_value=doc_type,
        confidence=1.0,
    )


def _generic_extract(doc_type: str, metadata: dict) -> list[EntitySpec]:


    out: list[EntitySpec] = []
    doc_spec = _doc_type_entity(doc_type)
    if doc_spec:
        out.append(doc_spec)
    if not metadata:
        return out
    for key, raw_value in metadata.items():
        et = _ENTITY_MAP.get((doc_type, key))
        if not et:
            continue
        value = _coerce_value(raw_value)
        if not value:
            continue
        out.append(EntitySpec(
            entity_type=et, entity_key=key, entity_value=value,
        ))
    return out


def extract_passport_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("passport", metadata)


def extract_visa_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("visa", metadata)


def extract_invoice_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("invoice", metadata)


def extract_receipt_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("receipt", metadata)


def extract_contract_entities(metadata: dict) -> list[EntitySpec]:


    return _generic_extract("contract", metadata)


def extract_medical_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("medical_record", metadata)


def extract_education_entities(metadata: dict) -> list[EntitySpec]:

    return _generic_extract("degree", metadata)


def extract_insurance_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("insurance", metadata)


def extract_tax_entities(metadata: dict) -> list[EntitySpec]:
    return _generic_extract("tax_document", metadata)


def extract_document_entities(
    doc_type: Optional[str], metadata: Optional[dict],
) -> list[EntitySpec]:


    if not doc_type or not isinstance(metadata, dict):
        return []
    if doc_type == "passport":
        return extract_passport_entities(metadata)
    if doc_type == "visa":
        return extract_visa_entities(metadata)
    if doc_type == "invoice":
        return extract_invoice_entities(metadata)
    if doc_type == "receipt":
        return extract_receipt_entities(metadata)
    if doc_type == "contract":
        return extract_contract_entities(metadata)
    if doc_type == "agreement":
                                                                  
                                                                     
        return _generic_extract("agreement", metadata)
    if doc_type == "medical_record":
        return extract_medical_entities(metadata)
    if doc_type == "degree":
        return extract_education_entities(metadata)
    if doc_type == "certificate":
        return _generic_extract("certificate", metadata)
    if doc_type == "insurance":
        return extract_insurance_entities(metadata)
    if doc_type == "tax_document":
        return extract_tax_entities(metadata)
                                                              
                                                                   
    if doc_type in _DOC_TYPE_OWNER:
        return _generic_extract(doc_type, metadata)
    return []


def _load_metadata_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _read_doc_metadata_for_file(
    vault_id: str, file_id: str,
) -> tuple[Optional[str], dict]:
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT doc_type, metadata_json FROM vault_document_metadata
                       WHERE vault_id=%s AND uploaded_file_id=%s""",
                    (vault_id, file_id),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return (None, {})
        return (row[0], _load_metadata_json(row[1]))
    except Exception as e:
        logger.warning(
            "_read_doc_metadata_for_file failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )
        return (None, {})


def _delete_entities_for_file(cur, vault_id, file_id) -> None:
    cur.execute(
        """DELETE FROM vault_document_entities
           WHERE vault_id=%s AND source_file_id=%s""",
        (vault_id, file_id),
    )


def safe_upsert_entities(
    vault_id: str, file_id: str,
    specs: Iterable[EntitySpec], *, replace: bool = False,
) -> None:


    try:
        rows = []
        for s in specs:
            if s.entity_type not in ALLOWED_ENTITY_TYPES:
                continue
            if not s.entity_key or not s.entity_value:
                continue
            if len(s.entity_key) > 100 or len(s.entity_value) > 500:
                continue
            if not (0.0 <= float(s.confidence) <= 1.0):
                continue
            rows.append((
                vault_id, file_id,
                s.entity_type, s.entity_key, s.entity_value,
                float(s.confidence),
            ))
        if not rows and not replace:
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_entities_for_file(cur, vault_id, file_id)
                if rows:
                    cur.executemany(
                        """
                        INSERT INTO vault_document_entities
                            (vault_id, source_file_id,
                             entity_type, entity_key, entity_value, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (vault_id, source_file_id,
                                     entity_type, entity_key) DO UPDATE SET
                            entity_value = EXCLUDED.entity_value,
                            confidence   = EXCLUDED.confidence,
                            updated_at   = NOW()
                        """,
                        rows,
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "safe_upsert_entities failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def build_entities_for_file_safe(
    vault_id: str, file_id: str, *, replace: bool = False,
) -> None:


    try:
        if not is_enabled():
            return
        doc_type, metadata = _read_doc_metadata_for_file(
            vault_id, file_id,
        )
        specs = extract_document_entities(doc_type, metadata)
        if not specs and not replace:
            return
        safe_upsert_entities(
            vault_id, file_id, specs, replace=replace,
        )
    except Exception as e:
        logger.warning(
            "build_entities_for_file_safe failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def rebuild_entities_for_vault_safe(
    vault_id: str,
) -> None:


    try:
        if not is_enabled():
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT uploaded_file_id, doc_type, metadata_json
                       FROM vault_document_metadata
                       WHERE vault_id=%s""",
                    (vault_id,),
                )
                rows = cur.fetchall() or []
        finally:
            conn.close()
        for (fid, doc_type, raw) in rows:
            md = _load_metadata_json(raw)
            specs = extract_document_entities(doc_type, md)
                                                                       
                                                         
            safe_upsert_entities(
                vault_id, fid, specs, replace=True,
            )
    except Exception as e:
        logger.warning(
            "rebuild_entities_for_vault_safe failed vault=%s: %s",
            vault_id, e,
        )


def fetch_entities(
    vault_id: str,
    *,
    source_file_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:


    try:
        clauses = ["vault_id=%s"]
        params: list = [vault_id]
        if source_file_id:
            clauses.append("source_file_id=%s")
            params.append(source_file_id)
        if entity_type and entity_type in ALLOWED_ENTITY_TYPES:
            clauses.append("entity_type=%s")
            params.append(entity_type)
        if entity_key:
            clauses.append("entity_key=%s")
            params.append(entity_key)
                                                                  
                                                        
        if doc_type:
            cl = " AND ".join(clauses)
            sql = (
                f"""SELECT id, source_file_id, entity_type, entity_key,
                          entity_value, confidence, created_at, updated_at
                    FROM vault_document_entities
                    WHERE {cl}
                      AND source_file_id IN (
                        SELECT source_file_id FROM vault_document_entities
                        WHERE vault_id=%s
                          AND entity_key='document_type'
                          AND entity_value=%s
                      )
                    ORDER BY source_file_id, entity_type, entity_key
                    LIMIT %s"""
            )
            params2 = list(params) + [vault_id, doc_type, max(1, limit)]
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params2)
                    rows = cur.fetchall() or []
            finally:
                conn.close()
        else:
            cl = " AND ".join(clauses)
            sql = (
                f"""SELECT id, source_file_id, entity_type, entity_key,
                          entity_value, confidence, created_at, updated_at
                    FROM vault_document_entities
                    WHERE {cl}
                    ORDER BY source_file_id, entity_type, entity_key
                    LIMIT %s"""
            )
            params.append(max(1, limit))
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall() or []
            finally:
                conn.close()
        out = []
        for row in rows:
            out.append({
                "id":             row[0],
                "source_file_id": row[1],
                "entity_type":    row[2],
                "entity_key":     row[3],
                "entity_value":   row[4],
                "confidence":     float(row[5] or 1.0),
                "created_at":     row[6],
                "updated_at":     row[7],
            })
        return out
    except Exception as e:
        logger.warning("fetch_entities failed: %s", e)
        return []
