

from __future__ import annotations

import io
import logging
from typing import Optional


logger = logging.getLogger(__name__)


SUPPORTED_IMAGE_MIMES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
    "image/webp",
    "image/tiff",
    "image/bmp",
    "image/gif",
    "image/avif",
                                                               
                                                                 
    "image/svg+xml",
})

                                                                 
_RASTER_DECODABLE_MIMES: frozenset[str] = frozenset({
    "image/jpeg", "image/png", "image/heic", "image/heif",
    "image/webp", "image/tiff", "image/bmp", "image/gif",
    "image/avif",
})

                                                                   
_VECTOR_OR_NON_DECODABLE_MIMES: frozenset[str] = frozenset({
    "image/svg+xml",
})

                                                                     
MIME_ALIASES: dict[str, str] = {
    "image/jpg":         "image/jpeg",
    "image/pjpeg":       "image/jpeg",
    "image/x-png":       "image/png",
    "image/heic-sequence": "image/heic",
    "image/heif-sequence": "image/heif",
    "image/x-heic":      "image/heic",
    "image/x-heif":      "image/heif",
    "image/x-webp":      "image/webp",
    "image/x-tiff":      "image/tiff",
    "image/x-bmp":       "image/bmp",
    "image/x-ms-bmp":    "image/bmp",
    "image/x-bitmap":    "image/bmp",
    "image/x-gif":       "image/gif",
    "image/avif-sequence": "image/avif",
    "image/svg":         "image/svg+xml",
    "application/svg+xml": "image/svg+xml",
}

                                                                    
EXTENSION_TO_MIME: dict[str, str] = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "jpe":  "image/jpeg",
    "jfif": "image/jpeg",
    "png":  "image/png",
    "heic": "image/heic",
    "heif": "image/heif",
    "webp": "image/webp",
    "tif":  "image/tiff",
    "tiff": "image/tiff",
    "bmp":  "image/bmp",
    "dib":  "image/bmp",
    "gif":  "image/gif",
    "avif": "image/avif",
    "svg":  "image/svg+xml",
}

                                                                      
MIME_TO_EXTS: dict[str, tuple[str, ...]] = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png":  ("png",),
    "image/heic": ("heic",),
    "image/heif": ("heif",),
    "image/webp": ("webp",),
    "image/tiff": ("tiff", "tif"),
    "image/bmp":  ("bmp",),
    "image/gif":  ("gif",),
    "image/avif": ("avif",),
    "image/svg+xml": ("svg",),
}

                                                                 
FORMAT_LABEL_JPEG: str = "jpeg"
FORMAT_LABEL_PNG:  str = "png"
FORMAT_LABEL_HEIC: str = "heic"
FORMAT_LABEL_HEIF: str = "heif"
FORMAT_LABEL_WEBP: str = "webp"
FORMAT_LABEL_TIFF: str = "tiff"
FORMAT_LABEL_BMP:  str = "bmp"
FORMAT_LABEL_GIF:  str = "gif"
FORMAT_LABEL_AVIF: str = "avif"
FORMAT_LABEL_SVG:  str = "svg"
FORMAT_LABEL_OTHER: str = "other"

_MIME_TO_FORMAT_LABEL: dict[str, str] = {
    "image/jpeg": FORMAT_LABEL_JPEG,
    "image/png":  FORMAT_LABEL_PNG,
    "image/heic": FORMAT_LABEL_HEIC,
    "image/heif": FORMAT_LABEL_HEIF,
    "image/webp": FORMAT_LABEL_WEBP,
    "image/tiff": FORMAT_LABEL_TIFF,
    "image/bmp":  FORMAT_LABEL_BMP,
    "image/gif":  FORMAT_LABEL_GIF,
    "image/avif": FORMAT_LABEL_AVIF,
    "image/svg+xml": FORMAT_LABEL_SVG,
}

ALL_FORMAT_LABELS: tuple[str, ...] = (
    FORMAT_LABEL_JPEG, FORMAT_LABEL_PNG, FORMAT_LABEL_HEIC,
    FORMAT_LABEL_HEIF, FORMAT_LABEL_WEBP, FORMAT_LABEL_TIFF,
    FORMAT_LABEL_BMP, FORMAT_LABEL_GIF, FORMAT_LABEL_AVIF,
    FORMAT_LABEL_SVG, FORMAT_LABEL_OTHER,
)

                                              
DECODE_BAND_OK:                 str = "ok"
DECODE_BAND_DECODER_MISSING:    str = "decoder_missing"
DECODE_BAND_DECODE_FAILED:      str = "decode_failed"
DECODE_BAND_UNSUPPORTED_FORMAT: str = "unsupported_image_format"
DECODE_BAND_CORRUPT:            str = "corrupt_image"
DECODE_BAND_EMPTY_INPUT:        str = "empty_input"

ALL_DECODE_BANDS: tuple[str, ...] = (
    DECODE_BAND_OK,
    DECODE_BAND_DECODER_MISSING,
    DECODE_BAND_DECODE_FAILED,
    DECODE_BAND_UNSUPPORTED_FORMAT,
    DECODE_BAND_CORRUPT,
    DECODE_BAND_EMPTY_INPUT,
)


