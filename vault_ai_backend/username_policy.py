

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import string
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Awaitable, Callable, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)


ALLOWED_CHARS_LETTERS_NUMBERS = "letters_numbers"
ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE = "letters_numbers_underscore"
ALLOWED_CHARS_LETTERS_NUMBERS_DOT_UNDERSCORE = "letters_numbers_dot_underscore"
ALLOWED_CHARS_EMAIL = "email"

ALLOWED_CHARSETS = frozenset({
    ALLOWED_CHARS_LETTERS_NUMBERS,
    ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE,
    ALLOWED_CHARS_LETTERS_NUMBERS_DOT_UNDERSCORE,
    ALLOWED_CHARS_EMAIL,
})

CONFIDENCE_OFFICIAL = "official"
CONFIDENCE_INFERRED = "inferred"
CONFIDENCE_UNKNOWN = "unknown"

CONFIDENCES = frozenset({
    CONFIDENCE_OFFICIAL,
    CONFIDENCE_INFERRED,
    CONFIDENCE_UNKNOWN,
})


DEFAULT_MIN_LENGTH = 8
DEFAULT_MAX_LENGTH = 16


@dataclass(frozen=True)
class UsernamePolicy:


    service: str
    allowed_chars: str = ALLOWED_CHARS_LETTERS_NUMBERS
    min_length: int = DEFAULT_MIN_LENGTH
    max_length: int = DEFAULT_MAX_LENGTH
    disallow_symbols: bool = True
    disallow_underscore: bool = True
    email_required: bool = False
    source_url: Optional[str] = None
    confidence: str = CONFIDENCE_UNKNOWN
    checked_at: int = field(default_factory=lambda: int(time.time()))

    def to_cache_row(self) -> dict:
        return {
            "allowed_chars": self.allowed_chars,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "disallow_symbols": self.disallow_symbols,
            "disallow_underscore": self.disallow_underscore,
            "email_required": self.email_required,
            "source_url": self.source_url,
            "confidence": self.confidence,
        }


def _service_key(service: str) -> str:


    return re.sub(r"\s+", " ", (service or "").strip()).lower()


def conservative_default(service: str) -> UsernamePolicy:


    return UsernamePolicy(
        service=service,
        allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS,
        min_length=DEFAULT_MIN_LENGTH,
        max_length=DEFAULT_MAX_LENGTH,
        disallow_symbols=True,
        disallow_underscore=True,
        email_required=False,
        source_url=None,
        confidence=CONFIDENCE_UNKNOWN,
    )


def _charset_for(policy: UsernamePolicy) -> str:
    if policy.allowed_chars == ALLOWED_CHARS_EMAIL:
                                                                   
                                                               
        raise ValueError("email policy requires user input, not random gen")
    if policy.allowed_chars == ALLOWED_CHARS_LETTERS_NUMBERS_DOT_UNDERSCORE:
        chars = string.ascii_lowercase + string.digits
        if not policy.disallow_underscore:
            chars += "_"
        chars += "."
        return chars
    if policy.allowed_chars == ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE:
        chars = string.ascii_lowercase + string.digits
        if not policy.disallow_underscore:
            chars += "_"
        return chars
                                                                       
                                                               
    return string.ascii_lowercase + string.digits


_ALIAS_LEFT_WORDS = (
    "river", "north", "silver", "orbit", "cedar", "blue", "stone",
    "quiet", "amber", "cobalt", "crimson", "emerald", "frost",
    "harbor", "meadow", "marble", "dawn", "dusk", "ember",
    "granite", "ivory", "jade", "indigo", "willow", "wild",
    "violet", "rust", "spruce", "maple", "birch", "pine", "moss",
    "ocean", "summit", "ridge", "valley", "lunar", "solar",
    "swift", "still", "calm", "open", "bright", "dark", "bold",
    "lone", "snow", "thunder", "storm", "cloud", "mist", "glass",
    "iron", "copper", "brass", "onyx", "ash", "wave", "tide",
    "ember", "raven", "azure", "sage", "lime", "neon", "echo",
    "vivid", "soft", "wide", "deep", "high", "low", "shore",
    "delta", "mesa", "fjord", "canyon", "prairie", "tundra",
)

