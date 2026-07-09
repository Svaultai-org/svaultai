

from __future__ import annotations

import io
import logging
import os
import re
import tarfile
import zipfile
from typing import Optional


logger = logging.getLogger(__name__)


ARCHIVE_AVAILABLE = True
ARCHIVE_BACKEND = "stdlib-zipfile-tarfile"


_ARCHIVE_EXTENSIONS: frozenset[str] = frozenset({
    "zip", "tar", "tgz", "gz",                                    
})


_ARCHIVE_MIME_PREFIXES: tuple[str, ...] = (
    "application/zip",
    "application/x-zip-compressed",
    "application/x-tar",
    "application/gzip",
    "application/x-gzip",
    "application/x-compressed-tar",
)


_TEXT_INNER_EXTENSIONS: frozenset[str] = frozenset({
    "txt", "md", "markdown", "csv", "tsv",
    "json", "yml", "yaml", "ini", "cfg", "toml",
    "html", "htm", "xml", "rss",
    "log",
                                                 
    "py", "js", "ts", "jsx", "tsx",
    "sh", "bash", "zsh", "fish",
    "rs", "go", "java", "kt", "rb", "lua", "swift",
    "c", "cpp", "cc", "h", "hpp",
    "css", "scss", "less",
                       
    "env", "dotenv", "conf", "config",
    "sql",
})


MAX_ENTRIES = 10_000
MAX_TOTAL_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_PER_INNER_FILE_BYTES = 10 * 1024 * 1024
MAX_AGGREGATED_TEXT_BYTES = 2 * 1024 * 1024


FORMAT_ZIP    = "zip"
FORMAT_TAR    = "tar"
FORMAT_TAR_GZ = "tar.gz"


class ArchiveIndexingError(Exception):
    pass


def _file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def _is_double_extension(file_name: Optional[str]) -> bool:


    if not file_name:
        return False
    low = str(file_name).strip().lower()
    return low.endswith(".tar.gz") or low.endswith(".tar.bz2")


def supports_archive_indexing(
    *, file_name: Optional[str], content_type: Optional[str] = None,
) -> bool:


    ext = _file_extension(file_name)
    if ext and ext in _ARCHIVE_EXTENSIONS:
        return True
    if _is_double_extension(file_name):
        return True
    mime = (content_type or "").strip().lower()
    if any(mime == prefix for prefix in _ARCHIVE_MIME_PREFIXES):
        return True
    return False


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_unsafe_path(name: str) -> Optional[str]:


    if not name or not str(name).strip():
        return "empty path"
    s = str(name)
    if "\x00" in s:
        return "null byte in path"
                                                   
    if s.startswith("/") or s.startswith("\\"):
        return "absolute path"
    if _WINDOWS_DRIVE_RE.match(s):
        return "drive-prefixed path"
                                                               
                                                           
    parts = re.split(r"[\\/]+", s)
    for p in parts:
        if p == "..":
            return "parent traversal"
    return None


def index_archive(
    file_bytes: bytes,
    *,
    file_name: Optional[str] = None,
    content_type: Optional[str] = None,
) -> dict:


    if not file_bytes:
        raise ArchiveIndexingError("no archive bytes")

    fmt = _detect_format(file_name=file_name, content_type=content_type)

    try:
        if fmt == FORMAT_ZIP:
            return _walk_zip(file_bytes, file_name=file_name)
        if fmt in (FORMAT_TAR, FORMAT_TAR_GZ):
            return _walk_tar(file_bytes, file_name=file_name, format=fmt)
    except ArchiveIndexingError:
        raise
    except Exception as exc:
                                                            
                                                             
        return _failed_report(
            format=fmt or "unknown",
            error=f"archive read failed: {exc.__class__.__name__}",
        )

    raise ArchiveIndexingError(
        f"unsupported archive format for {file_name!r}"
    )


def _detect_format(
    *,
    file_name: Optional[str],
    content_type: Optional[str],
) -> Optional[str]:
    low_name = (file_name or "").strip().lower()
    if low_name.endswith(".zip"):
        return FORMAT_ZIP
    if low_name.endswith(".tar.gz") or low_name.endswith(".tgz"):
        return FORMAT_TAR_GZ
    if low_name.endswith(".tar"):
        return FORMAT_TAR
    if low_name.endswith(".gz"):
                                                           
                                                            
        return FORMAT_TAR_GZ
    mime = (content_type or "").strip().lower()
    if mime in ("application/zip", "application/x-zip-compressed"):
        return FORMAT_ZIP
    if mime in ("application/x-tar",):
        return FORMAT_TAR
    if mime in (
        "application/gzip",
        "application/x-gzip",
        "application/x-compressed-tar",
    ):
        return FORMAT_TAR_GZ
    return None