_VISION_NATIVE_MIMES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})


def canonicalize_image_mime(mime: Optional[str]) -> Optional[str]:


    if not mime:
        return None
    m = mime.strip().lower()
                                                                     
                                       
    if ";" in m:
        m = m.split(";", 1)[0].strip()
    if m in SUPPORTED_IMAGE_MIMES:
        return m
    return MIME_ALIASES.get(m)


def is_supported_image_mime(mime: Optional[str]) -> bool:
    return canonicalize_image_mime(mime) is not None


def _extension_of(file_name: Optional[str]) -> str:
    if not file_name:
        return ""
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot < 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1:]


def is_supported_image_extension(file_name: Optional[str]) -> bool:
    return _extension_of(file_name) in EXTENSION_TO_MIME


def mime_from_extension(file_name: Optional[str]) -> Optional[str]:
    return EXTENSION_TO_MIME.get(_extension_of(file_name))


def detect_mime_from_bytes(raw_bytes: Optional[bytes]) -> Optional[str]:


    if not raw_bytes or len(raw_bytes) < 4:
        return None
                                                                  
                                                                  
    head_long = bytes(raw_bytes[:256])
    head = head_long[:32]

                               
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

                                  
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

                          
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

             
    if head[:2] == b"BM":
        return "image/bmp"

                                                          
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"

                              
    if head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WEBP":
        return "image/webp"

                                                               
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = bytes(head[8:12])
        if brand in (b"heic", b"heix", b"heim", b"heis", b"hevc",
                     b"hevx"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"
        if brand in (b"avif", b"avis"):
            return "image/avif"

                                                                  
    if head_long[:1] in (b"<", b"\xef"):                            
                                       
        sample = head_long
        if sample[:3] == b"\xef\xbb\xbf":
            sample = sample[3:]
                                                                
        if b"<svg" in sample or b"<SVG" in sample:
            return "image/svg+xml"

    return None


def detect_image_format(
    *, mime: Optional[str] = None,
    file_name: Optional[str] = None,
    raw_bytes: Optional[bytes] = None,
) -> str:


    resolved = resolve_image_mime(
        mime=mime, file_name=file_name, raw_bytes=raw_bytes,
    )
    if resolved and resolved in _MIME_TO_FORMAT_LABEL:
        return _MIME_TO_FORMAT_LABEL[resolved]
    return FORMAT_LABEL_OTHER


def is_image_row(
    *, mime: Optional[str] = None,
    file_name: Optional[str] = None,
    raw_bytes: Optional[bytes] = None,
    asset_type: Optional[str] = None,
) -> bool:


    if raw_bytes:
        if detect_mime_from_bytes(raw_bytes):
            return True
    if mime and is_supported_image_mime(mime):
        return True
    if file_name and is_supported_image_extension(file_name):
        return True
    if asset_type and asset_type.strip().lower() == "image":
        return True
    return False


def resolve_image_mime(
    *, mime: Optional[str] = None,
    file_name: Optional[str] = None,
    raw_bytes: Optional[bytes] = None,
) -> Optional[str]:


    if raw_bytes:
        m = detect_mime_from_bytes(raw_bytes)
        if m:
            return m
    canonical = canonicalize_image_mime(mime)
    if canonical:
        return canonical
    from_ext = mime_from_extension(file_name)
    if from_ext:
        return from_ext
    return None


_OPTIONAL_DECODERS_REGISTERED: bool = False
_HEIF_AVAILABLE: bool = False
_AVIF_AVAILABLE: bool = False


def register_optional_decoders() -> None:


    global _OPTIONAL_DECODERS_REGISTERED
    global _HEIF_AVAILABLE
    global _AVIF_AVAILABLE
    if _OPTIONAL_DECODERS_REGISTERED:
        return
                  
    try:
        import pillow_heif                

        try:
            pillow_heif.register_heif_opener()
            _HEIF_AVAILABLE = True
        except Exception:
            logger.exception(
                "[IMG-FMT] pillow_heif present but registration "
                "failed; HEIC/HEIF decode unavailable",
            )
    except Exception:
                                                                 
                                                              
        _HEIF_AVAILABLE = False

                                                               
    try:
        import pillow_avif                              

        _AVIF_AVAILABLE = True
    except Exception:
        try:
                                                                    
                                                                 
            from PIL import Image                

            Image.init()
            if "AVIF" in getattr(Image, "OPEN", {}):
                _AVIF_AVAILABLE = True
        except Exception:
            _AVIF_AVAILABLE = False

    _OPTIONAL_DECODERS_REGISTERED = True


def _open_image(raw_bytes: bytes):


    try:
        from PIL import Image
    except Exception:
        logger.exception("[IMG-FMT] Pillow unavailable")
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
                                                                     
                                                                   
        img.load()
        return img
    except Exception:
        return None


def normalize_with_reason(
    raw_bytes: Optional[bytes],
    *, mime_hint: Optional[str] = None,
    target_mime: str = "image/jpeg",
) -> tuple[Optional[bytes], Optional[str], str]:


    if not raw_bytes:
        return None, None, DECODE_BAND_EMPTY_INPUT
    register_optional_decoders()

    canonical = (
        canonicalize_image_mime(mime_hint)
        or detect_mime_from_bytes(raw_bytes)
        or ""
    )

                                                                     
    if canonical in _VECTOR_OR_NON_DECODABLE_MIMES:
        logger.info(
            "[IMG-FMT] skipped band=%s mime=%s",
            DECODE_BAND_UNSUPPORTED_FORMAT, canonical or "unknown",
        )
        return None, None, DECODE_BAND_UNSUPPORTED_FORMAT

    img = _open_image(raw_bytes)
    if img is None:
                                                                   
                                                                 
        if canonical in ("image/heic", "image/heif") and not _HEIF_AVAILABLE:
            band = DECODE_BAND_DECODER_MISSING
        elif canonical == "image/avif" and not _AVIF_AVAILABLE:
            band = DECODE_BAND_DECODER_MISSING
        elif canonical and canonical in _RASTER_DECODABLE_MIMES:
                                                                  
                                            
            band = DECODE_BAND_CORRUPT
        else:
                                                  
            band = DECODE_BAND_UNSUPPORTED_FORMAT
        logger.warning(
            "[IMG-FMT] decode failed band=%s mime=%s",
            band, canonical or "unknown",
        )
        return None, None, band

    target = target_mime.strip().lower() if target_mime else "image/jpeg"
    if target not in ("image/jpeg", "image/png"):
        target = "image/jpeg"

    try:
        if target == "image/jpeg":
                                                       
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, optimize=True)
            return buf.getvalue(), "image/jpeg", DECODE_BAND_OK
        else:
            if img.mode not in ("RGBA", "RGB", "L", "LA"):
                img = img.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png", DECODE_BAND_OK
    except Exception:
        logger.exception("[IMG-FMT] re-encode failed")
        return None, None, DECODE_BAND_DECODE_FAILED
    finally:
        try:
            img.close()
        except Exception:
            pass