_ALIAS_RIGHT_WORDS = (
    "fox", "mark", "gate", "field", "byte", "harbor", "pilot",
    "nova", "ember", "summit", "path", "crest", "pulse", "signal",
    "delta", "atlas", "pixel", "bloom", "stream", "shade",
    "echo", "spire", "halo", "drift", "loft",
    "arrow", "anchor", "bay", "beam", "bell", "berry", "branch",
    "brook", "cap", "cliff", "clover", "coast", "cove", "creek",
    "dale", "den", "dew", "dune", "fawn", "fern", "flint",
    "frame", "garden", "glen", "glow", "grain", "grove", "halo",
    "haven", "heath", "hill", "hollow", "horizon", "isle", "knoll",
    "lake", "lane", "leaf", "ledge", "loop", "marsh", "moor",
    "mound", "oak", "orchard", "patch", "peak", "pier", "plain",
    "pond", "port", "reef", "rim", "ripple", "rise", "rock",
    "root", "row", "shore", "shrub", "sky", "slope", "soil",
    "spark", "spring", "stem", "step", "still", "swarm", "tile",
    "trail", "twig", "vale", "vine", "warden", "watch", "weave",
    "well", "wing", "wood",
)

                                                               
_ALWAYS_FORBIDDEN_SUBSTRINGS = ("vault", "vaultai")


def _safe_substring_set(*words: str) -> set[str]:


    out: set[str] = set()
    for w in words:
        if not w:
            continue
        s = re.sub(r"[^a-z0-9]+", "", str(w).lower()).strip()
        if len(s) >= 3:
            out.add(s)
    return out


def _alias_contains_forbidden(candidate: str, forbidden: set[str]) -> bool:
    c = candidate.lower()
    for f in forbidden:
        if not f:
            continue
        if f in c:
            return True
    return False


def _build_alias_candidate(
    policy: UsernamePolicy, *, rng=secrets,
) -> str:


    left = rng.choice(_ALIAS_LEFT_WORDS)
    right = rng.choice(_ALIAS_RIGHT_WORDS)
                                                            
                                                                 
    base = left + right
    target_min = max(policy.min_length, 8)
    target_max = min(policy.max_length, 16)
    digits_needed_min = max(2, target_min - len(base))
    digits_needed_max = max(digits_needed_min, target_max - len(base))
    digits_needed = rng.randbelow(
        max(1, digits_needed_max - digits_needed_min + 1),
    ) + digits_needed_min
    digits_needed = min(digits_needed, 4)
    digits_needed = max(digits_needed, 2)
    suffix = "".join(
        rng.choice(string.digits) for _ in range(digits_needed)
    )
    return base + suffix


def generate_username(
    policy: UsernamePolicy,
    *,
    forbidden_substrings: Optional[set[str]] = None,
    user_identity_hints: Optional[list[str]] = None,
) -> str:


    if policy.email_required:
        raise ValueError(
            "email_required policy: ask the user for their email instead "
            "of generating a username"
        )

                                   
    forbidden: set[str] = set(_ALWAYS_FORBIDDEN_SUBSTRINGS)
                                                                 
                                               
    service_token = re.sub(
        r"[^a-z0-9]+", "", (policy.service or "").lower(),
    )
    if len(service_token) >= 3:
        forbidden.add(service_token)
    if forbidden_substrings:
        for s in forbidden_substrings:
            forbidden.update(_safe_substring_set(s))
    if user_identity_hints:
        forbidden.update(_safe_substring_set(*user_identity_hints))

                                                                 
    for _ in range(32):
        candidate = _build_alias_candidate(policy)
        if _alias_contains_forbidden(candidate, forbidden):
            continue
                                                               
                                                              
        candidate = re.sub(r"[^a-z0-9]", "", candidate)
                                            
        if len(candidate) < policy.min_length:
            charset = _charset_for(policy)
            while len(candidate) < policy.min_length:
                candidate += secrets.choice(charset)
        candidate = candidate[: policy.max_length]
        if _alias_contains_forbidden(candidate, forbidden):
            continue
        return candidate

                                                                 
    fallback = "".join(
        secrets.choice(string.digits) for _ in range(policy.min_length)
    )
    return fallback[: policy.max_length]


