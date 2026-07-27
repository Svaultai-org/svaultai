from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Optional

try:
    from psycopg2.extras import RealDictCursor
except Exception:  # pragma: no cover - psycopg2 is present in production
    RealDictCursor = None  # type: ignore

from taxonomy import ALLOWED_MEMORY_TYPES
from vault_core import decrypt_message, encrypt_message, get_db


logger = logging.getLogger(__name__)


_MAX_MESSAGE_LEN = 2000
_MAX_FIELD_LEN = 500
_MAX_TITLE_LEN = 120
_PROPOSAL_TTL_SECONDS = 10 * 60
_LOOKUP_CONTEXT = "vaultai-personal-memory/v1"
_CARD_SCHEMA = "vault_chat_response_v1"
_PROPOSAL_SCHEMA = "vault_memory_proposal_v1"
_PAYLOAD_SCHEMA = "vault_personal_memory_v1"

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_SUBJECT_ALIASES = {
    "mom": ("mother", "mom", "mother"),
    "mum": ("mother", "mum", "mother"),
    "mother": ("mother", "mother", "mother"),
    "mama": ("mother", "mama", "mother"),
    "dad": ("father", "dad", "father"),
    "father": ("father", "father", "father"),
    "papa": ("father", "papa", "father"),
}

_ATTR_RE = r"(?:birthday|birth\s+date|date\s+of\s+birth|dob)"
_SUBJECT_RE = r"(?:mom|mum|mother|mama|dad|father|papa)"
_APOSTROPHE_RE = r"(?:'|\u2019)"
_SAVE_TRIGGER_RE = re.compile(
    r"^\s*(?:remember(?:\s+that)?|save\s+this(?:\s+about\s+me)?|"
    r"save\s+that|save\s+memory|save\s+this\s+memory|"
    r"don(?:'|\u2019)?t\s+forget|dont\s+forget|"
    r"keep\s+this(?:\s+for\s+me)?|note\s+that)\s*:?\s+"
    r"(?P<fact>.+?)\s*$",
    re.IGNORECASE,
)
_SAVE_PENDING_RE = re.compile(
    r"^\s*(?:save\s+it|save\s+this\s+memory|save\s+that\s+memory|"
    r"save\s+memory|yes\s+save\s+it|yes\s+save\s+this)\.?\s*$",
    re.IGNORECASE,
)
_MEMORY_SAVE_PENDING_RE = re.compile(
    r"^\s*(?:save\s+(?:this|that)?\s*memory|save\s+it\s+as\s+a\s+memory)\.?\s*$",
    re.IGNORECASE,
)
_CANCEL_PENDING_RE = re.compile(
    r"^\s*(?:cancel|cancel\s+it|don't\s+save\s+it|dont\s+save\s+it)\.?\s*$",
    re.IGNORECASE,
)
_FACT_RE = re.compile(
    rf"^(?:my\s+)?(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    rf"(?P<attribute>{_ATTR_RE})\s*(?:is|=|:)?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    rf"^\s*(?:my\s+)?(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    rf"(?P<attribute>{_ATTR_RE})\s+is\s+"
    rf"(?:(?:actually|really)\s+)?(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_RECALL_RE = re.compile(
    rf"^\s*(?:when|what(?:'s|\s+is))\s+(?:is\s+)?(?:my\s+)?"
    rf"(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    rf"(?P<attribute>{_ATTR_RE})\??\s*$",
    re.IGNORECASE,
)
_FORGET_RE = re.compile(
    rf"^\s*(?:forget|delete|remove)\s+(?:my\s+)?"
    rf"(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    rf"(?P<attribute>{_ATTR_RE})\??\s*$",
    re.IGNORECASE,
)
_MAIDEN_FACT_RE = re.compile(
    rf"^(?:my\s+)?(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    r"maiden\s+name\s*(?:is|=|:)?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_MAIDEN_RECALL_RE = re.compile(
    rf"^\s*(?:what(?:'s|\s+is))\s+(?:my\s+)?"
    rf"(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    r"maiden\s+name\??\s*$",
    re.IGNORECASE,
)
_MAIDEN_FORGET_RE = re.compile(
    rf"^\s*(?:forget|delete|remove)\s+(?:my\s+)?"
    rf"(?P<subject>{_SUBJECT_RE})(?:{_APOSTROPHE_RE}s)?\s+"
    r"maiden\s+name\??\s*$",
    re.IGNORECASE,
)
_ANNIVERSARY_FACT_RE = re.compile(
    r"^(?:my\s+)?(?P<subject>wedding|marriage)\s+anniversary\s*"
    r"(?:is|=|:)?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_ANNIVERSARY_RECALL_RE = re.compile(
    r"^\s*(?:when|what(?:'s|\s+is))\s+(?:is\s+)?(?:my\s+)?"
    r"(?P<subject>wedding|marriage)\s+anniversary\??\s*$",
    re.IGNORECASE,
)
_ANNIVERSARY_FORGET_RE = re.compile(
    r"^\s*(?:forget|delete|remove)\s+(?:my\s+)?"
    r"(?P<subject>wedding|marriage)\s+anniversary\??\s*$",
    re.IGNORECASE,
)
_TRAVEL_FACT_RE = re.compile(
    r"^\s*i\s+(?:traveled|travelled|went|flew)\s+to\s+"
    r"(?P<place>.+?)\s+on\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_TRAVEL_RECALL_RE = re.compile(
    r"^\s*(?:when|what\s+date)\s+did\s+i\s+"
    r"(?:travel|travell|go|fly)\s+to\s+(?P<place>.+?)\??\s*$",
    re.IGNORECASE,
)
_TRAVEL_FORGET_RE = re.compile(
    r"^\s*(?:forget|delete|remove)\s+(?:my\s+)?"
    r"(?:trip|travel)\s+to\s+(?P<place>.+?)\??\s*$",
    re.IGNORECASE,
)
_FAVORITE_PLACE_FACT_RE = re.compile(
    r"^(?:my\s+)?favorite\s+place\s*(?:is|=|:)?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_FAVORITE_PLACE_RECALL_RE = re.compile(
    r"^\s*(?:what(?:'s|\s+is))\s+(?:my\s+)?favorite\s+place\??\s*$",
    re.IGNORECASE,
)
_BLOOD_TYPE_FACT_RE = re.compile(
    r"^(?:my\s+)?blood\s+type\s*(?:is|=|:)?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_BLOOD_TYPE_RECALL_RE = re.compile(
    r"^\s*(?:what(?:'s|\s+is))\s+(?:my\s+)?blood\s+type\??\s*$",
    re.IGNORECASE,
)
_LIKE_FACT_RE = re.compile(
    r"^\s*i\s+(?:like|prefer|love)\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_ISO_RE = re.compile(r"^\s*(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s*$")
_SLASH_DATE_RE = re.compile(
    r"^\s*(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})\s*$",
)
_DAY_MONTH_YEAR_RE = re.compile(
    r"^\s*(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<m>[A-Za-z]+)\s*,?\s+(?P<y>\d{4})\s*$",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR_RE = re.compile(
    r"^\s*(?P<m>[A-Za-z]+)\s+"
    r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(?P<y>\d{4})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PersonalMemoryIntent:
    action: str
    subject: str
    subject_display: str
    relationship: str
    attribute: str
    title: str
    memory_type: str = "note"
    category: str = "personal"
    value: Optional[str] = None
    normalized_value: Optional[str] = None
    display_value: Optional[str] = None
    body: Optional[str] = None
    event_date: Optional[str] = None
    place: Optional[str] = None
    tags: tuple[str, ...] = ()
    is_correction: bool = False
    needs_clarification: bool = False
    canonical_key_override: Optional[str] = None
    proposal_id: Optional[str] = None

    @property
    def canonical_key(self) -> str:
        if self.canonical_key_override:
            return self.canonical_key_override
        return f"{self.subject}:{self.attribute}"


_PENDING_PROPOSALS: dict[tuple[str, str], dict[str, Any]] = {}


def _clean_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip())[:_MAX_MESSAGE_LEN]


def _clip(value: Any, max_len: int = _MAX_FIELD_LEN) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_len]


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return text.strip("_")[:80] or "item"


def _title_case(value: str) -> str:
    words = [w for w in re.split(r"\s+", value.strip()) if w]
    if not words:
        return ""
    return " ".join(w[:1].upper() + w[1:] for w in words)


def _subject_parts(raw: str) -> tuple[str, str, str]:
    return _SUBJECT_ALIASES.get(raw.strip().lower(), (raw, raw, raw))


def _parse_date_text(text: str) -> tuple[Optional[str], Optional[str]]:
    value = (text or "").strip().rstrip(".")
    m = _ISO_RE.match(value)
    if m:
        y, month, day = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    else:
        slash = _SLASH_DATE_RE.match(value)
        if slash:
            # Product examples use day/month/year. Ambiguous US dates still
            # round-trip when day == month, and the plaintext never persists.
            day = int(slash.group("a"))
            month = int(slash.group("b"))
            y = int(slash.group("y"))
        else:
            m = _DAY_MONTH_YEAR_RE.match(value) or _MONTH_DAY_YEAR_RE.match(value)
            if not m:
                return None, None
            y = int(m.group("y"))
            month_name = m.group("m").strip().lower()
            month = _MONTHS.get(month_name)
            if not month:
                return None, None
            day = int(m.group("d"))
    try:
        parsed = date(y, month, day)
    except ValueError:
        return None, None
    return parsed.isoformat(), f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _with_action(intent: PersonalMemoryIntent, action: str) -> PersonalMemoryIntent:
    return replace(intent, action=action)


def _birthday_intent(match: re.Match[str], *, action: str,
                     is_correction: bool = False) -> PersonalMemoryIntent:
    subject, display, relationship = _subject_parts(match.group("subject"))
    normalized, display_value = _parse_date_text(match.group("value"))
    title = f"{display.title()}'s birthday"
    return PersonalMemoryIntent(
        action=action,
        subject=subject,
        subject_display=display,
        relationship=relationship,
        attribute="birthday",
        title=title,
        memory_type="date",
        category="family",
        value=display_value,
        normalized_value=normalized,
        display_value=display_value,
        event_date=normalized,
        tags=("family", "date"),
        is_correction=is_correction,
        needs_clarification=normalized is None,
    )


def _parse_fact_statement(
    text: str,
    *,
    action: str,
    is_correction: bool = False,
) -> Optional[PersonalMemoryIntent]:
    fact_match = _CORRECTION_RE.match(text) if is_correction else None
    if not fact_match:
        fact_match = _FACT_RE.match(text)
    if fact_match:
        return _birthday_intent(
            fact_match,
            action=action,
            is_correction=is_correction,
        )

    m = _MAIDEN_FACT_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        value = _clip(m.group("value"))
        return PersonalMemoryIntent(
            action=action,
            subject=subject,
            subject_display=display,
            relationship=relationship,
            attribute="maiden_name",
            title=f"{display.title()}'s maiden name",
            memory_type="identity",
            category="family",
            value=value,
            display_value=value,
            tags=("family", "identity"),
            is_correction=is_correction,
            needs_clarification=not bool(value),
        )

    m = _ANNIVERSARY_FACT_RE.match(text)
    if m:
        normalized, display_value = _parse_date_text(m.group("value"))
        return PersonalMemoryIntent(
            action=action,
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="wedding_anniversary",
            title="Wedding anniversary",
            memory_type="date",
            category="life_event",
            value=display_value,
            normalized_value=normalized,
            display_value=display_value,
            event_date=normalized,
            tags=("date", "life_event"),
            is_correction=is_correction,
            needs_clarification=normalized is None,
        )

    m = _TRAVEL_FACT_RE.match(text)
    if m:
        place = _clip(m.group("place"), 120)
        normalized, display_value = _parse_date_text(m.group("value"))
        return PersonalMemoryIntent(
            action=action,
            subject="self",
            subject_display="you",
            relationship="self",
            attribute=f"travel_date:{_slug(place)}",
            title=f"Trip to {_title_case(place)}",
            memory_type="travel",
            category="travel",
            value=display_value,
            normalized_value=normalized,
            display_value=display_value,
            event_date=normalized,
            place=place,
            tags=("travel", "date"),
            is_correction=is_correction,
            needs_clarification=normalized is None or not bool(place),
        )

    m = _FAVORITE_PLACE_FACT_RE.match(text)
    if m:
        value = _clip(m.group("value"))
        return PersonalMemoryIntent(
            action=action,
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="favorite_place",
            title="Favorite place",
            memory_type="location",
            category="places",
            value=value,
            display_value=value,
            tags=("place", "preference"),
            is_correction=is_correction,
            needs_clarification=not bool(value),
        )

    m = _BLOOD_TYPE_FACT_RE.match(text)
    if m:
        value = _clip(m.group("value"), 40)
        return PersonalMemoryIntent(
            action=action,
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="blood_type",
            title="Blood type",
            memory_type="identity",
            category="medical",
            value=value,
            display_value=value,
            tags=("medical", "identity"),
            is_correction=is_correction,
            needs_clarification=not bool(value),
        )

    m = _LIKE_FACT_RE.match(text)
    if m:
        value = _clip(m.group("value"))
        return PersonalMemoryIntent(
            action=action,
            subject="self",
            subject_display="your",
            relationship="self",
            attribute=f"preference:{_slug(value)}",
            title="Preference",
            memory_type="preference",
            category="preferences",
            value=value,
            display_value=value,
            tags=("preference",),
            is_correction=is_correction,
            needs_clarification=not bool(value),
        )

    if action == "save":
        body = _clip(text, 1000)
        if body:
            return PersonalMemoryIntent(
                action="save",
                subject="self",
                subject_display="your",
                relationship="self",
                attribute=f"note:{uuid.uuid4().hex}",
                title="Personal note",
                memory_type="note",
                category="note",
                value=body,
                display_value=body,
                body=body,
                tags=("note",),
                is_correction=False,
                needs_clarification=False,
            )
    return None


def parse_personal_memory_intent(message: str) -> Optional[PersonalMemoryIntent]:
    text = _clean_message(message)
    if not text:
        return None

    if _SAVE_PENDING_RE.match(text):
        return PersonalMemoryIntent(
            action="save_pending",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="pending",
            title="Pending memory",
        )
    if _CANCEL_PENDING_RE.match(text):
        return PersonalMemoryIntent(
            action="cancel_pending",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="pending",
            title="Pending memory",
        )

    m = _FORGET_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="forget",
            subject=subject,
            subject_display=display,
            relationship=relationship,
            attribute="birthday",
            title=f"{display.title()}'s birthday",
            memory_type="date",
            category="family",
        )
    m = _MAIDEN_FORGET_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="forget",
            subject=subject,
            subject_display=display,
            relationship=relationship,
            attribute="maiden_name",
            title=f"{display.title()}'s maiden name",
            memory_type="identity",
            category="family",
        )
    m = _ANNIVERSARY_FORGET_RE.match(text)
    if m:
        return PersonalMemoryIntent(
            action="forget",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="wedding_anniversary",
            title="Wedding anniversary",
            memory_type="date",
            category="life_event",
        )
    m = _TRAVEL_FORGET_RE.match(text)
    if m:
        place = _clip(m.group("place"), 120)
        return PersonalMemoryIntent(
            action="forget",
            subject="self",
            subject_display="you",
            relationship="self",
            attribute=f"travel_date:{_slug(place)}",
            title=f"Trip to {_title_case(place)}",
            memory_type="travel",
            category="travel",
            place=place,
        )

    m = _RECALL_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="recall",
            subject=subject,
            subject_display=display,
            relationship=relationship,
            attribute="birthday",
            title=f"{display.title()}'s birthday",
            memory_type="date",
            category="family",
        )
    m = _MAIDEN_RECALL_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="recall",
            subject=subject,
            subject_display=display,
            relationship=relationship,
            attribute="maiden_name",
            title=f"{display.title()}'s maiden name",
            memory_type="identity",
            category="family",
        )
    if _ANNIVERSARY_RECALL_RE.match(text):
        return PersonalMemoryIntent(
            action="recall",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="wedding_anniversary",
            title="Wedding anniversary",
            memory_type="date",
            category="life_event",
        )
    m = _TRAVEL_RECALL_RE.match(text)
    if m:
        place = _clip(m.group("place"), 120)
        return PersonalMemoryIntent(
            action="recall",
            subject="self",
            subject_display="you",
            relationship="self",
            attribute=f"travel_date:{_slug(place)}",
            title=f"Trip to {_title_case(place)}",
            memory_type="travel",
            category="travel",
            place=place,
        )
    if _FAVORITE_PLACE_RECALL_RE.match(text):
        return PersonalMemoryIntent(
            action="recall",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="favorite_place",
            title="Favorite place",
            memory_type="location",
            category="places",
        )
    if _BLOOD_TYPE_RECALL_RE.match(text):
        return PersonalMemoryIntent(
            action="recall",
            subject="self",
            subject_display="your",
            relationship="self",
            attribute="blood_type",
            title="Blood type",
            memory_type="identity",
            category="medical",
        )

    is_correction = bool(
        re.search(r"\b(?:actually|correction|correct|update|change)\b", text, re.I)
    )
    save_match = _SAVE_TRIGGER_RE.match(text)
    fact_text = save_match.group("fact") if save_match else text
    if save_match is not None:
        return _parse_fact_statement(
            fact_text,
            action="save",
            is_correction=is_correction,
        )
    if is_correction:
        return _parse_fact_statement(
            text,
            action="save",
            is_correction=True,
        )
    return _parse_fact_statement(text, action="propose")


