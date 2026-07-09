

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


logger = logging.getLogger(__name__)


INTENT_COVERAGE_COMPLETE_CHECK    = "coverage_complete_check"
INTENT_WANT_MORE_RESULTS          = "want_more_results"
INTENT_CHECK_OTHER_LOCATIONS      = "check_other_locations"
INTENT_RERUN_WITH_DIFFERENT_FILTER = "rerun_with_different_filter"
INTENT_PURE_REFERENT              = "pure_referent"
INTENT_NOT_A_FOLLOWUP             = "not_a_followup"

FOLLOWUP_INTENTS = (
    INTENT_COVERAGE_COMPLETE_CHECK,
    INTENT_WANT_MORE_RESULTS,
    INTENT_CHECK_OTHER_LOCATIONS,
    INTENT_RERUN_WITH_DIFFERENT_FILTER,
    INTENT_PURE_REFERENT,
    INTENT_NOT_A_FOLLOWUP,
)


_ANCHORS: dict[str, tuple[str, ...]] = {
    INTENT_COVERAGE_COMPLETE_CHECK: (
        "is that all of them",
        "are these the only matches",
        "are these both the only credential files in the vault",
        "are these the only files with credential lists",
        "are these the complete results",
        "are those all the files",
        "did you check every file in the vault",
        "have you scanned every file in the vault",
        "have you scanned everything",
        "is this the complete list",
        "is the scan finished",
        "have you looked at all files",
        "have you looked at all of them",
        "did you cover the whole vault",
    ),
    INTENT_WANT_MORE_RESULTS: (
        "are there any more results",
        "could there be more matches",
        "could there be more files somewhere",
        "show me more files",
        "what else did you find",
        "any other results you can show",
        "give me more matches",
        "show me additional results",
    ),
    INTENT_CHECK_OTHER_LOCATIONS: (
        "what about other folders",
        "did you check the archives folder",
        "what about my downloads folder",
        "is there a folder you skipped",
        "what about files inside zip archives",
        "did you look in subfolders",
        "any in other folders i should check",
    ),
    INTENT_RERUN_WITH_DIFFERENT_FILTER: (
        "include the weak matches too",
        "show me unsupported files too",
        "include archived files",
        "broaden the search",
        "use a looser filter",
        "show me all the maybes",
        "add weak matches to the list",
    ),
    INTENT_PURE_REFERENT: (
                                                                   
                                                                
        "open the first one",
        "show me the strong one",
        "delete it",
        "rename the second item",
        "open number two",
        "the top one please",
    ),
    INTENT_NOT_A_FOLLOWUP: (
        "what is the weather today",
        "remind me to call mom tomorrow",
        "create me a new login for chase bank",
        "generate a password",
        "what is two plus two",
        "tell me a joke",
        "set a timer for ten minutes",
    ),
}


MODE_A_CONFIDENCE_THRESHOLD = 0.7

                                                                     
MODE_B_CONFIDENCE_FLOOR = 0.55


_TOKEN_RE = re.compile(r"[a-z0-9']+")
_COVERAGE_SCOPE_TOKENS = frozenset((
    "all", "only", "every", "everything", "complete", "whole",
    "both",
))
_COVERAGE_RESULT_TOKENS = frozenset((
    "file", "files", "match", "matches", "result", "results",
    "vault", "scan", "scanned", "checked", "credentials",
    "credential", "list", "lists",
))


def _classify_token_shape(
    message: str,
    last_result_summary: Optional[dict],
) -> Optional[FollowupClassification]:


    if not last_result_summary:
        return None
    tokens = {_normalise_token(t) for t in _TOKEN_RE.findall(
        (message or "").lower()
    ) if t}
    if not tokens:
        return None
    scope_hit = bool(tokens & _COVERAGE_SCOPE_TOKENS)
    result_hit = bool(tokens & _COVERAGE_RESULT_TOKENS)
    if scope_hit and result_hit:
        return FollowupClassification(
            intent=INTENT_COVERAGE_COMPLETE_CHECK,
            confidence=0.86,
            mode="token_shape",
            best_anchor=None,
        )
    return None


