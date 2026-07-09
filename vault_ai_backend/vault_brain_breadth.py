

from __future__ import annotations

import re
from dataclasses import dataclass


BREADTH_NARROW       = "narrow"
BREADTH_BROAD        = "broad"
BREADTH_SUMMARY      = "summary"
BREADTH_CONTINUATION = "continuation"


ALL_BREADTHS = frozenset({
    BREADTH_NARROW, BREADTH_BROAD, BREADTH_SUMMARY, BREADTH_CONTINUATION,
})


@dataclass(frozen=True)
class BrainBreadth:

    breadth: str
    reason:  str = ""

    def to_dict(self) -> dict:
        return {"breadth": str(self.breadth), "reason": str(self.reason)}


_CONTINUE_PHRASES = re.compile(
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


_BROAD_PHRASES = re.compile(
    r"\b("
    r"any(thing|where)?\s+about|"
    r"all\s+(files|documents|notes|things)?\s*about|"
    r"every(thing|\s+file|\s+document|\s+note)?|"
    r"what\s+(files|documents)\s+(mention|discuss|contain|reference|cover|"
    r"have|include|talk\s+about)|"
    r"which\s+(files|documents)\s+(mention|discuss|contain|reference|cover|"
    r"have|include|talk\s+about)|"
    r"across\s+(my\s+)?(vault|files|documents)|"
    r"throughout|"
    r"in\s+general"
    r")\b",
    re.IGNORECASE,
)


_SUMMARY_PHRASES = re.compile(
    r"\b(summari[sz]e|summary|tl;?dr|recap|overview|brief|"
    r"gist|outline|tldr)\b",
    re.IGNORECASE,
)

                                                                     
_FOLDER_REFERENT = re.compile(
    r"\b(folder|directory|category|all\s+of\s+my)\b",
    re.IGNORECASE,
)


_SPECIFIC_NARROW = re.compile(
    r"\b("
    r"what'?s?\s+my\s+\w+|"
    r"what\s+is\s+my\s+\w+|"
    r"give\s+me\s+my\s+\w+|"
    r"my\s+\w+\s+(number|code|password|pin|address|phone|email|expires|expiry)"
    r")\b",
    re.IGNORECASE,
)


def classify_brain_breadth(
    message: str,
    *,
    has_continuation_context: bool = False,
) -> BrainBreadth:


    if not message or not str(message).strip():
        return BrainBreadth(breadth=BREADTH_NARROW, reason="empty")

    text = str(message).strip()

                                                                
    if _CONTINUE_PHRASES.search(text):
        if has_continuation_context:
            return BrainBreadth(
                breadth=BREADTH_CONTINUATION,
                reason="continuation_phrase_with_context",
            )
        return BrainBreadth(
            breadth=BREADTH_BROAD,
            reason="continuation_phrase_no_context",
        )

                         
    if _SUMMARY_PHRASES.search(text):
                                                                   
                                                                
        return BrainBreadth(
            breadth=BREADTH_SUMMARY,
            reason=("summary_with_folder"
                    if _FOLDER_REFERENT.search(text)
                    else "summary_phrase"),
        )

                       
    if _BROAD_PHRASES.search(text):
        return BrainBreadth(
            breadth=BREADTH_BROAD,
            reason="broad_phrase",
        )

                                                                    
    if _SPECIFIC_NARROW.search(text):
        return BrainBreadth(
            breadth=BREADTH_NARROW,
            reason="specific_narrow",
        )

                                                                  
    return BrainBreadth(breadth=BREADTH_NARROW, reason="default_narrow")


__all__ = [
    "BrainBreadth",
    "BREADTH_NARROW",
    "BREADTH_BROAD",
    "BREADTH_SUMMARY",
    "BREADTH_CONTINUATION",
    "ALL_BREADTHS",
    "classify_brain_breadth",
]
