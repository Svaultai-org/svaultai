

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


DEFAULT_RECENT_FILES_LIMIT = 10
DEFAULT_TOP_FOLDERS_LIMIT = 8
DEFAULT_CREDENTIAL_FILES_LIMIT = 25


_TRAVEL_DOC_TYPES: tuple[str, ...] = (
    "passport",
    "visa",
    "boarding_pass",
    "ticket",
    "hotel_itinerary",
)


_CREDENTIAL_FILENAME_HINTS: tuple[str, ...] = (
    "password", "passwords", "credentials", "credential",
    "login", "logins", "secret", "secrets", "auth", "token",
    "api-key", "apikey", "api_key", ".env", "env.local",
    "keystore", "keypass", "1password", "bitwarden", "lastpass",
    "wallet", "seedphrase", "seed-phrase", "mnemonic",
)


_CREDENTIAL_FOLDER_HINTS: tuple[str, ...] = (
    "credentials", "passwords", "secrets", "logins", "auth",
)


_CONTENT_USER_PATTERNS: dict[str, re.Pattern[str]] = {
    "username": re.compile(
        r"(?im)^\s*(?:user(?:name)?|user[\-_]?id|login[\-_]?id|account)\s*[:=]",
    ),
    "email": re.compile(
        r"(?im)^\s*(?:e[\-_]?mail(?:[\-_]?address)?|email[\-_]?address)\s*[:=]",
    ),
    "login_label": re.compile(
        r"(?im)^\s*login\s*[:=]",
    ),
}

_CONTENT_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "password": re.compile(
        r"(?im)^\s*(?:password|passwd|pass[\-_]?word|pass)\s*[:=]",
    ),
    "token": re.compile(
        r"(?im)^\s*(?:token|access[\-_]?token|bearer[\-_]?token|"
        r"auth[\-_]?token|jwt|refresh[\-_]?token)\s*[:=]",
    ),
    "api_key": re.compile(
        r"(?im)^\s*(?:api[\-_]?key|api[\-_]?secret|secret[\-_]?key|"
        r"app[\-_]?key|aws[\-_]?access[\-_]?key[\-_]?id|"
        r"aws[\-_]?secret[\-_]?access[\-_]?key)\s*[:=]",
    ),
    "secret": re.compile(
        r"(?im)^\s*(?:secret|client[\-_]?secret|app[\-_]?secret)\s*[:=]",
    ),
    "private_key": re.compile(
        r"(?im)^\s*(?:private[\-_]?key|priv[\-_]?key)\s*[:=]"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ),
    "mnemonic": re.compile(
        r"(?im)^\s*(?:mnemonic|seed[\-_]?phrase|recovery[\-_]?phrase|"
        r"recovery phrase|seed phrase)\s*[:=]?",
    ),
}

                                                             
_RAW_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)


_PWD_LIKE_LINE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:'\",.<>/?\\|`~]{5,47}$",
)

                                                             
_SERVICE_NAME_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z][A-Za-z0-9 .&\-]{0,38}$",
)

                                                         
_USERNAME_LIKE_LINE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9._\-]{1,30}$",
)

                                                                  
_SERVICE_NAME_REJECT_RE = re.compile(
    r"^(?:https?://|www\.|\d+(?:\.\d+)*|[A-Z]{1,3}\d+)$",
)

                                                              
_REPEATED_BLOCK_THRESHOLD = 3

                                                                 
_REPEATED_BLOCK_LINE_CAP = 4_000


def _looks_like_password(line: str) -> bool:
    if not _PWD_LIKE_LINE_RE.match(line):
        return False
    has_alpha = any(c.isalpha() for c in line)
    has_digit_or_punct = any(
        (c.isdigit() or not c.isalnum()) for c in line
    )
    if not (has_alpha and has_digit_or_punct):
        return False
                                                                   
    if line.isalpha():
        return False
                                                                 
                                                            
    if line.isdigit():
        return False
    return True


_STRICT_DOMAIN_TLD_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9\-]{0,63}"
    r"\.(?:com|org|net|io|co|gov|edu|info|biz|app|dev|me|us|uk|de|fr|"
    r"jp|cn|tv|tech|cloud|ai|xyz|club|store|online|site|blog|page|"
    r"finance|exchange|wallet|crypto|chain|scan|explorer)$",
    re.IGNORECASE,
)

                                                                   
_STRICT_PWD_STRONG_SPECIAL = "!@#$%^&*()+={};:'\",<>/?\\|`~[]"

                                                                
_STRICT_PWD_MIN_LEN = 8


def _looks_like_password_value(line: str) -> bool:


    if not _PWD_LIKE_LINE_RE.match(line):
        return False
    if len(line) < _STRICT_PWD_MIN_LEN:
        return False
    if line.isalpha() or line.isdigit():
        return False
                                        
    if _looks_like_email(line):
        return False
                                                                   
                    
    if _STRICT_DOMAIN_TLD_RE.match(line):
        return False
    has_letter = any(c.isalpha() for c in line)
    has_digit = any(c.isdigit() for c in line)
    has_strong_special = any(c in _STRICT_PWD_STRONG_SPECIAL for c in line)
    if not has_letter:
        return False
    if not (has_digit or has_strong_special):
        return False
    return True


def _looks_like_identifier_value(line: str) -> bool:


    if _looks_like_email(line):
        return True
    if not _USERNAME_LIKE_LINE_RE.match(line):
        return False
    if _STRICT_DOMAIN_TLD_RE.match(line):
        return False
                                                                
                                                              
    if line.isalpha():
        return False
    return True


def _count_complete_credential_records(text: Optional[str]) -> dict:


    if not text:
        return {"complete_records": 0, "complete_services": []}

    raw_lines = text.splitlines()
    if len(raw_lines) > _REPEATED_BLOCK_LINE_CAP:
        raw_lines = raw_lines[:_REPEATED_BLOCK_LINE_CAP]

    lines: list[str] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if stripped:
            lines.append(stripped)

    n = len(lines)
    if n < 3:                                               
        return {"complete_records": 0, "complete_services": []}

    records = 0
    services_seen: set[str] = set()
    services: list[str] = []

    i = 0
    while i < n - 2:
        l0 = lines[i]
        if not _looks_like_service_name(l0) or _STRICT_DOMAIN_TLD_RE.match(l0):
            i += 1
            continue
                                                                
                                                          
        identifier_idx: Optional[int] = None
        password_idx: Optional[int] = None
        end = min(i + 4, n)
        for k in range(i + 1, end):
            line_k = lines[k]
            if identifier_idx is None and _looks_like_identifier_value(line_k):
                identifier_idx = k
                continue
            if password_idx is None and _looks_like_password_value(line_k):
                password_idx = k
        if (
            identifier_idx is not None
            and password_idx is not None
            and identifier_idx != password_idx
        ):
            records += 1
            if l0 not in services_seen and len(services) < 5:
                services_seen.add(l0)
                services.append(l0)
            i = max(identifier_idx, password_idx) + 1
            continue
        i += 1

    return {
        "complete_records":  records,
        "complete_services": services,
    }


def _has_complete_credential_record(text: Optional[str]) -> bool:


    return _count_complete_credential_records(text)["complete_records"] >= 1


_LABELLED_USER_VALUE_RE = re.compile(
    r"(?im)^\s*(?:user(?:name)?|user[\-_]?id|login(?:[\-_]?id)?|"
    r"account|e[\-_]?mail(?:[\-_]?address)?|email[\-_]?address)"
    r"\s*[:=]\s*\S+",
)

_LABELLED_PWD_VALUE_RE = re.compile(
    r"(?im)^\s*(?:password|passwd|pass[\-_]?word|pass|token|"
    r"access[\-_]?token|bearer[\-_]?token|auth[\-_]?token|jwt|"
    r"refresh[\-_]?token|api[\-_]?key|api[\-_]?secret|"
    r"secret[\-_]?key|app[\-_]?key|aws[\-_]?access[\-_]?key[\-_]?id|"
    r"aws[\-_]?secret[\-_]?access[\-_]?key|secret|"
    r"client[\-_]?secret|app[\-_]?secret|private[\-_]?key|"
    r"priv[\-_]?key|mnemonic|seed[\-_]?phrase|recovery[\-_]?phrase)"
    r"\s*[:=]\s*\S+",
)


