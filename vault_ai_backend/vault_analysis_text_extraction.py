

from __future__ import annotations

import io
import json
import logging
import re
from typing import Optional


logger = logging.getLogger(__name__)


MAX_EXTRACTED_CHARS = 200_000


_TEXT_LIKE_EXTENSIONS: frozenset[str] = frozenset({
               
    "txt", "md", "markdown", "log", "ini", "cfg", "conf", "env",
                                       
    "csv", "tsv", "json", "yaml", "yml", "toml", "xml",
                                   
    "html", "htm", "svg", "rss", "atom",
                                   
    "py", "pyi", "js", "jsx", "ts", "tsx", "css", "scss", "less",
    "sh", "bash", "zsh", "ps1", "rb", "go", "rs", "java", "kt",
    "c", "cc", "cpp", "h", "hpp", "swift", "m", "mm", "lua",
    "sql", "php", "pl", "r", "scala", "dart", "vue",
                                                                 
                                         
    "pdf", "docx",
})


_CODE_EXTENSIONS: frozenset[str] = frozenset({
    "py", "pyi", "js", "jsx", "ts", "tsx", "sh", "bash", "zsh",
    "ps1", "rb", "go", "rs", "java", "kt", "c", "cc", "cpp", "h",
    "hpp", "swift", "m", "mm", "lua", "sql", "php", "pl", "r",
    "scala", "dart", "vue", "css", "scss", "less",
})


def file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def supports_text_extraction(
    *, file_name: Optional[str], content_type: Optional[str] = None,
) -> bool:


    ext = file_extension(file_name)
    if ext in _TEXT_LIKE_EXTENSIONS:
        return True
    mime = (content_type or "").strip().lower()
    if mime in ("application/pdf",):
        return True
    if mime.startswith("text/"):
        return True
    if mime in ("application/json", "application/xml"):
        return True
    return False


def is_code_file(file_name: Optional[str]) -> bool:


    return file_extension(file_name) in _CODE_EXTENSIONS


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text, False
    return text[:MAX_EXTRACTED_CHARS], True


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_ENTITY_RE = re.compile(r"&([a-zA-Z]+|#\d+);")
_WS_RUN_RE = re.compile(r"[ \t\f\v]+")
_NL_RUN_RE = re.compile(r"\n{3,}")


def _strip_markup(raw: str) -> str:
                                                                 
                                                              
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", raw)
    no_tags = _TAG_RE.sub(" ", no_scripts)
                                                                
                                                        
    def _entity_sub(m: "re.Match[str]") -> str:
        ent = m.group(1)
        return _ENTITY_FALLBACKS.get(ent, " ")
    no_entities = _ENTITY_RE.sub(_entity_sub, no_tags)
    collapsed = _WS_RUN_RE.sub(" ", no_entities)
    collapsed = _NL_RUN_RE.sub("\n\n", collapsed)
    return collapsed.strip()


_ENTITY_FALLBACKS: dict[str, str] = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": " ", "copy": "(c)", "reg": "(r)", "trade": "(tm)",
}


class TextExtractionError(Exception):
    pass


def extract_text(
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str] = None,
) -> tuple[str, bool]:


    ext = file_extension(file_name)
    if not supports_text_extraction(
        file_name=file_name, content_type=content_type,
    ):
        raise TextExtractionError(
            f"text extraction not supported for {file_name!r}"
        )

    try:
        if ext == "pdf" or (content_type or "").lower() == "application/pdf":
            return _extract_pdf(file_bytes)
        if ext == "docx":
            return _extract_docx(file_bytes)
        if ext == "json" or (content_type or "").lower() == "application/json":
            return _extract_json(file_bytes)
        if ext in ("html", "htm", "svg", "rss", "atom") \
                or (content_type or "").lower().endswith("/xml") \
                or (content_type or "").lower() == "text/html":
            return _extract_markup(file_bytes)
                                                               
                                                                  
        return _extract_plain_text(file_bytes)
    except TextExtractionError:
        raise
    except Exception as exc:
                                                              
                                                                  
        raise TextExtractionError(str(exc)) from exc


def _extract_plain_text(file_bytes: bytes) -> tuple[str, bool]:
    text = file_bytes.decode("utf-8", errors="ignore")
                                                                
                         
    text = text.lstrip("﻿").strip()
    return _truncate(text)


def _extract_json(file_bytes: bytes) -> tuple[str, bool]:
    raw = file_bytes.decode("utf-8", errors="ignore")
    try:
        obj = json.loads(raw)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        return _truncate(pretty)
    except Exception:
                                                                   
                                                               
        return _truncate(raw.strip())


def _extract_markup(file_bytes: bytes) -> tuple[str, bool]:
    raw = file_bytes.decode("utf-8", errors="ignore")
    stripped = _strip_markup(raw)
    return _truncate(stripped)


def _extract_pdf(file_bytes: bytes) -> tuple[str, bool]:
    try:
        import PyPDF2                
    except Exception as exc:
        raise TextExtractionError(
            "PDF extraction unavailable (PyPDF2 missing)"
        ) from exc
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise TextExtractionError(f"PDF could not be parsed: {exc}") from exc
    pages: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
                                                                    
            page_text = ""
        page_text = page_text.strip()
        if page_text:
            pages.append(page_text)
    text = "\n\n".join(pages).strip()
    return _truncate(text)


def _extract_docx(file_bytes: bytes) -> tuple[str, bool]:
    try:
        import docx                
    except Exception as exc:
        raise TextExtractionError(
            "DOCX extraction unavailable (python-docx missing)"
        ) from exc
    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise TextExtractionError(f"DOCX could not be parsed: {exc}") from exc
    lines = [p.text for p in document.paragraphs if p.text]
    text = "\n".join(lines).strip()
    return _truncate(text)
