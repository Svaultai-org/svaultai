"""Fast-path guard for the /chat endpoint.

The chat endpoint historically ran a full drain of every background
maintenance queue (OCR / embedding / understanding / relationship
building) before the deterministic router even got to look at the
message. On a simple "how do I delete my vault?" that meant the
user watched the thinking indicator through several seconds of
background work.

This module decides whether an incoming chat message can safely
skip those drains. The rules:

  * A closed set of intents (`INTENTS_SAFE_WITHOUT_DRAINS`) is
    allowed to run without any drains. These are intents whose
    card data comes from DB rows or static content — FAQ,
    refusals, vault overview counts, logins/secure items/IDs
    lists, billing, storage, activity, crypto Vault cards.
    Generated-login CREATE-DRAFT is intentionally excluded: the
    side-effect-free router can only produce a shell card, while the
    deterministic credential-create router is the authoritative path
    that stores the draft and attaches card.data.
  * File-search, document-summary, cross-vault search, and
    unrecognized (LLM fallback) DO need the drains — those paths
    can genuinely benefit from freshly-extracted file text or
    embeddings.
  * If the message looks like a pending-save confirmation phrase
    ("save it", "yes save this"), we drop through to the full path
    so the pending-draft handling in main.py runs unchanged.
  * If we already know the vault has an "active context" (e.g.
    the user is editing a specific item), the fast path is also
    skipped so the active-context branch handles the message.

None of the enforcement gates change:
  * PIN and trusted-device gates run BEFORE the fast path.
  * The router refuses seed / mnemonic / private-key questions
    the same way whether or not drains ran.
  * Chat still cannot broadcast crypto (`canBroadcast=False` on
    every send-draft card).
  * The delete-vault endpoint still requires phrase + PIN + HMAC
    challenge — chat never deletes a vault.

Timing spans emitted (closed-set names, no user text):
  * chat.request.start
  * chat.fast_router.start
  * chat.fast_router.done
  * chat.drain.scheduled
  * chat.llm_fallback.start
  * chat.response.ready

Every log line carries only:
  * the closed-set span name
  * a 12-char SHA-256 hashed vault id
  * elapsed ms since chat.request.start
  * bytes for message-length safety (never the message itself)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Callable, Optional

from vault_credential_command import is_explicit_credential_assertion_create


logger = logging.getLogger(__name__)


INTENT_FAQ:                          str = "vault_faq"
INTENT_CRYPTO_DELEGATED:             str = "vault_crypto_delegated"
INTENT_REFUSAL_SECRET_MATERIAL:      str = (
    "vault_refusal_secret_material"
)
INTENT_REFUSAL_EXCHANGE_ACTION:      str = (
    "vault_refusal_exchange_action"
)
INTENT_REFUSAL_BYPASS_PIN:           str = "vault_refusal_bypass_pin"
INTENT_REFUSAL_EXPORT_ALL:           str = "vault_refusal_export_all"
INTENT_REFUSAL_MASS_REVEAL:          str = "vault_refusal_mass_reveal"
INTENT_REFUSAL_AUTO_SEND:            str = "vault_refusal_auto_send"
INTENT_VAULT_OVERVIEW:               str = "vault_overview"
INTENT_SECURE_ITEM_LIST:             str = "vault_secure_item_list"
INTENT_SECURE_ITEM_SEARCH:           str = "vault_secure_item_search"
INTENT_LOGIN_LIST:                   str = "vault_login_list"
INTENT_LOGIN_SEARCH:                 str = "vault_login_search"
INTENT_LOGIN_DUPLICATES:             str = "vault_login_duplicates"
INTENT_LOGIN_REVEAL:                 str = "vault_login_reveal"
INTENT_LOGIN_COPY:                   str = "vault_login_copy"
INTENT_GENERATED_LOGIN_LIST:         str = "vault_generated_login_list"
INTENT_GENERATED_LOGIN_CREATE_DRAFT: str = (
    "vault_generated_login_create_draft"
)
INTENT_ID_DOCUMENT_LIST:             str = "vault_id_document_list"
INTENT_ID_DOCUMENT_SEARCH:           str = "vault_id_document_search"
INTENT_ID_DOCUMENT_EXPIRY:           str = "vault_id_document_expiry"
INTENT_ID_DOCUMENT_REVEAL:           str = "vault_id_document_reveal"
INTENT_BILLING_STATUS:               str = "vault_billing_status"
INTENT_BILLING_UPGRADE:              str = "vault_billing_upgrade"
INTENT_STORAGE_USAGE:                str = "vault_storage_usage"
INTENT_STORAGE_LARGEST:              str = "vault_storage_largest_files"
INTENT_ACTIVITY_RECENT:              str = "vault_activity_recent"
INTENT_ACTIVITY_ITEM_HISTORY:        str = "vault_activity_item_history"


INTENTS_SAFE_WITHOUT_DRAINS: frozenset[str] = frozenset({
    INTENT_FAQ,
    INTENT_CRYPTO_DELEGATED,
    INTENT_REFUSAL_SECRET_MATERIAL,
    INTENT_REFUSAL_EXCHANGE_ACTION,
    INTENT_REFUSAL_BYPASS_PIN,
    INTENT_REFUSAL_EXPORT_ALL,
    INTENT_REFUSAL_MASS_REVEAL,
    INTENT_REFUSAL_AUTO_SEND,
    INTENT_VAULT_OVERVIEW,
    INTENT_SECURE_ITEM_LIST,
    INTENT_SECURE_ITEM_SEARCH,
    INTENT_LOGIN_LIST,
    INTENT_LOGIN_SEARCH,
    INTENT_LOGIN_DUPLICATES,
    INTENT_LOGIN_REVEAL,
    INTENT_LOGIN_COPY,
    INTENT_GENERATED_LOGIN_LIST,
    INTENT_ID_DOCUMENT_LIST,
    INTENT_ID_DOCUMENT_SEARCH,
    INTENT_ID_DOCUMENT_EXPIRY,
    INTENT_ID_DOCUMENT_REVEAL,
    INTENT_BILLING_STATUS,
    INTENT_BILLING_UPGRADE,
    INTENT_STORAGE_USAGE,
    INTENT_STORAGE_LARGEST,
    INTENT_ACTIVITY_RECENT,
    INTENT_ACTIVITY_ITEM_HISTORY,
})


INTENTS_NEEDING_DRAINS: frozenset[str] = frozenset({
    "vault_file_search",
    "vault_document_summary",
    "vault_cross_vault_search",
    "vault_unrecognized",
})


SPAN_REQUEST_START:        str = "chat.request.start"
SPAN_FAST_ROUTER_START:    str = "chat.fast_router.start"
SPAN_FAST_ROUTER_DONE:     str = "chat.fast_router.done"
SPAN_DRAIN_SCHEDULED:      str = "chat.drain.scheduled"
SPAN_LLM_FALLBACK_START:   str = "chat.llm_fallback.start"
SPAN_RESPONSE_READY:       str = "chat.response.ready"


ALL_SPANS: frozenset[str] = frozenset({
    SPAN_REQUEST_START,
    SPAN_FAST_ROUTER_START,
    SPAN_FAST_ROUTER_DONE,
    SPAN_DRAIN_SCHEDULED,
    SPAN_LLM_FALLBACK_START,
    SPAN_RESPONSE_READY,
})


_SAFETY_STOPWORDS_FOR_LOG = (
    "pin=", "seed", "mnemonic", "private_key", "spend_key",
    "view_key", "bearer", "authorization", "auth_token",
    "api_key", "password", "encrypted_data", "pin_verifier",
)


def _hashed_vault_id(raw: Optional[str]) -> str:
    if not raw:
        return "anon"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def emit_span(
    span: str,
    *,
    vault_id: Optional[str],
    started_at_monotonic: Optional[float] = None,
    message_len_bytes: Optional[int] = None,
    intent: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """Emit a single closed-set timing log line.

    Never accepts a raw message, prompt, filename, or secret. If
    `extra` contains a stopword the emit is downgraded to a
    warning WITHOUT the extra field — the log line never carries
    the sensitive substring.
    """
    if span not in ALL_SPANS:

        logger.warning(
            "[CHAT-PERF] unknown span requested %r — dropping", span,
        )
        return
    elapsed_ms: Optional[int] = None
    if started_at_monotonic is not None:
        elapsed_ms = int(
            (time.monotonic() - started_at_monotonic) * 1000,
        )
    safe_extra: Optional[str] = None
    if extra:
        low = extra.lower()
        if not any(sw in low for sw in _SAFETY_STOPWORDS_FOR_LOG):
            safe_extra = extra[:80]
    parts: list[str] = [
        "[CHAT-PERF]",
        f"span={span}",
        f"vault={_hashed_vault_id(vault_id)}",
    ]
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms}")
    if message_len_bytes is not None:
        parts.append(f"msg_bytes={message_len_bytes}")
    if intent:
        parts.append(f"intent={intent}")
    if safe_extra:
        parts.append(f"extra={safe_extra}")
    logger.info(" ".join(parts))


def is_intent_fast_path_eligible(intent: Optional[str]) -> bool:
    if not intent or not isinstance(intent, str):
        return False
    return intent in INTENTS_SAFE_WITHOUT_DRAINS


def peek_intent_without_side_effects(
    decrypted_message: str,
    *,
    build_envelope: Callable[[str], Any],
) -> Optional[dict]:
    """Call the deterministic router on `decrypted_message` and
    return its envelope, or None if no deterministic route matched.

    The router is 100% regex + closed-set. It does not touch the
    DB, does not fetch cards, and does not populate live data. It's
    the cheapest possible way to know whether this message is
    fast-path-eligible.
    """
    if not isinstance(decrypted_message, str):
        return None
    text = decrypted_message.strip()
    if not text:
        return None
    # Delete buttons in the web/iOS clients send an internal sentinel to the
    # authoritative secure-item router.  Never let the read-only card router
    # interpret that sentinel as a login search (for example, turning
    # ``__delete_item:login:wife`` into a visible ``__delete_item wife``
    # not-found query).  Returning None preserves the message for the
    # confirmation-and-delete path later in the request pipeline.
    if text.lower().startswith("__delete_item:"):
        return None
    # A complete user-supplied login is create/save data. Credential words
    # make the deterministic card router look retrieval-like, but allowing
    # that envelope to short-circuit here prevents the downstream draft flow
    # from preserving the supplied values.
    if is_explicit_credential_assertion_create(text):
        return None
    try:
        envelope = build_envelope(text)
    except Exception:
        logger.exception(
            "[CHAT-PERF] router peek raised; falling through to "
            "slow path",
        )
        return None
    if isinstance(envelope, dict):
        return envelope
    return None


def can_skip_drains(
    envelope: Optional[dict],
    *,
    is_pending_confirm: bool,
    has_active_context: bool,
) -> bool:
    """Final decision. All three preconditions must hold:

      1. Router returned a deterministic envelope (else we don't
         know the intent yet).
      2. That envelope's intent is in the closed safe set.
      3. The message is NOT a pending-save confirmation phrase,
         because main.py has separate pending-draft logic that
         must run before any routing.
      4. The vault has no active context (draft being edited).
    """
    if not isinstance(envelope, dict):
        return False
    if is_pending_confirm:
        return False
    if has_active_context:
        return False
    intent = envelope.get("intent")
    return is_intent_fast_path_eligible(intent)


__all__ = [
    "INTENTS_SAFE_WITHOUT_DRAINS",
    "INTENTS_NEEDING_DRAINS",
    "SPAN_REQUEST_START",
    "SPAN_FAST_ROUTER_START",
    "SPAN_FAST_ROUTER_DONE",
    "SPAN_DRAIN_SCHEDULED",
    "SPAN_LLM_FALLBACK_START",
    "SPAN_RESPONSE_READY",
    "ALL_SPANS",
    "emit_span",
    "is_intent_fast_path_eligible",
    "peek_intent_without_side_effects",
    "can_skip_drains",
]