def _count_labelled_pair_credential_records(text: Optional[str]) -> int:


    if not text:
        return 0
    snippet = text[:_CONTENT_SCAN_BYTE_CAP]
    user_hits = len(_LABELLED_USER_VALUE_RE.findall(snippet))
    pwd_hits = len(_LABELLED_PWD_VALUE_RE.findall(snippet))
                                                                   
                                                                
    user_ws = len(_LABELLED_USER_WHITESPACE_VALUE_RE.findall(snippet))
    pwd_ws = len(_LABELLED_PWD_WHITESPACE_VALUE_RE.findall(snippet))
    return min(user_hits + user_ws, pwd_hits + pwd_ws)


_LABELLED_USER_WHITESPACE_VALUE_RE = re.compile(
    r"(?im)^\s*(?:user(?:name)?|user[\-_]?id|login(?:[\-_]?id)?|"
    r"account|e[\-_]?mail(?:[\-_]?address)?|email[\-_]?address)"
    r"\s{2,}(\S+)\s*$",
)

_LABELLED_PWD_WHITESPACE_VALUE_RE = re.compile(
    r"(?im)^\s*(?:password|passwd|pass[\-_]?word|pass|token|"
    r"access[\-_]?token|bearer[\-_]?token|auth[\-_]?token|jwt|"
    r"refresh[\-_]?token|api[\-_]?key|api[\-_]?secret|"
    r"secret[\-_]?key|app[\-_]?key|aws[\-_]?access[\-_]?key[\-_]?id|"
    r"aws[\-_]?secret[\-_]?access[\-_]?key|secret|"
    r"client[\-_]?secret|app[\-_]?secret|private[\-_]?key|"
    r"priv[\-_]?key|mnemonic|seed[\-_]?phrase|recovery[\-_]?phrase)"
    r"\s{2,}(\S+)\s*$",
)

                                                                        
_INLINE_LABELLED_PAIR_RE = re.compile(
    r"(?i)\b(?:user(?:name)?|email|login)\b\s*[:=]?\s*(\S+)\s+"
    r"(?:password|token|secret|api[\-_]?key)\b\s*[:=]?\s*(\S+)",
)


def _split_tabular_cells(line: str) -> list[str]:


    parts = re.split(r"\s*\|\s*|\t+|\s{2,}", line.strip())
    return [p.strip() for p in parts if p.strip()]


def _looks_like_tabular_credential_row(line: str) -> bool:


    cells = _split_tabular_cells(line)
    if len(cells) < 3:
        return False
    has_service = False
    has_identifier = False
    has_password = False
    for c in cells:
        if not has_service and _looks_like_service_name(c) \
                and not _STRICT_DOMAIN_TLD_RE.match(c):
            has_service = True
            continue
        if not has_identifier and _looks_like_identifier_value(c):
            has_identifier = True
            continue
        if not has_password and _looks_like_password_value(c):
            has_password = True
            continue
    return has_service and has_identifier and has_password


def _count_tabular_credential_rows(text: Optional[str]) -> int:


    if not text:
        return 0
    snippet = text[:_CONTENT_SCAN_BYTE_CAP]
    raw_lines = snippet.splitlines()
    if len(raw_lines) > _REPEATED_BLOCK_LINE_CAP:
        raw_lines = raw_lines[:_REPEATED_BLOCK_LINE_CAP]
    count = 0
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
                                                                      
                                                    
        if _looks_like_tabular_header(line):
            continue
        if _looks_like_tabular_credential_row(line):
            count += 1
    return count


_TABULAR_HEADER_TOKENS = frozenset({
    "service", "site", "app", "account", "platform",
    "username", "user", "email", "login", "user id", "userid",
    "password", "passwd", "token", "api key", "secret",
})


def _looks_like_tabular_header(line: str) -> bool:


    cells = [c.lower() for c in _split_tabular_cells(line)]
    if len(cells) < 2:
        return False
    return all(c in _TABULAR_HEADER_TOKENS for c in cells)


def _count_inline_labelled_pairs(text: Optional[str]) -> int:


    if not text:
        return 0
    snippet = text[:_CONTENT_SCAN_BYTE_CAP]
    count = 0
    for ident, secret in _INLINE_LABELLED_PAIR_RE.findall(snippet):
        if _looks_like_identifier_value(ident) \
                and _looks_like_password_value(secret):
            count += 1
    return count


def _looks_like_service_name(line: str) -> bool:
    if not _SERVICE_NAME_LINE_RE.match(line):
        return False
    if _SERVICE_NAME_REJECT_RE.match(line):
        return False
    return True


def _looks_like_username(line: str) -> bool:
    if "@" in line:
        return False
    if not _USERNAME_LIKE_LINE_RE.match(line):
        return False
                                                                 
                                                           
    return True


def _looks_like_email(line: str) -> bool:
                                                                
                                                              
    return bool(_RAW_EMAIL_RE.fullmatch(line))


def _count_repeated_credential_blocks(text: Optional[str]) -> int:


    return int(
        _compute_credential_density_metrics(text)
        .get("credential_block_count", 0)
    )


_MOSTLY_CREDENTIALS_DENSITY = 0.50
_MOSTLY_CREDENTIALS_MIN_BLOCKS = 3
_MOSTLY_CREDENTIALS_MIN_LINES = 9


def _compute_credential_density_metrics(text: Optional[str]) -> dict:


    zero_result = {
        "credential_block_count": 0,
        "service_count": 0,
        "service_names": [],
        "credential_like_lines": 0,
        "meaningful_lines": 0,
        "credential_density": 0.0,
        "mostly_credentials": False,
    }
    if not text:
        return zero_result

    raw_lines = text.splitlines()
    if len(raw_lines) > _REPEATED_BLOCK_LINE_CAP:
        raw_lines = raw_lines[:_REPEATED_BLOCK_LINE_CAP]

    lines: list[str] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if stripped:
            lines.append(stripped)

    meaningful_lines = len(lines)
    if meaningful_lines == 0:
        return zero_result

                                                                     
    block_consumed = [False] * meaningful_lines
    services: list[str] = []
    services_seen: set[str] = set()
    blocks = 0
    i = 0
    n = meaningful_lines
    while i < n - 1:
        l0 = lines[i]
        if not _looks_like_service_name(l0):
            i += 1
            continue
        l1 = lines[i + 1]
        l2 = lines[i + 2] if (i + 2) < n else None

        pwd_like_in_window = (
            _looks_like_password(l1)
            or (l2 is not None and _looks_like_password(l2))
        )
        identifier_in_window = (
            _looks_like_email(l1)
            or _looks_like_username(l1)
            or (
                l2 is not None
                and (_looks_like_email(l2) or _looks_like_username(l2))
            )
        )
        if pwd_like_in_window and identifier_in_window:
            blocks += 1
            if l0 not in services_seen:
                services_seen.add(l0)
                services.append(l0)
            block_consumed[i] = True
            block_consumed[i + 1] = True
            if l2 is not None:
                block_consumed[i + 2] = True
                i += 3
            else:
                i += 2
            continue
        if pwd_like_in_window:
            blocks += 1
            if l0 not in services_seen:
                services_seen.add(l0)
                services.append(l0)
            block_consumed[i] = True
            block_consumed[i + 1] = True
            i += 2
            continue
        i += 1

                                                                 
    credential_like = sum(1 for consumed in block_consumed if consumed)
    for idx, line in enumerate(lines):
        if block_consumed[idx]:
            continue
        if _line_matches_credential_label(line) or _looks_like_email(line):
            credential_like += 1

    density = (
        credential_like / meaningful_lines if meaningful_lines else 0.0
    )
    mostly = bool(
        density >= _MOSTLY_CREDENTIALS_DENSITY
        and (
            blocks >= _MOSTLY_CREDENTIALS_MIN_BLOCKS
            or credential_like >= _MOSTLY_CREDENTIALS_MIN_LINES
        )
    )
                                                                  
                                                              
    service_names_sample = services[:5]
    return {
        "credential_block_count": blocks,
        "service_count": len(services),
        "service_names": service_names_sample,
        "credential_like_lines": credential_like,
        "meaningful_lines": meaningful_lines,
        "credential_density": round(density, 4),
        "mostly_credentials": mostly,
    }


def _line_matches_credential_label(line: str) -> bool:


    for pat in _CONTENT_USER_PATTERNS.values():
        if pat.search(line):
            return True
    for pat in _CONTENT_SECRET_PATTERNS.values():
        if pat.search(line):
            return True
    return False

                                                                
