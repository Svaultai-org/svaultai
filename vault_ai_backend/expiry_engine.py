

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

from vault_core import get_db


logger = logging.getLogger(__name__)


ALLOWED_EXPIRY_TYPES: tuple[str, ...] = (
    "passport", "visa", "id_card", "driver_license", "insurance",
    "tax", "contract", "subscription", "custom",
)
ALLOWED_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
ALLOWED_STATUSES: tuple[str, ...] = (
    "active", "dismissed", "expired", "resolved",
)
ALLOWED_SOURCE_KINDS: tuple[str, ...] = (
    "uploaded_file", "vault_item", "memory",
)


WINDOW_SPECS: dict[str, tuple[int, ...]] = {
    "passport":         (365, 180, 90, 30),
    "visa":             (180, 90, 30, 7),
    "id_card":          (180, 90, 30),
    "driver_license":   (180, 90, 30),
    "insurance":        (90, 30, 7),
    "contract":         (120, 60, 30),
    "subscription":     (60, 30, 7),
    "tax":              (90, 30, 7),
    "custom":           (60, 30, 7),
}


DOC_TYPE_TO_EXPIRY: dict[str, str] = {
    "passport":         "passport",
    "visa":             "visa",
    "id_card":          "id_card",
    "driver_license":   "driver_license",
    "insurance":        "insurance",
    "contract":         "contract",
    "agreement":        "contract",
    "tax_document":     "tax",
                                                                
                                            
}


EXPIRY_DATE_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "passport":         ("expiry_date",),
    "visa":             ("expiry_date",),
    "id_card":          ("expiry_date",),
    "driver_license":   ("expiry_date",),
    "insurance":        ("expiry_date",),
    "contract":         ("renewal_date", "expiry_date"),
    "agreement":        ("renewal_date", "expiry_date"),
    "tax_document":     ("due_date",),
}


@dataclass(frozen=True)
class AlertSpec:


    source_kind: str
    source_file_id: Optional[str]                                        
    source_item_id: Optional[int]                                     
    expiry_type: str
    expiry_date: str                                   
    alert_window_days: int
    severity: str                                                 


def is_enabled() -> bool:


    return os.getenv(
        "VAULTAI_EXPIRY_ALERTS_ENABLED", "true",
    ).lower() == "true"


def severity_for_window(window_days: int, windows: tuple[int, ...]) -> str:


    if window_days not in windows:
        raise ValueError(f"window {window_days} not in {windows}")
    if window_days == windows[-1]:
        return "critical"
    if window_days == windows[0]:
        return "info"
    return "warning"


def select_window(days_until: int, windows: tuple[int, ...]) -> Optional[int]:


    if days_until is None or days_until < 0:
        return None
                                                                 
    for w in sorted(windows):
        if days_until <= w:
            return w
    return None


def _parse_iso_date(s) -> Optional[date]:
    if not s:
        return None
    try:
        if isinstance(s, date) and not isinstance(s, datetime):
            return s
        if isinstance(s, datetime):
            return s.date()
        if isinstance(s, str):
            s = s.strip()[:10]
            parts = s.split("-")
            if len(parts) != 3:
                return None
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return date(y, m, d)
    except Exception:
        return None
    return None


def _days_until(iso_date: str) -> Optional[int]:
    d = _parse_iso_date(iso_date)
    if d is None:
        return None
    return (d - date.today()).days


def _load_metadata_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _make_alert_for(
    source_kind: str, source_file_id: Optional[str],
    source_item_id: Optional[int], expiry_type: str,
    expiry_date: str,
) -> Optional[AlertSpec]:


    if expiry_type not in WINDOW_SPECS:
        return None
    days = _days_until(expiry_date)
    if days is None:
        return None
    window = select_window(days, WINDOW_SPECS[expiry_type])
    if window is None:
        return None
    try:
        sev = severity_for_window(window, WINDOW_SPECS[expiry_type])
    except Exception:
        return None
                                        
    pd = _parse_iso_date(expiry_date)
    if pd is None:
        return None
    return AlertSpec(
        source_kind=source_kind,
        source_file_id=source_file_id,
        source_item_id=source_item_id,
        expiry_type=expiry_type,
        expiry_date=pd.isoformat(),
        alert_window_days=window,
        severity=sev,
    )


def detect_passport_expiry(file_id: str, metadata: dict) -> list[AlertSpec]:
    iso = metadata.get("expiry_date")
    spec = _make_alert_for("uploaded_file", file_id, None, "passport", iso) if iso else None
    return [spec] if spec else []


def detect_visa_expiry(file_id: str, metadata: dict) -> list[AlertSpec]:
    iso = metadata.get("expiry_date")
    spec = _make_alert_for("uploaded_file", file_id, None, "visa", iso) if iso else None
    return [spec] if spec else []


def detect_id_expiry(file_id: str, doc_type: str, metadata: dict) -> list[AlertSpec]:


    if doc_type not in ("id_card", "driver_license"):
        return []
    iso = metadata.get("expiry_date")
    spec = _make_alert_for("uploaded_file", file_id, None, doc_type, iso) if iso else None
    return [spec] if spec else []


