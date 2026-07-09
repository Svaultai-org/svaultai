

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


SEARCH_VAULT_CONTENT      = "search_vault_content"
ANSWER_FROM_VAULT_CONTENT = "answer_from_vault_content"
ANSWER_FROM_FILE_CONTENT  = "answer_from_file_content"
SUMMARIZE_FILE_CONTENT    = "summarize_file_content"
SUMMARIZE_FOLDER_CONTENT  = "summarize_folder_content"
CREDENTIAL_LOOKUP         = "credential_lookup"
CONTINUE_LAST_SEARCH      = "continue_last_search"
NOT_VAULT_CONTENT         = "not_vault_content"


BRAIN_INTENTS = frozenset({
    SEARCH_VAULT_CONTENT,
    ANSWER_FROM_VAULT_CONTENT,
    ANSWER_FROM_FILE_CONTENT,
    SUMMARIZE_FILE_CONTENT,
    SUMMARIZE_FOLDER_CONTENT,
    CREDENTIAL_LOOKUP,
    CONTINUE_LAST_SEARCH,
})


@dataclass(frozen=True)
class BrainIntent:


    intent:  str
    reason:  str = ""
    scope_hint: str = ""                                                 

    def is_vault_content(self) -> bool:
        return self.intent in BRAIN_INTENTS

    def to_dict(self) -> dict:
        return {
            "intent":     str(self.intent),
            "reason":     str(self.reason),
            "scope_hint": str(self.scope_hint),
        }


_IMPERATIVE_PREFIX = re.compile(
    r"^\s*("
                
    r"save|store|add|update|change|delete|remove|rename|call\s+it|"
    r"name\s+it|edit|set|put|move|tag|untag|share|export|import|forget|"
                                                                     
                                                                  
    r"create|generate|make|produce|build|invent|"
                                                               
    r"give\s+me|"
                                                               
                                              
    r"i\s+want\s+you\s+to|please\s+(create|generate|make|produce)|"
    r"can\s+you\s+(create|generate|make|produce)"
    r")\b",
    re.IGNORECASE,
)

                                                             
_CONTINUE_LAST_PHRASES = re.compile(
    r"\b("
    r"show\s+more|"
    r"more\s+(matches|results|files|chunks|evidence)|"
    r"search\s+deeper|"
    r"dig\s+deeper|"
    r"keep\s+(looking|searching)|"
    r"any\s+more|"
    r"what\s+else|"
    r"continue\s+searching|"
    r"next\s+page|"
    r"another\s+page|"
    r"anything\s+else"
    r")\b",
    re.IGNORECASE,
)

                                                                 
_SEARCH_VERB = re.compile(
    r"\b(find|search|look\s+for|show\s+me|list)\b", re.IGNORECASE,
)

                                                   
_DO_I_HAVE = re.compile(
    r"\b(do|did)\s+i\s+(have|own|save|store|keep|put)\b", re.IGNORECASE,
)

                                                          
_ABOUT_FILES = re.compile(
    r"\b(any(thing)?|some(thing)?|files?|documents?|notes?|stuff)\b"
    r"[^?]*?\b(about|mention(?:ing|s)?|with|related\s+to|that\s+mention)\b",
    re.IGNORECASE,
)

                                                  
_WHICH_FILES = re.compile(
    r"\b(which|what)\b[^?]*?\b(files?|documents?|notes?)\b"
    r"[^?]*?\b(mention|contain|talk\s+about|say|reference|"
    r"have|include|cover)\b",
    re.IGNORECASE,
)

                                                               
_THIS_FILE = re.compile(
    r"\b(this|that)\s+(file|pdf|document|doc|image|photo|"
    r"picture|recording|audio|video|page|note)\b",
    re.IGNORECASE,
)

                                          
_SAY_VERB = re.compile(
    r"\b(say|states?|tells?|describes?|reads?|contains?)\b",
    re.IGNORECASE,
)

                  
_THIS_FOLDER = re.compile(
    r"\b(this|that|my)\s+(folder|directory|category)\b",
    re.IGNORECASE,
)

                                          
_SUMMARIZE_VERB = re.compile(
    r"\b(summari[sz]e|summary|tl;?dr|recap|brief|overview)\b",
    re.IGNORECASE,
)

                                                                 
_CREDENTIAL_NOUN = re.compile(
    r"\b(password|passcode|pin|login|credentials?|"
    r"username|account\s+number|routing\s+number|card\s+number|"
    r"cvv|expiry|expiration|secret|api\s+key|recovery\s+code)\b",
    re.IGNORECASE,
)

                                                            
_MY_CREDENTIAL_REFERENT = re.compile(
    r"\bmy\s+(card|gmail|chase|bank|ally|wells\s+fargo|capital\s+one|"
    r"netflix|amazon|paypal|venmo|cash\s*app|stripe|github|"
    r"twitter|facebook|instagram|tiktok|apple\s+id|google|"
    r"icloud|outlook|hotmail|yahoo|microsoft|adobe|spotify|"
    r"discord|reddit|slack|zoom|dropbox|notion|figma|"
    r"bank\s+account|credit\s+card|debit\s+card|account)\b",
    re.IGNORECASE,
)

                                                                 
_WHAT_DID_I_SAVE = re.compile(
    r"\bwhat\s+(did|do)\s+i\s+(have|save|store|keep|put|own)\b",
    re.IGNORECASE,
)

                                                               
_QUESTION_SHAPE = re.compile(
    r"^\s*(what|which|when|where|who|why|how|do|did|does|"
    r"is|are|was|were|can|could|should|find|search|show|list|tell)\b",
    re.IGNORECASE,
)

                                                                     
_LIST_SAVED_LOGINS = re.compile(
    r"\b(show|list|see|view)\b[^?]*?\b(my\s+)?"
    r"(saved\s+)?(logins?|credentials?|passwords?)\b",
    re.IGNORECASE,
)