_CONTENT_SCAN_BYTE_CAP = 200_000

                                                                 
CREDENTIAL_CONFIDENCE_STRONG = "strong"
CREDENTIAL_CONFIDENCE_MEDIUM = "medium"
CREDENTIAL_CONFIDENCE_WEAK = "weak"
CREDENTIAL_CONFIDENCE_LEVELS = (
    CREDENTIAL_CONFIDENCE_STRONG,
    CREDENTIAL_CONFIDENCE_MEDIUM,
    CREDENTIAL_CONFIDENCE_WEAK,
)


CREDENTIAL_TIER_CONFIRMED = "confirmed"
CREDENTIAL_TIER_POSSIBLE = "possible"
CREDENTIAL_TIER_FILENAME_ONLY = "filename_only"
CREDENTIAL_TIER_NAMES = (
    CREDENTIAL_TIER_CONFIRMED,
    CREDENTIAL_TIER_POSSIBLE,
    CREDENTIAL_TIER_FILENAME_ONLY,
)

                                                                  
_CONFIDENCE_TO_TIER: dict[str, str] = {
    CREDENTIAL_CONFIDENCE_STRONG: CREDENTIAL_TIER_CONFIRMED,
    CREDENTIAL_CONFIDENCE_MEDIUM: CREDENTIAL_TIER_POSSIBLE,
    CREDENTIAL_CONFIDENCE_WEAK:   CREDENTIAL_TIER_FILENAME_ONLY,
}


def _section_tier_for_confidence(confidence: Optional[str]) -> str:


    return _CONFIDENCE_TO_TIER.get(
        (confidence or "").lower(),
        CREDENTIAL_TIER_FILENAME_ONLY,
    )


def _scan_content_for_credentials(text: Optional[str]) -> dict:


    if not text:
        return {
            "user_labels": [],
            "secret_labels": [],
            "has_raw_email": False,
            "repeated_blocks": 0,
            "credential_block_count": 0,
            "service_count": 0,
            "service_names": [],
            "credential_density": 0.0,
            "mostly_credentials": False,
            "credential_like_lines": 0,
            "meaningful_lines": 0,
        }

    snippet = text[:_CONTENT_SCAN_BYTE_CAP]
    user_labels: list[str] = []
    for label, pat in _CONTENT_USER_PATTERNS.items():
        if pat.search(snippet):
            user_labels.append(label)

    secret_labels: list[str] = []
    for label, pat in _CONTENT_SECRET_PATTERNS.items():
        if pat.search(snippet):
            secret_labels.append(label)

    has_raw_email = bool(_RAW_EMAIL_RE.search(snippet))
    density = _compute_credential_density_metrics(snippet)
    repeated_blocks = density["credential_block_count"]
    return {
        "user_labels":             user_labels,
        "secret_labels":           secret_labels,
        "has_raw_email":           has_raw_email,
        "repeated_blocks":         repeated_blocks,
        "credential_block_count":  density["credential_block_count"],
        "service_count":           density["service_count"],
        "service_names":           density.get("service_names") or [],
        "credential_density":      density["credential_density"],
        "mostly_credentials":      density["mostly_credentials"],
        "credential_like_lines":   density["credential_like_lines"],
        "meaningful_lines":        density["meaningful_lines"],
    }


def _credential_confidence_from_signals(
    *,
    content_user_labels: list[str],
    content_secret_labels: list[str],
    has_raw_email: bool,
    repeated_blocks: int,
    filename_hit: bool,
    folder_hit: bool,
    detected_service_hit: bool,
    asset_type_hit: bool,
    tabular_records: int = 0,
    inline_pairs: int = 0,
) -> Optional[str]:


    has_user_signal = bool(content_user_labels) or has_raw_email
    has_secret_signal = bool(content_secret_labels)

                                                                   
    if tabular_records >= 1 or inline_pairs >= 1:
        return CREDENTIAL_CONFIDENCE_STRONG

    if has_secret_signal and has_user_signal:
        return CREDENTIAL_CONFIDENCE_STRONG
    if repeated_blocks >= _REPEATED_BLOCK_THRESHOLD:
        return CREDENTIAL_CONFIDENCE_STRONG
    if has_secret_signal:
        return CREDENTIAL_CONFIDENCE_MEDIUM
    if repeated_blocks >= 2:
        return CREDENTIAL_CONFIDENCE_MEDIUM
    if (
        filename_hit or folder_hit or detected_service_hit or asset_type_hit
    ):
        return CREDENTIAL_CONFIDENCE_WEAK
    return None


_TYPE_BUCKETS: dict[str, tuple[str, ...]] = {
    "PDFs":       ("pdf",),
    "Images":     ("jpg", "jpeg", "png", "gif", "webp", "heic", "tiff", "bmp"),
    "Videos":     ("mp4", "mov", "avi", "mkv", "webm", "m4v"),
    "Audio":      ("mp3", "m4a", "wav", "ogg", "flac", "aac"),
    "Documents":  ("doc", "docx", "rtf", "odt", "txt", "md"),
    "Spreadsheets": ("xls", "xlsx", "csv", "ods", "numbers"),
    "Archives":   ("zip", "tar", "gz", "tgz", "7z", "rar"),
    "Scripts":    ("py", "js", "ts", "sh", "ps1", "rb", "go", "rs"),
}


def _folder_of(relative_path: Optional[str]) -> Optional[str]:


    if not relative_path:
        return None
    rp = relative_path.strip().strip("/")
    if not rp:
        return None
    last_slash = rp.rfind("/")
    if last_slash <= 0:
        return None
    return rp[:last_slash]


def _root_folder_of(relative_path: Optional[str]) -> Optional[str]:


    if not relative_path:
        return None
    rp = relative_path.strip().strip("/")
    if not rp:
        return None
    first_slash = rp.find("/")
    if first_slash < 0:
        return None
    return rp[:first_slash]


def _extension_of(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    dot = file_name.rfind(".")
    if dot <= 0:
        return None
    return file_name[dot + 1:].lower().strip() or None


def summarize_vault_contents(rows: list[dict]) -> dict:


    total_files = len(rows)
    total_bytes = sum(int(r.get("file_size") or 0) for r in rows)

    folder_counter: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for r in rows:
        root = _root_folder_of(r.get("relative_path"))
        if root:
            folder_counter[root] += 1
        ext = _extension_of(r.get("file_name"))
        if ext:
            for label, exts in _TYPE_BUCKETS.items():
                if ext in exts:
                    type_counts[label] += 1
                    break

    top_folders = [
        {"name": name, "file_count": count}
        for name, count in folder_counter.most_common(
            DEFAULT_TOP_FOLDERS_LIMIT,
        )
    ]
    recent_files = [
        _row_to_card(r)
        for r in list_recent_files(rows, limit=DEFAULT_RECENT_FILES_LIMIT)
    ]

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "folder_count": len(folder_counter),
        "top_folders": top_folders,
        "recent_files": recent_files,
        "type_counts": dict(type_counts),
    }


def list_recent_files(
    rows: list[dict], *, limit: int = DEFAULT_RECENT_FILES_LIMIT,
) -> list[dict]:


    def _sort_key(r: dict):
        ts = r.get("created_at")
        if isinstance(ts, datetime):
                                                                  
                                                
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (1, ts)
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return (1, parsed)
            except Exception:
                return (0, datetime.min.replace(tzinfo=timezone.utc))
        return (0, datetime.min.replace(tzinfo=timezone.utc))

    sorted_rows = sorted(rows, key=_sort_key, reverse=True)
    return sorted_rows[:max(0, int(limit))]


def list_top_folders(
    rows: list[dict], *, limit: int = DEFAULT_TOP_FOLDERS_LIMIT,
) -> list[dict]:


    counter: Counter[str] = Counter()
    for r in rows:
        root = _root_folder_of(r.get("relative_path"))
        if root:
            counter[root] += 1
    return [
        {"name": name, "file_count": count}
        for name, count in counter.most_common(max(0, int(limit)))
    ]


def search_files_for_credentials(
    rows: list[dict], *, limit: int = DEFAULT_CREDENTIAL_FILES_LIMIT,
) -> list[dict]:


    report = search_files_for_credentials_report(rows, limit=limit)
    return report["matches"]


