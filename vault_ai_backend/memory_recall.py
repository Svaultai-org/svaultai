

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from vault_core import get_db
from ai_memory import (
    ALLOWED_MEMORY_TYPES, is_enabled as memory_is_enabled,
    tokenize_text, slugify_memory_key,
)


logger = logging.getLogger(__name__)


_W_EXACT_KEY        = 10.0
_W_KEY_TOKEN        = 5.0
_W_VALUE_TOKEN      = 2.0
_W_TYPE_MATCH       = 3.0
_W_RECENCY_MAX      = 3.0                             
_W_ANCHOR_DIRECTION = 2.0                                
_RECENCY_HALFLIFE_DAYS = 60


def _recency_boost(updated_at) -> float:

    try:
        if updated_at is None:
            return 0.0
        now = datetime.now(timezone.utc) if updated_at.tzinfo else datetime.now()
        age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
        bonus = _W_RECENCY_MAX * pow(0.5, age_days / _RECENCY_HALFLIFE_DAYS)
        return float(bonus)
    except Exception:
        return 0.0


def _score_row(
    row: dict, query_tokens: list[str], type_hint: Optional[str],
    anchor_date, direction: Optional[str],
) -> float:

    score = 0.0
    key_lower = (row.get("memory_key") or "").lower()
    val_lower = (row.get("memory_value") or "").lower()
    key_tokens = set(tokenize_text(key_lower))
    val_tokens = set(tokenize_text(val_lower))

    for q in query_tokens:
        if q == key_lower:
            score += _W_EXACT_KEY
        elif q in key_tokens:
            score += _W_KEY_TOKEN
        if q in val_tokens:
            score += _W_VALUE_TOKEN

    if type_hint and row.get("memory_type") == type_hint:
        score += _W_TYPE_MATCH

    score += _recency_boost(row.get("updated_at"))

    if anchor_date and direction:
        row_date = row.get("event_date_obj")
        if row_date is None:
                                           
            ca = row.get("created_at")
            if ca is not None:
                row_date = ca.date() if hasattr(ca, "date") else None
        if row_date is not None:
            if direction == "before" and row_date < anchor_date:
                score += _W_ANCHOR_DIRECTION
            elif direction == "after" and row_date > anchor_date:
                score += _W_ANCHOR_DIRECTION
            elif direction == "around":
                score += _W_ANCHOR_DIRECTION * 0.5

    return score


def _fetch_active_rows(
    vault_id: str, *, memory_type: Optional[str] = None,
) -> list[dict]:

    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if memory_type and memory_type in ALLOWED_MEMORY_TYPES:
                    cur.execute(
                        """SELECT id, memory_type, memory_key, memory_value,
                                  event_date, confidence, created_at, updated_at
                           FROM vault_ai_memory
                           WHERE vault_id=%s
                             AND superseded_at IS NULL
                             AND memory_type=%s
                           ORDER BY updated_at DESC LIMIT 500""",
                        (vault_id, memory_type),
                    )
                else:
                    cur.execute(
                        """SELECT id, memory_type, memory_key, memory_value,
                                  event_date, confidence, created_at, updated_at
                           FROM vault_ai_memory
                           WHERE vault_id=%s
                             AND superseded_at IS NULL
                           ORDER BY updated_at DESC LIMIT 500""",
                        (vault_id,),
                    )
                out: list[dict] = []
                for row in cur.fetchall() or []:
                    out.append({
                        "id":             row[0],
                        "memory_type":    row[1],
                        "memory_key":     row[2],
                        "memory_value":   row[3],
                        "event_date":     row[4].isoformat() if row[4] else None,
                        "event_date_obj": row[4],
                        "confidence":     float(row[5] or 1.0),
                        "created_at":     row[6],
                        "updated_at":     row[7],
                    })
                return out
        finally:
            conn.close()
    except Exception as e:
        logger.warning("_fetch_active_rows failed: %s", e)
        return []


def _resolve_anchor_date(rows: list[dict], anchor_text: str):


    if not anchor_text:
        return None
    needle = anchor_text.strip().lower()
    needle_slug = slugify_memory_key(anchor_text)
    candidates = []
    for r in rows:
        key = (r.get("memory_key") or "").lower()
        val = (r.get("memory_value") or "").lower()
        score = 0
        if needle_slug and needle_slug == key:
            score += 100
        elif needle in key:
            score += 50
        if needle in val:
            score += 20
        if score > 0:
            candidates.append((score, r))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    best = candidates[0][1]
    ed = best.get("event_date_obj")
    if ed is not None:
        return ed
    ca = best.get("created_at")
    return ca.date() if (ca and hasattr(ca, "date")) else None