def _walk_zip(file_bytes: bytes, *, file_name: Optional[str]) -> dict:
    buf = io.BytesIO(file_bytes)
    try:
        zf = zipfile.ZipFile(buf, "r")
    except zipfile.BadZipFile as exc:
        return _failed_report(
            format=FORMAT_ZIP, error=f"bad zip: {exc}",
        )
    except Exception as exc:
        return _failed_report(
            format=FORMAT_ZIP,
            error=f"zip open failed: {exc.__class__.__name__}",
        )

    report = _empty_report(format=FORMAT_ZIP)
    pieces: list[str] = [_archive_header(file_name=file_name, fmt="zip")]
    pieces_size = len(pieces[0])

    try:
        info_list = zf.infolist()
    except Exception as exc:
        zf.close()
        return _failed_report(
            format=FORMAT_ZIP,
            error=f"zip read failed: {exc.__class__.__name__}",
        )

    for idx, info in enumerate(info_list):
        if idx >= MAX_ENTRIES:
            report["truncated_by_entry_cap"] = True
            break
                                                  
        if info.is_dir():
            continue

        name = info.filename or ""
        reason = _is_unsafe_path(name)
        if reason is not None:
            report["rejected_count"] += 1
            report["rejected_paths"].append((name, reason))
            continue

                                                        
        if (getattr(info, "flag_bits", 0) & 0x1) != 0:
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (name, "encrypted entry — no password available")
            )
            continue

        size = int(info.file_size or 0)
        if size > MAX_PER_INNER_FILE_BYTES:
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (name, f"single-entry too large ({size} bytes)")
            )
            continue
        if report["total_uncompressed_bytes"] + size > \
                MAX_TOTAL_UNCOMPRESSED_BYTES:
            report["truncated_by_size_cap"] = True
            break

        is_text = _is_text_inner_extension(name)
        report["entries"].append({
            "name": name,
            "size": size,
            "is_text": is_text,
        })
        report["inner_file_count"] += 1
        report["total_uncompressed_bytes"] += size

        if not is_text:
            continue
        if pieces_size >= MAX_AGGREGATED_TEXT_BYTES:
            report["truncated_by_text_cap"] = True
            continue

        try:
            with zf.open(info, "r") as inf:
                inner_bytes = inf.read(MAX_PER_INNER_FILE_BYTES)
        except Exception:
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (name, "inner read failed")
            )
            continue

        snippet = _safe_inner_text(inner_bytes)
                                                                
                                                                  
        signals = _signals_for_inner(name, snippet)
        if signals is not None:
            report["inner_file_signals"].append(signals)

        block = _format_inner_block(name, snippet)
        if pieces_size + len(block) > MAX_AGGREGATED_TEXT_BYTES:
                                        
            room = max(0, MAX_AGGREGATED_TEXT_BYTES - pieces_size)
            block = block[:room]
            report["truncated_by_text_cap"] = True
        pieces.append(block)
        pieces_size += len(block)

    try:
        zf.close()
    except Exception:
        pass

    report["ok"] = True
    report["aggregated_text"] = "".join(pieces)
    return report