def detect_insurance_expiry(file_id: str, metadata: dict) -> list[AlertSpec]:
    iso = metadata.get("expiry_date")
    spec = _make_alert_for("uploaded_file", file_id, None, "insurance", iso) if iso else None
    return [spec] if spec else []


def detect_contract_expiry(file_id: str, doc_type: str, metadata: dict) -> list[AlertSpec]:


    if doc_type not in ("contract", "agreement"):
        return []
    iso = metadata.get("renewal_date") or metadata.get("expiry_date")
    spec = _make_alert_for("uploaded_file", file_id, None, "contract", iso) if iso else None
    return [spec] if spec else []


def detect_tax_deadlines(file_id: str, metadata: dict) -> list[AlertSpec]:


    iso = metadata.get("due_date")
    spec = _make_alert_for("uploaded_file", file_id, None, "tax", iso) if iso else None
    return [spec] if spec else []


def detect_memory_dates(
    vault_id: str,
) -> list[AlertSpec]:


    out: list[AlertSpec] = []
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT memory_type, memory_key, event_date
                       FROM vault_ai_memory
                       WHERE vault_id=%s
                         AND superseded_at IS NULL
                         AND event_date IS NOT NULL""",
                    (vault_id,),
                )
                rows = cur.fetchall() or []
        finally:
            conn.close()
        for (_mt, _mk, ed) in rows:
            if ed is None:
                continue
            iso = ed.isoformat() if hasattr(ed, "isoformat") else str(ed)
            spec = _make_alert_for(
                "memory", None, None, "custom", iso,
            )
            if spec:
                out.append(spec)
    except Exception as e:
        logger.warning(
            "detect_memory_dates failed vault=%s: %s",
            vault_id, e,
        )
    return out


def _read_doc_metadata_for_file(
    vault_id: str, file_id: str,
) -> tuple[Optional[str], dict]:


    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT doc_type, metadata_json FROM vault_document_metadata
                       WHERE vault_id=%s
                         AND uploaded_file_id=%s""",
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


def safe_upsert_alert(
    cur, vault_id: str, spec: AlertSpec,
) -> None:


    if spec.source_kind not in ALLOWED_SOURCE_KINDS:
        return
    if spec.expiry_type not in ALLOWED_EXPIRY_TYPES:
        return
    if spec.severity not in ALLOWED_SEVERITIES:
        return
    if spec.alert_window_days <= 0 or spec.alert_window_days > 3650:
        return
                                                                
                                                            
    if spec.source_kind == "uploaded_file":
        if not spec.source_file_id or spec.source_item_id is not None:
            return
    elif spec.source_kind == "vault_item":
        if spec.source_item_id is None or spec.source_file_id is not None:
            return
    else:                        
        if spec.source_file_id is not None or spec.source_item_id is not None:
            return

    if spec.source_kind in ("uploaded_file", "vault_item"):
                                                                          
        conflict = (
            "(vault_id, source_file_id, expiry_type, alert_window_days)"
            if spec.source_kind == "uploaded_file"
            else "(vault_id, source_item_id, expiry_type, alert_window_days)"
        )
    else:
                                                                         
                                      
        conflict = (
            "(vault_id, expiry_type, expiry_date, alert_window_days)"
        )
    cur.execute(
        f"""
        INSERT INTO vault_expiry_alerts
            (vault_id, source_kind, source_file_id, source_item_id,
             expiry_type, expiry_date, alert_window_days, severity, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active')
        ON CONFLICT {conflict}
        DO UPDATE SET
            expiry_date       = EXCLUDED.expiry_date,
            severity          = EXCLUDED.severity,
            status            = 'active',
            updated_at        = NOW()
        """,
        (vault_id, spec.source_kind, spec.source_file_id,
         spec.source_item_id, spec.expiry_type, spec.expiry_date,
         spec.alert_window_days, spec.severity),
    )


def _delete_alerts_for_file(cur, vault_id, file_id) -> None:
    cur.execute(
        """DELETE FROM vault_expiry_alerts
           WHERE vault_id=%s AND source_file_id=%s""",
        (vault_id, file_id),
    )


def _delete_alerts_for_item(cur, vault_id, item_id) -> None:
    cur.execute(
        """DELETE FROM vault_expiry_alerts
           WHERE vault_id=%s AND source_item_id=%s""",
        (vault_id, item_id),
    )


def _delete_alerts_for_kind(cur, vault_id, source_kind) -> None:
    cur.execute(
        """DELETE FROM vault_expiry_alerts
           WHERE vault_id=%s AND source_kind=%s""",
        (vault_id, source_kind),
    )


