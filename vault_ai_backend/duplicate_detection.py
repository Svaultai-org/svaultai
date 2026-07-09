

from __future__ import annotations

import re
from typing import Optional

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def normalize_content_sha256(raw: Optional[str]) -> Optional[str]:


    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not _SHA256_HEX_RE.match(s):
        return None
    return s


_VALID_DUPLICATE_ACTIONS = ("prompt", "skip", "keep_both", "replace")


def normalize_duplicate_action(raw: Optional[str]) -> str:


    if not raw:
        return "prompt"
    s = str(raw).strip().lower()
    if s in _VALID_DUPLICATE_ACTIONS:
        return s
    return "prompt"


def find_existing_file_by_hash(
    rows: list[dict],
    *,
    content_sha256: Optional[str],
    file_size: int,
) -> Optional[dict]:


    if not content_sha256:
        return None
    candidates = []
    for row in rows:
        if (row.get("content_sha256") or "").lower() != content_sha256:
            continue
        if int(row.get("file_size") or 0) != int(file_size):
            continue
        candidates.append(row)

    if not candidates:
        return None
                                                                
    canonical = [
        c for c in candidates if not c.get("duplicate_of_file_id")
    ]
    return (canonical or candidates)[0]


def find_name_conflict(
    rows: list[dict],
    *,
    saved_name: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
    incoming_content_sha256: Optional[str] = None,
) -> Optional[dict]:


    sn = (saved_name or "").strip().lower()
    fn = (file_name or "").strip().lower()
    if not sn and not fn:
        return None
    rp = (relative_path or "").strip() or None
    incoming_hash = (
        (incoming_content_sha256 or "").strip().lower() or None
    )

    for row in rows:
        existing_rp = (row.get("relative_path") or "").strip() or None
        if existing_rp != rp:
            continue

        existing_saved = (row.get("saved_name") or "").strip().lower()
        existing_file = (row.get("file_name") or "").strip().lower()

        name_matches = (
            (sn and existing_saved and existing_saved == sn)
            or (fn and existing_file and existing_file == fn)
            or (fn and existing_saved and existing_saved == fn)
            or (sn and existing_file and existing_file == sn)
        )
        if not name_matches:
            continue

                                                                
        if incoming_hash:
            existing_hash = (
                (row.get("content_sha256") or "").strip().lower() or None
            )
            if existing_hash and existing_hash == incoming_hash:
                continue

        return row
    return None


_VERSIONED_NAME_RE = re.compile(
    r"^(?P<base>.+?)(?:\s*\((?P<n>\d+)\))?(?P<ext>\.[^./\s]{1,12})?$"
)


def _split_versioned_name(name: str) -> tuple[str, Optional[str]]:


    name = name.strip()
    if not name:
        return ("", None)
    m = _VERSIONED_NAME_RE.match(name)
    if not m:
        return (name, None)
    base = (m.group("base") or "").strip()
    ext = m.group("ext")
                                                                  
                                                                
    base = re.sub(r"\s*\(\d+\)\s*$", "", base).strip()
    return (base or name, ext)


def next_available_versioned_name(
    rows: list[dict],
    *,
    base_name: str,
    relative_path: Optional[str],
) -> str:


    base, ext = _split_versioned_name(base_name or "")
    if not base:
        base = "file"
    ext = ext or ""

    rp = (relative_path or "").strip() or None
    rp_lower = (rp or "").lower()

    existing_names: set[str] = set()
    for row in rows:
        existing_rp = (row.get("relative_path") or "").strip() or None
        if (existing_rp or "").lower() != rp_lower:
            continue
        saved = (row.get("saved_name") or "").strip().lower()
        if saved:
            existing_names.add(saved)

    candidate = f"{base}{ext}"
    if candidate.lower() not in existing_names:
        return candidate
    for n in range(1, 1000):
        candidate = f"{base} ({n}){ext}"
        if candidate.lower() not in existing_names:
            return candidate
                                                                 
                           
    return f"{base} (many){ext}"


def short_hash_for_log(content_sha256: Optional[str]) -> str:


    if not content_sha256:
        return "-"
    return content_sha256[:8]
