

from __future__ import annotations

import io
import logging
import os
from typing import Optional, Tuple


logger = logging.getLogger(__name__)


_OCR_EXTENSIONS: frozenset[str] = frozenset({
    "jpg", "jpeg", "png", "webp", "tiff", "tif", "bmp",
})

_OCR_MIME_PREFIXES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
    "image/bmp",
)


MAX_OCR_CHARS = 200_000


_OCR_TIMEOUT_SECONDS = 30


def _detect_ocr_backend() -> Tuple[bool, str]:


    try:
        import pytesseract              
    except Exception:
        return (False, "pytesseract-missing")
    try:
        from PIL import Image              
    except Exception:
        return (False, "pillow-missing")
                                                               
                                                         
    return (True, "pytesseract")


OCR_AVAILABLE, OCR_BACKEND = _detect_ocr_backend()


_OCR_ENGINE = None                            


def set_ocr_engine(fn) -> None:


    global _OCR_ENGINE
    _OCR_ENGINE = fn


def reset_ocr_engine() -> None:


    global _OCR_ENGINE
    _OCR_ENGINE = _default_ocr_engine if OCR_AVAILABLE else None


def _default_ocr_engine(image_bytes: bytes, mime: Optional[str]) -> str:


    import pytesseract                
    from PIL import Image                
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
                                                                    
            if img.mode not in ("L", "RGB", "RGBA"):
                img = img.convert("RGB")
                                                                 
                                                           
            return pytesseract.image_to_string(
                img,
                timeout=_OCR_TIMEOUT_SECONDS,
            )
    except RuntimeError as exc:
                                                               
                                                         
        raise OCRError(f"tesseract failed: {exc}") from exc
    except Exception as exc:                                       
        raise OCRError(f"OCR engine error: {exc}") from exc


if OCR_AVAILABLE:
    _OCR_ENGINE = _default_ocr_engine


class OCRError(Exception):
    pass


def file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def supports_ocr(
    *, file_name: Optional[str], content_type: Optional[str] = None,
) -> bool:


    ext = file_extension(file_name)
    if ext == "svg":
                                                                      
        return False
    try:
        from vault_image_formats import (
            canonicalize_image_mime,
            is_image_row,
        )
        canonical_mime = canonicalize_image_mime(content_type)
                                                                    
                                                               
        if is_image_row(
            mime=canonical_mime or content_type,
            file_name=file_name,
        ):
                                                                
                                     
            if canonical_mime == "image/svg+xml":
                return False
            return True
    except Exception:
                                                                  
                                                             
        pass
    if ext and ext in _OCR_EXTENSIONS:
        return True
    mime = (content_type or "").strip().lower()
    if any(mime == prefix for prefix in _OCR_MIME_PREFIXES):
        return True
    return False


def _truncate(text: str, *, cap: int = MAX_OCR_CHARS) -> Tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def extract_ocr_text(
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str] = None,
    max_chars: int = MAX_OCR_CHARS,
) -> Tuple[str, bool]:


    if not supports_ocr(
        file_name=file_name, content_type=content_type,
    ):
        raise OCRError(
            f"OCR not supported for {file_name!r}"
        )
    if not file_bytes:
        raise OCRError("no image bytes to OCR")
    engine = _OCR_ENGINE
    if engine is None:
        raise OCRError(
            "OCR engine unavailable: install pytesseract + tesseract "
            "or inject a test engine via set_ocr_engine"
        )
    mime = (content_type or "").strip().lower() or None
    try:
        text = engine(file_bytes, mime)
    except OCRError:
        raise
    except Exception as exc:
                                                               
                                       
        raise OCRError(f"OCR engine error: {exc}") from exc
    if text is None:
        return "", False
                                                               
                                                        
    normalised = _normalise_ocr_text(str(text))
    truncated = False
    if max_chars and len(normalised) > max_chars:
        normalised = normalised[:max_chars]
        truncated = True
    return normalised, truncated


def _normalise_ocr_text(raw: str) -> str:


    out_lines: list[str] = []
    for line in raw.replace("\f", "\n").splitlines():
        clean = "".join(
            ch for ch in line
            if (ord(ch) >= 0x20 or ch in ("\t",))
        ).rstrip()
        out_lines.append(clean)
                                                          
    collapsed: list[str] = []
    last_blank = False
    for line in out_lines:
        if not line.strip():
            if last_blank:
                continue
            collapsed.append("")
            last_blank = True
        else:
            collapsed.append(line)
            last_blank = False
    return "\n".join(collapsed).strip()