def build_expiry_alerts_for_file_safe(
    vault_id: str, file_id: str, *, replace: bool = False,
) -> None:


    try:
        if not is_enabled():
            return
        doc_type, metadata = _read_doc_metadata_for_file(vault_id, file_id)
        if not doc_type:
            if replace:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        _delete_alerts_for_file(cur, vault_id, file_id)
                    conn.commit()
                finally:
                    conn.close()
            return
        specs: list[AlertSpec] = []
        if doc_type == "passport":
            specs += detect_passport_expiry(file_id, metadata)
        elif doc_type == "visa":
            specs += detect_visa_expiry(file_id, metadata)
        elif doc_type in ("id_card", "driver_license"):
            specs += detect_id_expiry(file_id, doc_type, metadata)
        elif doc_type == "insurance":
            specs += detect_insurance_expiry(file_id, metadata)
        elif doc_type in ("contract", "agreement"):
            specs += detect_contract_expiry(file_id, doc_type, metadata)
        elif doc_type == "tax_document":
            specs += detect_tax_deadlines(file_id, metadata)
                                                      

        wrote = False
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_alerts_for_file(cur, vault_id, file_id)
                for spec in specs:
                    safe_upsert_alert(cur, vault_id, spec)
            conn.commit()
            wrote = bool(specs) or replace
        finally:
            conn.close()
                                                            
                                                              
        if wrote:
            try:
                from vault_tool_result_cache import invalidate_for_event
                invalidate_for_event(
                    vault_id=vault_id, event="expiry_updated",
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(
            "build_expiry_alerts_for_file_safe failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def build_expiry_alerts_for_item_safe(
    vault_id: str, item_id: int, *, replace: bool = False,
) -> None:


    return


def build_expiry_alerts_for_memory_safe(
    vault_id: str, memory_type: str, memory_key: str,
) -> None:


    try:
        if not is_enabled():
            return
        specs = detect_memory_dates(vault_id)
        conn = get_db()
        try:
            with conn.cursor() as cur:
                _delete_alerts_for_kind(cur, vault_id, "memory")
                for spec in specs:
                    safe_upsert_alert(cur, vault_id, spec)
            conn.commit()
        finally:
            conn.close()
                                                              
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="expiry_updated",
            )
        except Exception:
            pass
    except Exception as e:
        logger.warning(
            "build_expiry_alerts_for_memory_safe failed vault=%s: %s",
            vault_id, e,
        )


def rebuild_expiry_alerts_safe(
    vault_id: str,
) -> None:


    try:
        if not is_enabled():
            return
        all_specs: list[AlertSpec] = []

                                                                  
        try:
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
                if doc_type == "passport":
                    all_specs += detect_passport_expiry(fid, md)
                elif doc_type == "visa":
                    all_specs += detect_visa_expiry(fid, md)
                elif doc_type in ("id_card", "driver_license"):
                    all_specs += detect_id_expiry(fid, doc_type, md)
                elif doc_type == "insurance":
                    all_specs += detect_insurance_expiry(fid, md)
                elif doc_type in ("contract", "agreement"):
                    all_specs += detect_contract_expiry(fid, doc_type, md)
                elif doc_type == "tax_document":
                    all_specs += detect_tax_deadlines(fid, md)
        except Exception as e:
            logger.warning("rebuild: doc walk failed: %s", e)


        all_specs += detect_memory_dates(vault_id)

                          
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM vault_expiry_alerts
                       WHERE vault_id=%s""",
                    (vault_id,),
                )
                for spec in all_specs:
                    safe_upsert_alert(cur, vault_id, spec)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "rebuild_expiry_alerts_safe failed vault=%s: %s",
            vault_id, e,
        )


def fetch_active_alerts(
    vault_id: str,
    *, expiry_type_filter: Optional[str] = None, limit: int = 100,
) -> list[dict]:


    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if expiry_type_filter and expiry_type_filter in ALLOWED_EXPIRY_TYPES:
                    cur.execute(
                        """SELECT id, source_kind, source_file_id, source_item_id,
                                  expiry_type, expiry_date, alert_window_days, severity
                           FROM vault_expiry_alerts
                           WHERE vault_id=%s
                             AND status='active'
                             AND expiry_type=%s
                           ORDER BY CASE severity
                                       WHEN 'critical' THEN 0
                                       WHEN 'warning'  THEN 1
                                       WHEN 'info'     THEN 2
                                       ELSE 3 END,
                                    expiry_date ASC
                           LIMIT %s""",
                        (vault_id, expiry_type_filter, max(1, limit)),
                    )
                else:
                    cur.execute(
                        """SELECT id, source_kind, source_file_id, source_item_id,
                                  expiry_type, expiry_date, alert_window_days, severity
                           FROM vault_expiry_alerts
                           WHERE vault_id=%s
                             AND status='active'
                           ORDER BY CASE severity
                                       WHEN 'critical' THEN 0
                                       WHEN 'warning'  THEN 1
                                       WHEN 'info'     THEN 2
                                       ELSE 3 END,
                                    expiry_date ASC
                           LIMIT %s""",
                        (vault_id, max(1, limit)),
                    )
                out = []
                for row in cur.fetchall() or []:
                    out.append({
                        "id":                row[0],
                        "source_kind":       row[1],
                        "source_file_id":    row[2],
                        "source_item_id":    row[3],
                        "expiry_type":       row[4],
                        "expiry_date":       row[5].isoformat() if row[5] else None,
                        "alert_window_days": row[6],
                        "severity":          row[7],
                    })
                return out
        finally:
            conn.close()
    except Exception as e:
        logger.warning("fetch_active_alerts failed: %s", e)
        return []
