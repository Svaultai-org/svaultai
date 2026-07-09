

from __future__ import annotations

import re
from typing import Optional


_REF_PURE = re.compile(
    r"(?i)\b(?:the|that|this)\s+one\b",
)

                                                               
_REF_FIRST = re.compile(
    r"(?i)\b(?:the\s+)?(?:first|1st|top|number\s*1|#\s*1)\s+"
    r"(?:one|file|result|match|item)?\b",
)

                                                                
_REF_NUMERIC = re.compile(
    r"(?i)(?:^|\b)(?:#\s*|number\s+)?(?P<n>[2-9])(?:nd|rd|th)?\s+"
    r"(?:one|file|result|match|item)\b",
)
                                                              
_WORD_ORDINALS: dict[str, int] = {
    "second": 2, "2nd": 2,
    "third":  3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth":  5, "5th": 5,
}
_REF_WORD_ORDINAL = re.compile(
    r"(?i)\b(?:the\s+)?(?P<w>second|third|fourth|fifth|2nd|3rd|4th|5th)\s+"
    r"(?:one|file|result|match|item)?\b",
)

                                    
_REF_LAST = re.compile(
    r"(?i)\b(?:the\s+)?(?:last|bottom)\s+(?:one|file|result|match|item)?\b",
)

                                                            
_REF_STRONG = re.compile(
    r"(?i)\b(?:the\s+)?(?:strong(?:est)?|best)\s+(?:one|ones|file|files|match|matches|result|results)?\b",
)
_REF_MEDIUM = re.compile(
    r"(?i)\b(?:the\s+)?medium\s+(?:one|ones|file|files|match|matches|result|results)?\b",
)
_REF_WEAK = re.compile(
    r"(?i)\b(?:the\s+)?weak\s+(?:one|ones|file|files|match|matches|result|results)?\b",
)

                                                               
_REF_EVERYTHING = re.compile(
    r"(?i)\b(?:the\s+)?one\s+with\s+everything\b",
)

                                                                  
_REF_HASHN = re.compile(
    r"(?i)#\s*(?P<n>\d+)\b",
)


_EXPLICIT_SAVED_LOGIN = re.compile(
    r"(?i)\b(?:saved\s+logins?|vault\s+items?|"
    r"my\s+passwords?\s+vault|password\s+manager)\b",
)


def detect_followup_reference(message: str) -> Optional[dict]:


    if not message:
        return None
    text = message.strip()
    if not text:
        return None

    if _EXPLICIT_SAVED_LOGIN.search(text):
        return None

                                                                  
    if _REF_EVERYTHING.search(text):
        return {"selector": "everything"}

                                
    if _REF_STRONG.search(text):
        return {"selector": "strong"}
    if _REF_MEDIUM.search(text):
        return {"selector": "medium"}
    if _REF_WEAK.search(text):
        return {"selector": "weak"}

                          
    if _REF_LAST.search(text):
        return {"selector": "last"}
    if _REF_FIRST.search(text):
        return {"selector": "first"}

    m = _REF_HASHN.search(text)
    if m:
        return {"selector": "ordinal", "n": int(m.group("n"))}
    m = _REF_NUMERIC.search(text)
    if m:
        return {"selector": "ordinal", "n": int(m.group("n"))}
    m = _REF_WORD_ORDINAL.search(text)
    if m:
        n = _WORD_ORDINALS.get(m.group("w").lower())
        if n:
            return {"selector": "ordinal", "n": n}

    if _REF_PURE.search(text):
        return {"selector": "pure"}

    return None


def resolve_followup(
    message: str,
    last_search: Optional[dict],
) -> dict:


    reference = detect_followup_reference(message)
    if reference is None:
        return {"action": "none"}
    if not last_search:
        return {"action": "none"}
    results = last_search.get("results") or []
    if not results:
        return {"action": "none"}

    selector = reference["selector"]
    n = reference.get("n")

                          
    if selector == "first":
        return {"action": "open_one", "file": results[0]}
    if selector == "last":
        return {"action": "open_one", "file": results[-1]}
    if selector == "ordinal":
        idx = (int(n) - 1) if n else 0
        if 0 <= idx < len(results):
            return {"action": "open_one", "file": results[idx]}
                                                                
                                                            
        return _disambiguate(results)

                                         
    if selector in ("strong", "medium", "weak"):
        bucket = [r for r in results if r.get("confidence") == selector]
        if len(bucket) == 1:
            return {"action": "open_one", "file": bucket[0]}
        if len(bucket) > 1:
            return _disambiguate(bucket)
                                                                  
                                                         
        return {"action": "none"}

                                                           
    if selector == "everything":
                                                              
                                                              
        winner = _pick_clear_credential_winner(results)
        if winner is not None:
            return {"action": "open_one", "file": winner}
                                                                  
                                                                 
        mostly = [r for r in results if r.get("mostly_credentials")]
        if len(mostly) > 1:
            return _disambiguate(mostly)
        strong = [r for r in results if r.get("confidence") == "strong"]
        if len(strong) == 1:
            return {"action": "open_one", "file": strong[0]}
        if len(strong) > 1:
            return _disambiguate(strong)
        if len(results) == 1:
            return {"action": "open_one", "file": results[0]}
        return _disambiguate(results)

                                           
    if selector == "pure":
                                                            
        if len(results) == 1:
            return {"action": "open_one", "file": results[0]}
                                                               
                                       
        winner = _pick_clear_credential_winner(results)
        if winner is not None:
            return {"action": "open_one", "file": winner}
                                                               
                                                                 
        strong = [r for r in results if r.get("confidence") == "strong"]
        if len(strong) == 1:
            return {"action": "open_one", "file": strong[0]}
        return _disambiguate(results)

    return {"action": "none"}


def _pick_clear_credential_winner(results: list[dict]) -> Optional[dict]:


    if not results:
        return None
    for r in results:
        if r.get("best_match") is True:
            return r
    return None


def _disambiguate(files: list[dict]) -> dict:


    return {"action": "disambiguate", "files": files[:5]}


def format_followup_disambiguation(files: list[dict]) -> str:


    if not files:
        return (
            "I couldn't tell which file you meant. "
            "Could you say more — name, folder, or confidence?"
        )

    confidences = {(f.get("confidence") or "").lower() for f in files}
    if confidences == {"strong"}:
        headline = (
            f"I found {len(files)} strong credential-file matches. "
            "Which one do you mean?"
        )
    elif "strong" in confidences:
        headline = (
            f"I found {len(files)} matches from the previous file "
            "search. Which one do you mean?"
        )
    else:
        headline = (
            f"I found {len(files)} matches from the previous file "
            "search. Which one do you mean?"
        )

    lines = [headline]
    for i, f in enumerate(files, start=1):
        label = (
            (f.get("saved_name") or "").strip()
            or (f.get("file_name") or "file")
        )
        rp = (f.get("relative_path") or "").strip()
        conf = (f.get("confidence") or "").strip()
        line = f"{i}. {label}"
        if conf:
            line += f" [{conf}]"
        if rp:
            line += f" — {rp}"
        lines.append(line)
    return "\n".join(lines)


def format_followup_open_one_message(file: dict) -> str:

    label = (
        (file.get("saved_name") or "").strip()
        or (file.get("file_name") or "this file")
    )
    return f"Here is {label}."
