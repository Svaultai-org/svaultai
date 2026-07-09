

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field as _field
from typing import Optional


logger = logging.getLogger(__name__)


RESULTS_TTL_SECONDS: int = 600


_lock = threading.Lock()
                                      
_store: dict[str, "SecureItemResultsContext"] = {}


FOLLOWUP_REVEAL_ONE:  str = "reveal_one"
FOLLOWUP_DELETE_ONE:  str = "delete_one"
FOLLOWUP_CLARIFY:     str = "clarify"
FOLLOWUP_NONE:        str = "none"


ALL_FOLLOWUPS: frozenset[str] = frozenset({
    FOLLOWUP_REVEAL_ONE, FOLLOWUP_DELETE_ONE,
    FOLLOWUP_CLARIFY, FOLLOWUP_NONE,
})


@dataclass(frozen=True)
class SecureItemResultsCard:


    item_id:   str
    title:     str
    item_type: str


@dataclass(frozen=True)
class SecureItemResultsContext:


    vault_id:    str
    cards:       tuple[SecureItemResultsCard, ...]
    last_query:  str
    created_at:  float
    expires_at:  float

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at


@dataclass(frozen=True)
class FollowupResolution:

    band:    str
    cards:   tuple[SecureItemResultsCard, ...] = ()
    reveal:  bool = False
    message: str = ""


def _now() -> float:
    return time.time()


def store_results_context(
    *,
    vault_id: str,
    cards: list[dict] | tuple[dict, ...],
    last_query: str,
    ttl_seconds: Optional[int] = None,
) -> SecureItemResultsContext:


    if not vault_id:
        raise ValueError("vault_id required")
    safe_cards: list[SecureItemResultsCard] = []
    for c in cards or ():
        if not isinstance(c, dict):
            continue
        safe_cards.append(SecureItemResultsCard(
            item_id=str(c.get("item_id") or ""),
            title=str(c.get("title") or "").strip(),
            item_type=str(c.get("type") or c.get("item_type") or "").strip(),
        ))
    ttl = int(
        ttl_seconds if ttl_seconds is not None else RESULTS_TTL_SECONDS
    )
    if ttl <= 0:
        ttl = RESULTS_TTL_SECONDS
    now = _now()
    ctx = SecureItemResultsContext(
        vault_id=vault_id,
        cards=tuple(safe_cards),
        last_query=str(last_query or "").strip(),
        created_at=now,
        expires_at=now + ttl,
    )
    with _lock:
        _store[vault_id] = ctx
    logger.info(
        "[SECURE-ITEM-RESULTS-CTX] stored vault=%s count=%d ttl=%d",
        (vault_id or "")[:8] + "…", len(safe_cards), ttl,
    )
    return ctx


def get_results_context(
    *, vault_id: str,
) -> Optional[SecureItemResultsContext]:


    if not vault_id:
        return None
    now = _now()
    with _lock:
        ctx = _store.get(vault_id)
        if ctx is None:
            return None
        if ctx.is_expired(now):
            _store.pop(vault_id, None)
            return None
        return ctx


def clear_results_context(vault_id: str) -> bool:

    if not vault_id:
        return False
    with _lock:
        return _store.pop(vault_id, None) is not None


def _reset_store_for_test() -> None:
    with _lock:
        _store.clear()


_GENERIC_VIEW_RE = re.compile(
    r"^\s*(?:"
    r"show\s+(?:it|them|me|me\s+all)?"
    r"|view\s+(?:it|them)?"
    r"|open\s+(?:it|them|the\s+card)?"
    r"|reveal\s+(?:it|them|the\s+(?:full|value|password))?"
    r"|show\s+full"
    r"|show\s+(?:the\s+)?full\s+value"
    r"|let\s+me\s+see"
    r"|read\s+(?:it|them)?"
    r")\s*[.!?]*\s*$",
    re.IGNORECASE,
)


_ORDINAL_RE = re.compile(
    r"\b(?:show|open|view|reveal|read|delete|remove|drop)\b"
    r".{0,20}\b(?:the\s+)?"
    r"(?:(first|1st)|"
    r"(second|2nd)|"
    r"(third|3rd)|"
    r"(fourth|4th)|"
    r"(fifth|5th)|"
    r"(last))\b",
    re.IGNORECASE,
)


_DELETE_VERB_RE = re.compile(
    r"^\s*(?:delete|remove|drop|trash|forget)\b",
    re.IGNORECASE,
)


_TARGET_PHRASE_RE = re.compile(
    r"^\s*(?:show|open|view|reveal|read|delete|remove|drop|trash|forget)\s+"
    r"(?:me\s+)?"
    r"(?:my\s+)?"
    r"(?:the\s+|that\s+|this\s+)?"
    r"(?:full\s+)?"
    r"(?P<rest>[A-Za-z][A-Za-z0-9 '\-]{2,80})"
    r"\s*[.!?]*\s*$",
    re.IGNORECASE,
)


_TITLE_NOISE_TOKENS: frozenset[str] = frozenset({
    "login", "logins", "credential", "credentials",
    "card", "cards", "item", "items", "saved",
    "secure", "vault", "record", "records",
    "details", "info", "data", "stuff",
    "one", "ones", "first", "second", "third", "last",
})


_ORDINAL_TO_INDEX: dict[str, int] = {
    "first":  0, "1st": 0,
    "second": 1, "2nd": 1,
    "third":  2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth":  4, "5th": 4,
}


_FULL_REVEAL_RE = re.compile(
    r"\b(?:reveal|show\s+full|show\s+the\s+(?:full|raw)|"
    r"the\s+full|the\s+raw|full\s+value)\b",
    re.IGNORECASE,
)