_FILE_CREDENTIAL_COVERAGE_FOLLOWUP = re.compile(
    r"\b(only|all|rest|these|those|both|any\s+more|what\s+about)\b"
    r"[^?]*?\b(files?|documents?)\b"
    r"[^?]*?\b(password|login|credentials?|secrets?|api\s+key|token)s?\b",
    re.IGNORECASE,
)

                                                                    
_CREDENTIAL_FILES_SEARCH = re.compile(
    r"\b(any|some|which|what|find|search|scan|look\s+for|list|"
    r"show\s+me|are\s+there|is\s+there|do\s+i\s+have)\b"
    r"[^?]*?\bfiles?\b"
    r"[^?]*?\b(passwords?|passcodes?|pins?|logins?|credentials?|"
    r"usernames?|login\s+details|saved\s+credentials?|"
    r"saved\s+logins?|secrets?|api\s+keys?|recovery\s+codes?|"
    r"account\s+numbers?)\b",
    re.IGNORECASE,
)
_LIST_OF_CREDENTIALS_IN_FILES = re.compile(
    r"\blist\s+of\s+(passwords?|logins?|credentials?)\b"
    r"[^?]*?\b(file|files|document|documents|in\s+them|in\s+it)\b",
    re.IGNORECASE,
)
_CREDENTIAL_PLURAL_FILES_FRAMING = re.compile(
                                                                     
                              
    r"\bfiles?\s+(with|that\s+(have|has|contain|contains|hold|holds|"
    r"carry|carries|store|stores|include|includes)|containing|"
    r"holding|having|storing)\b"
    r"[^?]*?\b(passwords?|passcodes?|pins?|logins?|credentials?|"
    r"usernames?|login\s+details|saved\s+credentials?|"
    r"saved\s+logins?|secrets?|api\s+keys?|recovery\s+codes?|"
    r"account\s+numbers?)\b",
    re.IGNORECASE,
)

                                                                     
_BARE_NAME_SHAPE = re.compile(r"^[\w\s'.,&\-]{1,60}$")


