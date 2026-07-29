"""Deterministic pre-router for POST /chat.

2026-07-27 architectural repair. Runs BEFORE the OpenAI planner
short-circuit. Handles three well-defined request classes with
deterministic code — no LLM — so identical requests always produce
identical structured responses, and so bug reports 1/2/3/4 from the
2026-07-27 audit brief cannot recur.

The three classes:

  A. BARE FOLLOW-UP against an active entity
       "show me", "show it", "open it", "download it", "view it",
       "delete it", "tell me about it", "show related"
     Requires: the previous structured action pinned an active
     entity in `vault_chat_active_entity`. The router looks up the
     active entity and resolves the verb against it, producing the
     same structured card the frontend already renders.

  B. EXPLICIT NAMED-OBJECT LOOKUP
       "show me <name>", "open <name>", "download <name>",
       "view <name>", "let me see <name>"
     Extracts the candidate name, normalizes it (`_normalize_lookup_key`
     from `vault_complete_search`), matches unique-longest against
     saved_name / file_name of the vault's uploaded files.
       * On unique match  → structured file card envelope + pins
         the file as the active entity.
       * On ambiguity     → structured clarification envelope +
         pins the candidate list as active (multi).
       * On no match      → returns None → the planner may still
         choose to run semantic/OCR search on it.
     CRITICAL: exact-name lookup runs BEFORE any category
     classification, OCR, vision, or LLM inference. A file the
     user labelled "naim id" wins over the "id" category-token
     classifier every time.

  C. EXPLICIT CREDENTIAL CREATION
       "create me a <service> login with <username>",
       "save a <service> account, username is <x>",
       "generate a <service> credential with password <y>"
     Uses `vault_credential_command.extract_credential_command`
     for value precedence (explicit > pending > previous >
     generated). When the command action is ACTION_CREATE and a
     service is identifiable, calls `generate_credential_draft`
     directly with the user's explicit fields — bypassing the
     planner so the LLM cannot silently overwrite a supplied
     username with a generated one.

Everything else → the router returns None and the existing chat
cascade (state machine → planner) handles it. This is by design.
Adding one more deterministic case is easier than reasoning about
a giant router; the LLM planner remains the general fallback.

## Diagnostics

For every request the router touches it emits ONE structured line:

    CHAT_TRACE request_id=... route=deterministic intent=...
    candidate_name_len=... exact_match_count=...
    resolved_object_type=... resolved_object_id_hash=...
    action=... response_type=... fallback_reason=...

Never logs message content, usernames, emails, passwords, vault
plaintext, or Stripe/session tokens.

## What this module does NOT do

  * It does not decrypt anything the caller has not already handed
    it (needs the AES key to render thumbnails; that is the ONLY
    crypto dependency).
  * It only persists credentials when the user explicitly asks to
    create/generate AND save in the same request. Plain create/generate
    still produces a reviewable draft.
  * It does not touch Stripe, deletion, or authentication.
  * It cannot bypass PIN gates or trusted-device checks — those
    ran upstream before chat_endpoint decrypted the message.

## Testing

Module-level tests live in
`test_chat_deterministic_router_2026_07_31.py`. Endpoint-level
tests thread the router through the actual chat_endpoint function
signature with a stub file-lister + active-entity store.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# chat_path tags. Match the CHAT_PATH_* enum shape in security_headers.py
# — these fill in the X-VaultAI-Chat-Path header so operators can see
# from response headers which router branch handled the request.
CHAT_PATH_DETERMINISTIC_FOLLOWUP:            str = "deterministic_followup"
CHAT_PATH_DETERMINISTIC_NAMED_OBJECT:        str = "deterministic_named_object"
CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS:     str = "deterministic_named_ambiguous"
CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE:   str = "deterministic_credential_create"


# Route kinds. Callers key on these to log outcome + set the chat_path
# header. Closed set — do not add without updating the tests.
KIND_FOLLOWUP_FILE:          str = "followup_file"
KIND_FOLLOWUP_LOGIN:         str = "followup_login"
KIND_NAMED_OBJECT_FILE:      str = "named_object_file"
KIND_NAMED_OBJECT_LOGIN:     str = "named_object_login"
KIND_NAMED_OBJECT_AMBIGUOUS: str = "named_object_ambiguous"
KIND_CREDENTIAL_DRAFT:       str = "credential_draft"
KIND_CREDENTIAL_DRAFT_BATCH: str = "credential_draft_batch"
KIND_CREDENTIAL_SAVED:       str = "credential_saved"


# Response types the frontend recognizes. The frontend chat parser
# (`vault_chat_stream_parser.dart`) keys on top-level `type` and card
# kinds. Every envelope this router produces uses one of these.
RESPONSE_TYPE_VAULT_FILE:              str = "vault_file"
RESPONSE_TYPE_FILE_DISAMBIGUATION:     str = "file_disambiguation"
RESPONSE_TYPE_FILE_SEARCH_RESULTS:     str = "file_search_results"
RESPONSE_TYPE_CREDENTIAL_DRAFT:        str = "vault_generated_login_card"


# Message-shape guards. Anything longer, containing a question mark,
# or with more than one verb-clause is deferred to the planner —
# we only handle short, unambiguous imperatives.
_MAX_ROUTABLE_CHARS: int = 200


_SAVE_NOW_RE = re.compile(
    r"\b("
    r"save\s+it\s+now|"
    r"save\s+now|"
    r"generate\s+and\s+save|"
    r"create\s+and\s+save|"
    r"and\s+save\s+it|"
    r"save\s+this\s+one"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Outcome type
# ---------------------------------------------------------------------------

@dataclass
class RouteOutcome:
    """What the router hands back when it fully resolves a request.

    ``envelope_json`` is the string payload the endpoint will wrap
    with `encrypted_reply` and stream to the client. It is either a
    JSON envelope the frontend chat parser will render as a card, OR
    a plain-text sentence for a clarification/error case.

    ``chat_path_tag`` fills the `X-VaultAI-Chat-Path` response header.

    ``pin_active_entity`` is a hint the caller uses to update the
    active-entity store AFTER writing the response, so a subsequent
    bare "show me" resolves to this object.
    """

    kind: str
    envelope_json: str
    chat_path_tag: str
    # (entity_type, entity_ref_dict, display_label, allowed_actions_tuple)
    # or None if nothing to pin. The caller writes it via
    # vault_chat_active_entity.set_active_entity.
    pin_active_entity: Optional[tuple[str, dict, str, tuple[str, ...]]] = None


# ---------------------------------------------------------------------------
# Verb / imperative recognition
# ---------------------------------------------------------------------------

# Actions that mean "resolve THIS object to a structured card / open /
# download / delete action". Keys are canonical verbs; values are the
# regex patterns that recognize the verb at the START of the message
# (case-insensitive, tolerant of common filler).
#
# Explicit-name lookup only fires when the message starts with a
# recognized verb followed by a name-shaped noun phrase — this keeps
# the router out of general questions.
_ACTION_VERBS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (verb, re.compile(pattern, re.IGNORECASE)) for verb, pattern in (
        # SHOW / VIEW / OPEN — display the object
        ("show",     r"^\s*(?:please\s+)?show\s+me\s+(?P<name>.+?)\s*[.!?]*\s*$"),
        ("show",     r"^\s*(?:please\s+)?show\s+(?P<name>(?!me\b|it\b|that\b|the\s+vault\b).+?)\s*[.!?]*\s*$"),
        ("view",     r"^\s*(?:please\s+)?view\s+(?P<name>(?!it\b|that\b).+?)\s*[.!?]*\s*$"),
        ("open",     r"^\s*(?:please\s+)?open\s+(?P<name>(?!it\b|that\b|the\s+vault\b).+?)\s*[.!?]*\s*$"),
        ("open",     r"^\s*(?:please\s+)?let\s+me\s+see\s+(?P<name>(?!it\b|that\b).+?)\s*[.!?]*\s*$"),
        # DOWNLOAD
        ("download", r"^\s*(?:please\s+)?download\s+(?P<name>(?!it\b|that\b).+?)\s*[.!?]*\s*$"),
        # RETRIEVE-STYLE
        ("show",     r"^\s*(?:please\s+)?find\s+(?P<name>(?!my\s+.+\s+login\b).+?)\s*[.!?]*\s*$"),
        ("show",     r"^\s*(?:please\s+)?bring\s+up\s+(?P<name>.+?)\s*[.!?]*\s*$"),
        ("show",     r"^\s*(?:please\s+)?pull\s+up\s+(?P<name>.+?)\s*[.!?]*\s*$"),
    )
)


# Filler prefixes we strip off the extracted name before comparing.
# "my", "the", "a" are common English determiners the user drops
# before the actual saved name.
_NAME_LEADING_STRIP_RE: re.Pattern[str] = re.compile(
    r"^(?:my|the|a|an)\s+", re.IGNORECASE,
)


# Trailing type-suffix tokens: "the video file" -> "the video".
# Only strip a SINGLE trailing occurrence and only when the remaining
# name is still >= _MIN_NAME_KEY_LEN chars. Refuses to eat words that
# are legitimate parts of a saved name — e.g. "testing video" must
# survive as "testing video", not become "testing".
_NAME_TRAILING_TYPE_TOKENS: frozenset[str] = frozenset({
    "file", "files",
    "pdf", "pdfs",
})


# ---------------------------------------------------------------------------
# Name normalization — mirrors vault_complete_search._normalize_lookup_key
# so both resolvers agree on what "matches".
# ---------------------------------------------------------------------------

def _normalize_name(name: Optional[str]) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    s = re.sub(r"[^\w\-\.\s]", "", s)
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\.[a-z0-9]{1,6}$", "", s).strip()
    return s


# Category-stop set — words the extractor refuses to treat as a
# specific saved-object name. Only truly generic taxonomy words go
# here; concrete document types like "passport" and "license" are NOT
# in this list because users routinely name specific files after them
# ("passport 2024"), and the resolver's substring matching handles
# both bare-word and multi-token variants uniformly. When "show me
# passport" hits a vault with two "passport 20xx" files, the router
# emits a disambiguation card rather than blindly deferring.
_NAMED_OBJECT_CATEGORY_STOP: frozenset[str] = frozenset({
    "id", "ids", "identity", "identities",
    "photo", "photos", "image", "images",
    "document", "documents", "file", "files",
    "tax", "taxes", "medical", "finance", "financial",
    "travel", "legal", "personal", "business",
    "credential", "credentials", "login", "logins",
    "password", "passwords",
})


# Minimum candidate-name length. "id" alone would substring-match
# almost anything; require ≥ 3 chars.
_MIN_NAME_KEY_LEN: int = 3


def _strip_name_filler(name: str) -> str:
    """Strip conversational filler from an extracted candidate name.

    "my naim id" -> "naim id"
    "the testing video" -> "testing video"    (video is part of the name)
    "the testing video file" -> "testing video"    (trailing 'file' is generic)

    Only strips ONE trailing generic-type token, and only when the
    remaining name is still >= _MIN_NAME_KEY_LEN chars. This is
    deliberate — words like "video", "photo", "note" are frequently
    part of real saved names ("testing video", "family photos",
    "meeting notes") and must not be eaten.
    """
    if not name:
        return ""
    s = name.strip()
    s = _NAME_LEADING_STRIP_RE.sub("", s)
    tokens = s.split()
    if (
        len(tokens) >= 2
        and tokens[-1].lower().strip(".,!?") in _NAME_TRAILING_TYPE_TOKENS
    ):
        remainder = " ".join(tokens[:-1]).strip()
        if len(remainder) >= _MIN_NAME_KEY_LEN:
            tokens = tokens[:-1]
    return " ".join(tokens).strip()


# ---------------------------------------------------------------------------
# Verb extractor
# ---------------------------------------------------------------------------

@dataclass
class _NamedActionHit:
    verb: str
    candidate_name: str        # raw, before normalization
    normalized_name: str       # after normalization


def _extract_named_action(message: str) -> Optional[_NamedActionHit]:
    """Return the (verb, candidate_name) pair when the message is a
    short imperative naming an object, else None."""
    if not isinstance(message, str) or not message.strip():
        return None
    if "?" in message:
        return None
    if len(message) > _MAX_ROUTABLE_CHARS:
        return None
    m_stripped = message.strip()
    for verb, pat in _ACTION_VERBS:
        m = pat.match(m_stripped)
        if m is None:
            continue
        try:
            raw_name = m.group("name").strip()
        except (IndexError, KeyError):
            continue
        if not raw_name:
            continue
        cleaned = _strip_name_filler(raw_name)
        normalized = _normalize_name(cleaned)
        if not normalized:
            continue
        if len(normalized) < _MIN_NAME_KEY_LEN:
            return None
        if normalized in _NAMED_OBJECT_CATEGORY_STOP:
            return None
        return _NamedActionHit(
            verb=verb,
            candidate_name=cleaned,
            normalized_name=normalized,
        )
    return None


# ---------------------------------------------------------------------------
# Named-object resolution against the vault's file list
# ---------------------------------------------------------------------------

@dataclass
class _NamedResolveResult:
    status: str                # 'hit' | 'ambiguous' | 'miss'
    row: Optional[dict] = None
    candidates: list[dict] = field(default_factory=list)


def _resolve_named_object_from_rows(
    normalized_name: str,
    rows: list[dict],
) -> _NamedResolveResult:
    """Unique-longest match of ``normalized_name`` against every row's
    saved_name / file_name (normalized). Mirrors
    ``vault_complete_search._resolve_named_object`` deliberately —
    a divergence between the two would produce inconsistent behavior
    across code paths."""
    if not normalized_name or not rows:
        return _NamedResolveResult(status="miss")

    hits: list[tuple[str, dict]] = []
    exact: list[dict] = []
    seen_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        fid = str(row.get("id") or row.get("file_id") or "")
        if not fid or fid in seen_ids:
            # Only consider each file once even if it has multiple
            # matching label sources.
            pass
        matched_here = False
        for source in ("saved_name", "file_name"):
            raw = row.get(source)
            if not raw or not isinstance(raw, str):
                continue
            key = _normalize_name(raw)
            if not key or len(key) < _MIN_NAME_KEY_LEN:
                continue
            if key in _NAMED_OBJECT_CATEGORY_STOP:
                continue
            if key == normalized_name:
                exact.append(row)
                matched_here = True
                break
            # Substring at word boundary — either the label is inside
            # the query OR the query is inside the label. The former
            # is the intended "show me <exact label>" case; the latter
            # covers "show me passport" against saved_name "passport 2025".
            if _substring_at_wordbound(key, normalized_name):
                hits.append((key, row))
                matched_here = True
                break
            if _substring_at_wordbound(normalized_name, key):
                hits.append((key, row))
                matched_here = True
                break
        if matched_here and fid:
            seen_ids.add(fid)

    # Exact match beats fuzzy. Unique exact wins.
    if exact:
        # Deduplicate by id.
        unique = _dedupe_rows(exact)
        if len(unique) == 1:
            return _NamedResolveResult(status="hit", row=unique[0])
        return _NamedResolveResult(
            status="ambiguous",
            candidates=unique[:8],
        )

    if not hits:
        return _NamedResolveResult(status="miss")

    # Longest key wins among substring hits.
    hits.sort(key=lambda t: len(t[0]), reverse=True)
    top_len = len(hits[0][0])
    top = [row for (k, row) in hits if len(k) == top_len]
    top = _dedupe_rows(top)
    if len(top) == 1:
        return _NamedResolveResult(status="hit", row=top[0])
    return _NamedResolveResult(
        status="ambiguous",
        candidates=top[:8],
    )


def _substring_at_wordbound(needle: str, haystack: str) -> bool:
    if not needle or not haystack:
        return False
    pat = re.compile(
        r"(?:^|(?<=\s))" + re.escape(needle) + r"(?=$|\s|[.,;:!?])",
    )
    return pat.search(haystack) is not None


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        rid = str(r.get("id") or r.get("file_id") or "")
        if not rid:
            out.append(r)
            continue
        if rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------

def _short_hash(s: str) -> str:
    """Non-secret short hash used in trace logs. NOT crypto — just a
    stable prefix so operators can cross-reference log lines without
    seeing raw IDs."""
    if not s:
        return "-"
    import hashlib
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _build_vault_file_envelope(row: dict, action: str) -> str:
    """Build the same `type=vault_file` envelope shape the existing
    pronoun-followup and planner tool-result code already emit, so
    the frontend renders exactly the same VaultFileCard.

    Fields the frontend keys on (verified by the frontend audit):
      type, file_id, file_name, saved_name, relative_path,
      content_type, asset_type, pending_action.
    """
    fid = str(row.get("id") or row.get("file_id") or "")
    envelope = {
        "type":          RESPONSE_TYPE_VAULT_FILE,
        "file_id":       fid,
        "file_name":     str(row.get("file_name") or ""),
        "saved_name":    row.get("saved_name") or None,
        "relative_path": row.get("relative_path") or None,
        "content_type":  row.get("content_type") or None,
        "asset_type":    row.get("asset_type") or None,
        "pending_action": action,
        # Provenance so the frontend + tests can tell where this came from.
        "resolved_by":   "deterministic_router",
    }
    return json.dumps(envelope, ensure_ascii=False)


def _build_disambiguation_envelope(
    candidate_name: str, candidates: list[dict],
) -> str:
    """Ambiguity clarification. Matches the frontend
    file_disambiguation contract exactly (main.dart:11203-11223 +
    chat_cards.dart:3520-3533):

      { "type":  "file_disambiguation",
        "files": [ { file_id, file_name, saved_name,
                     relative_path, mime_type, confidence,
                     reasons, best_match, mostly_credentials,
                     purpose_label }, ... ],
        "title": "<header text>",
        "count": <int>,
        "context_kind": "named_object",
        "message": "<body headline>" }

    The Flutter parser reads `files` (not `options`), so this
    envelope MUST use `files`. The 2026-07-31 Codex review caught
    a mismatch where the router emitted `options` and the frontend
    rendered an empty candidate list. That is fixed here.
    """
    entries: list[dict] = []
    for row in candidates[:8]:
        # Confidence is a THREE-VALUE STRING ENUM the Flutter
        # _ConfidenceBadge (chat_cards.dart:3345) switches on:
        # "strong" | "medium" | "weak". Emitting a numeric would
        # trigger a _TypeError in the row renderer at
        # chat_cards.dart:3524. Every candidate here matches on the
        # same substring length, so "medium" is the correct label.
        entries.append({
            "file_id":       str(row.get("id") or row.get("file_id") or ""),
            "file_name":     str(row.get("file_name") or ""),
            "saved_name":    row.get("saved_name") or None,
            "relative_path": row.get("relative_path") or None,
            # Frontend row reader keys on `mime_type`, not `content_type`.
            "mime_type":     row.get("content_type") or None,
            "asset_type":    row.get("asset_type") or None,
            "confidence":    "medium",
            "reasons":       ["saved-name substring match"],
            "best_match":    False,
            "mostly_credentials": False,
            "purpose_label": None,
        })
    envelope = {
        "type":            RESPONSE_TYPE_FILE_DISAMBIGUATION,
        # Canonical field the Flutter parser reads.
        "files":           entries,
        "title":           f'Which file do you mean by "{candidate_name}"?',
        "count":           len(entries),
        "context_kind":    "named_object",
        "candidate_name":  candidate_name,
        "message":         (
            f"I found {len(entries)} items whose saved name matches "
            f"\"{candidate_name}\". Tap the one you meant."
        ),
        "resolved_by":     "deterministic_router",
    }
    return json.dumps(envelope, ensure_ascii=False)


def _build_credential_draft_envelope(draft_payload: dict, service: str) -> str:
    """Wrap the draft payload in the vault_chat_card envelope the
    Flutter frontend recognizes AND fully populates so the
    ``_GeneratedLoginCard`` widget can render the service name, the
    username, the generated password (masked by default, revealable
    on tap), and Save/Cancel action buttons.

    2026-08-01: the prior envelope carried only the wrapper shape but
    NO field values, because the frontend renderer at that time was
    a hardcoded "Save requires confirmation" placeholder. That
    placeholder was an unfinished stub — production feedback made
    that clear: users had no way to see what would be saved. Both
    the envelope AND the widget renderer are updated in this pass;
    the envelope is populated here, and the widget rewrite lives at
    ``vault_ai_frontend/lib/ui/vault_chat_cards.dart::_GeneratedLoginCard``.

    Envelope shape (matches vault_chat_stream_parser.dart:88-168):

      { "type":   "vault_chat_card",
        "schema": "vault_chat_response_v1",
        "intent": "vault_generated_login_create_draft",
        "message": "<user-visible headline>",
        "card": {
            "cardType":     "vault_generated_login_card",
            "view":         "create_draft",
            "service":      "<service display name>",
            "service_name": "<service display name>",  # alias
            "username":     "<explicit or generated>",
            "password":     "<generated>",              # masked in UI
            "draft_id":     "<draft-id>",
            "email":        "<if user supplied one>",   # optional
            "url":          "<if user supplied one>",   # optional
            "title":        "<if user supplied one>",   # optional
            "explicit_fields": [ ... ],                 # provenance
            "actions":      ["save", "cancel"]
        }
      }

    Security note: the raw password IS included in this envelope.
    That is intentional and matches the pre-router state-machine
    behavior at vault_pending_draft_state._format_draft_reply which
    also serialized the plaintext password into the chat reply.
    The whole /chat SSE stream is AES-GCM encrypted with the
    caller's derived vault key, so the payload never crosses the
    trust boundary in plaintext. The frontend then masks the
    password by default; the user reveals it explicitly. On "save"
    the state machine persists the values via
    save_secret_tool — the same code path the OLD state machine
    used, unchanged.
    """
    # Prefer the persisted draft's authoritative values — that is
    # what will actually land in the vault when the user says "save
    # it". Fall back to the caller-supplied service only when the
    # draft payload does not carry it (should never happen for a
    # successful store_draft, but defensive).
    display_service = str(
        draft_payload.get("service_name")
        or draft_payload.get("service")
        or service
        or ""
    )
    username = str(draft_payload.get("username") or "")
    password = str(draft_payload.get("password") or "")
    draft_id = str(draft_payload.get("draft_id") or "")
    explicit_fields = list(draft_payload.get("explicit_fields") or [])

    # The Flutter parser (services/vault_chat_router.dart:VaultChatCard.
    # fromJson at line 251) reads structured content from the NESTED
    # `card.data` sub-dict, not from `card` itself. Only cardType and
    # view live at the outer `card` level; every field the widget
    # renders (service, username, password, draft_id, actions, ...)
    # goes inside `data`.
    #
    # Also: the parser strips a blacklist of forbidden keys from
    # `data` unless the card type has a positive allowlist. The
    # frontend router at vault_chat_router.dart adds a positive
    # allowlist for our card type (_sanitizeGeneratedLoginCard),
    # mirroring the existing login-detail allowlist pattern.
    card_data: dict = {
        # View discriminator the widget switches on. Same value the
        # renderer reads to distinguish create_draft from any future
        # view (e.g. list, edit).
        "view":            "create_draft",
        # Both keys carry the same value — some downstream consumers
        # read `service`, others `service_name`. Emit both to avoid
        # a rename regression on a future frontend change.
        "service":         display_service,
        "service_name":    display_service,
        "username":        username,
        "password":        password,
        "draft_id":        draft_id,
        "explicit_fields": explicit_fields,
        # Closed-set enum the frontend switches on to render the
        # button row. Order matters: Save first, Cancel second.
        "actions":         ["save", "cancel"],
        # Marker the sanitizer keys on. Kept intentionally verbose so
        # a code reviewer can grep it and understand why plaintext
        # values survive the strip.
        "schema":          "vault_generated_login_draft_v1",
    }

    # Optional user-supplied fields — surface only when present so
    # they render as extra rows rather than empty pills.
    if draft_payload.get("email"):
        card_data["email"] = str(draft_payload["email"])
    if draft_payload.get("url"):
        card_data["url"] = str(draft_payload["url"])
    if draft_payload.get("title"):
        card_data["title"] = str(draft_payload["title"])

    card: dict = {
        "cardType": "vault_generated_login_card",
        # The `view` at the outer `card` level is what the existing
        # `_GeneratedLoginCard` widget currently reads via
        # `widget.card.view`. Keep it here too so any consumer that
        # inspects the outer card object (not just `data`) still sees
        # the right view.
        "view":     "create_draft",
        "data":     card_data,
    }

    envelope = {
        "type":        "vault_chat_card",
        "schema":      "vault_chat_response_v1",
        "intent":      "vault_generated_login_create_draft",
        "message":     (
            f"I prepared a {display_service} login draft. "
            "Review the values, then tap Save to store it in your "
            "vault or Cancel to discard it."
        ),
        "card":        card,
        "resolved_by": "deterministic_router",
    }
    return json.dumps(envelope, ensure_ascii=False)


def _draft_payload_to_card_data(draft_payload: dict, service: str) -> dict:
    display_service = str(
        draft_payload.get("service_name")
        or draft_payload.get("service")
        or service
        or ""
    )
    data = {
        "view": "create_draft",
        "service": display_service,
        "service_name": display_service,
        "username": str(draft_payload.get("username") or ""),
        "password": str(draft_payload.get("password") or ""),
        "draft_id": str(draft_payload.get("draft_id") or ""),
        "explicit_fields": list(draft_payload.get("explicit_fields") or []),
        "actions": ["save", "cancel"],
        "schema": "vault_generated_login_draft_v1",
    }
    if draft_payload.get("email"):
        data["email"] = str(draft_payload["email"])
    if draft_payload.get("url"):
        data["url"] = str(draft_payload["url"])
    if draft_payload.get("title"):
        data["title"] = str(draft_payload["title"])
    return data


def _build_credential_draft_batch_envelope(
    draft_payloads: list[dict],
) -> str:
    drafts = [
        _draft_payload_to_card_data(
            payload,
            str(payload.get("service_name") or payload.get("service") or ""),
        )
        for payload in draft_payloads
    ]
    services = [
        str(d.get("service_name") or d.get("service") or "").strip()
        for d in drafts
        if str(d.get("service_name") or d.get("service") or "").strip()
    ]
    service_list = ", ".join(services)
    envelope = {
        "type": "vault_chat_card",
        "schema": "vault_chat_response_v1",
        "intent": "vault_generated_login_create_draft",
        "message": (
            f"I prepared {len(drafts)} login drafts"
            + (f" for {service_list}." if service_list else ".")
            + " Review each one before saving it."
        ),
        "card": {
            "cardType": "vault_generated_login_card",
            "view": "create_draft_batch",
            "data": {
                "schema": "vault_generated_login_draft_batch_v1",
                "view": "create_draft_batch",
                "drafts": drafts,
                "count": len(drafts),
                "actions": ["save", "cancel"],
            },
        },
        "resolved_by": "deterministic_router",
    }
    return json.dumps(envelope, ensure_ascii=False)


def _has_explicit_save_now_phrase(message: str) -> bool:
    return bool(_SAVE_NOW_RE.search(message or ""))


def _save_generated_drafts_after_confirmation(
    *,
    vault_id: str,
    key: bytes,
    draft_payloads: list[dict],
    credential_saver: Optional[Callable[..., Any]],
) -> tuple[bool, list[str]]:
    if credential_saver is None:
        return False, []
    from vault_pending_credential_confirm import save_pending_credential

    saved_services: list[str] = []
    for payload in draft_payloads:
        draft_id = str(payload.get("draft_id") or "").strip()
        if not draft_id:
            return False, saved_services
        try:
            result = save_pending_credential(
                vault_id=vault_id,
                key=key,
                memory={},
                save_secret_tool=credential_saver,
                selection_hint={
                    "kind": "generated_login_draft",
                    "id": draft_id,
                },
            )
        except Exception:
            logger.exception(
                "[DETERMINISTIC-ROUTER] credential_save raised vault=%s",
                (vault_id or "")[:8] + "...",
            )
            return False, saved_services
        if result is None:
            return False, saved_services
        saved_service = str(result.service_name or "").strip()
        if saved_service:
            saved_services.append(saved_service)
    return True, saved_services


def _format_saved_credential_reply(services: list[str]) -> str:
    clean = [s for s in services if str(s or "").strip()]
    if len(clean) == 1:
        return f"Saved your {clean[0].title()} login to your vault 🔐"
    if clean:
        return (
            f"Saved {len(clean)} logins to your vault: "
            + ", ".join(clean)
            + " 🔐"
        )
    return "Saved the login to your vault 🔐"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _trace(
    *,
    request_id: str,
    route: str,
    intent: str,
    candidate_name_len: int = 0,
    exact_match_count: int = 0,
    resolved_object_type: str = "",
    resolved_object_id_hash: str = "",
    action: str = "",
    response_type: str = "",
    fallback_reason: str = "",
    explicit_username_present: Optional[bool] = None,
    explicit_password_present: Optional[bool] = None,
    generated_username: Optional[bool] = None,
    generated_password: Optional[bool] = None,
) -> None:
    """Single structured trace line. Never prints message content."""
    parts = [
        "CHAT_TRACE",
        f"request_id={request_id or '-'}",
        f"route={route}",
        f"intent={intent}",
        f"candidate_name_len={int(candidate_name_len)}",
        f"exact_match_count={int(exact_match_count)}",
        f"resolved_object_type={resolved_object_type or '-'}",
        f"resolved_object_id_hash={resolved_object_id_hash or '-'}",
        f"action={action or '-'}",
        f"response_type={response_type or '-'}",
        f"fallback_reason={fallback_reason or '-'}",
    ]
    if explicit_username_present is not None:
        parts.append(f"explicit_username_present={str(bool(explicit_username_present)).lower()}")
    if explicit_password_present is not None:
        parts.append(f"explicit_password_present={str(bool(explicit_password_present)).lower()}")
    if generated_username is not None:
        parts.append(f"generated_username={str(bool(generated_username)).lower()}")
    if generated_password is not None:
        parts.append(f"generated_password={str(bool(generated_password)).lower()}")
    print(" ".join(parts), flush=True)


# ---------------------------------------------------------------------------
# Public router
# ---------------------------------------------------------------------------

def try_route_deterministically(
    *,
    vault_id: str,
    session_id: Optional[str],
    key: bytes,
    decrypted_message: str,
    files_lister: Callable[[], list[dict]],
    credential_drafter: Callable[..., str],
    active_entity_getter: Callable[..., Optional[dict]],
    active_entity_setter: Callable[..., bool],
    chat_request_id: str = "",
    credential_saver: Optional[Callable[..., Any]] = None,
) -> Optional[RouteOutcome]:
    """Attempt to fully handle the request without touching the LLM.

    Returns a ``RouteOutcome`` when handled — the caller MUST use
    the returned envelope + chat_path_tag + pin_active_entity hint.
    Returns None when the router does not recognize the request as
    one of its three handled patterns — the caller falls through
    to the existing chat cascade.

    Never raises. Any internal exception downgrades to None and a
    ``CHAT_TRACE ... fallback_reason=router_raised`` line.
    """
    try:
        return _try_route_inner(
            vault_id=vault_id,
            session_id=session_id,
            key=key,
            decrypted_message=decrypted_message,
            files_lister=files_lister,
            credential_drafter=credential_drafter,
            active_entity_getter=active_entity_getter,
            active_entity_setter=active_entity_setter,
            chat_request_id=chat_request_id,
            credential_saver=credential_saver,
        )
    except Exception:
        logger.exception(
            "[DETERMINISTIC-ROUTER] raised — falling through vault=%s",
            (vault_id or "")[:8] + "…",
        )
        _trace(
            request_id=chat_request_id,
            route="deterministic",
            intent="router_error",
            fallback_reason="router_raised",
        )
        return None


def _try_route_inner(
    *,
    vault_id: str,
    session_id: Optional[str],
    key: bytes,
    decrypted_message: str,
    files_lister: Callable[[], list[dict]],
    credential_drafter: Callable[..., str],
    active_entity_getter: Callable[..., Optional[dict]],
    active_entity_setter: Callable[..., bool],
    chat_request_id: str,
    credential_saver: Optional[Callable[..., Any]] = None,
) -> Optional[RouteOutcome]:
    if not vault_id or not decrypted_message:
        return None
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        _trace(
            request_id=chat_request_id,
            route="deterministic",
            intent="skip_vault_locked",
            fallback_reason="key_invalid",
        )
        return None
    if len(decrypted_message) > _MAX_ROUTABLE_CHARS:
        _trace(
            request_id=chat_request_id,
            route="deterministic",
            intent="skip_too_long",
            fallback_reason="message_over_max",
        )
        return None

    # ------------------------------------------------------------------
    # Pattern C: explicit credential creation. Runs FIRST because the
    # message may contain both a service name and a username — those
    # cannot be misread as a "show me <name>" lookup.
    # ------------------------------------------------------------------
    from vault_credential_command import (
        extract_credential_command,
        ACTION_CREATE,
        FIELD_USERNAME,
        FIELD_PASSWORD,
        FIELD_EMAIL,
        FIELD_URL,
        FIELD_TITLE,
    )
    try:
        cred_cmd = extract_credential_command(decrypted_message)
    except Exception:
        cred_cmd = None

    services_from_text = _extract_credential_services_from_message(
        decrypted_message
    )
    if services_from_text and not (
        cred_cmd is not None and cred_cmd.action == ACTION_CREATE
    ):
        draft_payloads: list[dict] = []
        for service in services_from_text[:5]:
            try:
                draft_raw = credential_drafter(
                    vault_id=vault_id,
                    key=key,
                    service_name=service,
                    username=None,
                    password=None,
                    email=None,
                    url=None,
                    title=None,
                )
            except Exception:
                logger.exception(
                    "[DETERMINISTIC-ROUTER] credential_drafter raised - "
                    "falling through vault=%s",
                    (vault_id or "")[:8] + "...",
                )
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    fallback_reason="drafter_raised",
                )
                return None
            try:
                draft_payload = json.loads(draft_raw or "{}")
            except Exception:
                draft_payload = {}
            if draft_payload.get("error") or not draft_payload.get("draft_id"):
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    fallback_reason=str(
                        draft_payload.get("error") or "drafter_returned_empty"
                    ),
                )
                return None
            draft_payloads.append(draft_payload)

        if _has_explicit_save_now_phrase(decrypted_message):
            saved, saved_services = _save_generated_drafts_after_confirmation(
                vault_id=vault_id,
                key=key,
                draft_payloads=draft_payloads,
                credential_saver=credential_saver,
            )
            if not saved:
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    fallback_reason="save_failed",
                )
                return None
            _trace(
                request_id=chat_request_id,
                route="deterministic",
                intent="credential_create",
                exact_match_count=len(saved_services),
                resolved_object_type="generated_login",
                action="save",
                response_type="credential_saved",
                explicit_username_present=False,
                explicit_password_present=False,
                generated_username=True,
                generated_password=True,
            )
            return RouteOutcome(
                kind=KIND_CREDENTIAL_SAVED,
                envelope_json=_format_saved_credential_reply(saved_services),
                chat_path_tag=CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
                pin_active_entity=None,
            )

        if len(draft_payloads) > 1:
            envelope = _build_credential_draft_batch_envelope(draft_payloads)
            pin_active = None
            kind = KIND_CREDENTIAL_DRAFT_BATCH
        else:
            envelope = _build_credential_draft_envelope(
                draft_payloads[0], services_from_text[0],
            )
            pin_active = (
                "generated_login_draft",
                {
                    "draft_id": str(
                        draft_payloads[0].get("draft_id") or ""
                    ),
                    "service": services_from_text[0],
                },
                services_from_text[0],
                ("show", "save", "cancel", "edit"),
            )
            kind = KIND_CREDENTIAL_DRAFT

        _trace(
            request_id=chat_request_id,
            route="deterministic",
            intent="credential_create",
            candidate_name_len=sum(len(s) for s in services_from_text),
            exact_match_count=len(draft_payloads),
            resolved_object_type="generated_login_draft",
            resolved_object_id_hash=_short_hash(
                str(draft_payloads[0].get("draft_id") or ""),
            ),
            action="create",
            response_type=RESPONSE_TYPE_CREDENTIAL_DRAFT,
            explicit_username_present=False,
            explicit_password_present=False,
            generated_username=True,
            generated_password=True,
        )
        return RouteOutcome(
            kind=kind,
            envelope_json=envelope,
            chat_path_tag=CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
            pin_active_entity=pin_active,
        )

    if cred_cmd is not None and cred_cmd.action == ACTION_CREATE:
        # Service must be identifiable — either from the extractor or
        # from a very-explicit "for X" phrase. If neither, defer to
        # the planner (which has better service-name understanding).
        service = _extract_service_from_message(decrypted_message)
        if not service:
            service = cred_cmd.service
        if service:
            explicit = dict(cred_cmd.explicit_fields or {})
            explicit_username_present = bool(explicit.get(FIELD_USERNAME))
            explicit_password_present = bool(explicit.get(FIELD_PASSWORD))
            try:
                draft_raw = credential_drafter(
                    vault_id=vault_id,
                    key=key,
                    service_name=service,
                    username=explicit.get(FIELD_USERNAME),
                    password=explicit.get(FIELD_PASSWORD),
                    email=explicit.get(FIELD_EMAIL),
                    url=explicit.get(FIELD_URL),
                    title=explicit.get(FIELD_TITLE),
                )
            except Exception:
                logger.exception(
                    "[DETERMINISTIC-ROUTER] credential_drafter raised — "
                    "falling through vault=%s",
                    (vault_id or "")[:8] + "…",
                )
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    fallback_reason="drafter_raised",
                )
                return None
            try:
                draft_payload = json.loads(draft_raw or "{}")
            except Exception:
                draft_payload = {}
            if draft_payload.get("error") or not draft_payload.get("draft_id"):
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    fallback_reason=str(
                        draft_payload.get("error") or "drafter_returned_empty"
                    ),
                    explicit_username_present=explicit_username_present,
                    explicit_password_present=explicit_password_present,
                )
                return None
            if _has_explicit_save_now_phrase(decrypted_message):
                saved, saved_services = _save_generated_drafts_after_confirmation(
                    vault_id=vault_id,
                    key=key,
                    draft_payloads=[draft_payload],
                    credential_saver=credential_saver,
                )
                if not saved:
                    _trace(
                        request_id=chat_request_id,
                        route="deterministic",
                        intent="credential_create",
                        fallback_reason="save_failed",
                        explicit_username_present=explicit_username_present,
                        explicit_password_present=explicit_password_present,
                    )
                    return None
                _trace(
                    request_id=chat_request_id,
                    route="deterministic",
                    intent="credential_create",
                    candidate_name_len=len(service),
                    exact_match_count=1,
                    resolved_object_type="generated_login",
                    resolved_object_id_hash=_short_hash(
                        str(draft_payload.get("draft_id") or ""),
                    ),
                    action="save",
                    response_type="credential_saved",
                    explicit_username_present=explicit_username_present,
                    explicit_password_present=explicit_password_present,
                    generated_username=(
                        "username" not in (
                            draft_payload.get("explicit_fields") or []
                        )
                    ),
                    generated_password=(
                        "password" not in (
                            draft_payload.get("explicit_fields") or []
                        )
                    ),
                )
                return RouteOutcome(
                    kind=KIND_CREDENTIAL_SAVED,
                    envelope_json=_format_saved_credential_reply(
                        saved_services,
                    ),
                    chat_path_tag=CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
                    pin_active_entity=None,
                )
            envelope = _build_credential_draft_envelope(
                draft_payload, service,
            )
            # A generated draft is a GENERATED_LOGIN_DRAFT active entity.
            # The state-machine already handles subsequent "save it" / "cancel" /
            # "change the username to X" turns on this entity type.
            pin_ref = {
                "draft_id": str(draft_payload.get("draft_id") or ""),
                "service":  service,
            }
            _trace(
                request_id=chat_request_id,
                route="deterministic",
                intent="credential_create",
                candidate_name_len=len(service),
                exact_match_count=1,
                resolved_object_type="generated_login_draft",
                resolved_object_id_hash=_short_hash(
                    str(draft_payload.get("draft_id") or ""),
                ),
                action="create",
                response_type=RESPONSE_TYPE_CREDENTIAL_DRAFT,
                explicit_username_present=explicit_username_present,
                explicit_password_present=explicit_password_present,
                generated_username=(
                    "username" not in (draft_payload.get("explicit_fields") or [])
                ),
                generated_password=(
                    "password" not in (draft_payload.get("explicit_fields") or [])
                ),
            )
            return RouteOutcome(
                kind=KIND_CREDENTIAL_DRAFT,
                envelope_json=envelope,
                chat_path_tag=CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
                pin_active_entity=(
                    "generated_login_draft",
                    pin_ref,
                    service,
                    ("show", "save", "cancel", "edit"),
                ),
            )

    # ------------------------------------------------------------------
    # Pattern B: explicit named-object lookup.
    # ------------------------------------------------------------------
    named_hit = _extract_named_action(decrypted_message)
    if named_hit is not None:
        try:
            rows = files_lister() or []
        except Exception:
            logger.exception(
                "[DETERMINISTIC-ROUTER] files_lister raised — "
                "falling through vault=%s",
                (vault_id or "")[:8] + "…",
            )
            _trace(
                request_id=chat_request_id,
                route="deterministic",
                intent="named_object",
                candidate_name_len=len(named_hit.normalized_name),
                fallback_reason="files_lister_raised",
            )
            return None
        resolve = _resolve_named_object_from_rows(
            named_hit.normalized_name, rows,
        )
        if resolve.status == "hit" and resolve.row is not None:
            envelope = _build_vault_file_envelope(
                resolve.row, action=named_hit.verb,
            )
            fid = str(
                resolve.row.get("id")
                or resolve.row.get("file_id")
                or "",
            )
            _trace(
                request_id=chat_request_id,
                route="deterministic",
                intent="named_object",
                candidate_name_len=len(named_hit.normalized_name),
                exact_match_count=1,
                resolved_object_type="file",
                resolved_object_id_hash=_short_hash(fid),
                action=named_hit.verb,
                response_type=RESPONSE_TYPE_VAULT_FILE,
            )
            return RouteOutcome(
                kind=KIND_NAMED_OBJECT_FILE,
                envelope_json=envelope,
                chat_path_tag=CHAT_PATH_DETERMINISTIC_NAMED_OBJECT,
                pin_active_entity=(
                    "file",
                    {"file_id": fid},
                    str(
                        resolve.row.get("saved_name")
                        or resolve.row.get("file_name")
                        or "",
                    )[:120],
                    # 2026-07-27 architectural gap fix: full follow-up
                    # verb set. Any bare "download it" / "delete it" /
                    # "show related" / "tell me about it" / "rename it"
                    # / "copy it" / "move it" now resolves against this
                    # pinned file via the existing pronoun-followup
                    # dispatcher, which was widened at the same time.
                    (
                        "show", "open", "view", "download",
                        "delete", "rename", "copy",
                        "related", "describe", "move",
                    ),
                ),
            )
        if resolve.status == "ambiguous":
            envelope = _build_disambiguation_envelope(
                named_hit.candidate_name, resolve.candidates,
            )
            _trace(
                request_id=chat_request_id,
                route="deterministic",
                intent="named_object",
                candidate_name_len=len(named_hit.normalized_name),
                exact_match_count=len(resolve.candidates),
                resolved_object_type="file_list",
                action=named_hit.verb,
                response_type=RESPONSE_TYPE_FILE_DISAMBIGUATION,
                fallback_reason="ambiguous_names",
            )
            return RouteOutcome(
                kind=KIND_NAMED_OBJECT_AMBIGUOUS,
                envelope_json=envelope,
                chat_path_tag=CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS,
                pin_active_entity=None,
            )
        # miss — defer to planner (may still find via OCR / vision / semantic)
        _trace(
            request_id=chat_request_id,
            route="deterministic",
            intent="named_object",
            candidate_name_len=len(named_hit.normalized_name),
            exact_match_count=0,
            action=named_hit.verb,
            fallback_reason="no_named_match",
        )
        return None

    # ------------------------------------------------------------------
    # Pattern A: bare follow-up against active entity.
    # Handled by the existing pronoun-followup at main.py:12899 for the
    # verb set it recognizes. We do NOT re-implement that here to avoid
    # divergence. The router returns None so the existing block handles it.
    # ------------------------------------------------------------------
    return None


# ---------------------------------------------------------------------------
# Service-name extractor (light-weight — only positive matches)
# ---------------------------------------------------------------------------

# "create/save/generate/make (me )? (an|the|my|a)? <SERVICE> (login|account|credential)"
# Order matters in the determiner alternation: `an` before `a` so
# "make an amazon login" does NOT capture the trailing "n" of "an"
# into the service token.
_SERVICE_FROM_CREATE_RE: re.Pattern[str] = re.compile(
    r"""
    (?:^|\b)
    (?:create|save|make|generate|set\s+up|add)
    (?:\s+(?:me|my|us))?
    \s+
    (?:(?:an|the|my|a)\s+)?
    (?P<service>[A-Za-z0-9][A-Za-z0-9\.\-\s&]{0,40}?)
    \s+
    (?:login|account|credential|credentials|password|sign[\s-]?in)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


