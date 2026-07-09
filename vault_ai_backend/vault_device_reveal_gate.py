

from __future__ import annotations

import logging
import re
from typing import Optional


logger = logging.getLogger(__name__)


REVEAL_FIELD_ALL:    str = "all"
REVEAL_FIELD_IMEI:   str = "imei"
REVEAL_FIELD_SERIAL: str = "serial"
REVEAL_FIELD_MAC:    str = "mac"
REVEAL_FIELD_PHONE:  str = "phone"
REVEAL_FIELD_RECOVERY: str = "recovery_reference"
REVEAL_FIELD_BACKUP:    str = "backup_code"
REVEAL_FIELD_PRIVATE:   str = "private_note"
REVEAL_FIELD_ACCOUNT:   str = "account_note"

ALL_REVEAL_FIELDS: tuple[str, ...] = (
    REVEAL_FIELD_ALL, REVEAL_FIELD_IMEI, REVEAL_FIELD_SERIAL,
    REVEAL_FIELD_MAC, REVEAL_FIELD_PHONE, REVEAL_FIELD_RECOVERY,
    REVEAL_FIELD_BACKUP, REVEAL_FIELD_PRIVATE, REVEAL_FIELD_ACCOUNT,
)


_REVEAL_FIELD_PATTERNS: tuple[tuple[str, str], ...] = (
          
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"imei(?:\s+number)?\b",                       REVEAL_FIELD_IMEI),
    (r"\bfull\s+imei\b",                            REVEAL_FIELD_IMEI),
    (r"\bwhat\s+imei\s+did\s+i\s+save\b",           REVEAL_FIELD_IMEI),
            
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"serial(?:\s+number)?\b",                     REVEAL_FIELD_SERIAL),
    (r"\bfull\s+serial(?:\s+number)?\b",            REVEAL_FIELD_SERIAL),
    (r"\bshow\s+my\s+laptop\s+serial\s+number\b",   REVEAL_FIELD_SERIAL),
         
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"mac(?:\s+address)?\b",                       REVEAL_FIELD_MAC),
    (r"\bfull\s+mac(?:\s+address)?\b",              REVEAL_FIELD_MAC),
           
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"phone\s+number\b",                           REVEAL_FIELD_PHONE),
    (r"\bfull\s+phone\s+number\b",                  REVEAL_FIELD_PHONE),
                                                
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:the\s+)?(?:bitlocker|filevault)\s+"
     r"(?:recovery\s+)?key(?:\s+reference)?\b",     REVEAL_FIELD_RECOVERY),
                                                                   
                                            
    (r"\bopen\s+(?:this|that|the)?\s*"
     r"(?:phone|laptop|device|iphone|ipad|tablet|mac|computer)\b",
     REVEAL_FIELD_ALL),
    (r"\bshow\s+(?:the\s+)?full\s+(?:details|record|info)\b",
     REVEAL_FIELD_ALL),
    (r"\breveal\s+(?:the\s+)?full\s+(?:details|record|info)\b",
     REVEAL_FIELD_ALL),
                              
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"backup\s+codes?\b",                          REVEAL_FIELD_BACKUP),
    (r"\bfull\s+backup\s+codes?\b",                 REVEAL_FIELD_BACKUP),
                                                  
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"private\s+(?:note|word|phrase|secret)\b",    REVEAL_FIELD_PRIVATE),
    (r"\bfull\s+private\s+(?:note|word|phrase|secret)\b",
     REVEAL_FIELD_PRIVATE),
                   
    (r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?|give\s+me)\s+"
     r"(?:me\s+)?(?:the\s+|my\s+|full\s+|that\s+)*"
     r"account\s+notes?\b",                          REVEAL_FIELD_ACCOUNT),
    (r"\bfull\s+account\s+notes?\b",                REVEAL_FIELD_ACCOUNT),
)


_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in _REVEAL_FIELD_PATTERNS
]


def reveal_target_field(user_message: Optional[str]) -> Optional[str]:


    if not isinstance(user_message, str) or not user_message:
        return None
    for pat, label in _COMPILED:
        if pat.search(user_message):
            return label
    return None


def is_explicit_reveal_request(user_message: Optional[str]) -> bool:


    return reveal_target_field(user_message) is not None


_STRICT_FULL_REVEAL_RE: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:show|tell\s+me|give\s+me|"
        r"what(?:\s+is|(?:'|’)?s)?)\s+"
        r"(?:me\s+)?(?:the\s+|my\s+|that\s+)*"
        r"full\s+",
        re.IGNORECASE,
    ),
    re.compile(r"\breveal\b",                re.IGNORECASE),
    re.compile(
        r"\bopen\s+(?:this|that|the|my)?\s*"
        r"(?:imei|serial|mac|phone|note|"
        r"backup|recovery|secret|record|item)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bunmask\b",                re.IGNORECASE),
)


def is_explicit_full_reveal_request(
    user_message: Optional[str],
) -> bool:


    if not isinstance(user_message, str) or not user_message:
        return False
    for pat in _STRICT_FULL_REVEAL_RE:
        if pat.search(user_message):
            return True
    return False


__all__ = [
    "REVEAL_FIELD_ALL",
    "REVEAL_FIELD_IMEI",
    "REVEAL_FIELD_SERIAL",
    "REVEAL_FIELD_MAC",
    "REVEAL_FIELD_PHONE",
    "REVEAL_FIELD_RECOVERY",
    "REVEAL_FIELD_BACKUP",
    "REVEAL_FIELD_PRIVATE",
    "REVEAL_FIELD_ACCOUNT",
    "ALL_REVEAL_FIELDS",
    "reveal_target_field",
    "is_explicit_reveal_request",
    "is_explicit_full_reveal_request",
]