def recall_ranked(
    vault_id: str,
    *,
    memory_type: Optional[str] = None,
    query_text: Optional[str] = None,
    anchor_text: Optional[str] = None,
    direction: Optional[str] = None,                                   
    limit: int = 25,
) -> list[dict]:


    if not memory_is_enabled():
        return []
    try:
        if direction and direction not in ("before", "after", "around"):
            direction = None
        rows = _fetch_active_rows(vault_id, memory_type=memory_type)
        if not rows:
            return []
        anchor_date = _resolve_anchor_date(rows, anchor_text) if anchor_text else None
        query_tokens = tokenize_text(query_text)
                                                                 
                                                                   
        scored = []
        for r in rows:
            s = _score_row(r, query_tokens, memory_type, anchor_date, direction)
            if query_tokens and s < _W_VALUE_TOKEN - 0.01:
                                                         
                continue
            scored.append((s, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [r for _s, r in scored[: max(1, limit)]]
    except Exception as e:
        logger.warning("recall_ranked failed: %s", e)
        return []


def memory_timeline(
    vault_id: str,
    *,
    memory_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:


    if not memory_is_enabled():
        return []
    try:
        rows = _fetch_active_rows(vault_id, memory_type=memory_type)
                                                                     
                             
        def sort_key(r):
            ed = r.get("event_date_obj")
            if ed is not None:
                return (1, ed, r.get("updated_at") or datetime.min)
            return (0, datetime.min.date(), r.get("updated_at") or datetime.min)
        rows.sort(key=sort_key, reverse=True)
        return rows[: max(1, limit)]
    except Exception as e:
        logger.warning("memory_timeline failed: %s", e)
        return []


def related_memories(
    vault_id: str,
    *,
    memory_key: str,
    memory_type: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:


    if not memory_is_enabled():
        return []
    try:
        key = slugify_memory_key(memory_key)
        if not key:
            return []
        rows = _fetch_active_rows(vault_id, memory_type=memory_type)
        if not rows:
            return []
        key_tokens = set(tokenize_text(key.replace("_", " ")))
        if not key_tokens:
            return []
        out = []
        for r in rows:
            r_key = r.get("memory_key") or ""
            if r_key == key:
                continue                                    
            r_tokens = set(tokenize_text(r_key.replace("_", " ")))
            r_tokens |= set(tokenize_text(r.get("memory_value") or ""))
            overlap = len(key_tokens & r_tokens)
            if overlap > 0:
                out.append((overlap, r))
        out.sort(key=lambda t: (t[0], t[1].get("updated_at") or datetime.min), reverse=True)
        return [r for _o, r in out[: max(1, limit)]]
    except Exception as e:
        logger.warning("related_memories failed: %s", e)
        return []


_TYPE_LABELS_EN: dict[str, str] = {
    "identity":     "Identity",
    "travel":       "Travel",
    "preference":   "Preferences",
    "project":      "Projects",
    "company":      "Companies",
    "goal":         "Goals",
    "location":     "Locations",
    "relationship": "People",
    "note":         "Notes",
    "family":       "Family",
    "date":         "Dates",
    "life_event":   "Life Events",
}


def label_for_type(memory_type: str) -> str:


    return _TYPE_LABELS_EN.get(memory_type, memory_type.replace("_", " ").title())


def render_rows(rows: list[dict], *, show_dates: bool = False) -> list[str]:


    out: list[str] = []
    for r in rows:
        value = (r.get("memory_value") or "").strip()
        if not value:
            continue
        if show_dates and r.get("event_date"):
            out.append(f"- {value} ({r['event_date']})")
        else:
            out.append(f"- {value}")
    return out


def render_grouped_by_type(
    rows: list[dict], *, render_order: Optional[tuple] = None,
) -> list[str]:


    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r.get("memory_type") or "note"].append(r)
    order = render_order or ALLOWED_MEMORY_TYPES
    lines: list[str] = []
    for t in order:
        items = grouped.get(t)
        if not items:
            continue
                                                                     
        seen: set[str] = set()
        unique: list[dict] = []
        for r in items:
            key = (r.get("memory_value") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(r)
        if not unique:
            continue
        lines.append("")
        lines.append(label_for_type(t))
        lines.extend(render_rows(unique))
    return lines
