"""Deterministic layered extractor for credential-related chat messages.

Turns a user message + conversation memory into a structured
``CredentialCommand`` that downstream handlers can act on WITHOUT
having to re-parse raw English or duplicate field-preservation
logic. Deterministic: no LLM, no I/O. Never logs plaintext.

Bug 2 (2026-07-25 deep fix) — replaces the earlier email-only
``_extract_explicit_email`` shortcut in main.py. Callers should
consult this extractor at the earliest point after decrypt, and
merge the result into whatever handler they route to.

The extractor supports:
  * Plain email addresses (e.g. someone@example.com)
  * Arbitrary usernames including dots/underscores/hyphens
    ("chosen.abdullahi", "user_name_45", "cobalt-user-21")
  * Phone-number usernames ("+15551234567")
  * Quoted values ("use \"chosen abdullahi\" as the username")
  * Field-value syntax ("username: chosen2026", "email=X")
  * Natural language ("use X as (my )?(username|login|account name)",
    "sign in with X", "the account name should be X",
    "with my email X as my username")
  * Password assignments (only when explicitly labeled "password:X")
  * Follow-up state ("change the username to X" against a live
    pending draft is classified as edit_pending, not create).

Explicit user values ALWAYS take precedence over generated values.
The extractor never guesses a service name from arbitrary tokens;
it only extracts one when the message has a positive service
signal (usually the LLM classifier's ``intent_data.service``, or
a very confident phrase like "for my <service> account"). Callers
merge classifier-detected services with extractor-detected explicit
fields.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action taxonomy — every follow-up on a pending draft must be classifiable
# into exactly one of these. Handlers act on the kind, not the raw phrase.
# ---------------------------------------------------------------------------

ACTION_CREATE          = "create"           # start a fresh credential draft
ACTION_EDIT_PENDING    = "edit_pending"     # modify the live pending draft
ACTION_CONFIRM_SAVE    = "confirm_save"     # persist the pending draft
ACTION_CANCEL          = "cancel"           # discard the pending draft
ACTION_REGENERATE      = "regenerate_field" # re-generate a specific field
ACTION_SHOW_DRAFT      = "show_draft"       # re-display the pending draft
ACTION_REPLACE_DRAFT   = "replace_draft"    # scrap and start over
ACTION_UNRELATED       = "unrelated"        # not a credential command
ACTION_CLARIFY         = "clarify"          # ambiguous; ask user


# Fields we track explicitly. "note" and "url" are supported as text
# preservers only — the current chat brain does not persist arbitrary
# notes, so callers may ignore them without loss.
FIELD_USERNAME = "username"
FIELD_PASSWORD = "password"
FIELD_EMAIL    = "email"
FIELD_URL      = "url"
FIELD_TITLE    = "title"
FIELD_NOTE     = "note"

ALL_FIELDS = (
    FIELD_USERNAME, FIELD_PASSWORD, FIELD_EMAIL,
    FIELD_URL, FIELD_TITLE, FIELD_NOTE,
)


@dataclass
class CredentialCommand:
    """Structured representation of a credential-related turn.

    ``action`` is one of the ACTION_* constants above.

    ``service`` is the target service string, or None. Extractor
    only sets this when the user positively named a service; the
    dispatcher usually merges the LLM classifier's ``service`` in
    afterward.

    ``explicit_fields`` maps field name -> user-supplied value.
    NEVER a generated value. Values are stored preserving user case
    and punctuation; only surrounding whitespace and matching
    outer quotes are trimmed.

    ``generate_fields`` is the set of fields the extractor believes
    the user wants the assistant to generate (e.g. "and a fresh
    password"). Fields in explicit_fields take precedence.

    ``preserve_fields`` is the set of fields the user asked to
    leave alone ("keep my username", "don't touch the password").

    Convention: explicit_fields, generate_fields, preserve_fields
    are pairwise disjoint after merge (explicit > preserve >
    generate). The extractor guarantees this internally; callers
    can trust the invariant.
    """

    action: str = ACTION_UNRELATED
    service: Optional[str] = None
    explicit_fields: dict[str, str] = field(default_factory=dict)
    generate_fields: set[str] = field(default_factory=set)
    preserve_fields: set[str] = field(default_factory=set)
    # Populated by the state machine, not by the base extractor.
    # Kinds: "targeted_field" (user named the field), "phrase" (rejection
    # phrase like "username not accepted"). Callers use this to choose
    # the reply tone.
    reason: Optional[str] = None

    def merge_service(self, service: Optional[str]) -> None:
        """Merge a service string from an outer source (e.g. the LLM
        classifier). Never overwrites an already-set service."""
        if service and not self.service:
            self.service = service


# ---------------------------------------------------------------------------
# Wrapper / verb stripping — used to normalize the message before we look
# for value patterns. Never removes anything a value might depend on.
# ---------------------------------------------------------------------------

# Common leading conversational filler. Keep this list short and
# only strip when it clearly leads a request. Order matters: longest
# first so we don't half-strip a phrase.
_LEADING_FILLER = (
    r"can\s+you\s+(?:please\s+)?",
    r"could\s+you\s+(?:please\s+)?",
    r"i\s+(?:want|need|would\s+like)\s+you\s+to\s+",
    r"please\s+",
    r"hey[\s,]+",
    r"ok(?:ay)?[\s,]+",
    r"so[\s,]+",
)

_LEADING_FILLER_RE = re.compile(
    r"^\s*(?:" + "|".join(_LEADING_FILLER) + r")+",
    re.IGNORECASE,
)


def _strip_leading_filler(msg: str) -> str:
    return _LEADING_FILLER_RE.sub("", msg or "").strip()


# ---------------------------------------------------------------------------
# Explicit-value token patterns. Each pattern captures ONE value in a
# named group. The extractor tries them in priority order and records
# every distinct hit.
# ---------------------------------------------------------------------------

# A bare email address surrounded by word boundaries / punctuation.
_EMAIL_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s\(\[\{<,;:\"'/]))"
    r"(?P<value>[A-Za-z0-9._+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)"
    r"(?=$|[\s\)\]\}>,;:\"'/.!?])",
)

# Phone number in E.164-ish form ("+15551234567", "+1 555 123 4567").
# Only claim a phone as a USERNAME when it appears in a labeling
# context — the base pattern is just for recognition.
_PHONE_TOKEN_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s\(\[\{<,;:]))"
    r"(?P<value>\+?\d[\d\s\-().]{6,}\d)"
    r"(?=$|[\s\)\]\}>,;:.!?])",
)


def _clean_captured_value(raw: str) -> str:
    """Strip whitespace and one layer of matching outer quotes."""
    if raw is None:
        return ""
    s = raw.strip()
    # Trim outer matching quotes.
    for lq, rq in (("\"", "\""), ("'", "'"), ("`", "`")):
        if len(s) >= 2 and s.startswith(lq) and s.endswith(rq):
            s = s[1:-1].strip()
            break
    # Drop a single trailing sentence terminator (regex can capture ".")
    if s and s[-1] in ".,;":
        s = s[:-1].strip()
    return s


# Rejection words that must NOT be treated as legitimate field values.
# "username is wrong", "password is bad" — these are complaints, not
# assignments. The state machine reroutes them to REGENERATE.
_REJECTION_VALUE_TOKENS: frozenset[str] = frozenset({
    "wrong", "bad", "invalid", "rejected", "weak", "short",
    "unacceptable", "not", "no", "junk", "trash", "garbage",
    "terrible", "awful", "broken", "poor",
})


def _is_rejection_value(value: str) -> bool:
    """Return True if ``value`` looks like a rejection word rather than
    a real user-supplied field value. Used to prevent
    ``username is wrong`` from being interpreted as ``username=wrong``."""
    if not value:
        return True
    lowered = value.strip().lower().rstrip(".,;!?")
    # Multi-word rejection phrases.
    if lowered in {"not acceptable", "not accepted", "not good",
                   "no good", "no thanks", "too short", "too weak"}:
        return True
    return lowered in _REJECTION_VALUE_TOKENS


# Labels that identify each field. The pattern must not swallow
# following words — we anchor on a labeled value construction.
_USERNAME_LABEL_RE = re.compile(
    r"\b(?:"
    r"user\s*name|username|user\s*id|user\s*handle|"
    r"login\s*(?:name|id)?|account\s*(?:name|id)?|"
    r"sign[\s-]*in\s*(?:name|id)?"
    r")\b",
    re.IGNORECASE,
)
_PASSWORD_LABEL_RE = re.compile(r"\bpassword\b", re.IGNORECASE)
_EMAIL_LABEL_RE    = re.compile(r"\bemail(?:\s+address)?\b", re.IGNORECASE)
_URL_LABEL_RE      = re.compile(r"\b(?:url|link|website|site)\b", re.IGNORECASE)


# Fully labelled credential assertions. The service is captured only from a
# positive login-shaped phrase, while username/password values remain exact.
# These run before the more permissive single-field patterns so a value can
# never swallow the following field label.
_CREDENTIAL_ASSERTION_PATTERNS = (
    re.compile(
        r"^username\s+(?P<username>\S+)\s+(?:and\s+)?"
        r"(?:password|pass|pwd)\s+(?P<password>\S+)\s+is\s+my\s+"
        r"(?P<service>.+?)\s+login[.!?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^my\s+(?P<service>.+?)\s+username\s+is\s+"
        r"(?P<username>\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+is\s+"
        r"(?P<password>\S+)[.!?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:(?:save|store|remember)\s+)?(?:my\s+)?"
        r"(?P<service>.+?)\s+(?:is\s+)?"
        r"(?:login\s*[,;:]?\s+)?(?:username|user)\s+(?:is\s+)?"
        r"(?P<username>\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+"
        r"(?:is\s+)?(?P<password>\S+)[.!?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:save\s+)?(?:my\s+)?(?P<service>.+?)\s+login\s+is\s+"
        r"(?P<username>\S+)\s*(?:/|and)\s*(?P<password>\S+)[.!?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^save\s+(?:my\s+)?(?P<service>.+?)\s+login\s+"
        r"(?P<username>\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+"
        r"(?P<password>\S+)[.!?]*$",
        re.IGNORECASE,
    ),
)


def _extract_credential_assertion(message: str) -> Optional[dict[str, str]]:
    text = (message or "").strip()
    for pattern in _CREDENTIAL_ASSERTION_PATTERNS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        values = {
            key: _clean_captured_value(match.group(key))
            for key in ("service", FIELD_USERNAME, FIELD_PASSWORD)
        }
        if all(values.values()):
            return values
    return None


# ``field: value`` and ``field = value`` and ``field is value`` styles.
# Value captures up to end of line, closing bracket, or a semicolon.
_FIELD_VALUE_PATTERNS = (
    # username: X   username=X   username is X
    # Separator handling: `[:=]` allows zero whitespace between
    # label/value ("username=alice42"), word separators require a
    # space so "usernameisalice" doesn't accidentally parse.
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:user\s*name|username|user\s*id|user\s*handle|"
            r"login\s*(?:name|id)?|account\s*(?:name|id)?|"
            r"sign[\s-]*in\s*(?:name|id)?)\s*"
            r"(?:[:=]\s*|(?:is|should\s+be|to\s+be|to)\s+)"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|[^\s,;]+(?:\s+[^\s,;]+){0,3}?)"
            r"(?=\s*(?:[,;]|$|\band\b|\bthen\b|\bplease\b|\bnow\b|"
            r"\bthanks?\b|\bfor\b|\bto\b(?!\s+be\b)))",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        re.compile(
            r"\bpassword\s*"
            r"(?:[:=]\s*|(?:is|should\s+be|to\s+be|to)\s+)"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_EMAIL,
        re.compile(
            r"\bemail(?:\s+address)?\s*"
            r"(?:[:=]\s*|(?:is|should\s+be|to\s+be|to)\s+)"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_URL,
        re.compile(
            r"\b(?:url|link|website|site)\s*"
            r"(?:[:=]\s*|(?:is|should\s+be|to\s+be|to)\s+)"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|https?://\S+|\S+\.\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_TITLE,
        re.compile(
            r"\btitle\s*"
            r"(?:[:=]\s*|(?:is|should\s+be|to\s+be|to)\s+)"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|[^,;.\n]+)",
            re.IGNORECASE,
        ),
    ),
)


# "use X as (my)? (username|login|account name)"
# "sign in with X"
# "for the username X"
# The value token spans up to the next preposition or terminator so
# quoted multi-word usernames work.
_ASSIGN_AS_PATTERNS = (
    (
        FIELD_USERNAME,
        re.compile(
            r"\buse\s+"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)"
            r"\s+(?:as|for)\s+"
            r"(?:my\s+|the\s+|our\s+)?"
            r"(?:user\s*name|username|user\s*id|user\s*handle|"
            r"login\s*(?:name|id)?|account\s*(?:name|id)?|"
            r"sign[\s-]*in\s*(?:name|id)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_EMAIL,
        re.compile(
            r"\buse\s+"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)"
            r"\s+(?:as|for)\s+"
            r"(?:my\s+|the\s+|our\s+)?"
            r"email(?:\s+address)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_USERNAME,
        re.compile(
            r"\bsign(?:\s|-)*in\s+with\s+"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_USERNAME,
        # "for the username X" or "for username X" — value must run to
        # the next stop-word so multi-token usernames survive.
        re.compile(
            r"\bfor\s+(?:the\s+|my\s+|our\s+)?"
            r"(?:user\s*name|username|login|account\s*name|user\s*id)\s+"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|[^\s,;.]+)",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        # "use X as (my) password" — mirrors the username shape so
        # "password" gets recognized as an explicit assignment.
        re.compile(
            r"\buse\s+"
            r"(?P<value>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)"
            r"\s+(?:as|for)\s+"
            r"(?:my\s+|the\s+|our\s+)?"
            r"password\b",
            re.IGNORECASE,
        ),
    ),
)


# "with my email address X as my username" — pulls the email out
# even when the label ordering is inverted, and asserts it must
# also become the username.
_EMAIL_AS_USERNAME_RE = re.compile(
    r"\b(?:with|using)\s+(?:my\s+|the\s+|our\s+)?email(?:\s+address)?\s+"
    r"(?P<value>[A-Za-z0-9._+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)"
    r"\s+(?:as|for)\s+(?:my\s+|the\s+)?"
    r"(?:user\s*name|username|login(?:\s*name)?|account\s*name)\b",
    re.IGNORECASE,
)

# "with my email address X" (no "as username" tail) — treated as an
# explicit email assignment; the caller decides whether the service
# uses email-as-username.
_EMAIL_BEARING_RE = re.compile(
    r"\b(?:with|using)\s+(?:my\s+|the\s+|our\s+)?email(?:\s+address)?\s+"
    r"(?P<value>[A-Za-z0-9._+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)",
    re.IGNORECASE,
)


# "generate only a password", "make a fresh password"
_GENERATE_HINT_PATTERNS = (
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:generate|make|create|give\s+me|produce)\s+"
            r"(?:a\s+|an\s+|the\s+|only\s+a\s+|just\s+a\s+|"
            r"a\s+fresh\s+|another\s+)?"
            r"(?:user\s*name|username)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        re.compile(
            r"\b(?:generate|make|create|give\s+me|produce)\s+"
            r"(?:a\s+|an\s+|the\s+|only\s+a\s+|just\s+a\s+|"
            r"a\s+fresh\s+|a\s+new\s+|a\s+strong\s+|"
            r"another\s+|a\s+longer\s+|a\s+stronger\s+)?"
            r"password\b",
            re.IGNORECASE,
        ),
    ),
)


# "keep my username", "don't change the password", "leave the username alone"
_PRESERVE_HINT_PATTERNS = (
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:keep|preserve|don'?t\s+(?:change|touch|modify)|"
            r"leave\s+alone|leave\s+intact|leave\s+as\s+is|"
            r"same)\s+(?:my\s+|the\s+|our\s+)?"
            r"(?:user\s*name|username|login\s+name|account\s+name)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        re.compile(
            r"\b(?:keep|preserve|don'?t\s+(?:change|touch|modify)|"
            r"leave\s+alone|leave\s+intact|leave\s+as\s+is|"
            r"same)\s+(?:my\s+|the\s+|our\s+)?password\b",
            re.IGNORECASE,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Follow-up classifier (used by the state machine). These operate on a
# pending draft and decide whether the message edits, saves, cancels,
# regenerates, shows, or is unrelated.
# ---------------------------------------------------------------------------

# Save phrases — MORE permissive than vault_pending_draft_confirm because
# by the time we consult this classifier we already know the draft
# exists and the message is not an edit (edits win).
_SAVE_INTENT_RE = re.compile(
    r"\b(?:save|store|keep|remember|add|persist|commit|write)\s+"
    r"(?:it|that|this|them|the\s+(?:draft|login|credential))?\b",
    re.IGNORECASE,
)
_SAVE_SIMPLE_RE = re.compile(
    r"^\s*(?:save|store|keep|remember|do\s+it|go\s+ahead|"
    r"looks?\s+good|that\s+works|perfect|yea|yeah|yep|yup|"
    r"yes\s+save|ok\s+save)"
    r"[\s.!?]*$",
    re.IGNORECASE,
)

_CANCEL_RE = re.compile(
    r"\b(?:cancel|never\s+mind|nevermind|forget\s+it|discard|"
    r"drop\s+it|abort|scrap\s+that|scrap\s+this|don'?t\s+save|"
    r"stop|no\s+don'?t|no\s+thanks?)\b",
    re.IGNORECASE,
)

_SHOW_DRAFT_RE = re.compile(
    r"\b(?:show|display|repeat|read|see|print)\s+"
    r"(?:me\s+(?:the\s+|my\s+|our\s+)?|the\s+|my\s+|our\s+)?"
    r"(?:draft|pending|login\s+draft|credential\s+draft)\b",
    re.IGNORECASE,
)

_REPLACE_DRAFT_RE = re.compile(
    r"\b(?:start\s+over|scrap\s+(?:this|that|it)|"
    r"replace\s+(?:the\s+|this\s+|that\s+)?draft|"
    r"do\s+(?:it\s+)?again|from\s+scratch)\b",
    re.IGNORECASE,
)

# Cancel patterns include "scrap that/this" — which also appears in
# the REPLACE list. We resolve the overlap by checking REPLACE_DRAFT
# BEFORE CANCEL in the state machine below. Alternative: broaden
# REPLACE to distinguish "scrap and start over" from "scrap it".


# Regenerate + rejection phrases target a specific field.
# Each field has TWO regex forms: verb-first ("change the username")
# and field-first ("password should be longer") so we cover both
# common phrasings without a single mega-alternation.
_REGENERATE_FIELD_PATTERNS = (
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:regenerate|redo|remake|make\s+another|"
            r"give\s+me\s+another|try\s+another|"
            r"change|replace|update|modify)\s+"
            r"(?:only\s+)?(?:the\s+|my\s+|our\s+)?"
            r"(?:user\s*name|username|login\s*name|account\s*name)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:user\s*name|username|login\s*name|account\s*name)\b"
            r"[^.!?]{0,20}\b(?:should\s+be|needs?\s+to\s+be|"
            r"new|different|another|shorter|longer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        re.compile(
            r"\b(?:regenerate|redo|remake|make\s+another|"
            r"give\s+me\s+another|try\s+another|new|another|"
            r"change|replace|update|modify)\s+"
            r"(?:only\s+)?(?:the\s+|my\s+|our\s+)?password\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        # "make the password longer", "make it stronger", "make my
        # password different" — the modifier follows the field.
        re.compile(
            r"\bmake\s+(?:it|(?:the\s+|my\s+|our\s+)?password)\s+"
            r"(?:longer|stronger|different|new|fresh|another|"
            r"harder(?:\s+to\s+guess)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        # "password should be longer/stronger", "password too short".
        re.compile(
            r"\bpassword\b[^.!?]{0,30}\b(?:should\s+be|needs?\s+to\s+be|"
            r"too\s+short|too\s+weak|not\s+long\s+enough|"
            r"longer|stronger|new|different)\b",
            re.IGNORECASE,
        ),
    ),
)

# Field-level rejection phrases — treat as regenerate.
_REJECT_FIELD_PATTERNS = (
    (
        FIELD_USERNAME,
        re.compile(
            r"\b(?:user\s*name|username|login\s*name|account\s*name)\b"
            r"[^.!?]{0,40}\b(?:not\s+acceptable|not\s+accepted|"
            r"rejected|invalid|no\s+good|"
            r"(?:doesn'?t|does\s+not|won'?t|will\s+not)\s+work|"
            r"bad)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FIELD_PASSWORD,
        re.compile(
            r"\bpassword\b[^.!?]{0,40}\b(?:not\s+acceptable|"
            r"not\s+accepted|rejected|invalid|no\s+good|weak|"
            r"(?:doesn'?t|does\s+not|won'?t|will\s+not)\s+work|"
            r"bad|too\s+short)\b",
            re.IGNORECASE,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def extract_explicit_fields(message: Optional[str]) -> dict[str, str]:
    """Return {field_name: user_supplied_value} extracted from ``message``.

    Deterministic. Never returns generated values. Values preserve
    the user's case and punctuation, minus outer whitespace and
    matched outer quotes.

    Only the FIRST value found per field wins — if the user says
    "username: foo, then username: bar" the extractor treats "foo"
    as authoritative. This is a deliberate conservative choice; the
    caller can override with a follow-up ``edit_pending`` turn.
    """
    out: dict[str, str] = {}
    if not message or not isinstance(message, str):
        return out
    text = message

    assertion = _extract_credential_assertion(text)
    if assertion is not None:
        return {
            FIELD_USERNAME: assertion[FIELD_USERNAME],
            FIELD_PASSWORD: assertion[FIELD_PASSWORD],
        }

    # Priority 1: "with my email X as my username" — explicit dual assignment.
    m = _EMAIL_AS_USERNAME_RE.search(text)
    if m:
        val = _clean_captured_value(m.group("value"))
        if val:
            out[FIELD_EMAIL] = val
            out[FIELD_USERNAME] = val

    # Priority 2: labeled field-value patterns (username:, password:, etc.)
    for field_name, pat in _FIELD_VALUE_PATTERNS:
        if field_name in out:
            continue
        m = pat.search(text)
        if m:
            val = _clean_captured_value(m.group("value"))
            if val and not _is_rejection_value(val):
                out[field_name] = val

    # Priority 3: "use X as (my) username" style.
    for field_name, pat in _ASSIGN_AS_PATTERNS:
        if field_name in out:
            continue
        m = pat.search(text)
        if m:
            val = _clean_captured_value(m.group("value"))
            if val and not _is_rejection_value(val):
                out[field_name] = val

    # Priority 4: "with my email X" (email only, no username tail).
    if FIELD_EMAIL not in out:
        m = _EMAIL_BEARING_RE.search(text)
        if m:
            val = _clean_captured_value(m.group("value"))
            if val:
                out[FIELD_EMAIL] = val

    # Priority 5: bare email token — the most conservative signal.
    # Treated as USERNAME when no other username was extracted, matching
    # user intent for "make a login with X@Y.com". Email is not stored
    # in the current chat draft schema, so username-only prevents field
    # loss. When a labeled email already exists we skip.
    if FIELD_USERNAME not in out:
        m = _EMAIL_RE.search(text)
        if m:
            val = _clean_captured_value(m.group("value"))
            if val:
                out[FIELD_USERNAME] = val

    return out


def _extract_create_service(message: str) -> Optional[str]:
    """Extract only a service explicitly attached to a create-login phrase."""
    without_fields = re.split(
        r"\s+(?:with|using)\s+(?:(?:my\s+)?(?:username|email|password)|.+?\s+as\s+(?:the\s+)?(?:username|email|password))\b",
        message.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    patterns = (
        r"^(?:please\s+)?(?:create|generate|make|add|save|set\s*up|give)(?:\s+me)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(.+?)\s+(?:account\s+)?(?:login|credential|account)$",
        r"^(?:please\s+)?(?:create|generate|make|add|save|set\s*up|give)(?:\s+me)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(?:login|credential|account)\s+(?:for\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, without_fields, re.IGNORECASE)
        if match:
            service = match.group(1).strip(" \t\r\n,;:\"'")
            return service or None
    return None


def _detect_generate_hints(text: str) -> set[str]:
    hints: set[str] = set()
    for field_name, pat in _GENERATE_HINT_PATTERNS:
        if pat.search(text):
            hints.add(field_name)
    return hints


def _detect_preserve_hints(text: str) -> set[str]:
    preserves: set[str] = set()
    for field_name, pat in _PRESERVE_HINT_PATTERNS:
        if pat.search(text):
            preserves.add(field_name)
    return preserves


def _detect_regenerate_targets(text: str) -> tuple[set[str], Optional[str]]:
    """Return (fields_to_regenerate, reason) where reason is one of
    ``targeted_field`` (user named the field to change), ``rejection``
    (service-side rejection language), or None."""
    targets: set[str] = set()
    reason: Optional[str] = None
    for field_name, pat in _REGENERATE_FIELD_PATTERNS:
        if pat.search(text):
            targets.add(field_name)
            reason = "targeted_field"
    for field_name, pat in _REJECT_FIELD_PATTERNS:
        if pat.search(text):
            targets.add(field_name)
            if reason is None:
                reason = "rejection"
    return targets, reason


def extract_credential_command(
    message: Optional[str],
    *,
    has_pending_draft: bool = False,
    pending_draft: Optional[dict] = None,
) -> CredentialCommand:
    # 2026-07-25 diagnostic entry-marker: prove that this extractor
    # was actually reached in production. Logs only booleans and
    # counts — no message content, no field values. Remove after
    # diagnosis.
    try:
        _msg_len = len(message) if isinstance(message, str) else 0
        print(
            f"[BRAIN-TRACE-DXR] site=extract_credential_command "
            f"msg_len={_msg_len} has_pending_draft={bool(has_pending_draft)}",
            flush=True,
        )
    except Exception:
        pass
    """Build a ``CredentialCommand`` from a chat message.

    When ``has_pending_draft`` is False the extractor only classifies
    ``create`` / ``unrelated``. When True it may also emit
    ``edit_pending``, ``confirm_save``, ``cancel``, ``regenerate_field``,
    ``show_draft``, ``replace_draft``.

    The caller (typically the /chat handler) should merge in the
    LLM classifier's ``service`` and ``parts_wanted`` before acting.

    Never logs. Never raises. Returns ``UNRELATED`` on any parse
    failure so downstream cascades continue unchanged.
    """
    if not message or not isinstance(message, str):
        return CredentialCommand(action=ACTION_UNRELATED)

    raw = message
    stripped = _strip_leading_filler(raw)
    explicit = extract_explicit_fields(raw)
    assertion = _extract_credential_assertion(raw)
    generate = _detect_generate_hints(raw)
    preserve = _detect_preserve_hints(raw)
    try:
        print(
            f"[BRAIN-TRACE-DXR] site=extract_credential_command_fields "
            f"explicit_field_keys={','.join(sorted(explicit.keys()))} "
            f"generate={','.join(sorted(generate))} "
            f"preserve={','.join(sorted(preserve))}",
            flush=True,
        )
    except Exception:
        pass

    # ---- edit_pending / regenerate_field / cancel / confirm_save
    # ---- checks fire only when a pending draft exists.
    if has_pending_draft:
        # REPLACE_DRAFT before CANCEL: "scrap that" appears in both
        # patterns; the more specific "start over / from scratch"
        # phrasing wins. Fall through to cancel only when there is
        # no explicit start-over signal.
        if _REPLACE_DRAFT_RE.search(stripped) and not explicit:
            return CredentialCommand(action=ACTION_REPLACE_DRAFT)

        # Cancel — a "no, discard" phrase must not be misread as a
        # labeled password containing the word "no".
        if _CANCEL_RE.search(stripped) and not explicit:
            return CredentialCommand(action=ACTION_CANCEL)

        # Show/repeat draft.
        if _SHOW_DRAFT_RE.search(stripped) and not explicit:
            return CredentialCommand(action=ACTION_SHOW_DRAFT)

        # Explicit-field edit — the user supplied a value. Highest
        # priority when a draft exists, because "change the username
        # to X" and "use X as my username" both belong here.
        if explicit:
            cmd = CredentialCommand(
                action=ACTION_EDIT_PENDING,
                explicit_fields=dict(explicit),
                generate_fields=generate - set(explicit.keys()),
                preserve_fields=preserve - set(explicit.keys()),
                reason="explicit_field",
            )
            return cmd

        # Regenerate a specific field (no explicit value given).
        regen_targets, regen_reason = _detect_regenerate_targets(stripped)
        if regen_targets:
            return CredentialCommand(
                action=ACTION_REGENERATE,
                generate_fields=set(regen_targets),
                preserve_fields=preserve - regen_targets,
                reason=regen_reason,
            )

        # Confirm/save phrases fire only after we've ruled out edits.
        if _SAVE_INTENT_RE.search(stripped) or _SAVE_SIMPLE_RE.match(stripped):
            return CredentialCommand(action=ACTION_CONFIRM_SAVE)

        # Otherwise the message is not obviously a follow-up to the
        # pending draft; fall through to unrelated.
        return CredentialCommand(action=ACTION_UNRELATED)

    # ---- no pending draft — only "create" or "unrelated" apply.
    if explicit or generate:
        return CredentialCommand(
            action=ACTION_CREATE,
            service=(
                assertion.get("service")
                if assertion
                else _extract_create_service(raw)
            ),
            explicit_fields=dict(explicit),
            generate_fields=generate - set(explicit.keys()),
            preserve_fields=preserve - set(explicit.keys()),
            reason="explicit_field" if explicit else None,
        )

    return CredentialCommand(action=ACTION_UNRELATED)


def is_explicit_credential_assertion_create(message: str) -> bool:
    """Return whether ``message`` supplies a complete login to create.

    This small predicate is shared with the earliest chat fast path so a
    username/password assertion cannot be mistaken for credential retrieval
    before the authoritative draft workflow gets a chance to run.
    """
    command = extract_credential_command(message, has_pending_draft=False)
    return bool(
        command.action == ACTION_CREATE
        and (command.service or "").strip()
        and command.explicit_fields.get(FIELD_USERNAME)
        and command.explicit_fields.get(FIELD_PASSWORD)
    )


__all__ = [
    "ACTION_CREATE",
    "ACTION_EDIT_PENDING",
    "ACTION_CONFIRM_SAVE",
    "ACTION_CANCEL",
    "ACTION_REGENERATE",
    "ACTION_SHOW_DRAFT",
    "ACTION_REPLACE_DRAFT",
    "ACTION_UNRELATED",
    "ACTION_CLARIFY",
    "FIELD_USERNAME",
    "FIELD_PASSWORD",
    "FIELD_EMAIL",
    "FIELD_URL",
    "FIELD_TITLE",
    "FIELD_NOTE",
    "ALL_FIELDS",
    "CredentialCommand",
    "extract_explicit_fields",
    "extract_credential_command",
    "is_explicit_credential_assertion_create",
]
