"""Conservative evidence gate for bank-document upload classification.

Mentioning a bank-related word is not evidence that the file contains bank
details. This gate never extracts, saves, logs, or validates a real account.
Unrecognized formats remain ordinary uploaded files.
"""
from typing import Optional
import re


_NEGATION = re.compile(r"\b(?:no|not|without|never|neither)\b", re.IGNORECASE)
_BANK_CONTEXT = re.compile(r"\b(?:bank|banking)\b", re.IGNORECASE)
_ACCOUNT = re.compile(
    r"\b(?:bank\s+)?(?:account|acct\.?)\s*(?:number|no\.?|#)\s*"
    r"(?:[:=]\s*|is\s+)?(?P<value>\d[\d -]{4,38}\d)(?!\w)",
    re.IGNORECASE,
)
_ROUTING = re.compile(
    r"\b(?:aba\s+)?routing(?:\s+(?:number|no\.?))?\s*"
    r"(?:[:=]\s*|is\s+)?(?P<value>\d{9})(?!\w)",
    re.IGNORECASE,
)
_IBAN = re.compile(
    r"\biban\s*(?:[:=]\s*|is\s+)?"
    r"(?P<value>[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30})(?!\w)",
    re.IGNORECASE,
)
_BIC = re.compile(
    r"\b(?:swift(?:\s*[/ -]\s*bic)?|bic)\b\s*(?:code\s*)?"
    r"(?:[:=]\s*|is\s+)(?P<value>[A-Z]{6}[A-Z0-9]{2}"
    r"(?:[A-Z0-9]{3})?)(?!\w)",
    re.IGNORECASE,
)


def _affirmative(line: str, start: int) -> bool:
    # Ignore negation in the candidate's own preceding clause, not a separate
    # disclaimer elsewhere in a document with genuine labelled details.
    prefix = re.split(r"[.!?;]", line[:start])[-1]
    return _NEGATION.search(prefix) is None


def has_substantive_bank_data(text: Optional[str]) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    lines = text.splitlines()
    bank_context = any(
        _affirmative(line, match.start())
        for line in lines for match in _BANK_CONTEXT.finditer(line)
    )
    for line in lines:
        for pattern in (_ROUTING, _IBAN, _BIC, _ACCOUNT):
            for match in pattern.finditer(line):
                if not _affirmative(line, match.start()):
                    continue
                value = re.sub(r"[ -]", "", match.group("value"))
                if pattern is _ACCOUNT:
                    if not bank_context or not 6 <= len(value) <= 34:
                        continue
                elif pattern is _IBAN and not 15 <= len(value) <= 34:
                    continue
                elif pattern is _BIC and not match.group("value").isupper():
                    # Ordinary prose such as "Swift: programming" is not a
                    # supplied financial identifier. Keep uncertain OCR as a file.
                    continue
                return True
    return False
