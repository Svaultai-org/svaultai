"""Exact and substring-based resolver for saved item names.

Bug 1 (2026-07-25 deep fix) — the previous ``_try_exact_saved_name_
early_return`` probe only tried whole ``intent_data`` values and the
whole ``decrypted_message`` as candidates. Real user phrases like
``"show me naim id"`` do not equal any saved name; the probe missed
and the request fell through to the tag-family handler which has
no visibility to ``saved_name``.

This resolver flips the direction: it fetches every completed
saved-name in the vault (bounded scan), builds each saved_name's
normalized lookup key, and looks for that key as a word-boundary
substring inside the normalized decrypted message. Wrapper verbs
(``show me``, ``find``, ``open``, ``retrieve``, ``I need``, ``where
is``) are tolerated because the substring test ignores them
naturally.

Rules:
  * VAULT-SCOPED. The resolver never sees another vault's rows.
  * READ-ONLY. Never writes; only issues one bounded SELECT.
  * DETERMINISTIC. No LLM, no side effects.
  * NEVER RAISES.
  * SILENT ON AMBIGUITY. When more than one saved-name matches,
    the resolver returns AMBIGUOUS with the list; the caller
    decides whether to ask for clarification or fall through.
  * NEVER LOGS SAVED NAMES OR MESSAGES IN PLAINTEXT beyond short
    diagnostic fingerprints (first 8 chars of vault_id, counts).

The resolver relies on the same ``_normalize_asset_lookup_key``
function used by the writer (``main.save_named_uploaded_asset``)
so normalization symmetry is preserved.

Category-label safety: if the normalized message equals a known
family tag ("identity", "finance", ...), the resolver returns
MISS — those are handled by ``list_by_tag`` and should not be
intercepted as saved names even if a saved item happens to be
called "identity".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


STATUS_HIT       = "hit"
STATUS_MISS      = "miss"
STATUS_AMBIGUOUS = "ambiguous"


# ---------------------------------------------------------------------------
# Wrapper verbs — words users prepend when asking about a specific item.
# We do NOT strip them from the input; we simply rely on substring
# containment. The list is documented so the intent is auditable.
# ---------------------------------------------------------------------------

_KNOWN_WRAPPER_VERBS: tuple[str, ...] = (
    "show", "show me", "show my", "find", "find me", "find my",
    "get", "get me", "get my", "give me", "bring up", "bring me",
    "open", "display", "where is", "where's", "i need", "look for",
    "look up", "look up my", "retrieve", "pull up", "pull", "fetch",
    "grab", "read", "read me", "please show", "please find",
)


# Known category tags — mirror the list_by_tag prompt in main.py.
# When the entire normalized message equals one of these, the
# resolver bows out so list_by_tag handles it.
_KNOWN_CATEGORY_TAGS: frozenset[str] = frozenset({
    "travel", "finance", "legal", "medical", "business", "education",
    "identity", "government", "security", "personal", "media",
    "receipt", "tax",
    # Bare category words that users sometimes type verbatim; still
    # not real saved names.
    "ids", "documents", "files", "photos", "images", "notes",
})


# Very short saved names are not safe to substring-match against
# arbitrary messages — "id" would match every message with "id" in
# it. We require at least this many characters in the normalized
# saved_name before we're willing to consider a substring hit.
_MIN_KEY_CHARS_FOR_SUBSTRING = 3


# Bounded scan cap. Vaults with more saved items still get exact-
# match lookups (via ``retrieve_saved_asset_by_exact_name``); this
# cap only bounds the substring scan.
_MAX_ROWS_TO_SCAN = 1000


@dataclass
class ResolveResult:
    """Outcome of a resolve call.

    ``status``: STATUS_HIT | STATUS_MISS | STATUS_AMBIGUOUS.

    ``hit``: the single matching row when status == HIT. Row shape
    matches ``retrieve_saved_asset_by_exact_name``'s dict.

    ``candidates``: on AMBIGUOUS, the list of matching rows.
    Callers may present these to the user for disambiguation.

    ``matched_key``: the normalized saved_name key that matched.
    """

    status: str
    hit: Optional[dict] = None
    candidates: list[dict] = field(default_factory=list)
    matched_key: Optional[str] = None


def _is_category_tag(normalized_key: str) -> bool:
    """Return True when the normalized key is a broad category label
    that should be handled by the tag-family handler."""
    if not normalized_key:
        return False
    return normalized_key in _KNOWN_CATEGORY_TAGS


def _substring_match_positions(
    normalized_message: str,
    normalized_saved_name: str,
) -> list[int]:
    """Return positions where ``normalized_saved_name`` occurs in
    ``normalized_message`` at word boundaries. Empty list when no
    match. Preserves word-boundary integrity: ``"pass"`` inside
    ``"passport"`` does not count."""
    if not normalized_message or not normalized_saved_name:
        return []
    if len(normalized_saved_name) < _MIN_KEY_CHARS_FOR_SUBSTRING:
        return []
    pat = re.compile(
        r"(?:^|(?<=\s))" + re.escape(normalized_saved_name)
        + r"(?=$|\s|[.,;:!?])",
        re.IGNORECASE,
    )
    return [m.start() for m in pat.finditer(normalized_message)]


def resolve_saved_name(
    *,
    vault_id: str,
    decrypted_message: Optional[str],
    fetch_saved_names: Callable[[str, int], list[dict]],
    normalize_key: Callable[[Optional[str]], str],
    exact_match_lookup: Optional[
        Callable[[str, str], Optional[dict]]
    ] = None,
    intent_candidates: Optional[list[str]] = None,
) -> ResolveResult:
    # 2026-07-25 diagnostic entry marker.
    try:
        logger.info(
            "[BRAIN-TRACE-DXR] site=resolve_saved_name "
            "vault=%s msg_len=%d intent_cands=%d",
            (vault_id or "")[:8],
            len(decrypted_message) if isinstance(decrypted_message, str) else 0,
            len(intent_candidates or []),
        )
    except Exception:
        pass
    """Resolve a chat message to a specific saved item, or None.

    Parameters
    ----------
    vault_id : str
        Required. Scopes every DB lookup.
    decrypted_message : str
        The full plaintext message the user typed. May be empty.
    fetch_saved_names : callable(vault_id, limit) -> list[row]
        Callback that returns the vault's completed uploads with a
        non-empty ``saved_name``. Bounded by ``limit``. Injected so
        main.py owns the DB layer.
    normalize_key : callable(str) -> str
        Callback returning the SAME normalized lookup key that the
        writer uses when it stores the item. Usually
        ``main._normalize_asset_lookup_key``.
    exact_match_lookup : callable(vault_id, name) -> row | None
        Optional fast-path lookup for exact-normalized matches (uses
        the DB index). If None, we skip the fast path.
    intent_candidates : list[str]
        Optional list of already-plucked candidate strings (from the
        LLM's intent_data fields). Tried before scanning the vault.

    Returns
    -------
    ResolveResult
    """
    if not vault_id:
        return ResolveResult(status=STATUS_MISS)

    # ---- fast path 1: try LLM-provided candidates via exact match.
    if exact_match_lookup is not None and intent_candidates:
        for cand in intent_candidates:
            if not isinstance(cand, str) or not cand.strip():
                continue
            try:
                hit = exact_match_lookup(vault_id, cand)
            except Exception:
                hit = None
            if hit is not None:
                return ResolveResult(
                    status=STATUS_HIT,
                    hit=hit,
                    matched_key=normalize_key(cand),
                )

    if not decrypted_message or not isinstance(decrypted_message, str):
        return ResolveResult(status=STATUS_MISS)

    normalized_message = normalize_key(decrypted_message)
    if not normalized_message:
        return ResolveResult(status=STATUS_MISS)

    # If the whole normalized message is a known category, defer to
    # the tag handler.
    if _is_category_tag(normalized_message):
        return ResolveResult(status=STATUS_MISS)

    # ---- fast path 2: whole-message exact match against the DB.
    if exact_match_lookup is not None:
        try:
            hit = exact_match_lookup(vault_id, decrypted_message)
        except Exception:
            hit = None
        if hit is not None:
            return ResolveResult(
                status=STATUS_HIT,
                hit=hit,
                matched_key=normalized_message,
            )

    # ---- bounded scan: fetch the vault's saved names and look for
    # any of them as word-boundary substrings inside the message.
    try:
        rows = fetch_saved_names(vault_id, _MAX_ROWS_TO_SCAN) or []
    except Exception:
        logger.exception(
            "[EXACT-NAME] fetch_saved_names failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return ResolveResult(status=STATUS_MISS)

    matches: list[tuple[str, dict, int]] = []
    seen_keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        saved_name = row.get("saved_name") or ""
        key = normalize_key(saved_name)
        if not key or key in seen_keys:
            continue
        if _is_category_tag(key):
            continue
        # Whole-message exact match — highest confidence.
        if key == normalized_message:
            return ResolveResult(
                status=STATUS_HIT,
                hit=row,
                matched_key=key,
            )
        positions = _substring_match_positions(normalized_message, key)
        if positions:
            matches.append((key, row, len(key)))
            seen_keys.add(key)

    if not matches:
        return ResolveResult(status=STATUS_MISS)

    # Prefer the longest matched key — more specific wins over
    # generic. When two matches tie in length we return AMBIGUOUS
    # so the caller can ask a clarifying question.
    matches.sort(key=lambda t: t[2], reverse=True)
    top_len = matches[0][2]
    top_matches = [(k, r) for (k, r, ln) in matches if ln == top_len]
    if len(top_matches) == 1:
        key, row = top_matches[0]
        return ResolveResult(status=STATUS_HIT, hit=row, matched_key=key)
    return ResolveResult(
        status=STATUS_AMBIGUOUS,
        candidates=[r for (_k, r) in top_matches],
        matched_key=None,
    )


__all__ = [
    "STATUS_HIT",
    "STATUS_MISS",
    "STATUS_AMBIGUOUS",
    "ResolveResult",
    "resolve_saved_name",
]