def _lookup_hash(key: bytes, canonical_key: str) -> bytes:
    return hmac.new(
        key,
        f"{_LOOKUP_CONTEXT}:{canonical_key}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _payload_for_intent(
    intent: PersonalMemoryIntent,
    *,
    source_message_id: Optional[str],
) -> dict[str, Any]:
    value = intent.display_value or intent.value
    return {
        "schema": _PAYLOAD_SCHEMA,
        "record_type": "personal_memory",
        "category": intent.category,
        "memory_type": _safe_memory_type(intent.memory_type),
        "title": _clip(intent.title, _MAX_TITLE_LEN),
        "value": _clip(value),
        "body": _clip(intent.body or value),
        "event_date": intent.event_date,
        "subject": intent.subject,
        "subject_display": intent.subject_display,
        "relationship": intent.relationship,
        "attribute": intent.attribute,
        "normalized_value": intent.normalized_value,
        "display_value": _clip(value),
        "place": intent.place,
        "tags": [t for t in intent.tags if t],
        "source": "explicit_user_memory",
        "status": "active",
        "canonical_key": intent.canonical_key,
        "source_message_id": source_message_id,
    }


def _intent_from_payload(payload: dict[str, Any], *, action: str = "save",
                         is_correction: bool = False) -> PersonalMemoryIntent:
    canonical = str(payload.get("canonical_key") or "")
    subject = str(payload.get("subject") or "self")
    attribute = str(payload.get("attribute") or "note")
    return PersonalMemoryIntent(
        action=action,
        subject=subject,
        subject_display=str(payload.get("subject_display") or subject),
        relationship=str(payload.get("relationship") or "self"),
        attribute=attribute,
        title=_clip(payload.get("title") or "Memory", _MAX_TITLE_LEN),
        memory_type=_safe_memory_type(payload.get("memory_type") or "note"),
        category=_clip(payload.get("category") or "personal", 80),
        value=_clip(payload.get("value") or payload.get("display_value")),
        normalized_value=(
            str(payload.get("normalized_value"))
            if payload.get("normalized_value") is not None
            else None
        ),
        display_value=_clip(payload.get("display_value") or payload.get("value")),
        body=_clip(payload.get("body") or payload.get("value")),
        event_date=(
            str(payload.get("event_date"))
            if payload.get("event_date") is not None
            else None
        ),
        place=(
            str(payload.get("place"))
            if payload.get("place") is not None
            else None
        ),
        tags=tuple(
            str(t) for t in (payload.get("tags") or [])
            if isinstance(t, str) and t
        ),
        is_correction=is_correction,
        needs_clarification=False,
        canonical_key_override=canonical or f"{subject}:{attribute}",
    )


