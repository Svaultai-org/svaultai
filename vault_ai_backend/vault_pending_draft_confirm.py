

from __future__ import annotations

import re
from typing import Optional


_CONFIRM_PATTERNS: tuple[str, ...] = (
                           
    r"^\s*save\s+it(?:\s+now)?\s*[.!?]*\s*$",
               
    r"^\s*save\s+this\s*[.!?]*\s*$",
                               
    r"^\s*save\s+that(?:\s+now)?\s*[.!?]*\s*$",
              
    r"^\s*save\s+now\s*[.!?]*\s*$",
                                                            
                               
    r"^\s*save\s*[.!?]*\s*$",
                                                       
    r"^\s*please[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
         
    r"^\s*yes\s*[.!?]*\s*$",
                                                            
    r"^\s*yes[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
                                                   
                                                                     
    r"^\s*(?:yea|yeah|yep|yup)\s*[.!?]*\s*$",
    r"^\s*(?:yea|yeah|yep|yup)[\s,.!]+save(?:\s+(?:it|this|that|now))?"
    r"\s*[.!?]*\s*$",
             
    r"^\s*confirm\s*[.!?]*\s*$",
                  
    r"^\s*confirm\s+save\s*[.!?]*\s*$",
                                                  
    r"^\s*go\s+ahead(?:\s+and\s+save(?:\s+(?:it|this|that))?)?\s*[.!?]*\s*$",
                                        
    r"^\s*store\s+(?:it|this|that)\s*[.!?]*\s*$",
                                     
    r"^\s*keep\s+(?:it|this|that)\s*[.!?]*\s*$",
                                  
    r"^\s*add\s+(?:it|this|that)\s*[.!?]*\s*$",
                                 
    r"^\s*ok(?:ay)?[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
                         
    r"^\s*sure[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
           
    r"^\s*do\s+it\s*[.!?]*\s*$",
)


_COMPILED_CONFIRM: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _CONFIRM_PATTERNS
)


_SAVE_THEMED_PATTERNS: tuple[str, ...] = (
    r"^\s*save\s+it(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+this\s*[.!?]*\s*$",
    r"^\s*save\s+that(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+now\s*[.!?]*\s*$",
    r"^\s*save\s*[.!?]*\s*$",
    r"^\s*please[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*yes[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*(?:yea|yeah|yep|yup)[\s,.!]+save(?:\s+(?:it|this|that|now))?"
    r"\s*[.!?]*\s*$",
    r"^\s*confirm\s+save\s*[.!?]*\s*$",
    r"^\s*go\s+ahead\s+and\s+save(?:\s+(?:it|this|that))?\s*[.!?]*\s*$",
    r"^\s*store\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*keep\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*add\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*ok(?:ay)?[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*sure[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
)


_COMPILED_SAVE_THEMED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _SAVE_THEMED_PATTERNS
)


NO_DRAFT_FRIENDLY_REPLY: str = (
    "I don't have a pending save right now. Tell me what you'd "
    "like to save first."
)


def is_pending_draft_confirm_phrase(user_message: Optional[str]) -> bool:


    if not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    if not msg:
        return False
    for pat in _COMPILED_CONFIRM:
        if pat.match(msg):
            return True
    return False


def is_save_themed_confirm_phrase(user_message: Optional[str]) -> bool:


    if not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    if not msg:
        return False
    for pat in _COMPILED_SAVE_THEMED:
        if pat.match(msg):
            return True
    return False


__all__ = [
    "is_pending_draft_confirm_phrase",
    "is_save_themed_confirm_phrase",
    "NO_DRAFT_FRIENDLY_REPLY",
]