def _normalise_token(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


@dataclass(frozen=True)
class FollowupClassification:

    intent: str                                     
    confidence: float                  
    mode: str                                                                     
    best_anchor: Optional[str] = None                                             

    def to_dict(self) -> dict:
        return {
            "intent":      str(self.intent),
            "confidence":  float(self.confidence),
            "mode":        str(self.mode),
            "best_anchor": (self.best_anchor or None),
        }


EmbedFn = Callable[[str], Awaitable[Optional[list[float]]]]


class _AnchorCache:


    def __init__(self) -> None:
        self._by_fn: dict[int, dict[str, list[float]]] = {}

    async def ensure(self, embed_fn: EmbedFn) -> dict[str, list[float]]:
        fp = id(embed_fn)
        if fp in self._by_fn:
            return self._by_fn[fp]
        out: dict[str, list[float]] = {}
        for intent, anchors in _ANCHORS.items():
            for anchor in anchors:
                vec = await embed_fn(anchor)
                if vec is None:
                    continue
                out[f"{intent}::{anchor}"] = vec
        self._by_fn[fp] = out
        return out


_ANCHOR_CACHE = _AnchorCache()


def reset_anchor_cache_for_tests() -> None:

    global _ANCHOR_CACHE
    _ANCHOR_CACHE = _AnchorCache()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


async def classify_mode_a(
    message: str,
    embed_fn: EmbedFn,
) -> FollowupClassification:


    if not message or not message.strip():
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=1.0,
            mode="noop_no_message",
            best_anchor=None,
        )
    msg_vec = await embed_fn(message.strip())
    if msg_vec is None:
                                                                  
                                                                       
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_a_embedding",
            best_anchor=None,
        )
    anchors = await _ANCHOR_CACHE.ensure(embed_fn)
    if not anchors:
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_a_embedding",
            best_anchor=None,
        )
    best_key: Optional[str] = None
    best_score: float = -1.0
    for key, vec in anchors.items():
        s = _cosine(msg_vec, vec)
        if s > best_score:
            best_score = s
            best_key = key
    if best_key is None:
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_a_embedding",
            best_anchor=None,
        )
    intent, _, anchor = best_key.partition("::")
    if intent not in FOLLOWUP_INTENTS:
        intent = INTENT_NOT_A_FOLLOWUP
    return FollowupClassification(
        intent=intent,
        confidence=float(max(0.0, min(1.0, best_score))),
        mode="mode_a_embedding",
        best_anchor=anchor,
    )


LlmFollowupFn = Callable[
    [str, Optional[dict]],
    Awaitable[Optional[dict]],
]


_MODE_B_SYSTEM_PROMPT = """You are a strict classifier for follow-up
intents in a vault assistant.

You will be given the user's message and a brief summary of the
previous assistant result (result_type, total_matches_known,
is_partial). Output a JSON object with exactly two keys:

  {
    "intent":      <one of: coverage_complete_check, want_more_results,
                            check_other_locations, rerun_with_different_filter,
                            pure_referent, not_a_followup>,
    "confidence":  <float in [0.0, 1.0]>
  }

Rules:
  * Output only the JSON object. No prose, no markdown.
  * Do NOT answer the user's question — only classify it.
  * If the message is unrelated to the previous result, output
    not_a_followup.
  * "is that all?" → coverage_complete_check
  * "are there more?" → want_more_results
  * "what about archives?" → check_other_locations
  * "include weak ones too" → rerun_with_different_filter
  * "open the first" / "the strong one" → pure_referent
"""


async def classify_mode_b(
    message: str,
    last_result_summary: Optional[dict],
    llm_fn: Optional[LlmFollowupFn],
) -> FollowupClassification:


    if llm_fn is None:
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_b_llm",
            best_anchor=None,
        )
    try:
        out = await llm_fn(message, last_result_summary)
    except Exception:
        logger.exception("followup classifier Mode B raised")
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_b_llm",
            best_anchor=None,
        )
    if not isinstance(out, dict):
        return FollowupClassification(
            intent=INTENT_NOT_A_FOLLOWUP,
            confidence=0.0,
            mode="mode_b_llm",
            best_anchor=None,
        )
    intent = str(out.get("intent") or "").strip()
    if intent not in FOLLOWUP_INTENTS:
        intent = INTENT_NOT_A_FOLLOWUP
    try:
        confidence = float(out.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if confidence < MODE_B_CONFIDENCE_FLOOR:
        intent = INTENT_NOT_A_FOLLOWUP
    return FollowupClassification(
        intent=intent,
        confidence=confidence,
        mode="mode_b_llm",
    )


async def classify_followup(
    message: str,
    *,
    embed_fn: EmbedFn,
    llm_fallback_fn: Optional[LlmFollowupFn] = None,
    last_result_summary: Optional[dict] = None,
    mode_a_threshold: float = MODE_A_CONFIDENCE_THRESHOLD,
) -> FollowupClassification:


    token_shape = _classify_token_shape(message, last_result_summary)
    if token_shape is not None:
        return token_shape
    a = await classify_mode_a(message, embed_fn)
    if a.intent != INTENT_NOT_A_FOLLOWUP and a.confidence >= mode_a_threshold:
        return a
    if llm_fallback_fn is None:
        return a
    b = await classify_mode_b(message, last_result_summary, llm_fallback_fn)
                                                                 
                                                    
    if b.intent != INTENT_NOT_A_FOLLOWUP and b.confidence >= a.confidence:
        return b
    return a


__all__ = [
    "FollowupClassification",
    "FOLLOWUP_INTENTS",
    "INTENT_COVERAGE_COMPLETE_CHECK",
    "INTENT_WANT_MORE_RESULTS",
    "INTENT_CHECK_OTHER_LOCATIONS",
    "INTENT_RERUN_WITH_DIFFERENT_FILTER",
    "INTENT_PURE_REFERENT",
    "INTENT_NOT_A_FOLLOWUP",
    "MODE_A_CONFIDENCE_THRESHOLD",
    "MODE_B_CONFIDENCE_FLOOR",
    "classify_mode_a",
    "classify_mode_b",
    "classify_followup",
    "reset_anchor_cache_for_tests",
]