def search_files_for_credentials_report(
    rows: list[dict], *, limit: int = DEFAULT_CREDENTIAL_FILES_LIMIT,
) -> dict:


    matches: list[dict] = []
    scanned_count = 0
    not_scanned_count = 0

    for r in rows:
        file_name = (r.get("file_name") or "").lower()
        saved_name = (r.get("saved_name") or "").lower()
        relative_path = (r.get("relative_path") or "").lower()
        detected_service = (r.get("detected_service") or "").lower()
        asset_type = (r.get("asset_type") or "").lower()
        extracted_text = r.get("extracted_text")

                                             
        filename_hint: Optional[str] = None
        for hint in _CREDENTIAL_FILENAME_HINTS:
            if hint in file_name or hint in saved_name:
                filename_hint = hint
                break

        folder_hint: Optional[str] = None
        if relative_path:
            for hint in _CREDENTIAL_FOLDER_HINTS:
                if hint in relative_path:
                    folder_hint = hint
                    break

        detected_service_hit = detected_service in (
            "login", "credential", "password",
        )
        asset_type_hit = asset_type == "login"

                                                                     
        content_signals = _scan_content_for_credentials(extracted_text)
        if extracted_text:
            scanned_count += 1
        else:
            not_scanned_count += 1

                                                                 
        tabular_record_count_early = _count_tabular_credential_rows(
            extracted_text,
        )
        inline_pair_count_early = _count_inline_labelled_pairs(
            extracted_text,
        )

        confidence = _credential_confidence_from_signals(
            content_user_labels=content_signals["user_labels"],
            content_secret_labels=content_signals["secret_labels"],
            has_raw_email=content_signals["has_raw_email"],
            repeated_blocks=content_signals.get("repeated_blocks", 0),
            filename_hit=bool(filename_hint),
            folder_hit=bool(folder_hint),
            detected_service_hit=detected_service_hit,
            asset_type_hit=asset_type_hit,
            tabular_records=tabular_record_count_early,
            inline_pairs=inline_pair_count_early,
        )
        if confidence is None:
            continue

        reasons = _format_credential_reasons(
            content_signals=content_signals,
            filename_hint=filename_hint,
            folder_hint=folder_hint,
            detected_service_hit=detected_service_hit,
            asset_type_hit=asset_type_hit,
        )

                                                   
        try:
            from vault_document_purpose import (
                classify_document_purpose,
                purpose_is_credential_bearing,
                purpose_is_form_like,
                PURPOSE_RANK,
            )
            purpose_decision = classify_document_purpose(
                extracted_text, metrics=content_signals,
            )
        except Exception:
                                                                 
                                                               
            logger.exception("document-purpose classifier failed")
            purpose_decision = {
                "purpose":       "unknown",
                "confidence":    0.0,
                "evidence":      [],
                "purpose_label": "",
                "purpose_rank":  2,
            }
            purpose_is_credential_bearing = lambda p: False              
            purpose_is_form_like = lambda p: False              

        purpose = purpose_decision["purpose"]
        purpose_label = purpose_decision["purpose_label"]
        purpose_rank = purpose_decision["purpose_rank"]
        purpose_evidence = purpose_decision["evidence"]

                                                              
        if purpose_is_form_like(purpose):
            overwhelming = (
                content_signals.get("mostly_credentials")
                and int(content_signals.get("credential_block_count") or 0) >= 4
            )
            if not overwhelming:
                                                                 
                                                            
                continue
                                                             
                                   
            confidence = CREDENTIAL_CONFIDENCE_WEAK
        else:
                                                     
             
            form_field_hits = int(
                purpose_decision.get("form_field_hits") or 0
            )
            insurance_hits = int(
                purpose_decision.get("insurance_hits") or 0
            )
            gov_hit = bool(purpose_decision.get("gov_hit"))
            looks_form_borderline = (
                form_field_hits >= 2 or insurance_hits >= 1 or gov_hit
            )
            if (
                confidence == CREDENTIAL_CONFIDENCE_STRONG
                and looks_form_borderline
                and not content_signals.get("mostly_credentials")
            ):
                confidence = CREDENTIAL_CONFIDENCE_MEDIUM

                                                            
        if purpose_evidence and purpose_decision["confidence"] >= 0.75:
                                                                 
                                                            
            reasons = list(purpose_evidence) + reasons

                                                                 
        elif content_signals.get("mostly_credentials"):
            reasons = (
                ["file appears to be mostly a credential list"] + reasons
            )

                                                                  
        tier = _section_tier_for_confidence(confidence)
        password_present = bool(
            content_signals.get("secret_labels")
        ) or int(content_signals.get("repeated_blocks") or 0) >= 1
        safe_service_names = list(
            content_signals.get("service_names") or []
        )[:5]
        safe_identifier_count = (
            len(content_signals.get("user_labels") or [])
            + (1 if content_signals.get("has_raw_email") else 0)
        )

                                                                   
        strict_blocks = _count_complete_credential_records(extracted_text)
        complete_record_count = int(strict_blocks.get("complete_records") or 0)
        complete_service_names = list(
            strict_blocks.get("complete_services") or []
        )
        labelled_pair_count = _count_labelled_pair_credential_records(
            extracted_text,
        )
                                                                 
                                                                   
        tabular_record_count = tabular_record_count_early
        inline_pair_count = inline_pair_count_early
                                                                   
                                                               
        has_credential_value = (
            complete_record_count >= 1
            or labelled_pair_count >= 1
            or tabular_record_count >= 1
            or inline_pair_count >= 1
        )

        matches.append({
            **_row_to_card(r),
            "reasons":                reasons,
            "confidence":             confidence,
            "tier":                   tier,
            "password_present":       has_credential_value,
            "safe_service_names":     safe_service_names,
            "safe_identifier_count":  int(safe_identifier_count),
            "purpose":                purpose,
            "purpose_label":          purpose_label,
            "purpose_rank":           purpose_rank,
                                                             
                                                            
            "complete_record_count":  complete_record_count,
            "complete_service_names": complete_service_names,
            "labelled_pair_count":    int(labelled_pair_count),
            "tabular_record_count":   int(tabular_record_count),
            "inline_pair_count":      int(inline_pair_count),
            "has_credential_value":   bool(has_credential_value),
            "credential_block_count": int(
                content_signals.get("credential_block_count") or 0
            ),
            "service_count":          int(
                content_signals.get("service_count") or 0
            ),
            "credential_density":     float(
                content_signals.get("credential_density") or 0.0
            ),
            "mostly_credentials":     bool(
                content_signals.get("mostly_credentials") or False
            ),
            "credential_like_lines":  int(
                content_signals.get("credential_like_lines") or 0
            ),
            "meaningful_lines":       int(
                content_signals.get("meaningful_lines") or 0
            ),
                                                                 
                                                              
            "_content_sha256":        r.get("content_sha256"),
            "_created_at":            r.get("created_at"),
        })

                                       
    def _purpose_rank_for_sort(m: dict) -> int:
                                                                 
                                                           
        v = m.get("purpose_rank")
        return int(v) if isinstance(v, int) else 2

    matches.sort(
        key=lambda m: (
            _purpose_rank_for_sort(m),
            not bool(m.get("mostly_credentials")),
            -float(m.get("credential_density") or 0.0),
            -int(m.get("credential_block_count") or 0),
            CREDENTIAL_CONFIDENCE_LEVELS.index(m["confidence"]),
            (m.get("saved_name") or m.get("file_name") or "").lower(),
        )
    )

    matches = _collapse_credential_duplicates(matches)
    matches = _mark_credential_best_match(matches)
                                                                  
                                                                  
    for _m in matches:
        _sha = _m.get("_content_sha256")
        if _sha:
            _m["content_sha256"] = _sha
    cleaned = [
        {k: v for k, v in m.items() if not k.startswith("_")}
        for m in matches[:max(0, int(limit))]
    ]

                                                                   
    sections: dict[str, list[dict]] = {
        tier: [] for tier in CREDENTIAL_TIER_NAMES
    }
    for row in cleaned:
        tier = (row.get("tier") or "").lower()
        if tier not in sections:
            tier = CREDENTIAL_TIER_FILENAME_ONLY
        sections[tier].append(row)
    has_content_matches = bool(
        sections[CREDENTIAL_TIER_CONFIRMED]
        or sections[CREDENTIAL_TIER_POSSIBLE]
    )

    return {
        "matches": cleaned,
        "scanned_count": scanned_count,
        "not_scanned_count": not_scanned_count,
        "sections": sections,
        "has_content_matches": has_content_matches,
    }


VERIFIER_REJECT_REASONS: tuple[str, ...] = (
    "rejected_form_like",
    "rejected_no_extracted_text",
    "rejected_no_secret_value",
    "rejected_no_identifier",
    "rejected_no_service_context",
    "rejected_no_complete_record",
    "rejected_keyword_list",
    "rejected_filename_only",
    "rejected_duplicate_collapsed",
    "rejected_unsupported_type",
)