def _walk_tar(
    file_bytes: bytes,
    *,
    file_name: Optional[str],
    format: str,
) -> dict:
    buf = io.BytesIO(file_bytes)
    mode = "r:gz" if format == FORMAT_TAR_GZ else "r:"
    try:
        tf = tarfile.open(fileobj=buf, mode=mode)
    except tarfile.ReadError as exc:
        return _failed_report(
            format=format, error=f"bad tar: {exc}",
        )
    except Exception as exc:
        return _failed_report(
            format=format,
            error=f"tar open failed: {exc.__class__.__name__}",
        )

    report = _empty_report(format=format)
    pieces: list[str] = [
        _archive_header(file_name=file_name, fmt=format),
    ]
    pieces_size = len(pieces[0])

    try:
        members = tf.getmembers()
    except Exception as exc:
        try:
            tf.close()
        except Exception:
            pass
        return _failed_report(
            format=format,
            error=f"tar read failed: {exc.__class__.__name__}",
        )

    for idx, member in enumerate(members):
        if idx >= MAX_ENTRIES:
            report["truncated_by_entry_cap"] = True
            break

                                                                  
        if member.issym() or member.islnk():
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (member.name or "", "symlink or hardlink")
            )
            continue
        if not member.isfile():
                                                            
            continue

        name = member.name or ""
        reason = _is_unsafe_path(name)
        if reason is not None:
            report["rejected_count"] += 1
            report["rejected_paths"].append((name, reason))
            continue

        size = int(member.size or 0)
        if size > MAX_PER_INNER_FILE_BYTES:
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (name, f"single-entry too large ({size} bytes)")
            )
            continue
        if report["total_uncompressed_bytes"] + size > \
                MAX_TOTAL_UNCOMPRESSED_BYTES:
            report["truncated_by_size_cap"] = True
            break

        is_text = _is_text_inner_extension(name)
        report["entries"].append({
            "name": name,
            "size": size,
            "is_text": is_text,
        })
        report["inner_file_count"] += 1
        report["total_uncompressed_bytes"] += size

        if not is_text:
            continue
        if pieces_size >= MAX_AGGREGATED_TEXT_BYTES:
            report["truncated_by_text_cap"] = True
            continue

        try:
            inf = tf.extractfile(member)
            if inf is None:
                continue
            try:
                inner_bytes = inf.read(MAX_PER_INNER_FILE_BYTES)
            finally:
                inf.close()
        except Exception:
            report["rejected_count"] += 1
            report["rejected_paths"].append(
                (name, "inner read failed")
            )
            continue

        snippet = _safe_inner_text(inner_bytes)
                                                             
        signals = _signals_for_inner(name, snippet)
        if signals is not None:
            report["inner_file_signals"].append(signals)

        block = _format_inner_block(name, snippet)
        if pieces_size + len(block) > MAX_AGGREGATED_TEXT_BYTES:
            room = max(0, MAX_AGGREGATED_TEXT_BYTES - pieces_size)
            block = block[:room]
            report["truncated_by_text_cap"] = True
        pieces.append(block)
        pieces_size += len(block)

    try:
        tf.close()
    except Exception:
        pass

    report["ok"] = True
    report["aggregated_text"] = "".join(pieces)
    return report


def _is_text_inner_extension(name: str) -> bool:
    if not name:
        return False
    low = str(name).lower()
    dot = low.rfind(".")
    if dot <= 0 or dot >= len(low) - 1:
        return False
    return low[dot + 1:] in _TEXT_INNER_EXTENSIONS


def _safe_inner_text(raw: bytes) -> str:


    if not raw:
        return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _format_inner_block(name: str, snippet: str) -> str:


    safe_name = (name or "").replace("\n", " ").replace("\r", " ")
    return (
        f"\n\n--- file: {safe_name} ---\n"
        + (snippet or "")
    )


def _archive_header(*, file_name: Optional[str], fmt: str) -> str:
    name = (file_name or "archive").strip() or "archive"
    return (
        f"Archive: {name}\n"
        f"Format: {fmt}\n"
        f"Inner files (listing below):\n"
    )


def _empty_report(*, format: str) -> dict:
    return {
        "ok":                       False,
        "format":                   format,
        "inner_file_count":         0,
        "rejected_count":           0,
        "rejected_paths":           [],
        "entries":                  [],
                                                               
                                                                 
        "inner_file_signals":       [],
        "aggregated_text":          "",
        "total_uncompressed_bytes": 0,
        "truncated_by_entry_cap":   False,
        "truncated_by_size_cap":    False,
        "truncated_by_text_cap":    False,
        "error":                    None,
    }


def _failed_report(*, format: str, error: str) -> dict:
    rep = _empty_report(format=format)
    rep["ok"] = False
    rep["error"] = error
    return rep


def _signals_for_inner(name: str, snippet: str) -> Optional[dict]:


    try:
        import vault_understanding as vu
        return vu.detect_inner_file_signals(
            snippet, file_name=name,
        )
    except Exception:
        return None


def build_archive_signals(
    report: dict, *, max_inner_files: int = 256,
) -> dict:


    if not isinstance(report, dict):
        return {}
    inner = report.get("inner_file_signals") or []
    if not isinstance(inner, list):
        inner = []
    return {
        "format":             str(report.get("format") or ""),
        "inner_file_count":   int(report.get("inner_file_count") or 0),
        "rejected_count":     int(report.get("rejected_count") or 0),
        "truncated_by_entry_cap": bool(
            report.get("truncated_by_entry_cap")
        ),
        "truncated_by_size_cap":  bool(
            report.get("truncated_by_size_cap")
        ),
        "truncated_by_text_cap":  bool(
            report.get("truncated_by_text_cap")
        ),
        "inner_files":        list(inner[: int(max_inner_files)]),
    }


def build_aggregated_text(report: dict) -> str:


    return str(report.get("aggregated_text") or "")
