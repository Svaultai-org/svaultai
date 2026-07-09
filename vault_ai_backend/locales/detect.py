

from __future__ import annotations

from typing import Optional


_ARABIC_RANGES = (
    (0x0600, 0x06FF),          
    (0x0750, 0x077F),                     
    (0x08A0, 0x08FF),                     
    (0xFB50, 0xFDFF),                               
    (0xFE70, 0xFEFF),                               
)
_HANGUL_RANGES = (
    (0xAC00, 0xD7AF),                    
    (0x1100, 0x11FF),               
    (0x3130, 0x318F),                             
)
_HIRAGANA_RANGES = (
    (0x3040, 0x309F),
)
_KATAKANA_RANGES = (
    (0x30A0, 0x30FF),
    (0x31F0, 0x31FF),
)
_HAN_RANGES = (
    (0x4E00, 0x9FFF),                          
    (0x3400, 0x4DBF),                   
)


def _in_ranges(cp: int, ranges: tuple) -> bool:
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False


def _classify_char(ch: str) -> Optional[str]:


    if not ch or not ch.isalpha():
        return None
    cp = ord(ch)
    if _in_ranges(cp, _ARABIC_RANGES):
        return "ar"
    if _in_ranges(cp, _HANGUL_RANGES):
        return "ko"
    if _in_ranges(cp, _HIRAGANA_RANGES) or _in_ranges(cp, _KATAKANA_RANGES):
        return "ja"
    if _in_ranges(cp, _HAN_RANGES):
                                                                    
                                                                     
        return "han"
                                                                    
    return None


_MIN_ALPHA_CHARS = 5
_PLURALITY_THRESHOLD = 0.4
                                                  
                                                                
_INSPECT_CHARS = 2048


def detect_document_locale(
    text: Optional[str], user_locale: Optional[str] = "en",
) -> str:


    try:
        if not text:
            return user_locale or "en"
        window = text[:_INSPECT_CHARS]
        counts: dict = {}
        total_alpha = 0
        for ch in window:
            tag = _classify_char(ch)
            if tag is None and ch.isalpha():
                                                                   
                                                            
                total_alpha += 1
                continue
            if tag is None:
                continue
            total_alpha += 1
            counts[tag] = counts.get(tag, 0) + 1
        if total_alpha < _MIN_ALPHA_CHARS or not counts:
            return user_locale or "en"

                                                                      
        from . import SUPPORTED_LOCALES
        ja_count   = counts.get("ja", 0)
        han_count  = counts.pop("han", 0)
        if ja_count > 0:
            counts["ja"] = ja_count + han_count
        elif han_count > 0:
            counts["zh"] = counts.get("zh", 0) + han_count

        top, top_count = max(counts.items(), key=lambda x: x[1])
        if top_count / total_alpha < _PLURALITY_THRESHOLD:
            return user_locale or "en"
        if top in SUPPORTED_LOCALES:
            return top
        return user_locale or "en"
    except Exception:
        return user_locale or "en"


def detect_script(text: Optional[str]) -> str:

    try:
        if not text:
            return "other"
        counts: dict[str, int] = {}
        total_alpha = 0
        for ch in text[:_INSPECT_CHARS]:
            if not ch.isalpha():
                continue
            total_alpha += 1
            cp = ord(ch)
            if _in_ranges(cp, _ARABIC_RANGES):
                counts["arabic"] = counts.get("arabic", 0) + 1
            elif _in_ranges(cp, _HANGUL_RANGES):
                counts["hangul"] = counts.get("hangul", 0) + 1
            elif (_in_ranges(cp, _HIRAGANA_RANGES)
                  or _in_ranges(cp, _KATAKANA_RANGES)
                  or _in_ranges(cp, _HAN_RANGES)):
                counts["cjk"] = counts.get("cjk", 0) + 1
            elif 0x0041 <= cp <= 0x024F:
                                                         
                counts["latin"] = counts.get("latin", 0) + 1
            else:
                counts["other"] = counts.get("other", 0) + 1
        if not counts or total_alpha < 2:
            return "other"
        top = max(counts.items(), key=lambda x: x[1])[0]
        return top
    except Exception:
        return "other"