def _classify_credential_reject_reason(m: dict) -> Optional[str]:


    purpose = (m.get("purpose") or "").lower()
    try:
        from vault_document_purpose import purpose_is_form_like
    except Exception:
        purpose_is_form_like = lambda p: False              
    if purpose_is_form_like(purpose):
        return "rejected_form_like"

    complete_records = int(m.get("complete_record_count") or 0)
    labelled_pairs = int(m.get("labelled_pair_count") or 0)
    has_value = bool(m.get("has_credential_value"))
    identifier_count = int(m.get("safe_identifier_count") or 0)
    block_count = int(m.get("credential_block_count") or 0)
    service_count = int(m.get("service_count") or 0)
    tabular_rows = int(m.get("tabular_record_count") or 0)
    inline_pairs = int(m.get("inline_pair_count") or 0)
    total_evidence = (
        complete_records + labelled_pairs + tabular_rows + inline_pairs
    )

    if total_evidence >= 1 and has_value:
        return None            

                                                               
    if not (m.get("extracted_text") or m.get("_had_extracted_text")):
        return "rejected_no_extracted_text"

                                                            
    tier = (m.get("tier") or "").lower()
    if tier == "filename_only":
        return "rejected_filename_only"

                                                                   
    if block_count >= 1 and complete_records == 0 and labelled_pairs == 0:
        return "rejected_keyword_list"

    if not has_value:
        return "rejected_no_secret_value"

    if identifier_count < 1 and labelled_pairs == 0:
        return "rejected_no_identifier"

    if service_count < 1 and complete_records == 0:
        return "rejected_no_service_context"

    return "rejected_no_complete_record"


def _passes_credential_verifier(m: dict) -> bool:


    return _classify_credential_reject_reason(m) is None


def _evidence_source_for_row(m: dict) -> str:


    asset_type = (m.get("asset_type") or "").lower()
    mime = (m.get("mime_type") or "").lower()
    if asset_type == "archive" or mime in (
        "application/zip", "application/x-zip-compressed",
        "application/x-tar", "application/gzip", "application/x-7z-compressed",
    ):
        return "archive"
    if asset_type == "image" or mime.startswith("image/"):
        return "ocr"
    if asset_type == "audio" or mime.startswith("audio/"):
        return "transcript"
    if asset_type == "video" or mime.startswith("video/"):
        return "transcript"
    return "file_text"


_EVIDENCE_SOURCE_LABELS: dict[str, str] = {
    "file_text": "file text",
    "ocr":       "OCR",
    "archive":   "archive",
    "transcript": "transcript",
}


def _collect_duplicate_paths(m: dict) -> list[str]:


    raw = m.get("duplicate_paths")
    if isinstance(raw, list):
        return [str(p) for p in raw if isinstance(p, str) and p.strip()]
    return []


def _shape_verified_match(m: dict) -> dict:


    complete_records = int(m.get("complete_record_count") or 0)
    labelled_pairs = int(m.get("labelled_pair_count") or 0)
    tabular_rows = int(m.get("tabular_record_count") or 0)
    inline_pairs = int(m.get("inline_pair_count") or 0)
    record_count = max(
        1, complete_records + labelled_pairs + tabular_rows + inline_pairs
    )
    complete_services = list(m.get("complete_service_names") or [])
    safe_service_names = (
        complete_services
        if complete_services
        else list(m.get("safe_service_names") or [])
    )
    source = _evidence_source_for_row(m)
    duplicate_paths = _collect_duplicate_paths(m)
    return {
        "file_id":            m.get("file_id"),
        "file_name":          m.get("file_name"),
        "saved_name":         m.get("saved_name"),
        "relative_path":      m.get("relative_path"),
        "mime_type":          m.get("mime_type"),
        "asset_type":         m.get("asset_type"),
        "evidence_source":    source,
        "evidence_source_label": _EVIDENCE_SOURCE_LABELS.get(
            source, "file text",
        ),
        "record_count":       int(record_count),
        "safe_service_names": safe_service_names[:5],
                                                                     
                                                                   
        "password_present":   bool(m.get("has_credential_value")),
                                                                  
                                                                  
        "duplicate_paths":    duplicate_paths,
                                                                  
                                                                 
        "content_sha256":     (m.get("content_sha256") or "").lower(),
    }


def _dedupe_verified_matches_by_file_id(
    matches: list[dict],
) -> list[dict]:


    if not matches:
        return []
    order: list[str] = []
    bucket: dict[str, dict] = {}
    passthrough: list[dict] = []
    for m in matches:
        fid = m.get("file_id")
        if not fid:
            passthrough.append(m)
            continue
        key = str(fid)
        if key not in bucket:
            bucket[key] = dict(m)
            bucket[key]["_service_set"] = set(
                bucket[key].get("safe_service_names") or []
            )
            bucket[key]["_duppath_set"] = set(
                bucket[key].get("duplicate_paths") or []
            )
            bucket[key]["_evidence_set"] = set()
            src = bucket[key].get("evidence_source")
            if src:
                bucket[key]["_evidence_set"].add(src)
            order.append(key)
            continue
        existing = bucket[key]
        existing["record_count"] = int(
            existing.get("record_count") or 0
        ) + int(m.get("record_count") or 0)
        for name in (m.get("safe_service_names") or []):
            existing["_service_set"].add(name)
        for p in (m.get("duplicate_paths") or []):
            existing["_duppath_set"].add(p)
        src = m.get("evidence_source")
        if src:
            existing["_evidence_set"].add(src)
        existing["password_present"] = bool(
            existing.get("password_present")
            or m.get("password_present")
        )

    pass1: list[dict] = []
    for key in order:
        row = bucket[key]
        services = sorted(row.pop("_service_set"))
        duppaths = sorted(row.pop("_duppath_set"))
        evidence_set = sorted(row.pop("_evidence_set"))
        row["safe_service_names"] = services[:5]
        row["duplicate_paths"] = duppaths
        row["evidence_sources"] = evidence_set
        pass1.append(row)
    pass1.extend(passthrough)

                                                                 
    sha_seen: dict[str, dict] = {}
    out: list[dict] = []
    for row in pass1:
        sha = (row.get("content_sha256") or "").strip().lower()
        if not sha:
            out.append(row)
            continue
        if sha in sha_seen:
            survivor = sha_seen[sha]
            extra_path = (row.get("relative_path") or "").strip()
            if extra_path:
                dup_list = list(survivor.get("duplicate_paths") or [])
                if extra_path not in dup_list:
                    dup_list.append(extra_path)
                    survivor["duplicate_paths"] = sorted(dup_list)
                                                                
                                                            
            services = set(survivor.get("safe_service_names") or [])
            for name in (row.get("safe_service_names") or []):
                services.add(name)
            survivor["safe_service_names"] = sorted(services)[:5]
            evidence_set = set(survivor.get("evidence_sources") or [])
            for s in (row.get("evidence_sources") or []):
                evidence_set.add(s)
            survivor["evidence_sources"] = sorted(evidence_set)
            survivor["password_present"] = bool(
                survivor.get("password_present")
                or row.get("password_present")
            )
            continue
        sha_seen[sha] = row
        out.append(row)
    return out


def verified_credential_files_report(
    rows: list[dict], *, limit: int = DEFAULT_CREDENTIAL_FILES_LIMIT,
    coverage: Optional[dict] = None,
) -> dict:


    report = search_files_for_credentials_report(rows, limit=limit)
    verified: list[dict] = []
    for m in report["matches"]:
        if _passes_credential_verifier(m):
            verified.append(_shape_verified_match(m))

                                                              
    verified = _dedupe_verified_matches_by_file_id(verified)

                                                              
    if isinstance(coverage, dict) and int(coverage.get("total") or 0) > 0:
        total = int(coverage.get("total") or 0)
        scanned = int(coverage.get("scanned") or 0)
        pending = int(coverage.get("pending") or 0)
        processing = int(coverage.get("processing") or 0)
        not_scanned_count = max(0, pending + processing)
        scanned_count = max(0, scanned)
                                                                
                                                                   
        loose_not_scanned = int(report.get("not_scanned_count") or 0)
        not_scanned_count = max(not_scanned_count, loose_not_scanned)
    else:
        scanned_count = int(report.get("scanned_count") or 0)
        not_scanned_count = int(report.get("not_scanned_count") or 0)

    return {
        "matches":            verified,
        "scanned_count":      scanned_count,
        "not_scanned_count":  not_scanned_count,
        "is_partial":         not_scanned_count > 0,
    }


