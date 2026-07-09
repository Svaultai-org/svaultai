

from __future__ import annotations

import logging
import re
from typing import Optional


logger = logging.getLogger(__name__)


_OVERCLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
                                                                      
                                      
    (r"(?:vaultai|the\s+vault|your\s+vault|i)"
     r"(?:\s+|(?:'|’)?ll\s+|(?:'|’)?ve\s+)"
     r"(?:will\s+|can\s+|am\s+going\s+to\s+)?"
     r"(?:track|locate|find|recover|retrieve|return)\s+"
     r"(?:your|the|my)\s+"
     r"(?:lost|missing|stolen)?\s*"
     r"(?:phone|device|laptop|iphone|ipad|tablet|mac|"
     r"computer|pc)",
     "overclaim_track_subject"),
                                                                  
    (r"(?:vaultai|the\s+vault|your\s+vault|i)"
     r"(?:\s+|(?:'|’)?ll\s+|(?:'|’)?ve\s+)"
     r"(?:will\s+|can\s+|am\s+going\s+to\s+)?"
     r"(?:help\s+you\s+|let\s+you\s+|allow\s+you\s+to\s+)?"
     r"(?:track|locate|recover)\s+"
     r"(?:your|the|my)\s+"
     r"(?:stolen|lost|missing)\s+"
     r"(?:phone|device|laptop|iphone|ipad|tablet)",
     "overclaim_help_track"),
                                                           
    (r"(?:vaultai|the\s+vault|your\s+vault)\s+"
     r"(?:tracks|locates|finds|recovers|retrieves)\s+"
     r"(?:your\s+|the\s+|my\s+)?"
     r"(?:devices|phones|laptops|iphones)",
     "overclaim_tracks_generic"),
)


_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), slug)
    for pat, slug in _OVERCLAIM_PATTERNS
]


SAFE_FRAMING_TEXT: str = (
    "I store the details you'll need if the device is lost or "
    "stolen — IMEI, serial number, receipt — so you can report it "
    "to your carrier, the police, or recover it through Find My "
    "iPhone / Find My Device."
)


SYSTEM_PROMPT_RULE: str = (
    "DEVICE VAULT (anti-overclaim — pinned by tests):\n"
    "- You STORE device details (IMEI, serial number, receipt, "
    "lock-screen note, emergency contact) so the user can recover "
    "or report the device if it's lost or stolen.\n"
    "- You do NOT track, locate, recover, or return a stolen "
    "phone yourself. Actual tracking depends on Find My iPhone, "
    "Find My Device, the carrier, the police, or the platform's "
    "own tools.\n"
    "- Good phrasing: \"Store the details you'll need if the "
    "device is lost or stolen.\" / \"You can report it to your "
    "carrier with the IMEI you saved.\" / \"Use Find My iPhone "
    "with the serial number stored here.\"\n"
    "- Forbidden phrasing: \"VaultAI will track your stolen "
    "phone.\" / \"I'll locate your lost device.\" / \"The vault "
    "tracks your iPhone.\"\n"
    "- If the user says \"my phone was stolen\" — calmly list "
    "what you have on file for that device (masked IMEI, masked "
    "serial, lock-screen note, emergency contact, receipt link) "
    "and remind them they can use those details with their "
    "carrier, the police, or Find My iPhone / Find My Device."
)


def detect_overclaim(reply_text: Optional[str]) -> Optional[str]:


    if not reply_text:
        return None
    text = str(reply_text)
    for pat, slug in _COMPILED:
        if pat.search(text):
            return slug
    return None


def rewrite_overclaim(
    reply_text: Optional[str],
) -> tuple[str, Optional[str]]:


    if not reply_text:
        return "", None
    text = str(reply_text)
    for pat, slug in _COMPILED:
        m = pat.search(text)
        if m is None:
            continue
                                      
        before_text = text[:m.start()]
                                                  
        last_boundary = max(
            before_text.rfind("."),
            before_text.rfind("!"),
            before_text.rfind("?"),
            before_text.rfind("\n"),
        )
        sentence_start = last_boundary + 1 if last_boundary >= 0 else 0
                                                  
        rest = text[m.end():]
        next_boundary = min(
            (i for i in (
                rest.find("."),
                rest.find("!"),
                rest.find("?"),
                rest.find("\n"),
            ) if i >= 0),
            default=-1,
        )
        sentence_end = (
            m.end() + next_boundary + 1
            if next_boundary >= 0
            else len(text)
        )
        rewritten = (
            text[:sentence_start].rstrip()
            + ((" " if sentence_start > 0 else ""))
            + SAFE_FRAMING_TEXT
            + text[sentence_end:]
        )
        logger.warning(
            "[DEVICE-SAFETY] rewrote_overclaim slug=%s "
            "reply_len=%d",
            slug, len(text),
        )
        return rewritten, slug
    return text, None


__all__ = [
    "FORBIDDEN_OVERCLAIM_PATTERNS",
    "SAFE_FRAMING_TEXT",
    "SYSTEM_PROMPT_RULE",
    "detect_overclaim",
    "rewrite_overclaim",
]


FORBIDDEN_OVERCLAIM_PATTERNS: tuple[str, ...] = tuple(
    p for p, _ in _OVERCLAIM_PATTERNS
)
