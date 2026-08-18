"""Page-aware extraction of reviewable secure records from documents.

The serialized layout markers live only inside the vault-encrypted extracted
text.  They preserve page and record boundaries without logging field values
or sending them to an external classifier.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Optional


MAX_SECURE_DOCUMENT_RECORDS = 200
PAGE_MARKER_RE = re.compile(r"^\[\[SVAULTAI_PAGE:(\d+)\]\]$")
RECORD_MARKER_RE = re.compile(
    r"^\[\[SVAULTAI_RECORD:([^\]]+)\]\]$"
)


@dataclass(frozen=True)
class _LayoutRecord:
    page_numbers: tuple[int, ...]
    source_ref: str
    lines: tuple[str, ...]


_FIELD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("username", re.compile(
        r"^\s*(?:user\s*name|username|user|login(?:\s+id)?)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("email", re.compile(
        r"^\s*(?:e-?mail(?:\s+address)?)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("password", re.compile(
        r"^\s*(?:password|passwd|pass|pwd)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("pin", re.compile(
        r"^\s*(?:pin(?:\s+(?:code|number))?)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("account_number", re.compile(
        r"^\s*(?:account|acct)(?:\s+(?:number|no\.?|#))\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("secure_identifier", re.compile(
        r"^\s*(?:(?:account|member|customer|client|secure)\s+id(?:entifier)?|identifier|secure\s+identifier)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("access_code", re.compile(
        r"^\s*(?:(?:recovery|access|verification|auth|2fa|otp)\s+code)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("url", re.compile(
        r"^\s*(?:website|url|site)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
    ("note", re.compile(
        r"^\s*(?:note|notes)\s*[:=\-]?\s+(.+)$",
        re.IGNORECASE,
    )),
)

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$"
)
_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)


def _join_spans(line: dict) -> str:
    return " ".join(
        str(span.get("text") or "").strip()
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
    ).strip()


def _page_layout_groups(page: object) -> list[list[str]]:
    rows: list[tuple[float, float, str]] = []
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            text = _join_spans(line)
            if not text:
                continue
            bbox = line.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            rows.append((float(bbox[1]), float(bbox[0]), text))
    rows.sort(key=lambda row: (row[0], row[1]))
    if not rows:
        return []

    distinct_y = sorted({round(row[0], 1) for row in rows})
    positive_steps = [
        second - first
        for first, second in zip(distinct_y, distinct_y[1:])
        if second - first > 2.0
    ]
    baseline = median(positive_steps) if positive_steps else 18.0
    record_gap = max(30.0, baseline * 1.55)

    groups: list[list[str]] = []
    current: list[str] = []
    previous_y: Optional[float] = None
    for y, _x, text in rows:
        if previous_y is not None and y - previous_y > record_gap and current:
            groups.append(current)
            current = []
        current.append(text)
        previous_y = y
    if current:
        groups.append(current)
    return groups


def extract_pdf_text_with_layout(file_bytes: bytes) -> Optional[str]:
    """Return all PDF pages with deterministic page/record boundaries."""
    try:
        import pymupdf

        document = pymupdf.open(stream=file_bytes, filetype="pdf")
        pages: list[list[list[str]]] = [
            _page_layout_groups(page) for page in document
        ]
        document.close()
    except Exception:
        return None

    # A title orphaned at the bottom of a page belongs to the first record on
    # the next page.  Preserve both page numbers in its provenance.
    merged_from_previous: dict[int, tuple[int, int, list[str]]] = {}
    for page_index in range(len(pages) - 1):
        if (
            pages[page_index]
            and len(pages[page_index][-1]) == 1
            and pages[page_index + 1]
        ):
            previous_record_index = len(pages[page_index])
            title = pages[page_index].pop()
            merged_from_previous[page_index + 1] = (
                page_index + 1,
                previous_record_index,
                title,
            )

    output: list[str] = []
    for page_index, groups in enumerate(pages):
        page_number = page_index + 1
        output.append(f"[[SVAULTAI_PAGE:{page_number}]]")
        if page_index in merged_from_previous and groups:
            previous_page, previous_record_index, title = (
                merged_from_previous[page_index]
            )
            groups[0] = title + groups[0]
            source_page = previous_page
            page_suffix = f"-p{page_number}"
        else:
            source_page = page_number
            page_suffix = ""
        for record_index, lines in enumerate(groups, 1):
            source_record_index = (
                previous_record_index
                if page_index in merged_from_previous and record_index == 1
                else record_index
            )
            source_ref = (
                f"p{source_page}-r{source_record_index}{page_suffix}"
            )
            output.append(f"[[SVAULTAI_RECORD:{source_ref}]]")
            output.extend(lines)
    return "\n".join(output).strip() or None


def _parse_layout_records(text: str) -> tuple[list[_LayoutRecord], set[int]]:
    records: list[_LayoutRecord] = []
    pages_with_text: set[int] = set()
    current_page = 1
    current_ref: Optional[str] = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_ref, current_lines
        if current_ref and current_lines:
            page_numbers = tuple(
                sorted({int(value) for value in re.findall(r"p(\d+)", current_ref)})
            ) or (current_page,)
            records.append(_LayoutRecord(
                page_numbers=page_numbers,
                source_ref=current_ref,
                lines=tuple(current_lines),
            ))
            pages_with_text.update(page_numbers)
        current_ref = None
        current_lines = []

    for raw_line in text.splitlines():
        page_match = PAGE_MARKER_RE.match(raw_line.strip())
        if page_match:
            flush()
            current_page = int(page_match.group(1))
            continue
        record_match = RECORD_MARKER_RE.match(raw_line.strip())
        if record_match:
            flush()
            current_ref = record_match.group(1)
            continue
        if current_ref is not None and raw_line != "":
            current_lines.append(raw_line)
    flush()
    return records, pages_with_text


def _parse_labelled_value(line: str) -> tuple[Optional[str], Optional[str]]:
    for field, pattern in _FIELD_PATTERNS:
        match = pattern.match(line)
        if match:
            # Do not normalize, lowercase, or strip punctuation from values.
            value = match.group(1)
            return field, value if value != "" else None
    return None, None


def _looks_like_title(line: str) -> bool:
    field, _value = _parse_labelled_value(line)
    if field is not None or _EMAIL_RE.fullmatch(line) or _URL_RE.fullmatch(line):
        return False
    if line.isdigit():
        return False
    return True


def _put_unique(fields: dict[str, str], name: str, value: str) -> None:
    if name not in fields:
        fields[name] = value
        return
    index = 2
    while f"{name}_{index}" in fields:
        index += 1
    fields[f"{name}_{index}"] = value


def _record_type(fields: dict[str, str]) -> tuple[str, str]:
    if "access_code" in fields:
        return "recovery_or_access_code", "RECOVERY_OR_ACCESS_CODE"
    if "account_number" in fields:
        if len(fields) == 1:
            return "account_number", "ACCOUNT_NUMBER"
        return "account", "ACCOUNT"
    if "password" in fields:
        return "login", "LOGIN"
    if "pin" in fields:
        return "pin", "PIN"
    if "url" in fields and len(fields) == 1:
        return "url", "URL"
    if any(key in fields for key in ("username", "email", "secure_identifier")):
        return "secure_identifier", "SECURE_IDENTIFIER"
    return "other_secure_record", "OTHER_SECURE_RECORD"


def _normalize_layout_record(record: _LayoutRecord) -> Optional[dict]:
    lines = [line for line in record.lines if line != ""]
    if not lines:
        return None

    if _looks_like_title(lines[0]):
        service = lines.pop(0)
    else:
        service = f"Secure record {record.source_ref}"

    fields: dict[str, str] = {}
    unlabeled: list[str] = []
    for line in lines:
        field, value = _parse_labelled_value(line)
        if field and value is not None:
            _put_unique(fields, field, value)
        elif _EMAIL_RE.fullmatch(line):
            _put_unique(fields, "email", line)
        elif _URL_RE.fullmatch(line):
            _put_unique(fields, "url", line)
        elif line.isdigit() and len(line) <= 8:
            _put_unique(fields, "pin", line)
        elif line.isdigit() and len(line) >= 9:
            _put_unique(fields, "account_number", line)
        else:
            unlabeled.append(line)

    if unlabeled:
        if "email" not in fields and "username" not in fields and len(unlabeled) > 1:
            fields["username"] = unlabeled.pop(0)
        if unlabeled and "password" not in fields:
            fields["password"] = unlabeled.pop(0)
        for value in unlabeled:
            _put_unique(fields, "secure_value", value)

    if not fields:
        return None
    secret_type, public_type = _record_type(fields)
    source_material = "\n".join(record.lines).encode("utf-8")
    return {
        "secret_type": secret_type,
        "record_type": public_type,
        "service": service,
        "fields": fields,
        "provenance": {
            "page_number": record.page_numbers[0],
            "page_numbers": list(record.page_numbers),
            "source_ref": record.source_ref,
            "source_span_hash": hashlib.sha256(source_material).hexdigest(),
        },
    }


def extract_secure_records(text: str) -> list[dict]:
    """Extract mixed secure records while retaining duplicates for review."""
    layout_records, _pages = _parse_layout_records(text or "")
    if layout_records:
        normalized = [
            record for record in (
                _normalize_layout_record(raw) for raw in layout_records
            ) if record is not None
        ]
        return normalized[:MAX_SECURE_DOCUMENT_RECORDS]

    # Plain-text/DOCX/OCR compatibility keeps the established labelled parser.
    from extractor import extract_multiple_credentials

    records = extract_multiple_credentials(text or "")
    for index, record in enumerate(records, 1):
        record.setdefault("record_type", "LOGIN")
        record.setdefault("provenance", {
            "page_number": 1,
            "page_numbers": [1],
            "source_ref": f"text-r{index}",
            "source_span_hash": hashlib.sha256(
                repr(record).encode("utf-8")
            ).hexdigest(),
        })
    return records[:MAX_SECURE_DOCUMENT_RECORDS]


def extraction_counts(text: str, records: Iterable[dict]) -> dict[str, int]:
    layout_records, pages_with_text = _parse_layout_records(text or "")
    record_list = list(records)
    page_markers = {
        int(match.group(1))
        for line in (text or "").splitlines()
        if (match := PAGE_MARKER_RE.match(line.strip()))
    }
    return {
        "pdf_page_count": len(page_markers),
        "text_extraction_page_count": len(pages_with_text),
        "ocr_page_count": 0,
        "raw_secret_candidate_count": len(layout_records) or len(record_list),
        "normalized_record_count": len(record_list),
        "ui_rendered_record_count": len(record_list),
    }


def has_structured_layout(text: Optional[str]) -> bool:
    return bool(text and "[[SVAULTAI_PAGE:" in text)


__all__ = [
    "MAX_SECURE_DOCUMENT_RECORDS",
    "extract_pdf_text_with_layout",
    "extract_secure_records",
    "extraction_counts",
    "has_structured_layout",
]