def _folder_of_row(m: dict) -> str:
    rp = (m.get("relative_path") or "").strip().strip("/")
    if not rp:
        return "(root)"
    last_slash = rp.rfind("/")
    if last_slash <= 0:
        return "(root)"
    return rp[:last_slash]


def credential_search_diagnostics(
    rows: list[dict], *, limit_per_folder: int = 25,
) -> dict:


    loose = search_files_for_credentials_report(rows, limit=10**6)
    loose_matches = loose["matches"]
    loose_by_id = {m.get("file_id") or m.get("id"): m for m in loose_matches}

                                                                 
    duplicate_groups: dict[tuple[str, str], list[dict]] = {}
    for raw in rows:
        name = (
            (raw.get("saved_name") or raw.get("file_name") or "").strip().lower()
        )
        sha = (raw.get("content_sha256") or "").strip().lower()
        if not sha or not name:
            continue
        duplicate_groups.setdefault((name, sha), []).append(raw)
    duplicate_groups_export: list[dict] = []
    for (name, sha), copies in duplicate_groups.items():
        if len(copies) <= 1:
            continue
        paths: list[str] = []
        for c in copies:
            rp = (c.get("relative_path") or "").strip()
            if rp and rp not in paths:
                paths.append(rp)
        if not paths:
            paths = ["(root)"]
        duplicate_groups_export.append({
            "key":       f"{name}|{sha[:12]}",
            "file_name": name,
            "paths":     paths,
        })

    by_folder: dict[str, dict] = {}
    rejected_total = 0
    verified_total = 0
    rejected_by_reason_total: dict[str, int] = {}
    missing_text_total = 0

    for raw in rows:
        rid = raw.get("id") or raw.get("file_id")
        loose_row = loose_by_id.get(rid)
        rp = (raw.get("relative_path") or "").strip().strip("/")
        folder = "(root)" if not rp else (
            rp[:rp.rfind("/")] if rp.rfind("/") > 0 else "(root)"
        )
        bucket = by_folder.setdefault(folder, {
            "folder":                  folder,
            "input_files":             0,
            "loose_candidates":        0,
            "verified":                0,
            "rejected":                0,
            "rejected_by_reason":      {},
            "missing_extracted_text":  0,
            "candidates":              [],
        })
        bucket["input_files"] += 1

        if not raw.get("extracted_text"):
            bucket["missing_extracted_text"] += 1
            missing_text_total += 1

        if loose_row is None:
                                                                    
                                                                    
            if not raw.get("extracted_text"):
                verdict = "rejected_no_extracted_text"
            else:
                verdict = "rejected_filename_only"
            bucket["rejected"] += 1
            bucket["rejected_by_reason"][verdict] = (
                bucket["rejected_by_reason"].get(verdict, 0) + 1
            )
            rejected_total += 1
            rejected_by_reason_total[verdict] = (
                rejected_by_reason_total.get(verdict, 0) + 1
            )
            if len(bucket["candidates"]) < limit_per_folder:
                bucket["candidates"].append({
                    "file_id":               rid,
                    "file_name":             raw.get("file_name"),
                    "saved_name":            raw.get("saved_name"),
                    "relative_path":         raw.get("relative_path"),
                    "verdict":               verdict,
                    "complete_record_count": 0,
                    "labelled_pair_count":   0,
                    "has_credential_value":  False,
                    "purpose":               "",
                    "duplicate_paths":       [],
                })
            continue

        bucket["loose_candidates"] += 1
        verdict = _classify_credential_reject_reason(loose_row)
        if verdict is None:
            bucket["verified"] += 1
            verified_total += 1
            verdict_label = "accepted"
        else:
            bucket["rejected"] += 1
            rejected_total += 1
            bucket["rejected_by_reason"][verdict] = (
                bucket["rejected_by_reason"].get(verdict, 0) + 1
            )
            rejected_by_reason_total[verdict] = (
                rejected_by_reason_total.get(verdict, 0) + 1
            )
            verdict_label = verdict

                                                                  
        name = (raw.get("saved_name") or raw.get("file_name") or "").strip().lower()
        sha = (raw.get("content_sha256") or "").strip().lower()
        dup_paths: list[str] = []
        if name and sha:
            for c in duplicate_groups.get((name, sha), []):
                cp = (c.get("relative_path") or "").strip()
                if cp and cp not in dup_paths:
                    dup_paths.append(cp)

        if len(bucket["candidates"]) < limit_per_folder:
            bucket["candidates"].append({
                "file_id":               rid,
                "file_name":             loose_row.get("file_name"),
                "saved_name":            loose_row.get("saved_name"),
                "relative_path":         loose_row.get("relative_path"),
                "verdict":               verdict_label,
                "complete_record_count": int(
                    loose_row.get("complete_record_count") or 0
                ),
                "labelled_pair_count":   int(
                    loose_row.get("labelled_pair_count") or 0
                ),
                "has_credential_value":  bool(
                    loose_row.get("has_credential_value")
                ),
                "purpose":               loose_row.get("purpose") or "",
                "duplicate_paths":       dup_paths,
            })

    by_folder_sorted = sorted(
        by_folder.values(), key=lambda b: b["folder"].lower(),
    )

                                                                 
    EXCLUDED_REASON_MAP: dict[str, str] = {
        "rejected_no_extracted_text":   "no_text",
        "rejected_filename_only":       "filename_only",
        "rejected_form_like":           "form_like",
        "rejected_no_secret_value":     "no_secret_value",
        "rejected_no_identifier":       "no_identifier",
        "rejected_no_service_context":  "no_service_context",
        "rejected_no_complete_record":  "verifier_rejected",
        "rejected_keyword_list":        "verifier_rejected",
        "rejected_duplicate_collapsed": "duplicate_collapsed",
        "rejected_unsupported_type":    "unsupported",
    }
    excluded_by_reason: dict[str, int] = {}
    for reason, count in rejected_by_reason_total.items():
        bucket = EXCLUDED_REASON_MAP.get(reason, "verifier_rejected")
        excluded_by_reason[bucket] = (
            excluded_by_reason.get(bucket, 0) + int(count)
        )

                                                                 
    per_folder: list[dict] = []
    for bucket in by_folder_sorted:
        per_folder.append({
            "folder":                  bucket["folder"],
            "total_files":             bucket["input_files"],
            "scanned_files":           bucket["input_files"] - bucket[
                "missing_extracted_text"
            ],
            "credential_candidates":   bucket["loose_candidates"],
            "verified_credential_files": bucket["verified"],
        })

                                                                   
    name_to_paths: dict[str, list[str]] = {}
    for grp in duplicate_groups_export:
        for p in grp["paths"]:
            name_to_paths.setdefault(grp["file_name"], []).append(p)
    per_file: list[dict] = []
    for bucket in by_folder_sorted:
        for cand in bucket["candidates"]:
            name = (cand.get("file_name") or "").lower()
            rp = cand.get("relative_path") or ""
                                                                
                                                               
            dup_of = ""
            if name and name in name_to_paths:
                for p in name_to_paths[name]:
                    if p and p != rp:
                        dup_of = p
                        break
            per_file.append({
                "file_id":               cand.get("file_id"),
                "file_name":             cand.get("file_name"),
                "relative_path":         rp,
                "extraction_source":     _extraction_source_for_path(rp),
                "text_available":        bool(
                    cand.get("complete_record_count")
                    or cand.get("labelled_pair_count")
                    or cand.get("has_credential_value")
                    or cand["verdict"] != "rejected_no_extracted_text"
                ),
                "record_count":          int(
                    cand.get("complete_record_count") or 0
                ) + int(
                    cand.get("labelled_pair_count") or 0
                ),
                "verifier_passed":       cand["verdict"] == "accepted",
                "reject_reason":         (
                    "" if cand["verdict"] == "accepted"
                    else cand["verdict"]
                ),
                "duplicate_of":          dup_of,
            })

    return {
        "totals": {
            "input_files":            len(rows),
            "loose_candidates":       len(loose_matches),
            "verified":               verified_total,
            "rejected":               rejected_total,
            "rejected_by_reason":     rejected_by_reason_total,
            "missing_extracted_text": missing_text_total,
            "duplicate_groups":       len(duplicate_groups_export),
        },
        "excluded_by_reason": excluded_by_reason,
        "per_folder":         per_folder,
        "per_file":           per_file,
        "by_folder":          by_folder_sorted,
        "duplicate_groups":   duplicate_groups_export,
    }