def generate_username_options(
    policy: UsernamePolicy,
    *,
    n: int = 3,
    forbidden_substrings: Optional[set[str]] = None,
    user_identity_hints: Optional[list[str]] = None,
) -> list[str]:


    n = max(1, int(n))
    out: list[str] = []
    attempts = 0
    while len(out) < n and attempts < n * 16:
        attempts += 1
        candidate = generate_username(
            policy,
            forbidden_substrings=forbidden_substrings,
            user_identity_hints=user_identity_hints,
        )
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def tighten_policy(policy: UsernamePolicy) -> UsernamePolicy:


    if policy.email_required:
        return policy

    changed = False
    allowed_chars = policy.allowed_chars
    disallow_symbols = policy.disallow_symbols
    disallow_underscore = policy.disallow_underscore
    min_length = policy.min_length
    max_length = policy.max_length

    if not disallow_underscore:
        disallow_underscore = True
        changed = True
    if not disallow_symbols:
        disallow_symbols = True
        changed = True
    if allowed_chars != ALLOWED_CHARS_LETTERS_NUMBERS:
        allowed_chars = ALLOWED_CHARS_LETTERS_NUMBERS
        changed = True
                                                                   
                                                                      
    if min_length < 8 or max_length > 12:
        min_length = max(min_length, 8)
        max_length = min(max_length, 12)
        changed = True

    return UsernamePolicy(
        service=policy.service,
        allowed_chars=allowed_chars,
        min_length=min_length,
        max_length=max_length,
        disallow_symbols=disallow_symbols,
        disallow_underscore=disallow_underscore,
        email_required=False,
        source_url=policy.source_url,
        confidence=CONFIDENCE_INFERRED if changed else policy.confidence,
    )


def format_policy_note(policy: UsernamePolicy) -> str:


    service_label = policy.service.title() if policy.service else "this service"

    if policy.confidence == CONFIDENCE_OFFICIAL and policy.source_url:
        if policy.disallow_underscore or policy.disallow_symbols:
            return (
                f"I found {service_label} usernames should avoid special "
                "characters, so I used letters and numbers only."
            )
        return (
            f"I used the {service_label} username format from their official "
            "rules."
        )
    if policy.confidence == CONFIDENCE_OFFICIAL:
        if policy.disallow_underscore or policy.disallow_symbols:
            return (
                f"I found {service_label} usernames should avoid special "
                "characters, so I used letters and numbers only."
            )
        return f"I used {service_label}'s known username format."
    if policy.confidence == CONFIDENCE_INFERRED:
        return (
            f"I picked a {service_label}-friendly format based on what I "
            "could find — let me know if it gets rejected and I'll tighten "
            "the rules."
        )
                        
    return (
        "I generated this using a conservative username format because I "
        f"could not confirm {service_label}'s exact username rules."
    )