def _decode_payload(blob: Any, key: bytes) -> Optional[dict[str, Any]]:
    if not blob:
        return None
    try:
        if isinstance(blob, memoryview):
            raw = blob.tobytes()
        elif isinstance(blob, bytes):
            raw = blob
        else:
            raw = str(blob).encode("utf-8")
        text = raw.decode("utf-8")
        decoded = json.loads(decrypt_message(text, key))
        return decoded if isinstance(decoded, dict) else None
    except Exception:
        return None


def _encrypted_payload(payload: dict[str, Any], key: bytes) -> bytes:
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return encrypt_message(text, key).encode("utf-8")


def _safe_memory_type(memory_type: Any) -> str:
    raw = str(memory_type or "").strip().lower()
    aliases = {
        "dates": "date",
        "preferences": "preference",
        "places": "location",
        "projects": "project",
        "goals": "goal",
        "people": "relationship",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in ALLOWED_MEMORY_TYPES else "note"


def _row_to_dict(row: Any, columns: tuple[str, ...]) -> Optional[dict[str, Any]]:
    if not row:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {columns[i]: row[i] for i in range(min(len(columns), len(row)))}


def _fetch_active(cur: Any, vault_id: str, digest: bytes) -> Optional[dict[str, Any]]:
    cur.execute(
        """SELECT id, payload_ciphertext, created_at, updated_at
           FROM vault_ai_memory
           WHERE vault_id=%s
             AND memory_lookup_hash=%s
             AND superseded_at IS NULL
           ORDER BY updated_at DESC
           LIMIT 1""",
        (vault_id, digest),
    )
    return _row_to_dict(
        cur.fetchone(),
        ("id", "payload_ciphertext", "created_at", "updated_at"),
    )


def _fetch_active_by_id(cur: Any, vault_id: str, memory_id: int) -> Optional[dict[str, Any]]:
    cur.execute(
        """SELECT id, memory_type, payload_ciphertext, created_at, updated_at
           FROM vault_ai_memory
           WHERE id=%s
             AND vault_id=%s
             AND superseded_at IS NULL
             AND payload_ciphertext IS NOT NULL
             AND memory_lookup_hash IS NOT NULL
           LIMIT 1""",
        (memory_id, vault_id),
    )
    return _row_to_dict(
        cur.fetchone(),
        ("id", "memory_type", "payload_ciphertext", "created_at", "updated_at"),
    )


def _fetch_active_rows(cur: Any, vault_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    cur.execute(
        """SELECT id, memory_type, payload_ciphertext, created_at, updated_at
           FROM vault_ai_memory
           WHERE vault_id=%s
             AND superseded_at IS NULL
             AND payload_ciphertext IS NOT NULL
             AND memory_lookup_hash IS NOT NULL
           ORDER BY updated_at DESC
           LIMIT %s""",
        (vault_id, max(1, min(int(limit or 500), 1000))),
    )
    rows = cur.fetchall() or []
    return [
        _row_to_dict(
            row,
            ("id", "memory_type", "payload_ciphertext", "created_at", "updated_at"),
        ) or {}
        for row in rows
    ]


def _insert_payload(cur: Any, vault_id: str, intent: PersonalMemoryIntent, key: bytes,
                    *, source_message_id: Optional[str]) -> int:
    payload = _payload_for_intent(intent, source_message_id=source_message_id)
    cur.execute(
        """INSERT INTO vault_ai_memory (
               vault_id, memory_type, memory_key, memory_value,
               event_date, confidence, source,
               memory_language, memory_script, memory_normalized_key,
               payload_ciphertext, memory_lookup_hash
           )
           VALUES (%s, %s, NULL, NULL, NULL, 1.0, 'chat',
                   NULL, NULL, NULL, %s, %s)
           RETURNING id""",
        (
            vault_id,
            _safe_memory_type(intent.memory_type),
            _encrypted_payload(payload, key),
            _lookup_hash(key, intent.canonical_key),
        ),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


def _format_possessive(subject_display: str) -> str:
    if subject_display == "your":
        return "your"
    if subject_display == "you":
        return "your"
    return f"your {subject_display}'s"


def _missing_text(intent: PersonalMemoryIntent) -> str:
    if intent.attribute == "birthday":
        return f"I don't have {_format_possessive(intent.subject_display)} birthday saved yet."
    if intent.attribute == "maiden_name":
        return f"I don't have {_format_possessive(intent.subject_display)} maiden name saved yet."
    if intent.attribute == "wedding_anniversary":
        return "I don't have your wedding anniversary saved yet."
    if intent.attribute.startswith("travel_date:"):
        return f"I don't have your trip to {intent.place or 'that place'} saved yet."
    if intent.attribute == "favorite_place":
        return "I don't have your favorite place saved yet."
    if intent.attribute == "blood_type":
        return "I don't have your blood type saved yet."
    return "I don't have that memory saved yet."


def _saved_text(intent: PersonalMemoryIntent, verb: str = "Saved") -> str:
    display = intent.display_value or intent.value or ""
    if intent.attribute == "birthday":
        return (
            f"{verb}: {_format_possessive(intent.subject_display)} "
            f"birthday is {display}."
        )
    if intent.attribute == "maiden_name":
        return (
            f"{verb}: {_format_possessive(intent.subject_display)} "
            f"maiden name is {display}."
        )
    if intent.attribute == "wedding_anniversary":
        return f"{verb}: your wedding anniversary is {display}."
    if intent.attribute.startswith("travel_date:"):
        return f"{verb}: you traveled to {intent.place} on {display}."
    if intent.attribute == "favorite_place":
        return f"{verb}: your favorite place is {display}."
    if intent.attribute == "blood_type":
        return f"{verb}: your blood type is {display}."
    return f"{verb}: {intent.title}."


def _recall_text(intent: PersonalMemoryIntent, payload: dict[str, Any]) -> str:
    display = str(
        payload.get("display_value")
        or payload.get("value")
        or payload.get("body")
        or ""
    ).strip()
    if not display:
        return _missing_text(intent)
    if intent.attribute == "birthday":
        return (
            f"{_format_possessive(intent.subject_display).capitalize()} "
            f"birthday is {display}."
        )
    if intent.attribute == "maiden_name":
        return (
            f"{_format_possessive(intent.subject_display).capitalize()} "
            f"maiden name is {display}."
        )
    if intent.attribute == "wedding_anniversary":
        return f"Your wedding anniversary is {display}."
    if intent.attribute.startswith("travel_date:"):
        return f"You traveled to {intent.place or payload.get('place')} on {display}."
    if intent.attribute == "favorite_place":
        return f"Your favorite place is {display}."
    if intent.attribute == "blood_type":
        return f"Your blood type is {display}."
    return f"{payload.get('title') or intent.title}: {display}"


def _safe_item_from_payload(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    return {
        "id": str(row.get("id")),
        "memory_type": _safe_memory_type(
            payload.get("memory_type") or row.get("memory_type") or "note"
        ),
        "category": str(payload.get("category") or "personal"),
        "title": str(payload.get("title") or "Memory"),
        "value": str(payload.get("value") or payload.get("display_value") or ""),
        "body": str(payload.get("body") or ""),
        "event_date": payload.get("event_date"),
        "subject": str(payload.get("subject") or ""),
        "attribute": str(payload.get("attribute") or ""),
        "place": payload.get("place"),
        "tags": [
            str(t) for t in (payload.get("tags") or [])
            if isinstance(t, str) and t
        ],
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else None,
    }


def _save_memory(
    vault_id: str,
    key: bytes,
    intent: PersonalMemoryIntent,
    *,
    source_message_id: Optional[str],
) -> str:
    if intent.needs_clarification:
        return "I can save that memory, but I need the missing details first."

    digest = _lookup_hash(key, intent.canonical_key)
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        existing = _fetch_active(cur, vault_id, digest)
        if existing:
            existing_payload = _decode_payload(existing.get("payload_ciphertext"), key)
            prior_display = (
                existing_payload.get("display_value")
                if isinstance(existing_payload, dict)
                else None
            )
            prior_norm = (
                existing_payload.get("normalized_value")
                if isinstance(existing_payload, dict)
                else None
            )
            new_norm = intent.normalized_value or intent.display_value or intent.value
            old_norm = prior_norm or prior_display
            if old_norm == new_norm:
                cur.execute(
                    "UPDATE vault_ai_memory SET updated_at=NOW() "
                    "WHERE id=%s AND vault_id=%s",
                    (existing["id"], vault_id),
                )
                conn.commit()
                return (
                    f"I already have that saved: "
                    f"{_saved_text(intent, verb='').lstrip(': ').rstrip('.') }."
                )
            if not intent.is_correction:
                conn.rollback()
                return (
                    f"I already have {intent.title} saved. If that is wrong, "
                    "tell me it is actually the new value."
                )
            cur.execute(
                """UPDATE vault_ai_memory
                      SET superseded_at=NOW()
                    WHERE id=%s AND vault_id=%s""",
                (existing["id"], vault_id),
            )
            new_id = _insert_payload(
                cur, vault_id, intent, key, source_message_id=source_message_id
            )
            cur.execute(
                """UPDATE vault_ai_memory
                      SET superseded_by_id=%s
                    WHERE id=%s AND vault_id=%s""",
                (new_id, existing["id"], vault_id),
            )
            conn.commit()
            return _saved_text(intent, verb="Updated")

        _insert_payload(cur, vault_id, intent, key, source_message_id=source_message_id)
        conn.commit()
        return _saved_text(intent, verb="Saved")
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(
            "personal memory save failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        return "I couldn't save that memory. Please try again."
    finally:
        if conn is not None:
            conn.close()


def _recall_memory(vault_id: str, key: bytes, intent: PersonalMemoryIntent) -> str:
    digest = _lookup_hash(key, intent.canonical_key)
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        existing = _fetch_active(cur, vault_id, digest)
    except Exception as exc:
        logger.warning(
            "personal memory recall failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        return "I couldn't check that memory right now. Please try again."
    finally:
        if conn is not None:
            conn.close()
    if not existing:
        return _missing_text(intent)
    payload = _decode_payload(existing.get("payload_ciphertext"), key)
    if not payload or payload.get("status") != "active":
        return _missing_text(intent)
    return _recall_text(intent, payload)


def _forget_memory(vault_id: str, key: bytes, intent: PersonalMemoryIntent) -> str:
    digest = _lookup_hash(key, intent.canonical_key)
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        existing = _fetch_active(cur, vault_id, digest)
        if not existing:
            conn.rollback()
            return _missing_text(intent)
        cur.execute(
            """UPDATE vault_ai_memory
                  SET superseded_at=NOW()
                WHERE id=%s AND vault_id=%s""",
            (existing["id"], vault_id),
        )
        conn.commit()
        if intent.attribute == "birthday":
            return f"Forgot {_format_possessive(intent.subject_display)} birthday."
        if intent.attribute == "maiden_name":
            return f"Forgot {_format_possessive(intent.subject_display)} maiden name."
        return f"Forgot {intent.title}."
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(
            "personal memory forget failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        return "I couldn't forget that memory right now. Please try again."
    finally:
        if conn is not None:
            conn.close()


def _pending_key(vault_id: str, session_id: Optional[str]) -> tuple[str, str]:
    return vault_id, session_id or "default"


def _purge_expired_proposals() -> None:
    now = time.monotonic()
    expired = [
        key for key, value in _PENDING_PROPOSALS.items()
        if float(value.get("expires_at") or 0.0) <= now
    ]
    for key in expired:
        _PENDING_PROPOSALS.pop(key, None)


def _store_pending_proposal(
    vault_id: str,
    session_id: Optional[str],
    payload: dict[str, Any],
) -> None:
    _purge_expired_proposals()
    _PENDING_PROPOSALS[_pending_key(vault_id, session_id)] = {
        "payload": payload,
        "expires_at": time.monotonic() + _PROPOSAL_TTL_SECONDS,
    }


def _pop_pending_proposal(
    vault_id: str,
    session_id: Optional[str],
) -> Optional[dict[str, Any]]:
    _purge_expired_proposals()
    item = _PENDING_PROPOSALS.pop(_pending_key(vault_id, session_id), None)
    payload = item.get("payload") if isinstance(item, dict) else None
    return payload if isinstance(payload, dict) else None


def _peek_pending_proposal(
    vault_id: str,
    session_id: Optional[str],
) -> Optional[dict[str, Any]]:
    _purge_expired_proposals()
    item = _PENDING_PROPOSALS.get(_pending_key(vault_id, session_id))
    payload = item.get("payload") if isinstance(item, dict) else None
    return payload if isinstance(payload, dict) else None


def _proposal_envelope(intent: PersonalMemoryIntent) -> str:
    proposal_id = intent.proposal_id or uuid.uuid4().hex
    card_data = {
        "schema": _PROPOSAL_SCHEMA,
        "proposal_id": proposal_id,
        "title": _clip(intent.title, _MAX_TITLE_LEN),
        "value": _clip(intent.display_value or intent.value),
        "body": _clip(intent.body or intent.display_value or intent.value),
        "memory_type": _safe_memory_type(intent.memory_type),
        "category": intent.category,
        "subject": intent.subject,
        "subject_display": intent.subject_display,
        "relationship": intent.relationship,
        "attribute": intent.attribute,
        "event_date": intent.event_date,
        "place": intent.place,
        "tags": [t for t in intent.tags if t],
        "actions": ["save", "edit", "cancel"],
    }
    envelope = {
        "type": "vault_chat_card",
        "schema": _CARD_SCHEMA,
        "intent": "vault_memory_save_proposal",
        "message": "I can save this memory to your vault.",
        "card": {
            "cardType": "vault_memory_proposal_card",
            "view": "save_proposal",
            "data": card_data,
        },
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True)


def save_memory_payload(
    *,
    vault_id: str,
    key: bytes,
    payload: dict[str, Any],
    source_message_id: Optional[str] = None,
    is_correction: bool = True,
) -> dict[str, Any]:
    intent = _intent_from_payload(
        payload,
        action="save",
        is_correction=is_correction,
    )
    reply = _save_memory(
        vault_id,
        key,
        intent,
        source_message_id=source_message_id,
    )
    if reply.startswith("I couldn't"):
        return {"ok": False, "message": reply}
    item = get_memory_by_lookup(vault_id=vault_id, key=key, intent=intent)
    return {
        "ok": True,
        "message": reply,
        "item": item,
    }


def get_memory_by_lookup(
    *,
    vault_id: str,
    key: bytes,
    intent: PersonalMemoryIntent,
) -> Optional[dict[str, Any]]:
    digest = _lookup_hash(key, intent.canonical_key)
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        row = _fetch_active(cur, vault_id, digest)
        if not row:
            return None
        payload = _decode_payload(row.get("payload_ciphertext"), key)
        if not payload:
            return None
        return _safe_item_from_payload(row, payload)
    finally:
        if conn is not None:
            conn.close()


def list_memory_items(
    *,
    vault_id: str,
    key: bytes,
    query: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 500,
) -> dict[str, Any]:
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        rows = _fetch_active_rows(cur, vault_id, limit=limit)
        items: list[dict[str, Any]] = []
        q = (query or "").strip().lower()
        filt = _safe_memory_type(memory_type) if memory_type else None
        for row in rows:
            payload = _decode_payload(row.get("payload_ciphertext"), key)
            if not payload or payload.get("status") != "active":
                continue
            item = _safe_item_from_payload(row, payload)
            if filt and item.get("memory_type") != filt:
                continue
            if q:
                haystack = " ".join(
                    str(item.get(k) or "")
                    for k in ("title", "value", "body", "category", "memory_type")
                ).lower()
                if q not in haystack:
                    continue
            items.append(item)
        counts: dict[str, int] = {}
        for item in items:
            t = str(item.get("memory_type") or "note")
            counts[t] = counts.get(t, 0) + 1
        return {"items": items[: max(1, min(limit, 1000))], "counts": counts}
    finally:
        if conn is not None:
            conn.close()


def update_memory_item(
    *,
    vault_id: str,
    key: bytes,
    memory_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        existing = _fetch_active_by_id(cur, vault_id, memory_id)
        if not existing:
            return {"ok": False, "message": "I couldn't find that memory."}
        old_payload = _decode_payload(existing.get("payload_ciphertext"), key) or {}
        merged = {**old_payload, **payload}
        merged["schema"] = _PAYLOAD_SCHEMA
        merged["record_type"] = "personal_memory"
        merged["status"] = "active"
        intent = _intent_from_payload(merged, action="save", is_correction=True)
        cur.execute(
            """UPDATE vault_ai_memory
                  SET superseded_at=NOW()
                WHERE id=%s AND vault_id=%s""",
            (memory_id, vault_id),
        )
        new_id = _insert_payload(cur, vault_id, intent, key, source_message_id=None)
        cur.execute(
            """UPDATE vault_ai_memory
                  SET superseded_by_id=%s
                WHERE id=%s AND vault_id=%s""",
            (new_id, memory_id, vault_id),
        )
        conn.commit()
        row = _fetch_active_by_id(cur, vault_id, new_id)
        item_payload = _decode_payload(row.get("payload_ciphertext"), key) if row else None
        return {
            "ok": True,
            "message": "Memory updated.",
            "item": _safe_item_from_payload(row or {"id": new_id}, item_payload or merged),
        }
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(
            "personal memory update failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        return {"ok": False, "message": "I couldn't update that memory."}
    finally:
        if conn is not None:
            conn.close()


def delete_memory_item(
    *,
    vault_id: str,
    key: bytes,
    memory_id: int,
) -> dict[str, Any]:
    del key  # The caller already proved vault authorization by unlocking.
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        existing = _fetch_active_by_id(cur, vault_id, memory_id)
        if not existing:
            conn.rollback()
            return {"ok": False, "message": "I couldn't find that memory."}
        cur.execute(
            """UPDATE vault_ai_memory
                  SET superseded_at=NOW()
                WHERE id=%s AND vault_id=%s""",
            (memory_id, vault_id),
        )
        conn.commit()
        return {"ok": True, "message": "Memory deleted."}
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(
            "personal memory delete failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        return {"ok": False, "message": "I couldn't delete that memory."}
    finally:
        if conn is not None:
            conn.close()


def build_payload_from_request(data: dict[str, Any]) -> dict[str, Any]:
    subject = _clip(data.get("subject") or "self", 80)
    attribute = _clip(data.get("attribute") or "note", 120)
    title = _clip(data.get("title") or "Memory", _MAX_TITLE_LEN)
    value = _clip(data.get("value") or data.get("display_value") or data.get("body"))
    event_date = data.get("event_date")
    if event_date is not None:
        event_date = _clip(event_date, 40)
    tags_raw = data.get("tags")
    tags = [
        _clip(t, 40)
        for t in tags_raw
        if isinstance(t, str) and t.strip()
    ] if isinstance(tags_raw, list) else []
    canonical = data.get("canonical_key")
    if not canonical:
        if attribute == "note" and subject == "self":
            canonical = f"note:{uuid.uuid4().hex}"
        else:
            canonical = f"{subject}:{attribute}"
    return {
        "schema": _PAYLOAD_SCHEMA,
        "record_type": "personal_memory",
        "category": _clip(data.get("category") or "personal", 80),
        "memory_type": _safe_memory_type(data.get("memory_type") or "note"),
        "title": title,
        "value": value,
        "body": _clip(data.get("body") or value, 1000),
        "event_date": event_date,
        "subject": subject,
        "subject_display": _clip(data.get("subject_display") or subject, 80),
        "relationship": _clip(data.get("relationship") or "self", 80),
        "attribute": attribute,
        "normalized_value": data.get("normalized_value"),
        "display_value": _clip(data.get("display_value") or value),
        "place": data.get("place"),
        "tags": tags,
        "source": "explicit_user_memory",
        "status": "active",
        "canonical_key": _clip(canonical, 180),
        "source_message_id": data.get("source_message_id"),
    }


def handle_personal_memory_turn(
    *,
    vault_id: str,
    key: bytes,
    message: str,
    source_message_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    intent = parse_personal_memory_intent(message)
    if intent is None:
        return None
    if intent.action == "save_pending":
        pending = _peek_pending_proposal(vault_id, session_id)
        if pending is None:
            # Bare "save it" is also used by generated-login drafts. Do not
            # steal that flow unless this is explicitly a memory save command.
            if _MEMORY_SAVE_PENDING_RE.match(_clean_message(message)):
                return "I don't have a pending memory proposal to save."
            return None
        _pop_pending_proposal(vault_id, session_id)
        saved = save_memory_payload(
            vault_id=vault_id,
            key=key,
            payload=pending,
            source_message_id=source_message_id,
            is_correction=True,
        )
        return str(saved.get("message") or "Saved.")
    if intent.action == "cancel_pending":
        pending = _pop_pending_proposal(vault_id, session_id)
        if pending is None:
            return None
        return "Memory proposal cancelled."
    if intent.action == "save":
        return _save_memory(
            vault_id, key, intent, source_message_id=source_message_id
        )
    if intent.action == "propose":
        if intent.needs_clarification:
            return "I can save that memory, but I need the missing details first."
        payload = _payload_for_intent(
            intent,
            source_message_id=source_message_id,
        )
        _store_pending_proposal(vault_id, session_id, payload)
        return _proposal_envelope(intent)
    if intent.action == "recall":
        return _recall_memory(vault_id, key, intent)
    if intent.action == "forget":
        return _forget_memory(vault_id, key, intent)
    return None
