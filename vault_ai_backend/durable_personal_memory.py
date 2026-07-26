from __future__ import annotations

import hmac
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from vault_core import decrypt_message, encrypt_message, get_db


logger = logging.getLogger(__name__)


_SUPPORTED_ATTRIBUTE = "birthday"
_MEMORY_TYPE = "date"
_MAX_MESSAGE_LEN = 1000

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
    r"don(?:'|\u2019)?t\s+forget|dont\s+forget|"
    r"keep\s+this(?:\s+for\s+me)?|note\s+that)\s*:?\s+"
    r"(?P<fact>.+?)\s*$",
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
_ISO_RE = re.compile(r"^\s*(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s*$")
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
    attribute: str = _SUPPORTED_ATTRIBUTE
    normalized_value: Optional[str] = None
    display_value: Optional[str] = None
    is_correction: bool = False
    needs_clarification: bool = False

    @property
    def canonical_key(self) -> str:
        return f"{self.subject}:{self.attribute}"


def _clean_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip())[:_MAX_MESSAGE_LEN]


def _subject_parts(raw: str) -> tuple[str, str, str]:
    return _SUBJECT_ALIASES.get(raw.strip().lower(), (raw, raw, raw))


def _parse_date_text(text: str) -> tuple[Optional[str], Optional[str]]:
    value = (text or "").strip().rstrip(".")
    m = _ISO_RE.match(value)
    if m:
        y, month, day = int(m.group("y")), int(m.group("m")), int(m.group("d"))
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


def parse_personal_memory_intent(message: str) -> Optional[PersonalMemoryIntent]:
    text = _clean_message(message)
    if not text:
        return None

    m = _FORGET_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="forget",
            subject=subject,
            subject_display=display,
            relationship=relationship,
        )

    m = _RECALL_RE.match(text)
    if m:
        subject, display, relationship = _subject_parts(m.group("subject"))
        return PersonalMemoryIntent(
            action="recall",
            subject=subject,
            subject_display=display,
            relationship=relationship,
        )

    is_correction = bool(
        re.search(r"\b(?:actually|correction|correct|update|change)\b", text, re.I)
    )
    save_match = _SAVE_TRIGGER_RE.match(text)
    fact_text = save_match.group("fact") if save_match else text
    fact_match = None
    if is_correction and save_match is None:
        fact_match = _CORRECTION_RE.match(text)
    if not fact_match:
        fact_match = _FACT_RE.match(fact_text)
    if not fact_match:
        return None

    if save_match is None and not is_correction:
        return None

    subject, display, relationship = _subject_parts(fact_match.group("subject"))
    normalized, display_value = _parse_date_text(fact_match.group("value"))
    return PersonalMemoryIntent(
        action="save",
        subject=subject,
        subject_display=display,
        relationship=relationship,
        normalized_value=normalized,
        display_value=display_value,
        is_correction=is_correction,
        needs_clarification=normalized is None,
    )


def _lookup_hash(key: bytes, canonical_key: str) -> bytes:
    return hmac.new(
        key,
        f"vaultai-personal-memory/v1:{canonical_key}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _payload_for_intent(
    intent: PersonalMemoryIntent,
    *,
    source_message_id: Optional[str],
) -> dict:
    return {
        "record_type": "personal_memory",
        "category": "family",
        "subject": intent.subject,
        "subject_display": intent.subject_display,
        "relationship": intent.relationship,
        "attribute": intent.attribute,
        "normalized_value": intent.normalized_value,
        "display_value": intent.display_value,
        "source": "explicit_user_memory",
        "status": "active",
        "canonical_key": intent.canonical_key,
        "source_message_id": source_message_id,
    }


def _decode_payload(blob, key: bytes) -> Optional[dict]:
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


def _encrypted_payload(payload: dict, key: bytes) -> bytes:
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return encrypt_message(text, key).encode("utf-8")


def _fetch_active(cur, vault_id: str, digest: bytes) -> Optional[dict]:
    cur.execute(
        """SELECT id, payload_ciphertext, event_date, created_at, updated_at
           FROM vault_ai_memory
           WHERE vault_id=%s
             AND memory_lookup_hash=%s
             AND superseded_at IS NULL
           ORDER BY updated_at DESC
           LIMIT 1""",
        (vault_id, digest),
    )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {
        "id": row[0],
        "payload_ciphertext": row[1],
        "event_date": row[2] if len(row) > 2 else None,
        "created_at": row[3] if len(row) > 3 else None,
        "updated_at": row[4] if len(row) > 4 else None,
    }