def _looks_like_full_reveal(msg: str) -> bool:
    return bool(_FULL_REVEAL_RE.search(msg or ""))


def _normalize_title_cue(rest: str) -> str:


    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", (rest or "").lower())
    kept = [t for t in tokens if t not in _TITLE_NOISE_TOKENS]
    return " ".join(kept).strip()


def _match_cards_by_title(
    cards: tuple[SecureItemResultsCard, ...], cue: str,
) -> list[SecureItemResultsCard]:


    cue = cue.strip()
    if not cue:
        return []
    out: list[SecureItemResultsCard] = []
    for c in cards:
        haystack = (c.title or "").lower()
        item_type_tokens = (c.item_type or "").lower().replace("_", " ")
        if cue in haystack or cue in item_type_tokens:
            out.append(c)
            continue
                                                               
        cue_tokens = cue.split()
        if cue_tokens and all(
            t in haystack or t in item_type_tokens for t in cue_tokens
        ):
            out.append(c)
    return out


def classify_results_followup(
    *, user_message: str,
    context: SecureItemResultsContext,
) -> FollowupResolution:


    if context is None or not context.cards:
        return FollowupResolution(band=FOLLOWUP_NONE)
    if not isinstance(user_message, str) or not user_message.strip():
        return FollowupResolution(band=FOLLOWUP_NONE)
    msg = user_message.strip()

    cards = context.cards
    delete_intent = bool(_DELETE_VERB_RE.match(msg))
    full_reveal   = _looks_like_full_reveal(msg)

                                                             
    ord_match = _ORDINAL_RE.search(msg)
    if ord_match:
        idx: Optional[int] = None
        last_used = False
                                                                  
        for grp in ("first", "1st", "second", "2nd",
                    "third", "3rd", "fourth", "4th",
                    "fifth", "5th"):
            if grp in [g.lower() for g in ord_match.groups() if g]:
                idx = _ORDINAL_TO_INDEX[grp]
                break
        if idx is None and any(
            g and g.lower() == "last" for g in ord_match.groups()
        ):
            idx = len(cards) - 1
            last_used = True
        if idx is not None and 0 <= idx < len(cards):
            band = FOLLOWUP_DELETE_ONE if delete_intent else FOLLOWUP_REVEAL_ONE
            return FollowupResolution(
                band=band,
                cards=(cards[idx],),
                reveal=full_reveal and band == FOLLOWUP_REVEAL_ONE,
            )
        if idx is not None:
                                                    
            return _clarify(cards)
                                              

    if _GENERIC_VIEW_RE.match(msg):
        if len(cards) == 1:
            return FollowupResolution(
                band=FOLLOWUP_REVEAL_ONE,
                cards=(cards[0],),
                reveal=full_reveal,
            )
        return _clarify(cards)

                                                                   
    if delete_intent and re.match(
        r"^\s*(?:delete|remove|drop|trash|forget)\s+"
        r"(?:it|them|that)?\s*[.!?]*\s*$",
        msg, re.IGNORECASE,
    ):
        if len(cards) == 1:
            return FollowupResolution(
                band=FOLLOWUP_DELETE_ONE,
                cards=(cards[0],),
            )
        return _clarify(cards, delete=True)

                                                             
    tp = _TARGET_PHRASE_RE.match(msg)
    if tp:
        cue = _normalize_title_cue(tp.group("rest") or "")
        if cue:
            matches = _match_cards_by_title(cards, cue)
            if len(matches) == 1:
                band = (FOLLOWUP_DELETE_ONE if delete_intent
                        else FOLLOWUP_REVEAL_ONE)
                return FollowupResolution(
                    band=band,
                    cards=(matches[0],),
                    reveal=full_reveal and band == FOLLOWUP_REVEAL_ONE,
                )
            if len(matches) > 1:
                return _clarify(matches, delete=delete_intent)
                                                              
                                                             
            return FollowupResolution(band=FOLLOWUP_NONE)

    return FollowupResolution(band=FOLLOWUP_NONE)


def _clarify(
    cards: tuple[SecureItemResultsCard, ...] | list[SecureItemResultsCard],
    *, delete: bool = False,
) -> FollowupResolution:


    safe_cards = tuple(cards)
    verb = "delete" if delete else "open"
    if not safe_cards:
        msg = (
            "I don't have any saved items from the last reply "
            "still on hand. Could you rephrase what you'd like to "
            f"{verb}?"
        )
    elif len(safe_cards) == 1:
                                                              
                          
        return FollowupResolution(
            band=(FOLLOWUP_DELETE_ONE if delete else FOLLOWUP_REVEAL_ONE),
            cards=safe_cards,
        )
    else:
        labels = [c.title or "Saved item" for c in safe_cards]
        if len(labels) == 2:
            joined = f"{labels[0]} or {labels[1]}"
        else:
            joined = ", ".join(labels[:-1]) + f", or {labels[-1]}"
        msg = (
            f"I found {len(safe_cards)} saved items. Which one "
            f"should I {verb} — {joined}?"
        )
    return FollowupResolution(
        band=FOLLOWUP_CLARIFY,
        cards=safe_cards,
        message=msg,
    )


__all__ = [
    "RESULTS_TTL_SECONDS",
    "SecureItemResultsCard",
    "SecureItemResultsContext",
    "FollowupResolution",
    "FOLLOWUP_REVEAL_ONE",
    "FOLLOWUP_DELETE_ONE",
    "FOLLOWUP_CLARIFY",
    "FOLLOWUP_NONE",
    "ALL_FOLLOWUPS",
    "store_results_context",
    "get_results_context",
    "clear_results_context",
    "classify_results_followup",
]