# "for my <service>" — secondary form (used when the "with my email X"
# clause reversed the sentence order).
_SERVICE_FROM_FOR_RE: re.Pattern[str] = re.compile(
    r"""
    \bfor\s+(?:(?:my|the|our)\s+)?
    (?P<service>[A-Za-z0-9][A-Za-z0-9\.\-\s&]{0,40}?)
    \s+
    (?:login|account|credential|credentials|password)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Words that must NOT be picked up as service names — English stop
# words that could accidentally match the pattern above.
_SERVICE_STOPWORDS: frozenset[str] = frozenset({
    "new", "another", "quick", "fresh", "extra", "second",
    "third", "different", "additional", "spare", "temporary",
    "test", "throwaway", "one", "same", "similar",
    "and", "or", "me", "my", "us", "a", "an", "the",
    "save", "create", "generate", "make", "add", "set", "up",
})


def _extract_service_from_message(message: str) -> Optional[str]:
    if not isinstance(message, str) or not message.strip():
        return None
    for pat in (_SERVICE_FROM_CREATE_RE, _SERVICE_FROM_FOR_RE):
        m = pat.search(message)
        if not m:
            continue
        try:
            candidate = m.group("service").strip()
        except (IndexError, KeyError):
            continue
        if not candidate:
            continue
        tokens = [t.strip(".,!?") for t in candidate.split() if t.strip()]
        if not tokens:
            continue
        # Reject if all tokens are stop-words.
        if all(t.lower() in _SERVICE_STOPWORDS for t in tokens):
            continue
        # Prune leading stop-words.
        while tokens and tokens[0].lower() in _SERVICE_STOPWORDS:
            tokens.pop(0)
        if not tokens:
            continue
        cleaned = " ".join(tokens)
        if len(cleaned) > 80:
            cleaned = cleaned[:80].strip()
        return cleaned
    return None


def _extract_credential_services_from_message(message: str) -> list[str]:
    if not isinstance(message, str) or not message.strip():
        return []
    lowered = message.lower()
    if not re.search(
        r"\b(create|save|make|generate|set\s+up|add)\b", lowered
    ):
        return []
    tail = re.sub(
        r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?"
        r"(?:create|save|make|generate|set\s+up|add)"
        r"(?:\s+(?:me|my|us))?\s+",
        "",
        message,
        count=1,
        flags=re.IGNORECASE,
    )

    def clean_candidate(candidate: str) -> str:
        candidate = str(candidate or "").strip()
        candidate = re.sub(
            r"\b(?:logins?|accounts?|credentials?|passwords?|"
            r"sign[\s-]?ins?)\b\.?\s*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r"^(?:and|or|me|my|us|an|a|the|new|fresh|another)\s+",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip(" ,.!?")
        tokens = [t.strip(".,!?") for t in candidate.split() if t.strip()]
        while tokens and tokens[0].lower() in _SERVICE_STOPWORDS:
            tokens.pop(0)
        return " ".join(tokens)[:80].strip()

    def append_candidate(candidate: str) -> None:
        cleaned = clean_candidate(candidate)
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        services.append(cleaned)

    services: list[str] = []
    seen: set[str] = set()

    # "Facebook, Instagram, and HBO Max logins" uses one trailing
    # item-type noun for the whole list. The older extractor only saw
    # the final "HBO Max logins" pair and silently omitted the earlier
    # services. Split that shared-noun form before the per-item scan.
    shared_noun = re.match(
        r"""
        ^\s*
        (?P<service_list>[A-Za-z0-9][A-Za-z0-9\.\-\s,&]{1,160}?)
        \s+
        (?:logins?|accounts?|credentials?|passwords?|sign[\s-]?ins?)
        \s*[.!?]*\s*$
        """,
        tail,
        re.IGNORECASE | re.VERBOSE,
    )
    if shared_noun:
        raw_list = str(shared_noun.group("service_list") or "")
        if "," in raw_list or re.search(r"\band\b", raw_list, re.IGNORECASE):
            parts = [
                p for p in re.split(r"\s*,\s*|\s+\band\b\s+", raw_list)
                if p.strip()
            ]
            for part in parts:
                append_candidate(part)
            if len(services) > 1:
                return services

    matches = re.finditer(
        r"""
        (?P<service>[A-Za-z0-9][A-Za-z0-9\.\-\s&]{0,40}?)
        \s+
        (?:logins?|accounts?|credentials?|passwords?|sign[\s-]?ins?)
        \b
        """,
        tail,
        re.IGNORECASE | re.VERBOSE,
    )
    for m in matches:
        append_candidate(str(m.group("service") or ""))
    return services


__all__ = [
    "CHAT_PATH_DETERMINISTIC_FOLLOWUP",
    "CHAT_PATH_DETERMINISTIC_NAMED_OBJECT",
    "CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS",
    "CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE",
    "KIND_FOLLOWUP_FILE",
    "KIND_FOLLOWUP_LOGIN",
    "KIND_NAMED_OBJECT_FILE",
    "KIND_NAMED_OBJECT_LOGIN",
    "KIND_NAMED_OBJECT_AMBIGUOUS",
    "KIND_CREDENTIAL_DRAFT",
    "KIND_CREDENTIAL_DRAFT_BATCH",
    "KIND_CREDENTIAL_SAVED",
    "RESPONSE_TYPE_VAULT_FILE",
    "RESPONSE_TYPE_FILE_DISAMBIGUATION",
    "RESPONSE_TYPE_FILE_SEARCH_RESULTS",
    "RESPONSE_TYPE_CREDENTIAL_DRAFT",
    "RouteOutcome",
    "try_route_deterministically",
]