def _extraction_source_for_path(relative_path: str) -> str:


    rp = (relative_path or "").lower()
    if any(rp.endswith(s) for s in (".zip", ".tar", ".gz", ".7z", ".rar")):
        return "archive"
    if any(rp.endswith(s) for s in (".png", ".jpg", ".jpeg", ".gif",
                                    ".webp", ".heic", ".bmp", ".tiff")):
        return "ocr"
    if any(rp.endswith(s) for s in (".mp3", ".wav", ".m4a", ".ogg",
                                    ".mp4", ".mov", ".webm", ".mkv")):
        return "transcript"
    return "file_text"


def _collapse_credential_duplicates(matches: list[dict]) -> list[dict]:


    seen: dict[tuple[str, str], dict] = {}
    out: list[dict] = []
    for m in matches:
        name = (
            (m.get("saved_name") or "").lower()
            or (m.get("file_name") or "").lower()
        )
        sha = (m.get("_content_sha256") or "").lower()
        key = (name, sha)
                                                                
                                                        
        if sha and key in seen:
            survivor = seen[key]
            dup_path = (m.get("relative_path") or "").strip()
            if dup_path:
                                                                  
                                                                
                survivor_paths = survivor.setdefault(
                    "duplicate_paths", []
                )
                if dup_path not in survivor_paths:
                    survivor_paths.append(dup_path)
            continue
        if sha:
            seen[key] = m
        out.append(m)
    return out


def _mark_credential_best_match(matches: list[dict]) -> list[dict]:


    if not matches:
        return matches

    try:
        from vault_document_purpose import purpose_is_credential_bearing
    except Exception:
        purpose_is_credential_bearing = lambda p: True              

    top = matches[0]
    top_purpose = top.get("purpose") or ""
    if not purpose_is_credential_bearing(top_purpose):
        return matches

                                                                 
    if top_purpose == "credential_export":
        top["best_match"] = True
        return matches

    if not top.get("mostly_credentials"):
        return matches

                                                          
    top_purpose_rank = (
        top.get("purpose_rank") if isinstance(top.get("purpose_rank"), int)
        else 2
    )
    same_rank_runners = [
        m for m in matches[1:]
        if (m.get("purpose_rank") == top_purpose_rank)
        and m.get("mostly_credentials")
        and purpose_is_credential_bearing(m.get("purpose") or "")
    ]
    if not same_rank_runners:
        top["best_match"] = True
        return matches
    top_density = float(top.get("credential_density") or 0.0)
    next_density = float(
        same_rank_runners[0].get("credential_density") or 0.0
    )
    if top_density >= next_density + 0.10:
        top["best_match"] = True
    return matches


def _format_credential_reasons(
    *,
    content_signals: dict,
    filename_hint: Optional[str],
    folder_hint: Optional[str],
    detected_service_hit: bool,
    asset_type_hit: bool,
) -> list[str]:


    user_labels = content_signals.get("user_labels") or []
    secret_labels = content_signals.get("secret_labels") or []
    has_raw_email = content_signals.get("has_raw_email")
    repeated_blocks = int(content_signals.get("repeated_blocks") or 0)

    reasons: list[str] = []

                                                              
    if repeated_blocks >= _REPEATED_BLOCK_THRESHOLD:
        reasons.append(
            "content contains repeated service/email/password-like "
            "credential records"
        )
    elif repeated_blocks >= 2:
        reasons.append(
            "content contains a few service/email/password-like blocks"
        )

                                                                      
    if secret_labels and (user_labels or has_raw_email):
                                                                   
                                                                   
        effective_user_labels = list(user_labels) or ["email"]
        reasons.append(
            _describe_content_pair(effective_user_labels, secret_labels)
        )
    elif secret_labels:
        reasons.append(_describe_content_secret_only(secret_labels))
    elif user_labels:
                                                                   
                                                                    
        reasons.append(_describe_content_user_only(user_labels))

                                                              
    if filename_hint:
        reasons.append(f'filename mentions "{filename_hint}"')
    if folder_hint:
        reasons.append(f'inside a "{folder_hint}" folder')
    if detected_service_hit:
        reasons.append("detected as a credential file")
    if asset_type_hit:
        reasons.append("marked as a login asset")

    return reasons


_USER_LABEL_HUMAN: dict[str, str] = {
    "username":     "username",
    "email":        "email",
    "login_label":  "login",
}
_SECRET_LABEL_HUMAN: dict[str, str] = {
    "password":     "password",
    "token":        "token",
    "api_key":      "api key",
    "secret":       "secret",
    "private_key":  "private key",
    "mnemonic":     "mnemonic / recovery phrase",
}


def _describe_content_pair(
    user_labels: list[str], secret_labels: list[str],
) -> str:
    user_part = _USER_LABEL_HUMAN.get(user_labels[0], "username")
    secret_part = _SECRET_LABEL_HUMAN.get(secret_labels[0], "password")
    return f"contains {user_part}/{secret_part} fields"


def _describe_content_secret_only(secret_labels: list[str]) -> str:
    if "mnemonic" in secret_labels:
        return "contains mnemonic / recovery-phrase field"
    if "private_key" in secret_labels:
        return "contains private-key field or PEM block"
    if "api_key" in secret_labels:
        return "contains api key / api secret field"
    if "token" in secret_labels:
        return "contains token / access-token field"
    if "password" in secret_labels:
        return "contains password field"
    return "contains credential field"


def _describe_content_user_only(user_labels: list[str]) -> str:
    if "email" in user_labels:
        return "contains email field"
    return "contains username / login field"


def travel_readiness_check(
    *,
    rows: list[dict],
    metadata_rows: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
) -> dict:


    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

                                                     
    meta_by_file: dict[str, dict] = {}
    if metadata_rows:
        for mr in metadata_rows:
            fid = str(mr.get("uploaded_file_id") or "")
            if fid:
                meta_by_file[fid] = mr

    have_types: dict[str, list[dict]] = {dt: [] for dt in _TRAVEL_DOC_TYPES}

                                                                  
    for r in rows:
        fid = str(r.get("id") or "")
        if not fid:
            continue
        meta = meta_by_file.get(fid)
        doc_type = ((meta or {}).get("doc_type") or "").lower() or None

                                             
        if doc_type is None:
            doc_type = _detect_travel_doc_type_from_name(
                r.get("file_name"), r.get("saved_name"),
            )
        if doc_type in _TRAVEL_DOC_TYPES:
            have_types[doc_type].append({
                "file_id": fid,
                "file_name": r.get("file_name"),
                "saved_name": r.get("saved_name"),
                "relative_path": r.get("relative_path"),
                "metadata": (meta or {}).get("metadata_json"),
            })

    found = [dt for dt, lst in have_types.items() if lst]
    missing = [dt for dt in _TRAVEL_DOC_TYPES if not have_types[dt]]

    expired: list[dict] = []
    expiring_soon: list[dict] = []
    EXPIRING_SOON_DAYS = 30

    for dt in found:
        for entry in have_types[dt]:
            meta_json = entry.get("metadata") or {}
            expiry_str = (
                meta_json.get("expiry_date")
                if isinstance(meta_json, dict)
                else None
            )
            parsed = _parse_iso_date(expiry_str)
            if parsed is None:
                continue
            delta = (parsed - now_utc).days
            label = (
                entry.get("saved_name")
                or entry.get("file_name")
                or dt
            )
            payload = {
                "doc_type": dt,
                "file_id": entry["file_id"],
                "expiry_date": expiry_str,
                "label": label,
            }
            if delta < 0:
                payload["days_overdue"] = -delta
                expired.append(payload)
            elif delta <= EXPIRING_SOON_DAYS:
                payload["days_until"] = delta
                expiring_soon.append(payload)

    if expired or (not found):
        confidence = "blocked"
    elif missing or expiring_soon:
        confidence = "partial"
    else:
        confidence = "ready"

    return {
        "found": found,
        "missing": missing,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "confidence": confidence,
    }


def _detect_travel_doc_type_from_name(
    file_name: Optional[str], saved_name: Optional[str],
) -> Optional[str]:
    name = ((file_name or "") + " " + (saved_name or "")).lower()
    if not name.strip():
        return None
    if "passport" in name:
        return "passport"
    if "visa" in name:
        return "visa"
    if "boarding" in name and "pass" in name:
        return "boarding_pass"
    if "ticket" in name and ("flight" in name or "train" in name or "boarding" not in name):
        return "ticket"
    if "hotel" in name or "itinerary" in name or "booking" in name:
        return "hotel_itinerary"
    return None