def normalize_to_supported_image(
    raw_bytes: Optional[bytes],
    *, mime_hint: Optional[str] = None,
    target_mime: str = "image/jpeg",
) -> Optional[tuple[bytes, str]]:


    encoded, mime, _band = normalize_with_reason(
        raw_bytes, mime_hint=mime_hint, target_mime=target_mime,
    )
    if encoded is None:
        return None
    return encoded, mime or "image/jpeg"


def normalize_for_vision(
    raw_bytes: Optional[bytes],
    *, mime_hint: Optional[str] = None,
) -> Optional[tuple[bytes, str]]:


    if not raw_bytes:
        return None
    canonical = (
        detect_mime_from_bytes(raw_bytes)
        or canonicalize_image_mime(mime_hint)
    )
    if canonical in _VISION_NATIVE_MIMES:
        return raw_bytes, canonical or "image/jpeg"
                                                               
                                   
    return normalize_to_supported_image(
        raw_bytes, mime_hint=canonical or mime_hint,
        target_mime="image/jpeg",
    )


def decoder_availability() -> dict[str, bool]:


    register_optional_decoders()
    return {
        "pillow":      _pillow_available(),
        "heif":        _HEIF_AVAILABLE,
        "avif":        _AVIF_AVAILABLE,
    }


def _pillow_available() -> bool:
    try:
        import PIL              

        return True
    except Exception:
        return False


__all__ = [
    "SUPPORTED_IMAGE_MIMES",
    "EXTENSION_TO_MIME",
    "MIME_ALIASES",
    "MIME_TO_EXTS",
                                 
    "FORMAT_LABEL_JPEG", "FORMAT_LABEL_PNG", "FORMAT_LABEL_HEIC",
    "FORMAT_LABEL_HEIF", "FORMAT_LABEL_WEBP", "FORMAT_LABEL_TIFF",
    "FORMAT_LABEL_BMP", "FORMAT_LABEL_GIF", "FORMAT_LABEL_AVIF",
    "FORMAT_LABEL_SVG", "FORMAT_LABEL_OTHER", "ALL_FORMAT_LABELS",
                                
    "DECODE_BAND_OK", "DECODE_BAND_DECODER_MISSING",
    "DECODE_BAND_DECODE_FAILED", "DECODE_BAND_UNSUPPORTED_FORMAT",
    "DECODE_BAND_CORRUPT", "DECODE_BAND_EMPTY_INPUT",
    "ALL_DECODE_BANDS",
                           
    "canonicalize_image_mime",
    "is_supported_image_mime",
    "is_supported_image_extension",
    "mime_from_extension",
    "detect_mime_from_bytes",
    "detect_image_format",
    "is_image_row",
    "resolve_image_mime",
    "register_optional_decoders",
    "normalize_to_supported_image",
    "normalize_with_reason",
    "normalize_for_vision",
    "decoder_availability",
]
