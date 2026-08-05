"""Retrieval-free intent grammar for ordinary conversation.

The classifier composes normalized vocabularies; it deliberately does not map
complete QA sentences to answers. It has no vault, database, memory, wallet,
credential, or search dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


INTENT_PENDING_CONFIRMATION = "pending_confirmation"
INTENT_PENDING_CANCELLATION = "pending_cancellation"
INTENT_GENERAL_CHAT = "general_chat"
INTENT_ASSISTANT_IDENTITY = "assistant_identity"
INTENT_CAPABILITY_QUESTION = "capability_question"
INTENT_LANGUAGE_RESPONSE_REQUEST = "language_response_request"
INTENT_FAQ_QUESTION = "faq_question"
INTENT_FILE_SEARCH = "file_search"
INTENT_FILE_ACTION = "file_action"
INTENT_FILE_UPLOAD = "file_upload"
INTENT_MEMORY_RECALL = "memory_recall"
INTENT_MEMORY_SAVE = "memory_save"
INTENT_MEMORY_EDIT = "memory_edit"
INTENT_MEMORY_DELETE = "memory_delete"
INTENT_CREDENTIAL_CREATE = "credential_create"
INTENT_CREDENTIAL_RETRIEVE = "credential_retrieve"
INTENT_CREDENTIAL_EDIT = "credential_edit"
INTENT_CREDENTIAL_DELETE = "credential_delete"
INTENT_WALLET_ACTION = "wallet_action"
INTENT_INHERITANCE_ACTION = "inheritance_action"
INTENT_UNKNOWN_GENERAL = "unknown_general"


@dataclass(frozen=True)
class GeneralChatRoute:
    intent: str
    underlying_intent: str
    language: str
    response: str
    requested_language: bool = False
    model_response_required: bool = False
    clauses: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompoundMessage:
    clauses: tuple[str, ...]
    general_clauses: tuple[str, ...]
    vault_clauses: tuple[str, ...]


_LANGUAGES = {
    "english": "en", "spanish": "es", "espanol": "es",
    "french": "fr", "francais": "fr", "arabic": "ar",
    "portuguese": "pt", "portugues": "pt", "german": "de",
    "deutsch": "de", "italian": "it", "japanese": "ja",
    "korean": "ko", "chinese": "zh",
}
_LANGUAGE_DIRECTIVE_RE = re.compile(
    r"\b(?:in|into|answer|respond|reply|speak|translate|say)\b"
    r"(?:\s+(?:to|me|it|that|your|last|answer|response))*\s+"
    r"(?P<language>" + "|".join(map(re.escape, _LANGUAGES)) + r")\b",
    re.IGNORECASE,
)
_OPEN_LANGUAGE_DIRECTIVE_RE = re.compile(
    r"\b(?:answer|respond|reply|speak|write|translate|say)\b"
    r"[^.!?\n]{0,40}\b(?:in|into|using)\s+"
    r"(?P<language>[A-Za-z][A-Za-z -]{1,38})\b|"
    r"\b(?:tell\s+me|explain)\b[^.!?\n]{0,100}\bin\s+"
    r"(?P<language_tail>[A-Za-z][A-Za-z -]{1,38})\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_COMPOUND_SEPARATOR_RE = re.compile(
    r"\r?\n+|\s*;\s*|\s+\band\s+then\b\s+",
    re.IGNORECASE,
)

# Reusable intent vocabulary. Classification requires combinations across
# these sets rather than matching a whole sentence.
_GREETING_WORDS = frozenset({
    "hi", "hello", "hey", "yo", "hiya", "howdy", "morning",
    "afternoon", "evening",
})
_THANKS_WORDS = frozenset({"thanks", "thank", "appreciate"})
_GOODBYE_WORDS = frozenset({"bye", "goodbye", "farewell"})
_ASSISTANT_TARGETS = frozenset({"you", "yourself", "assistant", "svaultai"})
_IDENTITY_CUES = frozenset({"who", "what", "kind", "about", "describe", "explain", "tell"})
_CAPABILITY_CUES = frozenset({"can", "capable", "help", "do", "work", "works", "working"})
_CONVERSATION_CUES = frozenset({
    "question", "more", "explain", "mean", "simplify", "simpler",
    "continue", "again", "another", "help", "something",
})
_SMALL_TALK_CUES = frozenset({"how", "doing", "going", "today", "working"})

_RETRIEVAL_VERBS = frozenset({"find", "search", "show", "open", "list", "retrieve", "inspect", "recall"})
_MUTATION_VERBS = frozenset({"upload", "save", "rename", "delete", "move", "edit", "forget", "generate", "send", "update"})
_FILE_TERMS = frozenset({"vault", "file", "files", "document", "documents", "passport", "receipt", "contract", "contracts", "video", "videos", "uploaded"})
_MEMORY_TERMS = frozenset({"memory", "remember", "name", "birthday", "trip", "favorite", "city"})
_CREDENTIAL_TERMS = frozenset({"login", "logins", "credential", "credentials", "password", "username"})
_WALLET_TERMS = frozenset({"wallet", "eth", "btc", "sol", "trx", "balance", "transaction"})
_INHERITANCE_TERMS = frozenset({"inheritance", "beneficiary", "connection"})


_RESPONSES = {
    "en": {
        "greeting": "I'm doing well and ready to help with your vault. What would you like to do?",
        "identity": "I'm SvaultAI, a privacy-focused assistant for your encrypted digital vault. I can explain the app and help manage vault items when you explicitly ask me to.",
        "capability": "I can help organize and use your encrypted vault, including files, credentials, memories, and supported wallet features. I access vault data only when you clearly request it.",
        "thanks": "You're welcome. What would you like help with next?",
        "goodbye": "Goodbye! I'll be here when you need help with your vault.",
        "general": "Of course. Tell me what you'd like help with; I won't search your vault unless you clearly request it.",
    },
    "es": {
        "greeting": "Estoy bien y listo para ayudarte con tu bóveda. ¿Qué te gustaría hacer?",
        "identity": "Soy SvaultAI, un asistente centrado en la privacidad para tu bóveda digital cifrada. Puedo explicar la aplicación y ayudarte a gestionar tus datos cuando me lo pidas explícitamente.",
        "capability": "Puedo ayudarte a organizar y usar tu bóveda cifrada. Solo accedo a sus datos cuando lo solicitas claramente.",
        "general": "Claro. Dime en qué quieres que te ayude; no buscaré en tu bóveda sin una solicitud clara.",
    },
    "fr": {
        "greeting": "Je vais bien et je suis prêt à vous aider avec votre coffre-fort. Que souhaitez-vous faire ?",
        "identity": "Je suis SvaultAI, un assistant axé sur la confidentialité pour votre coffre-fort numérique chiffré. Je peux expliquer l’application et vous aider à gérer vos données sur demande explicite.",
        "capability": "Je peux vous aider à organiser et utiliser votre coffre-fort chiffré. Je n’accède à ses données que sur demande claire.",
        "general": "Bien sûr. Dites-moi comment je peux vous aider ; je ne rechercherai rien dans votre coffre-fort sans demande claire.",
    },
    "ar": {
        "greeting": "أنا بخير ومستعد لمساعدتك في خزنتك. ماذا تريد أن تفعل؟",
        "identity": "أنا SvaultAI، مساعد يركز على الخصوصية لخزنتك الرقمية المشفرة. يمكنني شرح التطبيق ومساعدتك في إدارة بياناتك عند الطلب الواضح.",
        "capability": "يمكنني مساعدتك في تنظيم خزنتك المشفرة واستخدامها. لا أصل إلى بياناتها إلا عندما تطلب ذلك بوضوح.",
        "general": "بالتأكيد. أخبرني بما تحتاج إليه، ولن أبحث في خزنتك من دون طلب واضح.",
    },
    "pt": {
        "identity": "Sou o SvaultAI, um assistente focado em privacidade para o seu cofre digital criptografado. Posso explicar o aplicativo e ajudar a gerenciar seus dados quando você pedir.",
        "capability": "Posso ajudar a organizar e usar seu cofre criptografado. Só acesso dados do cofre quando você pede claramente.",
        "general": "Claro. Diga como posso ajudar; não pesquisarei seu cofre sem um pedido claro.",
    },
    "de": {
        "identity": "Ich bin SvaultAI, ein datenschutzorientierter Assistent für deinen verschlüsselten digitalen Tresor. Ich erkläre die App und helfe auf ausdrückliche Anfrage bei deinen Daten.",
        "capability": "Ich kann dir helfen, deinen verschlüsselten Tresor zu organisieren. Ich greife nur nach einer eindeutigen Anfrage auf Tresordaten zu.",
        "general": "Gerne. Sag mir, wobei ich helfen kann; ohne eine eindeutige Aufforderung durchsuche ich deinen Tresor nicht.",
    },
}


def _tokens(message: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in _TOKEN_RE.findall(message or ""))


def requested_response_language(message: str) -> Optional[str]:
    match = _LANGUAGE_DIRECTIVE_RE.search(message) if isinstance(message, str) else None
    return _LANGUAGES.get(match.group("language").lower()) if match else None


def has_language_directive(message: str) -> bool:
    """Return true for any syntactically named response language."""
    if not isinstance(message, str) or not message.strip():
        return False
    return bool(
        _LANGUAGE_DIRECTIVE_RE.search(message)
        or _OPEN_LANGUAGE_DIRECTIVE_RE.search(message)
    )


def _has_explicit_vault_intent(tokens: set[str]) -> bool:
    action = bool(tokens & (_RETRIEVAL_VERBS | _MUTATION_VERBS))
    private_domain = bool(tokens & (_FILE_TERMS | _MEMORY_TERMS | _CREDENTIAL_TERMS | _WALLET_TERMS | _INHERITANCE_TERMS))
    possessive_fact = "my" in tokens and private_domain
    return (action and private_domain) or possessive_fact


def split_compound_message(message: str) -> tuple[str, ...]:
    """Split command-like clauses without encoding complete QA phrases."""
    if not isinstance(message, str) or not message.strip():
        return ()
    normalized = re.sub(r"\s*,\s*(?=(?:then\s+)?(?:tell|explain|reply|answer|respond|show|find|open|list|save|delete|what|how)\b)", "\n", message, flags=re.IGNORECASE)
    parts = _COMPOUND_SEPARATOR_RE.split(normalized)
    clauses = []
    for part in parts:
        clean = _LIST_PREFIX_RE.sub("", part).strip(" \t,.-")
        if clean:
            clauses.append(clean)
    return tuple(clauses)


def analyze_compound_message(message: str) -> CompoundMessage:
    clauses = split_compound_message(message)
    general: list[str] = []
    vault: list[str] = []
    for clause in clauses:
        tokens = set(_tokens(clause))
        if _has_explicit_vault_intent(tokens):
            vault.append(clause)
        elif _semantic_general_intent(clause) != INTENT_UNKNOWN_GENERAL or has_language_directive(clause):
            general.append(clause)
        else:
            # Unknown compound prose is non-retrieval by default. It must not
            # become search merely because it is malformed or multi-clause.
            general.append(clause)
    return CompoundMessage(clauses, tuple(general), tuple(vault))


def _semantic_general_intent(message: str) -> str:
    ordered = _tokens(message)
    tokens = set(ordered)
    if not tokens or _has_explicit_vault_intent(tokens):
        return INTENT_UNKNOWN_GENERAL
    if (
        tokens & _CAPABILITY_CUES
        and (tokens & _ASSISTANT_TARGETS or "app" in tokens)
    ):
        return INTENT_CAPABILITY_QUESTION
    if tokens & _ASSISTANT_TARGETS and tokens & _IDENTITY_CUES:
        return INTENT_ASSISTANT_IDENTITY
    if tokens & (_GREETING_WORDS | _THANKS_WORDS | _GOODBYE_WORDS):
        return INTENT_GENERAL_CHAT
    if tokens & _CONVERSATION_CUES:
        return INTENT_GENERAL_CHAT
    if "you" in tokens and tokens & _SMALL_TALK_CUES:
        return INTENT_GENERAL_CHAT
    return INTENT_UNKNOWN_GENERAL


def classify_general_intent(message: str) -> str:
    base = _semantic_general_intent(message)
    if base == INTENT_UNKNOWN_GENERAL:
        return base
    return INTENT_LANGUAGE_RESPONSE_REQUEST if has_language_directive(message) else base


def route_general_chat(message: str, default_language: str = "en") -> Optional[GeneralChatRoute]:
    compound = analyze_compound_message(message)
    if len(compound.clauses) > 1:
        if compound.vault_clauses:
            return None
        return GeneralChatRoute(
            INTENT_LANGUAGE_RESPONSE_REQUEST
            if any(has_language_directive(c) for c in compound.clauses)
            else INTENT_GENERAL_CHAT,
            INTENT_GENERAL_CHAT,
            default_language,
            "",
            any(has_language_directive(c) for c in compound.clauses),
            True,
            compound.clauses,
        )
    underlying = _semantic_general_intent(message)
    requested = requested_response_language(message)
    open_language_request = has_language_directive(message)
    explicit_vault_intent = _has_explicit_vault_intent(set(_tokens(message)))
    if explicit_vault_intent:
        return None
    # A bare language directive is itself safe general conversation.
    if underlying == INTENT_UNKNOWN_GENERAL and open_language_request:
        underlying = INTENT_GENERAL_CHAT
    if underlying == INTENT_UNKNOWN_GENERAL:
        return None
    intent = INTENT_LANGUAGE_RESPONSE_REQUEST if open_language_request else underlying
    language = requested or (default_language if default_language in _RESPONSES else "en")
    if open_language_request:
        return GeneralChatRoute(
            intent, underlying, requested or default_language, "",
            True, True,
        )
    tokens = set(_tokens(message))
    if underlying == INTENT_ASSISTANT_IDENTITY:
        kind = "identity"
    elif underlying == INTENT_CAPABILITY_QUESTION:
        kind = "capability"
    elif tokens & _THANKS_WORDS:
        kind = "thanks"
    elif tokens & _GOODBYE_WORDS:
        kind = "goodbye"
    elif tokens & _GREETING_WORDS or ("you" in tokens and tokens & _SMALL_TALK_CUES):
        kind = "greeting"
    else:
        kind = "general"
    table = _RESPONSES.get(language, _RESPONSES["en"])
    response = table.get(kind) or table.get("general") or _RESPONSES["en"][kind]
    return GeneralChatRoute(intent, underlying, language, response, bool(requested))


__all__ = [name for name in globals() if name.startswith("INTENT_")] + [
    "GeneralChatRoute", "requested_response_language", "has_language_directive",
    "CompoundMessage", "split_compound_message", "analyze_compound_message",
    "classify_general_intent", "route_general_chat",
]