def _parse_iso_date(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                parsed if parsed.tzinfo
                else parsed.replace(tzinfo=timezone.utc)
            )
        except Exception:
            return None
    return None


def format_vault_summary_reply(summary: dict) -> str:


    total = int(summary.get("total_files") or 0)
    if total == 0:
        return "I don't see any uploaded files in your vault yet."

    folder_count = int(summary.get("folder_count") or 0)
    type_counts: dict = summary.get("type_counts") or {}

    lines = [
        f"You have {total} uploaded file"
        f"{'s' if total != 1 else ''} in your vault"
        + (
            f" across {folder_count} folder"
            f"{'s' if folder_count != 1 else ''}"
            if folder_count else ""
        )
        + "."
    ]
    if type_counts:
        bits = []
        for label in (
            "PDFs", "Images", "Videos", "Audio", "Documents",
            "Spreadsheets", "Archives", "Scripts",
        ):
            if type_counts.get(label):
                bits.append(f"{type_counts[label]} {label}")
        if bits:
            lines.append("Includes: " + ", ".join(bits) + ".")

    top_folders = summary.get("top_folders") or []
    if top_folders:
        lines.append("")
        lines.append("Top folders:")
        for f in top_folders:
            lines.append(
                f"- {f['name']} — {f['file_count']} file"
                f"{'s' if f['file_count'] != 1 else ''}"
            )

    recent = summary.get("recent_files") or []
    if recent:
        lines.append("")
        lines.append("Recent files:")
        for f in recent[:5]:
            label = (
                f.get("saved_name") or f.get("file_name") or "file"
            )
            lines.append(f"- {label}")

    return "\n".join(lines)


def format_folder_list_reply(folders: list[dict]) -> str:
    if not folders:
        return "You don't have any folders in your vault yet."
    n = len(folders)
    lines = [f"You have {n} folder{'s' if n != 1 else ''}:"]
    for f in folders:
        lines.append(
            f"- {f['name']} — {f['file_count']} file"
            f"{'s' if f['file_count'] != 1 else ''}"
        )
    return "\n".join(lines)


def format_recent_uploads_reply(recent: list[dict]) -> str:
    if not recent:
        return "I don't see any recent uploads."
    n = len(recent)
    lines = [f"Your {n} most recent file{'s' if n != 1 else ''}:"]
    for r in recent:
        label = r.get("saved_name") or r.get("file_name") or "file"
        rp = (r.get("relative_path") or "").strip()
        lines.append(f"- {label}" + (f" ({rp})" if rp else ""))
    return "\n".join(lines)


def format_credential_files_reply(
    matches: list[dict],
    *,
    not_scanned_count: int = 0,
    scanned_count: int = 0,
    is_partial: Optional[bool] = None,
    sections: Optional[dict] = None,
    has_content_matches: Optional[bool] = None,
) -> str:


    if is_partial is None:
        is_partial = not_scanned_count > 0
                         
    if not matches:
        if scanned_count > 0:
            base = (
                "I scanned the readable files and did not find saved "
                "credential records."
            )
        else:
            base = (
                "I didn't find any uploaded files with saved "
                "credential records. Saved logins live separately — "
                "ask 'show my saved logins' to see those."
            )
        if not_scanned_count > 0:
            base += (
                f"\n\n{not_scanned_count} file"
                f"{'s' if not_scanned_count != 1 else ''} still need "
                "extraction/OCR before I can fully check them."
            )
        return base

    lines: list[str] = []

                                                         
    n = len(matches)
    total = scanned_count + not_scanned_count
    if is_partial and total > 0:
                                                                    
                                                                 
        scanned_word = "file" if scanned_count == 1 else "files"
        not_scanned_word = "file" if not_scanned_count == 1 else "files"
        lines.append(
            f"I checked {scanned_count} of {total} {scanned_word}. "
            f"{not_scanned_count} still need extraction/OCR. These "
            "results are incomplete."
        )
    elif scanned_count > 0:
        scanned_word = "file" if scanned_count == 1 else "files"
        files_word = "file" if n == 1 else "files"
        lines.append(
            f"I checked {scanned_count} {scanned_word} and found "
            f"{n} {files_word} with saved credential records."
        )
    else:
                                                            
        files_word = "file" if n == 1 else "files"
        lines.append(
            f"I found {n} {files_word} with saved credential records."
        )
    lines.append("")
    section_header = (
        "Partial results from already scanned files:"
        if is_partial else "Files with saved credentials:"
    )
    lines.append(section_header)
    _append_credential_section_rows(lines, matches)

    lines.append("")
    lines.append(
        "Open any of these files to view the contents. I won't "
        "extract credentials unless you ask explicitly."
    )
    if not_scanned_count > 0 and not is_partial:
        lines.append("")
        lines.append(
            f"{not_scanned_count} file"
            f"{'s' if not_scanned_count != 1 else ''} still need "
            "extraction/OCR before I can fully check them."
        )
    return "\n".join(lines)


def _append_credential_section_rows(
    lines: list[str], rows: list[dict],
) -> None:


    for m in rows:
        label = m.get("saved_name") or m.get("file_name") or "file"
        rp = (m.get("relative_path") or "").strip()
        record_count = int(m.get("record_count") or 0)
        services = list(m.get("safe_service_names") or [])
        evidence_label = (
            m.get("evidence_source_label")
            or _EVIDENCE_SOURCE_LABELS.get(
                (m.get("evidence_source") or "").lower(), "file text",
            )
        )
        line = f"- {label}"
        if record_count > 0:
            line += (
                f" · {record_count} record"
                f"{'s' if record_count != 1 else ''}"
            )
        line += f" · evidence: {evidence_label}"
        if rp:
            line += f" (in {rp})"
        lines.append(line)
        if services:
            sample = ", ".join(services[:3])
            lines.append(f"  services: {sample}")


def format_travel_readiness_reply(report: dict) -> str:


    found = report.get("found") or []
    missing = report.get("missing") or []
    expired = report.get("expired") or []
    expiring_soon = report.get("expiring_soon") or []
    confidence = report.get("confidence") or "blocked"

    if confidence == "blocked" and not found:
        return (
            "I don't see any travel documents in your vault yet. "
            "Upload a passport, visa, or boarding pass to start a "
            "travel readiness check."
        )

    headline = {
        "ready":    "You look travel-ready.",
        "partial":  "You're partly travel-ready — some items are missing or expiring.",
        "blocked":  "I see travel documents, but there are blockers.",
    }.get(confidence, "Travel readiness check:")

    lines = [headline, ""]

    if found:
        lines.append("Found:")
        for dt in found:
            lines.append(f"- {_pretty_doc_type(dt)}")
        lines.append("")

    if expired:
        lines.append("Expired:")
        for e in expired:
            lines.append(
                f"- {_pretty_doc_type(e['doc_type'])} "
                f"({e.get('label')}) — expired "
                f"{e.get('days_overdue', '?')} days ago"
            )
        lines.append("")

    if expiring_soon:
        lines.append("Expiring soon:")
        for e in expiring_soon:
            lines.append(
                f"- {_pretty_doc_type(e['doc_type'])} "
                f"({e.get('label')}) — expires in "
                f"{e.get('days_until', '?')} days"
            )
        lines.append("")

    if missing:
        lines.append("Missing:")
        for dt in missing:
            lines.append(f"- {_pretty_doc_type(dt)}")

    return "\n".join(line for line in lines if line is not None).rstrip()


def _pretty_doc_type(dt: str) -> str:
    return {
        "passport":         "Passport",
        "visa":             "Visa",
        "boarding_pass":    "Boarding pass",
        "ticket":           "Ticket",
        "hotel_itinerary":  "Hotel itinerary",
    }.get(dt, dt.replace("_", " ").title())


def _row_to_card(row: dict) -> dict:


    out = {
        "file_id":    row.get("id"),
        "file_name":  row.get("file_name"),
        "saved_name": row.get("saved_name"),
        "mime_type":  row.get("content_type"),
        "asset_type": row.get("asset_type") or "file",
    }
    rp = row.get("relative_path")
    if rp:
        out["relative_path"] = rp
    size = row.get("file_size")
    if isinstance(size, int):
        out["size_bytes"] = size
    return out