def _insert_payload(cur, vault_id: str, intent: PersonalMemoryIntent, key: bytes,
                    *, source_message_id: Optional[str]) -> int:
    payload = _payload_for_intent(intent, source_message_id=source_message_id)
    cur.execute(
        """INSERT INTO vault_ai_memory (
               vault_id, memory_type, memory_key, memory_value,
               event_date, confidence, source,
               memory_language, memory_script, memory_normalized_key,
               payload_ciphertext, memory_lookup_hash
           )
           VALUES (%s, %s, NULL, NULL, %s, 1.0, 'chat',
                   NULL, NULL, NULL, %s, %s)
           RETURNING id""",
        (
            vault_id,
            _MEMORY_TYPE,
            intent.normalized_value,
            _encrypted_payload(payload, key),
            _lookup_hash(key, intent.canonical_key),
        ),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


def _format_possessive(subject_display: str) -> str:
    return f"your {subject_display}'s"


def _save_memory(
    vault_id: str,
    key: bytes,
    intent: PersonalMemoryIntent,
    *,
    source_message_id: Optional[str],
) -> str:
    if intent.needs_clarification:
        return (
            f"I can save {_format_possessive(intent.subject_display)} "
            "birthday, but I need the full date, including the year."
        )

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
            if prior_norm == intent.normalized_value:
                cur.execute(
                    "UPDATE vault_ai_memory SET updated_at=NOW() "
                    "WHERE id=%s AND vault_id=%s",
                    (existing["id"], vault_id),
                )
                conn.commit()
                return (
                    f"I already have that saved: "
                    f"{_format_possessive(intent.subject_display)} birthday "
                    f"is {intent.display_value}."
                )
            if not intent.is_correction:
                conn.rollback()
                return (
                    f"I already have {_format_possessive(intent.subject_display)} "
                    f"birthday as {prior_display or 'a different date'}. "
                    "If that is wrong, tell me it is actually the new date."
                )
            new_id = _insert_payload(
                cur, vault_id, intent, key, source_message_id=source_message_id
            )
            cur.execute(
                """UPDATE vault_ai_memory
                      SET superseded_at=NOW(), superseded_by_id=%s
                    WHERE id=%s AND vault_id=%s""",
                (new_id, existing["id"], vault_id),
            )
            conn.commit()
            return (
                f"Updated: {_format_possessive(intent.subject_display)} "
                f"birthday is {intent.display_value}."
            )

        _insert_payload(cur, vault_id, intent, key, source_message_id=source_message_id)
        conn.commit()
        return (
            f"Saved: {_format_possessive(intent.subject_display)} birthday "
            f"is {intent.display_value}."
        )
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
        return f"I don't have {_format_possessive(intent.subject_display)} birthday saved yet."
    payload = _decode_payload(existing.get("payload_ciphertext"), key)
    if not payload or payload.get("status") != "active":
        return f"I don't have {_format_possessive(intent.subject_display)} birthday saved yet."
    display = payload.get("display_value")
    if not display:
        return f"I don't have {_format_possessive(intent.subject_display)} birthday saved yet."
    return f"{_format_possessive(intent.subject_display).capitalize()} birthday is {display}."


def _forget_memory(vault_id: str, key: bytes, intent: PersonalMemoryIntent) -> str:
    digest = _lookup_hash(key, intent.canonical_key)
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        existing = _fetch_active(cur, vault_id, digest)
        if not existing:
            conn.rollback()
            return f"I don't have {_format_possessive(intent.subject_display)} birthday saved yet."
        cur.execute(
            """UPDATE vault_ai_memory
                  SET superseded_at=NOW()
                WHERE id=%s AND vault_id=%s""",
            (existing["id"], vault_id),
        )
        conn.commit()
        return f"Forgot {_format_possessive(intent.subject_display)} birthday."
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


def handle_personal_memory_turn(
    *,
    vault_id: str,
    key: bytes,
    message: str,
    source_message_id: Optional[str] = None,
) -> Optional[str]:
    intent = parse_personal_memory_intent(message)
    if intent is None:
        return None
    if intent.action == "save":
        return _save_memory(
            vault_id, key, intent, source_message_id=source_message_id
        )
    if intent.action == "recall":
        return _recall_memory(vault_id, key, intent)
    if intent.action == "forget":
        return _forget_memory(vault_id, key, intent)
    return None