class PolicyCache:


    def __init__(self, connection_factory: Callable[[], psycopg2.extensions.connection]):
        self._connect = connection_factory

    def get(self, service: str) -> Optional[UsernamePolicy]:
        key = _service_key(service)
        if not key:
            return None
        conn = self._connect()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT service_display, allowed_chars, min_length, max_length,
                       disallow_symbols, disallow_underscore, email_required,
                       source_url, confidence,
                       EXTRACT(EPOCH FROM checked_at)::bigint AS checked_at
                FROM username_policies
                WHERE service_key = %s
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return UsernamePolicy(
                service=row["service_display"] or service,
                allowed_chars=row["allowed_chars"],
                min_length=int(row["min_length"]),
                max_length=int(row["max_length"]),
                disallow_symbols=bool(row["disallow_symbols"]),
                disallow_underscore=bool(row["disallow_underscore"]),
                email_required=bool(row["email_required"]),
                source_url=row["source_url"],
                confidence=row["confidence"],
                checked_at=int(row["checked_at"] or 0),
            )
        finally:
            conn.close()

    def put(self, policy: UsernamePolicy) -> None:
        key = _service_key(policy.service)
        if not key:
            return
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO username_policies (
                    service_key, service_display,
                    allowed_chars, min_length, max_length,
                    disallow_symbols, disallow_underscore, email_required,
                    source_url, confidence, checked_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    service_display    = EXCLUDED.service_display,
                    allowed_chars      = EXCLUDED.allowed_chars,
                    min_length         = EXCLUDED.min_length,
                    max_length         = EXCLUDED.max_length,
                    disallow_symbols   = EXCLUDED.disallow_symbols,
                    disallow_underscore= EXCLUDED.disallow_underscore,
                    email_required     = EXCLUDED.email_required,
                    source_url         = EXCLUDED.source_url,
                    confidence         = EXCLUDED.confidence,
                    checked_at         = NOW()
                """,
                (
                    key, policy.service,
                    policy.allowed_chars, policy.min_length, policy.max_length,
                    policy.disallow_symbols, policy.disallow_underscore,
                    policy.email_required,
                    policy.source_url, policy.confidence,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("[USERNAME-POLICY] cache write failed for %r", key)
        finally:
            conn.close()


LlmInfer = Callable[[str], Awaitable[Optional[dict]]]


def _default_intent_model() -> str:
    try:
        from vault_config import ai as _ai_cfg
        return _ai_cfg().intent_model
    except Exception:
        return "gpt-4o-mini"


async def infer_policy_via_llm(
    service: str,
    openai_client: Any,
    model: Optional[str] = None,
) -> Optional[dict]:


    prompt = (
        "You are a research helper that returns ONLY a strict JSON object "
        "describing the username rules for a named online service.\n"
        "\n"
        "Service: " + (service or "").strip()[:200] + "\n"
        "\n"
        "Return EXACTLY this JSON shape and no prose:\n"
        "{\n"
        '  "allowed_chars": one of '
        '"letters_numbers" | "letters_numbers_underscore" | '
        '"letters_numbers_dot_underscore" | "email",\n'
        '  "min_length": integer 1-64,\n'
        '  "max_length": integer 1-64,\n'
        '  "disallow_symbols": true | false,\n'
        '  "disallow_underscore": true | false,\n'
        '  "email_required": true | false,\n'
        '  "source_url": short URL or null,\n'
        '  "confidence": "official" | "inferred" | "unknown"\n'
        "}\n"
        "\n"
        "Be conservative. If you do not know the service, return "
        '"confidence": "unknown" and the strictest letters_numbers shape '
        "with min=8 max=16."
    )

    resolved_model = model if model else _default_intent_model()
    try:
                                                            
                                                               
        if openai_client is not None and hasattr(
            openai_client, "chat",
        ):
            response = await openai_client.chat.completions.create(
                model=resolved_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
        else:
            from vault_ai_provider import chat_complete_with_fallback
            result = await chat_complete_with_fallback(
                messages=[{"role": "user", "content": prompt}],
                model=resolved_model,
                model_kind="intent",
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = result.content or ""
    except Exception as exc:
        logger.warning(
            "[USERNAME-POLICY] LLM inference failed for %r: %s", service, exc,
        )
        return None

    import json
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning(
            "[USERNAME-POLICY] LLM returned non-JSON for %r: %r", service, raw[:200],
        )
        return None
    if not isinstance(data, dict):
        return None
    return data


_web_lookup_hook: Optional[Callable[[str], Awaitable[Optional[dict]]]] = None


def _coerce_policy(
    service: str,
    raw: dict,
    default_confidence: str = CONFIDENCE_INFERRED,
) -> UsernamePolicy:


    allowed = str(raw.get("allowed_chars") or "").strip()
    if allowed not in ALLOWED_CHARSETS:
        allowed = ALLOWED_CHARS_LETTERS_NUMBERS

    def _int_or(default: int, key: str, lo: int, hi: int) -> int:
        try:
            v = int(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v

    min_len = _int_or(DEFAULT_MIN_LENGTH, "min_length", 1, 64)
    max_len = _int_or(DEFAULT_MAX_LENGTH, "max_length", min_len, 64)

    disallow_symbols = bool(raw.get("disallow_symbols", True))
    disallow_underscore = bool(raw.get("disallow_underscore", True))
    email_required = bool(raw.get("email_required", False))

    source_url = raw.get("source_url") or None
    if isinstance(source_url, str):
        source_url = source_url.strip()[:2048] or None
    else:
        source_url = None

    confidence = str(raw.get("confidence") or "").strip().lower()
    if confidence not in CONFIDENCES:
        confidence = default_confidence

                                                                       
    if allowed == ALLOWED_CHARS_EMAIL:
        email_required = True

    return UsernamePolicy(
        service=service,
        allowed_chars=allowed,
        min_length=min_len,
        max_length=max_len,
        disallow_symbols=disallow_symbols,
        disallow_underscore=disallow_underscore,
        email_required=email_required,
        source_url=source_url,
        confidence=confidence,
    )


async def resolve_username_policy(
    service: str,
    *,
    cache: Optional[PolicyCache],
    openai_client: Any = None,
) -> UsernamePolicy:


    if not (service or "").strip():
        return conservative_default("this service")

    if cache is not None:
        cached = cache.get(service)
        if cached is not None:
            return cached

                                                      
    if _web_lookup_hook is not None:
        try:
            raw = await _web_lookup_hook(service)
        except Exception:
            raw = None
        if raw:
            policy = _coerce_policy(service, raw, default_confidence=CONFIDENCE_OFFICIAL)
            if cache is not None:
                cache.put(policy)
            return policy

                                                                  
    if openai_client is not None:
        raw = await infer_policy_via_llm(service, openai_client)
        if raw:
            policy = _coerce_policy(service, raw, default_confidence=CONFIDENCE_INFERRED)
            if cache is not None:
                cache.put(policy)
            return policy

                                                                    
    policy = conservative_default(service)
    if cache is not None:
        cache.put(policy)
    return policy
