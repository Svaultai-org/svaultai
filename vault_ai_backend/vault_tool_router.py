

from __future__ import annotations

import logging
import os
import re
from typing import Iterable


logger = logging.getLogger(__name__)


BASE_TOOLS = (
    "get_vault_status",
    "list_vault_files",
    "search_extracted_text",
)


BUCKET_TOOLS = {
    "vault_state": (
        "get_vault_status",
        "get_vault_overview",
        "get_vault_intelligence",
    ),
    "file_list": (
        "list_vault_files",
        "list_files_by_category",
        "list_document_categories",
    ),
    "file_search": (
        "search_extracted_text",
        "search_vault_content",
        "list_vault_files",
                                                                   
                                                           
        "find_in_vault",
    ),
    "file_read": (
        "read_file_text",
        "read_image_with_vision",
        "read_media_transcript",
        "inspect_uploaded_file",
        "get_file_metadata",
        "list_file_chunks",
        "read_file_chunk",
    ),
    "credentials": (
        "list_secrets",
        "retrieve_secret",
        "save_secret",
        "list_saved_credentials",
        "get_credential_metadata",
        "save_generated_credential_after_confirmation",
                                                         
                                                              
        "generate_credential_draft",
    ),
    "entities": (
        "list_vault_entities",
        "find_files_for_entity",
    ),
    "relationships": (
        "list_file_relationships",
    ),
    "expiry": (
        "list_expiring_items",
        "get_expiry_alert",
    ),
    "activity": (
        "get_vault_activity",
    ),
}


INTENT_PATTERNS: tuple[tuple[str, str], ...] = (
                                                                    
                        
    ("file_read", (
        r"\b(read|open|inspect|look at|view|show me what|"
        r"what does|whose face|what.s (in|inside)|content of|"
        r"contents of|inside|inside this|what.s on|what.s "
        r"written)\b"
        r"|\b(transcript|transcribe|caption|subtitle|"
        r"summary of)\b"
        r"|\b(photo|picture|image|pdf|video|audio|voice "
        r"memo|recording|screenshot|scan)\b"
    )),
                                                  
    ("file_search", (
        r"\b(find|search|locate|look for|where is|where are|"
        r"any (file|files|photo|picture|image|video|"
        r"document|pdf|note|record)|do i have|do you have)\b"
        r"|\b(mentions?|matching|contain|containing)\b"
    )),
                                                 
    ("file_list", (
        r"\b(list|show me all|show all|how many|what files|"
        r"what documents|what photos|what videos|what audio|"
        r"my files|my documents|my photos|my videos|my audio|"
        r"recent uploads|recently uploaded|categories|"
        r"document types|kinds of)\b"
    )),
                                                  
    ("vault_state", (
        r"\b(vault|overall|status|summary|overview|how much|"
        r"how big|how full|state of (my )?vault|"
        r"how (much|many) (have you|did you) (analyz|read|"
        r"reviewed)|coverage)\b"
    )),
                                                         
    ("credentials", (
        r"\b(password|username|login|credential|account|"
        r"sign in|signin|sign-in|generate|email and "
        r"password|otp|2fa|two.factor)\b"
        r"|\b(save it|save the credential|save this|"
        r"generate and save)\b"
    )),
                                                  
    ("entities", (
        r"\b(people|person|who is|who are|organization|"
        r"company|companies|place|places|city|cities|where "
        r"do (you|i)|everyone|everybody|entities|name|names)\b"
    )),
                                                              
    ("relationships", (
        r"\b(related|connected|connection|relationship|"
        r"belongs? with|belong together|go together|paired|"
        r"linked|tied|associated)\b"
    )),
                                                                
                                                         
    ("expiry", (
        r"\bexpir|\brenew|\bdue (date|soon)|\bwhen (does|will) "
        r"my (passport|visa|license|id|insurance|subscription)"
        r"|\bdeadline\b"
    )),
                                            
    ("activity", (
        r"\b(recent(ly)?|today|yesterday|this week|"
        r"this month|just (added|uploaded|saved)|new "
        r"uploads|new files|what changed|history)\b"
    )),
)


_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (bucket, re.compile(pat, re.IGNORECASE))
    for bucket, pat in INTENT_PATTERNS
)


def _router_enabled() -> bool:


    val = os.getenv(
        "VAULTAI_TOOL_ROUTER_ENABLED", "true",
    ).strip().lower()
    return val in ("1", "true", "yes", "on")


def select_buckets_for_message(message: str) -> tuple[str, ...]:


    if not isinstance(message, str) or not message.strip():
        return ()
    hits: list[str] = []
    text = message.lower()
    for bucket, pat in _COMPILED:
        if pat.search(text):
            hits.append(bucket)
    return tuple(hits)


def select_tool_names_for_message(message: str) -> set[str]:


    if not _router_enabled():
                                                              
        union: set[str] = set(BASE_TOOLS)
        for tools in BUCKET_TOOLS.values():
            union.update(tools)
        return union

    selected: set[str] = set(BASE_TOOLS)
    buckets = select_buckets_for_message(message)
    for b in buckets:
        for t in BUCKET_TOOLS.get(b, ()):
            selected.add(t)
    return selected


def filter_function_schemas(
    functions: Iterable[dict],
    message: str,
    *,
    keep_secret_tools: bool = True,
) -> list[dict]:


    if not functions:
        return []
    selected = select_tool_names_for_message(message)
    if keep_secret_tools:
        selected.update({
            "save_secret", "retrieve_secret", "list_secrets",
        })
    out: list[dict] = []
    for fn in functions:
        name = (
            fn.get("function", {}).get("name")
            if isinstance(fn, dict) else None
        )
        if not name:
            continue
        if name in selected:
            out.append(fn)
    return out


__all__ = [
    "BASE_TOOLS",
    "BUCKET_TOOLS",
    "INTENT_PATTERNS",
    "select_buckets_for_message",
    "select_tool_names_for_message",
    "filter_function_schemas",
]