def classify_brain_intent(
    message: str,
    *,
    pending_file_present: bool = False,
    has_uploaded_files_in_turn: bool = False,
    has_continuation_context: bool = False,
) -> BrainIntent:


    if not message or not str(message).strip():
        return BrainIntent(intent=NOT_VAULT_CONTENT, reason="empty")

    text = str(message).strip()

                                                                     
    if (
        _CREDENTIAL_FILES_SEARCH.search(text)
        or _LIST_OF_CREDENTIALS_IN_FILES.search(text)
        or _CREDENTIAL_PLURAL_FILES_FRAMING.search(text)
    ):
        if has_continuation_context and \
           _FILE_CREDENTIAL_COVERAGE_FOLLOWUP.search(text):
            return BrainIntent(
                intent=CREDENTIAL_LOOKUP,
                reason="credential_coverage_followup",
            )
        return BrainIntent(
            intent=CREDENTIAL_LOOKUP,
            reason="credential_files_strict_memory",
        )

                                                                   
    if has_continuation_context and _CONTINUE_LAST_PHRASES.search(text):
        return BrainIntent(
            intent=CONTINUE_LAST_SEARCH,
            reason="continue_last_phrase",
        )

    if has_continuation_context and \
       _FILE_CREDENTIAL_COVERAGE_FOLLOWUP.search(text):
        return BrainIntent(
            intent=CREDENTIAL_LOOKUP,
            reason="credential_coverage_followup",
        )

                                                              
    if _IMPERATIVE_PREFIX.search(text):
        return BrainIntent(
            intent=NOT_VAULT_CONTENT,
            reason="imperative_action_prefix",
        )

                                                                       
    if _LIST_SAVED_LOGINS.search(text) and \
       not re.search(r"\blist\s+of\s+(login|credential|password)", text, re.IGNORECASE):
        return BrainIntent(
            intent=NOT_VAULT_CONTENT,
            reason="list_saved_logins_surface",
        )

                                                                       
    if pending_file_present and "?" not in text and \
       not _QUESTION_SHAPE.search(text) and _BARE_NAME_SHAPE.match(text):
        return BrainIntent(
            intent=NOT_VAULT_CONTENT,
            reason="pending_file_bare_name",
        )

                              
    if _SUMMARIZE_VERB.search(text) and _THIS_FOLDER.search(text):
        return BrainIntent(
            intent=SUMMARIZE_FOLDER_CONTENT,
            reason="summarize_folder_phrase",
            scope_hint="this_folder",
        )

                            
    if _SUMMARIZE_VERB.search(text) and (
        _THIS_FILE.search(text)
        or has_uploaded_files_in_turn
    ):
        return BrainIntent(
            intent=SUMMARIZE_FILE_CONTENT,
            reason="summarize_file_phrase",
            scope_hint="this_file",
        )

                                                                    
    if _THIS_FILE.search(text) and (
        _SAY_VERB.search(text)
        or _QUESTION_SHAPE.search(text)
        or "what" in text.lower()
    ):
        return BrainIntent(
            intent=ANSWER_FROM_FILE_CONTENT,
            reason="per_file_content_question",
            scope_hint="this_file",
        )

                                                                  
    if has_uploaded_files_in_turn and _QUESTION_SHAPE.search(text):
        return BrainIntent(
            intent=ANSWER_FROM_FILE_CONTENT,
            reason="upload_turn_question",
            scope_hint="this_file",
        )

                                                                   
    if (
        _CREDENTIAL_FILES_SEARCH.search(text)
        or _LIST_OF_CREDENTIALS_IN_FILES.search(text)
        or _CREDENTIAL_PLURAL_FILES_FRAMING.search(text)
    ):
        return BrainIntent(
            intent=CREDENTIAL_LOOKUP,
            reason="credential_files_strict_memory",
        )

                                                                      
    if _CREDENTIAL_NOUN.search(text):
                                                                     
                                          
        return BrainIntent(
            intent=CREDENTIAL_LOOKUP,
            reason="credential_noun_present",
        )
    if _MY_CREDENTIAL_REFERENT.search(text) and (
        _QUESTION_SHAPE.search(text)
        or _WHAT_DID_I_SAVE.search(text)
    ):
        return BrainIntent(
            intent=CREDENTIAL_LOOKUP,
            reason="my_credential_referent",
        )

                                                                    
    if _DO_I_HAVE.search(text) or _ABOUT_FILES.search(text) or \
       _WHICH_FILES.search(text):
        return BrainIntent(
            intent=SEARCH_VAULT_CONTENT,
            reason="search_for_files_about_x",
        )

                                                                  
    if _SEARCH_VERB.search(text) and _QUESTION_SHAPE.search(text):
        return BrainIntent(
            intent=SEARCH_VAULT_CONTENT,
            reason="search_verb_question",
        )

                                                            
    if _WHAT_DID_I_SAVE.search(text):
        return BrainIntent(
            intent=ANSWER_FROM_VAULT_CONTENT,
            reason="what_did_i_save",
        )

                                                                
    if "?" in text and _QUESTION_SHAPE.search(text):
        lower = text.lower()
        chitchat_pings = (
            "what's up", "whats up", "how are you", "how's it going",
            "hows it going", "good morning", "good evening",
            "good night", "thanks", "thank you", "hello", "hi ",
        )
        if any(ping in lower for ping in chitchat_pings):
            return BrainIntent(
                intent=NOT_VAULT_CONTENT,
                reason="chitchat",
            )
                                                                     
                                                                    
        if any(noun in lower for noun in (
            "file", "doc", "document", "note", "record",
            "contract", "receipt", "tax", "invoice", "bill",
            "passport", "id", "license", "lease", "policy",
            "insurance", "bank", "card", "credit", "loan",
            "mortgage", "warranty", "manual", "subscription",
            "mention", "say",
        )):
            return BrainIntent(
                intent=ANSWER_FROM_VAULT_CONTENT,
                reason="question_with_content_noun",
            )

    return BrainIntent(intent=NOT_VAULT_CONTENT, reason="no_match")


def is_credential_files_query(message: str) -> bool:


    if not message:
        return False
    text = str(message)
    return bool(
        _CREDENTIAL_FILES_SEARCH.search(text)
        or _LIST_OF_CREDENTIALS_IN_FILES.search(text)
        or _CREDENTIAL_PLURAL_FILES_FRAMING.search(text)
    )


def looks_like_vault_files_question(message: str) -> bool:


    if not message:
        return False
    text = str(message).lower()
    file_nouns = (
        "file", "files", "document", "documents", "doc", "docs",
        "upload", "uploads", "uploaded", "attachment", "pdf",
        "image", "picture", "photo", "scan", "scans",
    )
    return any(noun in text for noun in file_nouns)


__all__ = [
    "BrainIntent",
    "BRAIN_INTENTS",
    "SEARCH_VAULT_CONTENT",
    "ANSWER_FROM_VAULT_CONTENT",
    "ANSWER_FROM_FILE_CONTENT",
    "SUMMARIZE_FILE_CONTENT",
    "SUMMARIZE_FOLDER_CONTENT",
    "CREDENTIAL_LOOKUP",
    "CONTINUE_LAST_SEARCH",
    "NOT_VAULT_CONTENT",
    "classify_brain_intent",
    "is_credential_files_query",
    "looks_like_vault_files_question",
]
